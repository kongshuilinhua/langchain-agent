from __future__ import annotations

import json
from dataclasses import dataclass

from core.config import get_settings


@dataclass
class CacheLookup:
    hit: bool
    value: dict | None = None
    backend: str = "none"


class OptionalRedisStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        self._error = ""
        if not self.settings.redis_url:
            return
        try:
            import redis

            self._client = redis.Redis.from_url(self.settings.redis_url, decode_responses=True, socket_timeout=1)
            self._client.ping()
        except Exception as exc:
            self._client = None
            self._error = str(exc)[:240]

    @property
    def available(self) -> bool:
        return self._client is not None

    def status(self) -> dict:
        configured = bool(self.settings.redis_url)
        return {
            "configured": configured,
            "available": self.available,
            "backend": "redis" if self.available else "none",
            "required": bool(configured and self.settings.rag_cache_enabled),
            "error": self._error or None,
        }

    def get_json(self, key: str) -> CacheLookup:
        if not self._client:
            return CacheLookup(hit=False)
        try:
            raw = self._client.get(key)
        except Exception:
            return CacheLookup(hit=False)
        if not raw:
            return CacheLookup(hit=False, backend="redis")
        try:
            return CacheLookup(hit=True, value=json.loads(raw), backend="redis")
        except json.JSONDecodeError:
            return CacheLookup(hit=False, backend="redis")

    def set_json(self, key: str, value: dict, ttl_seconds: int) -> None:
        if not self._client:
            return
        try:
            self._client.setex(key, max(int(ttl_seconds), 1), json.dumps(value, ensure_ascii=False))
        except Exception:
            return

    def set_job(self, job_id: str, value: dict, ttl_seconds: int = 86400) -> None:
        self.set_json(f"knowledge_job:{job_id}", value, ttl_seconds)

    def get_job(self, job_id: str) -> CacheLookup:
        return self.get_json(f"knowledge_job:{job_id}")


redis_store = OptionalRedisStore()
