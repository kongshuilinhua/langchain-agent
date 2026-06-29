"""令牌撤销（Redis 黑名单）单元测试。

🎯 不依赖真实 Redis / 数据库：用内存假客户端替换 OptionalRedisStore._client，
   覆盖三件事：
   1. 撤销后令牌被 decode 拒绝（修复历史 bug：旧实现因 redis_store.client 不存在而整条链路失效）；
   2. Redis 不可用时优雅降级（撤销返回 False、解码放行）；
   3. store 原语 exists / set_string 的基本行为与 degraded 健康标记。
"""

import time

import pytest

from core.config import get_settings
from core.security import auth
from core.services import rag_cache


class FakeRedis:
    """最小内存假客户端，仅实现 store 用到的 get / setex / exists / ping。"""

    def __init__(self) -> None:
        self.store: dict[str, tuple[str, float]] = {}

    def _live(self, key: str):
        item = self.store.get(key)
        if not item:
            return None
        value, expire_at = item
        if expire_at and expire_at < time.time():
            self.store.pop(key, None)
            return None
        return value

    def get(self, key):
        return self._live(key)

    def setex(self, key, ttl, value):
        self.store[key] = (value, time.time() + int(ttl))

    def exists(self, key):
        return 1 if self._live(key) is not None else 0

    def ping(self):
        return True


class BrokenRedis(FakeRedis):
    """每次操作都抛 RedisError，用于验证运行期故障降级。"""

    def exists(self, key):
        raise rag_cache._REDIS_ERRORS[0]("boom")

    def setex(self, key, ttl, value):
        raise rag_cache._REDIS_ERRORS[0]("boom")


def _make_store(client) -> rag_cache.OptionalRedisStore:
    """绕过 __init__ 的真实连接，注入指定客户端。"""
    store = rag_cache.OptionalRedisStore.__new__(rag_cache.OptionalRedisStore)
    store.settings = get_settings()
    store._client = client
    store._error = ""
    store._runtime_error = ""
    return store


def test_revoked_token_is_rejected(monkeypatch):
    store = _make_store(FakeRedis())
    monkeypatch.setattr(rag_cache, "redis_store", store)

    token = auth.create_access_token({"sub": "1"})
    assert auth.decode_access_token(token)["sub"] == "1"  # 撤销前可正常解码

    assert auth.revoke_access_token(token) is True
    with pytest.raises(ValueError, match="revoked"):
        auth.decode_access_token(token)


def test_degrades_when_redis_absent(monkeypatch):
    store = _make_store(None)  # 未配置 Redis
    monkeypatch.setattr(rag_cache, "redis_store", store)

    token = auth.create_access_token({"sub": "1"})
    assert auth.revoke_access_token(token) is False        # 无法写黑名单
    assert auth.decode_access_token(token)["sub"] == "1"   # 降级放行，不阻断登录态


def test_runtime_failure_degrades_and_marks_status(monkeypatch):
    store = _make_store(BrokenRedis())
    monkeypatch.setattr(rag_cache, "redis_store", store)

    token = auth.create_access_token({"sub": "1"})
    # 运行期 Redis 抛错：撤销失败、解码降级放行，且不向上抛异常
    assert auth.revoke_access_token(token) is False
    assert auth.decode_access_token(token)["sub"] == "1"

    # available 仍为 True（保留重连机会），但 degraded 标记被点亮供监控感知
    assert store.available is True
    assert store.status()["degraded"] is True


def test_store_primitives_roundtrip():
    store = _make_store(FakeRedis())
    assert store.exists("k") is False
    assert store.set_string("k", 60, "1") is True
    assert store.exists("k") is True
    assert store.status()["degraded"] is False
