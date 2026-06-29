"""Redis 共享态熔断器单元测试（不依赖真实 Redis）。

验证 store 的 breaker_* 原语（达阈值熔断 / 成功清零 / 宕机 fail-open）
及 RedisCircuitBreaker 包装类。
"""

import time

from core.config import get_settings
from core.integrations.circuit_breaker import RedisCircuitBreaker
from core.services import rag_cache


class FakeRedis:
    """支持 incr/expire/setex/exists/delete + pipeline 的内存假客户端。"""

    def __init__(self) -> None:
        self.kv: dict[str, tuple] = {}

    def _live(self, key):
        item = self.kv.get(key)
        if not item:
            return None
        value, expire_at = item
        if expire_at and expire_at < time.time():
            self.kv.pop(key, None)
            return None
        return value

    def incr(self, key):
        current = int(self._live(key) or 0) + 1
        prev = self.kv.get(key)
        expire_at = prev[1] if prev else None
        self.kv[key] = (current, expire_at)
        return current

    def expire(self, key, ttl):
        item = self.kv.get(key)
        if not item:
            return False
        self.kv[key] = (item[0], time.time() + int(ttl))
        return True

    def setex(self, key, ttl, value):
        self.kv[key] = (value, time.time() + int(ttl))

    def exists(self, key):
        return 1 if self._live(key) is not None else 0

    def delete(self, *keys):
        removed = 0
        for key in keys:
            if self.kv.pop(key, None) is not None:
                removed += 1
        return removed

    def pipeline(self):
        return _FakePipe(self)

    def ping(self):
        return True


class _FakePipe:
    def __init__(self, redis) -> None:
        self.redis = redis
        self.ops: list[tuple] = []

    def incr(self, *args):
        self.ops.append(("incr", args))
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


def test_breaker_opens_after_threshold():
    store = _make_store(FakeRedis())
    name = "model:x"
    assert store.breaker_allow(name) is True
    assert store.breaker_on_failure(name, 3, 60) == "CLOSED"  # 1
    assert store.breaker_on_failure(name, 3, 60) == "CLOSED"  # 2
    assert store.breaker_on_failure(name, 3, 60) == "OPEN"    # 3 → 熔断
    assert store.breaker_allow(name) is False


def test_breaker_success_resets():
    store = _make_store(FakeRedis())
    name = "model:y"
    for _ in range(3):
        store.breaker_on_failure(name, 3, 60)
    assert store.breaker_allow(name) is False
    store.breaker_on_success(name)
    assert store.breaker_allow(name) is True


def test_breaker_fail_open_when_redis_down():
    store = _make_store(None)
    assert store.breaker_allow("m") is True          # 放行
    assert store.breaker_on_failure("m", 3, 60) is None  # 记录类无副作用


def test_redis_circuit_breaker_wrapper(monkeypatch):
    monkeypatch.setattr(rag_cache, "redis_store", _make_store(FakeRedis()))
    breaker = RedisCircuitBreaker("model:z", failure_threshold=2, timewindow=60)
    assert breaker.allow_request() is True
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.allow_request() is False
    assert breaker.status()["open"] is True
    breaker.record_success()
    assert breaker.allow_request() is True
