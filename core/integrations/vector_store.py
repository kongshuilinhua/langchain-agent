from __future__ import annotations

import math
import socket
import hashlib
from urllib.parse import urlparse
from dataclasses import dataclass
from typing import Iterable

from core.config import get_settings


@dataclass
class VectorHit:
    vector_id: str
    text: str
    score: float
    metadata: dict


class MemoryVectorStore:
    def __init__(self) -> None:
        self._items: list[tuple[str, list[float], str, dict]] = []

    def upsert(self, vector_id: str, vector: list[float], text: str, metadata: dict) -> None:
        self._items = [item for item in self._items if item[0] != vector_id]
        self._items.append((vector_id, vector, text, metadata))

    def search(self, vector: list[float], *, limit: int = 5, filters: dict | None = None) -> list[VectorHit]:
        filters = filters or {}
        hits = []
        for vector_id, item_vector, text, metadata in self._items:
            if any(metadata.get(key) != value for key, value in filters.items()):
                continue
            hits.append(VectorHit(vector_id, text, _cosine(vector, item_vector), metadata))
        return sorted(hits, key=lambda item: item.score, reverse=True)[:limit]

    def delete(self, *, filters: dict) -> None:
        self._items = [
            item
            for item in self._items
            if not all(item[3].get(key) == value for key, value in filters.items())
        ]


class MilvusVectorStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._fallback = MemoryVectorStore()
        self._client = None
        self._error = ""
        if self.settings.vector_backend == "milvus":
            try:
                from pymilvus import MilvusClient

                self._probe_milvus_endpoint()
                self._client = MilvusClient(uri=self.settings.milvus_uri, token=self.settings.milvus_token, timeout=2)
                self._client.list_collections(timeout=2)
            except Exception as exc:
                self._client = None
                self._error = str(exc)[:240]

    @property
    def available(self) -> bool:
        return self.settings.vector_backend != "milvus" or self._client is not None

    @property
    def using_fallback(self) -> bool:
        return self.settings.vector_backend == "milvus" and self._client is None

    def status(self) -> dict:
        return {
            "backend": self.settings.vector_backend,
            "configured_backend": self.settings.vector_backend,
            "active_backend": "milvus" if self._client else "memory",
            "collection": self.settings.milvus_collection if self.settings.vector_backend == "milvus" else None,
            "uri": self.settings.milvus_uri if self.settings.vector_backend == "milvus" else None,
            "available": self.available,
            "fallback": self.using_fallback,
            "error": self._error or None,
        }

    def upsert(self, vector_id: str, vector: list[float], text: str, metadata: dict) -> None:
        if not self._client:
            self._fallback.upsert(vector_id, vector, text, metadata)
            return
        self._ensure_collection(len(vector))
        payload = {"id": _int64_id(vector_id), "vector": vector, "text": text, "vector_id": vector_id, **metadata}
        self._client.upsert(collection_name=self.settings.milvus_collection, data=[payload])

    def search(self, vector: list[float], *, limit: int = 5, filters: dict | None = None) -> list[VectorHit]:
        if not self._client:
            return self._fallback.search(vector, limit=limit, filters=filters)
        self._ensure_collection(len(vector))
        expr = build_milvus_filter(filters or {})
        results = self._client.search(
            collection_name=self.settings.milvus_collection,
            data=[vector],
            limit=limit,
            filter=expr or "",
            output_fields=[
                "text",
                "vector_id",
                "workspace_id",
                "knowledge_base_id",
                "document_id",
                "chunk_id",
                "parent_id",
                "filename",
                "title",
                "page",
                "section",
                "content_hash",
            ],
        )
        hits = []
        for item in results[0]:
            entity = item.get("entity", {})
            hits.append(
                VectorHit(
                    vector_id=str(item.get("id")),
                    text=entity.get("text", ""),
                    score=float(item.get("distance", 0)),
                    metadata={key: value for key, value in entity.items() if key != "text"},
                )
            )
        return hits

    def delete(self, *, filters: dict) -> None:
        if not self._client:
            self._fallback.delete(filters=filters)
            return
        expr = build_milvus_filter(filters)
        if expr:
            self._client.delete(collection_name=self.settings.milvus_collection, filter=expr)

    def _ensure_collection(self, vector_dimension: int) -> None:
        if not self._client:
            return
        if self._client.has_collection(self.settings.milvus_collection):
            return
        dimension = self.settings.milvus_dimension or vector_dimension
        self._client.create_collection(
            collection_name=self.settings.milvus_collection,
            dimension=dimension,
            auto_id=False,
        )

    def _probe_milvus_endpoint(self) -> None:
        parsed = urlparse(self.settings.milvus_uri)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 19530)
        if not host:
            raise ValueError("MILVUS_URI is invalid")
        with socket.create_connection((host, port), timeout=1):
            return


def build_milvus_filter(filters: dict) -> str:
    parts = []
    for key, value in filters.items():
        if isinstance(value, str):
            safe = value.replace('"', '\\"')
            parts.append(f'{key} == "{safe}"')
        else:
            parts.append(f"{key} == {value}")
    return " and ".join(parts)


def _cosine(left: Iterable[float], right: Iterable[float]) -> float:
    left_values = list(left)
    right_values = list(right)
    numerator = sum(a * b for a, b in zip(left_values, right_values))
    left_norm = math.sqrt(sum(a * a for a in left_values)) or 1.0
    right_norm = math.sqrt(sum(b * b for b in right_values)) or 1.0
    return numerator / (left_norm * right_norm)


def _int64_id(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False) & ((1 << 63) - 1)


vector_store = MilvusVectorStore()
