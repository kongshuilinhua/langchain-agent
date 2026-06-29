"""Redis ZSET 滑动窗口分布式限流单元测试（不依赖真实 Redis）。

用支持 ZSET + pipeline 的内存假客户端验证：放行→超限→窗口滑动→宕机 fail-open，
以及 FastAPI 依赖在超限时抛 429。
"""

import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api import rate_limit as rl
from core.config import get_settings
from core.services import rag_cache


class FakeZSetRedis:
    """最小 ZSET + pipeline 假客户端。"""

    def __init__(self) -> None:
        self.z: dict[str, dict] = {}

    def zremrangebyscore(self, key, lo, hi):
        d = self.z.get(key, {})
        removed = [m for m, s in d.items() if lo <= s <= hi]
        for m in removed:
            d.pop(m, None)
        return len(removed)

    def zadd(self, key, mapping):
        d = self.z.setdefault(key, {})
        added = 0
        for member, score in mapping.items():
            if member not in d:
                added += 1
            d[member] = score
        return added

    def zcard(self, key):
        return len(self.z.get(key, {}))

    def zrem(self, key, *members):
        d = self.z.get(key, {})
        removed = 0
        for member in members:
            if d.pop(member, None) is not None:
                removed += 1
        return removed

    def expire(self, key, ttl):
        return True

    def pipeline(self):
        return _FakePipe(self)

    def ping(self):
        return True


class _FakePipe:
    def __init__(self, redis) -> None:
        self.redis = redis
        self.ops: list[tuple] = []

    def zremrangebyscore(self, *args):
        self.ops.append(("zremrangebyscore", args))
        return self

    def zadd(self, *args):
        self.ops.append(("zadd", args))
        return self

    def zcard(self, *args):
        self.ops.append(("zcard", args))
        return self

    def expire(self, *args):
        self.ops.append(("expire", args))
        return self

    def execute(self):
        return [getattr(self.redis, name)(*args) for name, args in self.ops]


def _make_store(client) -> rag_cache.OptionalRedisStore:
    store = rag_cache.OptionalRedisStore.__new__(rag_cache.OptionalRedisStore)
    store.settings = get_settings()
    store._client = client
    store._error = ""
    store._runtime_error = ""
    return store


def test_rate_limit_allows_then_blocks():
    store = _make_store(FakeZSetRedis())
    key = "rl:test:1.2.3.4"
    results = [store.rate_limit_check(key, limit=3, window_seconds=60) for _ in range(3)]
    assert all(allowed for allowed, _ in results)
    assert [remaining for _, remaining in results] == [2, 1, 0]

    blocked, remaining = store.rate_limit_check(key, 3, 60)
    assert blocked is False and remaining == 0


def test_rate_limit_window_slides():
    store = _make_store(FakeZSetRedis())
    key = "rl:test:slide"
    # 预置 3 条窗口外的旧请求，应被 ZREMRANGEBYSCORE 清掉
    store._client.z[key] = {f"old{i}": time.time() - 1000 for i in range(3)}
    allowed, remaining = store.rate_limit_check(key, limit=3, window_seconds=60)
    assert allowed is True and remaining == 2  # 旧的清掉后只剩本次


def test_rate_limit_fail_open_when_redis_down():
    store = _make_store(None)
    allowed, remaining = store.rate_limit_check("k", 1, 60)
    assert allowed is True and remaining == -1  # 降级放行


def test_dependency_raises_429(monkeypatch):
    monkeypatch.setattr(rag_cache, "redis_store", _make_store(FakeZSetRedis()))
    dep = rl.redis_rate_limit(2, 60, scope="register")
    req = SimpleNamespace(client=SimpleNamespace(host="9.9.9.9"), headers={})

    dep(req)
    dep(req)  # 前两次放行
    with pytest.raises(HTTPException) as exc_info:
        dep(req)  # 第三次超限
    assert exc_info.value.status_code == 429
    assert exc_info.value.headers.get("Retry-After") == "60"
