"""Embedding 缓存与 TTL 抖动单元测试（不依赖真实 Redis / 数据库）。

覆盖：
1. ttl_with_jitter 抖动范围与下限保护；
2. store 的 get_embedding / set_embedding 往返与 key 隔离；
3. embed() 第二次命中缓存、不再打外部 API；
4. 关闭缓存开关时每次都打 API（不回退误命中）。
"""

import time
from types import SimpleNamespace

from core.config import get_settings
from core.integrations import llm as llm_module
from core.services import rag_cache


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, tuple[str, float]] = {}

    def _live(self, key):
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


def _make_store(client) -> rag_cache.OptionalRedisStore:
    store = rag_cache.OptionalRedisStore.__new__(rag_cache.OptionalRedisStore)
    store.settings = get_settings()
    store._client = client
    store._error = ""
    store._runtime_error = ""
    return store


def _provider_with_fake_api(monkeypatch, embedding):
    provider = llm_module.OpenAICompatibleProvider()
    monkeypatch.setattr(provider, "_api_key", lambda *a, **k: "key")
    monkeypatch.setattr(provider, "_api_base", lambda *a, **k: "http://x")
    calls = {"n": 0}

    def fake_post(url, payload, api_key, **kwargs):
        calls["n"] += 1
        return {"data": [{"embedding": list(embedding)}]}

    monkeypatch.setattr(provider, "_post_json", fake_post)
    return provider, calls


def test_ttl_with_jitter_bounds():
    for _ in range(200):
        assert 900 <= rag_cache.ttl_with_jitter(1000, ratio=0.1) <= 1100
    assert rag_cache.ttl_with_jitter(1) == 1   # delta=0 → 返回原值
    assert rag_cache.ttl_with_jitter(0) == 1   # 下限保护，永不为 0


def test_embedding_roundtrip():
    store = _make_store(FakeRedis())
    assert store.get_embedding("m", "hello") is None
    assert store.set_embedding("m", "hello", [0.1, 0.2], 3600) is True
    assert store.get_embedding("m", "hello") == [0.1, 0.2]
    # 不同 model / 文本走不同 key，不串味
    assert store.get_embedding("m2", "hello") is None
    assert store.get_embedding("m", "world") is None


def test_embed_uses_cache(monkeypatch):
    monkeypatch.setattr(rag_cache, "redis_store", _make_store(FakeRedis()))
    monkeypatch.setattr(llm_module, "get_settings", lambda: SimpleNamespace(
        mock_llm=False, openai_embedding_model="text-embedding-v3",
        embedding_cache_enabled=True, embedding_cache_ttl_seconds=3600,
    ))
    provider, calls = _provider_with_fake_api(monkeypatch, [0.3, 0.4, 0.5])

    v1 = provider.embed("repeat me")
    v2 = provider.embed("repeat me")
    assert v1 == v2 == [0.3, 0.4, 0.5]
    assert calls["n"] == 1   # 第二次命中缓存，未再打 API


def test_embed_skips_cache_when_disabled(monkeypatch):
    monkeypatch.setattr(rag_cache, "redis_store", _make_store(FakeRedis()))
    monkeypatch.setattr(llm_module, "get_settings", lambda: SimpleNamespace(
        mock_llm=False, openai_embedding_model="m",
        embedding_cache_enabled=False, embedding_cache_ttl_seconds=3600,
    ))
    provider, calls = _provider_with_fake_api(monkeypatch, [1.0])

    provider.embed("x")
    provider.embed("x")
    assert calls["n"] == 2   # 关缓存时每次都打 API
