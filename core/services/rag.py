from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from core.config import get_settings
from core.db.models import KnowledgeChunk, KnowledgeDocument
from core.integrations.llm import OpenAICompatibleProvider
from core.integrations import vector_store as vector_store_module
from core.services.rag_cache import redis_store


BM25_BATCH_SIZE = 1000

import threading

# Thread-safe global cache for compiled BM25 indices
# Key: (frozenset(knowledge_base_ids), version_hash) -> Value: (compiled_bm25_index, rows_data)
_BM25_INDEX_CACHE = {}
_BM25_CACHE_LOCK = threading.Lock()



@dataclass
class RagResult:
    sources: list[dict]
    status: dict


def retrieve(
    db: Session,
    *,
    workspace_id: int,
    knowledge_base_ids: list[int],
    query: str,
    config: dict,
    runtime_config: dict | None = None,
) -> RagResult:
    settings = get_settings()
    started_status = _base_status(query, knowledge_base_ids, config)
    if not knowledge_base_ids:
        started_status.update({"reason": "no_knowledge_base", "no_evidence": True})
        return RagResult([], started_status)

    cache_key = _cache_key(db, workspace_id=workspace_id, knowledge_base_ids=knowledge_base_ids, query=query, config=config)
    if config.get("cache_enabled", True):
        cached = redis_store.get_json(cache_key)
        if cached.hit and cached.value:
            status = cached.value.get("status", {})
            status.update({"cache": {"enabled": True, "hit": True, "backend": cached.backend}})
            return RagResult(cached.value.get("sources", []), status)

    provider = OpenAICompatibleProvider()
    query_vector = provider.embed(query, runtime_config=runtime_config)
    dense_hits = _dense_search(
        workspace_id=workspace_id,
        knowledge_base_ids=knowledge_base_ids,
        query_vector=query_vector,
        limit=int(config.get("dense_top_k") or settings.rag_dense_top_k),
    )
    bm25_hits = _bm25_search(
        db,
        workspace_id=workspace_id,
        knowledge_base_ids=knowledge_base_ids,
        query=query,
        limit=int(config.get("bm25_top_k") or settings.rag_bm25_top_k),
    )
    fused_hits = _rrf(dense_hits, bm25_hits, k=int(config.get("rrf_k") or settings.rag_rrf_k))
    rerank_applied = False
    rerank_error = ""
    final_hits = fused_hits
    if config.get("rerank_enabled", settings.rag_rerank_enabled) and fused_hits:
        try:
            final_hits = _rerank(
                provider,
                query=query,
                hits=fused_hits,
                top_n=int(config.get("rerank_top_n") or settings.rag_rerank_top_n),
                model=settings.rag_rerank_model,
            )
            rerank_applied = True
        except Exception as exc:
            rerank_error = str(exc)[:240]
            final_hits = fused_hits

    top_k = int(config.get("top_k") or settings.rag_top_k)
    sources = [_source_payload(hit) for hit in final_hits[:top_k]]
    no_evidence = not _has_evidence(sources, query)
    status = started_status | {
        "reason": "available" if sources else "no_match",
        "matched_chunks": len(final_hits),
        "sources_emitted": bool(sources),
        "dense": {"top_k": int(config.get("dense_top_k") or settings.rag_dense_top_k), "matched": len(dense_hits)},
        "bm25": {"top_k": int(config.get("bm25_top_k") or settings.rag_bm25_top_k), "matched": len(bm25_hits)},
        "rrf": {"k": int(config.get("rrf_k") or settings.rag_rrf_k), "matched": len(fused_hits)},
        "rerank": {
            "enabled": bool(config.get("rerank_enabled", settings.rag_rerank_enabled)),
            "applied": rerank_applied,
            "model": settings.rag_rerank_model,
            "error": rerank_error or None,
        },
        "cache": {"enabled": bool(config.get("cache_enabled", settings.rag_cache_enabled)), "hit": False, "backend": "redis" if redis_store.available else "none"},
        "no_evidence": no_evidence,
        "refuse_when_no_evidence": bool(config.get("refuse_when_no_evidence", settings.rag_refuse_when_no_evidence)),
        "rag_model": "environment",
    }
    if config.get("cache_enabled", True):
        redis_store.set_json(cache_key, {"sources": sources, "status": status}, settings.rag_cache_ttl_seconds)
    return RagResult(sources, status)


def _base_status(query: str, knowledge_base_ids: list[int], config: dict) -> dict:
    settings = get_settings()
    return {
        "enabled": True,
        "knowledge_base_ids": knowledge_base_ids,
        "query": query,
        "top_k": int(config.get("top_k") or settings.rag_top_k),
        "matched_chunks": 0,
        "sources_emitted": False,
        "reason": "started",
    }


def _dense_search(*, workspace_id: int, knowledge_base_ids: list[int], query_vector: list[float], limit: int) -> list[dict]:
    hits = []
    for kb_id in knowledge_base_ids:
        for hit in vector_store_module.vector_store.search(
            query_vector,
            limit=limit,
            filters={"workspace_id": workspace_id, "knowledge_base_id": kb_id},
        ):
            metadata = hit.metadata or {}
            hits.append(
                {
                    "id": metadata.get("chunk_id") or hit.vector_id,
                    "vector_id": hit.vector_id,
                    "text": hit.text,
                    "score": float(hit.score),
                    "dense_score": float(hit.score),
                    "retrieval_channel": "dense",
                    "metadata": metadata,
                }
            )
    return sorted(hits, key=lambda item: item["score"], reverse=True)[:limit]


def _bm25_search(db: Session, *, workspace_id: int, knowledge_base_ids: list[int], query: str, limit: int) -> list[dict]:
    # Calculate the exact version hash representing the state of all KBs
    stats = (
        db.query(
            KnowledgeDocument.knowledge_base_id,
            func.count(KnowledgeDocument.id),
            func.max(KnowledgeDocument.updated_at),
        )
        .filter(KnowledgeDocument.knowledge_base_id.in_(knowledge_base_ids))
        .group_by(KnowledgeDocument.knowledge_base_id)
        .all()
    )
    parts = [f"{kb_id}:{count}:{max_updated.isoformat() if max_updated else '0'}" for kb_id, count, max_updated in sorted(stats, key=lambda x: x[0])]
    version = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    
    cache_key = (frozenset(knowledge_base_ids), version)
    
    # Try fetching from global memory cache
    with _BM25_CACHE_LOCK:
        cached_data = _BM25_INDEX_CACHE.get(cache_key)
        
    if cached_data:
        bm25_index, rows_data = cached_data
    else:
        # Retrieve all chunks and build index
        query_chunks = (
            db.query(KnowledgeChunk)
            .filter(
                KnowledgeChunk.workspace_id == workspace_id,
                KnowledgeChunk.knowledge_base_id.in_(knowledge_base_ids)
            )
        )
        total_count = query_chunks.count()
        if total_count == 0:
            return []
            
        rows_data = []
        tokenized_corpus = []
        
        for offset in range(0, total_count, BM25_BATCH_SIZE):
            batch = query_chunks.order_by(KnowledgeChunk.id.asc()).offset(offset).limit(BM25_BATCH_SIZE).all()
            for row in batch:
                meta = row.metadata_ or {}
                tokens = meta.get("tokens")
                if tokens is None:
                    tokens = _tokenize(row.text)
                tokenized_corpus.append(tokens)
                rows_data.append({
                    "id": row.chunk_id or row.vector_id,
                    "vector_id": row.vector_id,
                    "text": row.text,
                    "metadata": _row_metadata(row),
                    "tokens": tokens
                })
            db.expire_all()
            
        # Compile the BM25 index
        try:
            from rank_bm25 import BM25Okapi
            bm25_index = BM25Okapi(tokenized_corpus)
        except Exception:
            bm25_index = None
            
        # Store compiled index in the global memory cache
        with _BM25_CACHE_LOCK:
            # Evict old cache items to control memory usage
            if len(_BM25_INDEX_CACHE) > 100:
                _BM25_INDEX_CACHE.clear()
            _BM25_INDEX_CACHE[cache_key] = (bm25_index, rows_data)
    
    tokenized_query = _tokenize(query)
    
    # Calculate BM25 scores
    if bm25_index:
        try:
            scores = [float(s) for s in bm25_index.get_scores(tokenized_query)]
        except Exception:
            scores = _bm25_scores([r["tokens"] for r in rows_data], tokenized_query)
    else:
        scores = _bm25_scores([r["tokens"] for r in rows_data], tokenized_query)
        
    hits = []
    query_token_set = set(tokenized_query)
    
    for data, score in zip(rows_data, scores):
        row_tokens = data["tokens"]
        overlap = query_token_set.intersection(row_tokens)
        if score <= 0 and tokenized_query and not overlap:
            continue
        if score <= 0 and overlap:
            score = len(overlap) / max(len(query_token_set), 1)
        hits.append(
            {
                "id": data["id"],
                "vector_id": data["vector_id"],
                "text": data["text"],
                "score": float(score),
                "bm25_score": float(score),
                "retrieval_channel": "bm25",
                "metadata": data["metadata"],
            }
        )
    return sorted(hits, key=lambda item: item["score"], reverse=True)[:limit]


def _rrf(dense_hits: list[dict], bm25_hits: list[dict], *, k: int) -> list[dict]:
    combined: dict[str, dict] = {}
    for channel, hits in (("dense", dense_hits), ("bm25", bm25_hits)):
        for rank, hit in enumerate(hits, start=1):
            key = hit["id"]
            item = combined.setdefault(key, {**hit, "score": 0.0, "channels": set()})
            item["score"] += 1 / (k + rank)
            item["channels"].add(channel)
            if channel == "dense":
                item["dense_score"] = hit.get("dense_score", hit.get("score", 0.0))
            if channel == "bm25":
                item["bm25_score"] = hit.get("bm25_score", hit.get("score", 0.0))
    results = []
    for item in combined.values():
        channels = sorted(item.pop("channels", []))
        item["retrieval_channel"] = "rrf:" + "+".join(channels)
        results.append(item)
    return sorted(results, key=lambda item: item["score"], reverse=True)


def _rerank(provider: OpenAICompatibleProvider, *, query: str, hits: list[dict], top_n: int, model: str) -> list[dict]:
    documents = [hit["text"] for hit in hits]
    ranked = provider.rerank(query, documents, top_n=min(top_n, len(documents)), model=model)
    output = []
    used = set()
    for item in ranked:
        index = item["index"]
        if index < 0 or index >= len(hits) or index in used:
            continue
        used.add(index)
        hit = {**hits[index]}
        hit["score"] = float(item.get("relevance_score", hit.get("score", 0)))
        hit["retrieval_channel"] = "rerank"
        output.append(hit)
    output.extend(hit for index, hit in enumerate(hits) if index not in used)
    return output


def _source_payload(hit: dict) -> dict:
    metadata = hit.get("metadata") or {}
    title = metadata.get("title") or metadata.get("filename") or f"document-{metadata.get('document_id', '')}".strip("-")
    return {
        "source_id": title,
        "document_id": metadata.get("document_id"),
        "chunk_id": metadata.get("chunk_id") or hit.get("id"),
        "parent_id": metadata.get("parent_id") or metadata.get("chunk_id") or hit.get("id"),
        "title": title or "knowledge",
        "page": metadata.get("page"),
        "section": metadata.get("section") or "",
        "snippet": (hit.get("text") or "")[:360],
        "score": float(hit.get("score") or 0),
        "dense_score": float(hit.get("dense_score") or 0),
        "bm25_score": float(hit.get("bm25_score") or 0),
        "retrieval_channel": hit.get("retrieval_channel") or "dense",
    }


def _row_metadata(row: KnowledgeChunk) -> dict:
    metadata = dict(row.metadata_ or {})
    metadata.update(
        {
            "workspace_id": row.workspace_id,
            "knowledge_base_id": row.knowledge_base_id,
            "document_id": row.document_id,
            "chunk_id": row.chunk_id or row.vector_id,
            "parent_id": row.parent_id or row.vector_id,
            "title": row.title,
            "page": row.page,
            "section": row.section,
            "content_hash": row.content_hash,
        }
    )
    return metadata


def _tokenize(text: str) -> list[str]:
    try:
        import jieba

        return [token.strip().lower() for token in jieba.lcut(text) if token.strip()]
    except Exception:
        return [token.lower() for token in re.findall(r"[\w\u4e00-\u9fff]+", text)]


def _bm25_scores(corpus: list[list[str]], query_tokens: list[str]) -> list[float]:
    if not corpus or not query_tokens:
        return [0.0 for _ in corpus]
    try:
        from rank_bm25 import BM25Okapi

        return [float(score) for score in BM25Okapi(corpus).get_scores(query_tokens)]
    except Exception:
        doc_count = len(corpus)
        avg_len = sum(len(doc) for doc in corpus) / max(doc_count, 1)
        doc_freq = {}
        for doc in corpus:
            for token in set(doc):
                doc_freq[token] = doc_freq.get(token, 0) + 1
        scores = []
        for doc in corpus:
            score = 0.0
            length = len(doc) or 1
            for token in query_tokens:
                freq = doc.count(token)
                if not freq:
                    continue
                idf = math.log((doc_count - doc_freq.get(token, 0) + 0.5) / (doc_freq.get(token, 0) + 0.5) + 1)
                denom = freq + 1.5 * (1 - 0.75 + 0.75 * length / max(avg_len, 1))
                score += idf * (freq * 2.5 / denom)
            scores.append(score)
        return scores


RAG_CONVERSATIONAL_STOPWORDS = {
    "这个", "那个", "能够", "可以", "能够", "帮我", "做什么", "做点什么", 
    "功能", "介绍", "自己", "是谁", "谁是", "你好", "您好", "怎么", "如何", 
    "什么", "智能体", "机器人", "助手", "客服", "智能", "系统", "功能", 
    "回答", "问题", "帮我", "谢谢", "再见", "请问", "关于", "内容", "我们",
    "你们", "他们", "它们", "什么样", "哪些", "哪个", "帮助"
}


def _has_evidence(sources: list[dict], query: str) -> bool:
    if not sources:
        return False
        
    # 过滤掉常见的辅助性/对话性停用词，避免其误匹配知识库中的通用词（例如“智能”、“系统”等）
    tokens = [
        token for token in _tokenize(query) 
        if len(token) > 1 and token.lower() not in RAG_CONVERSATIONAL_STOPWORDS
    ]
    
    snippets = " ".join(source.get("snippet", "") for source in sources).lower()
    
    # 1. 关键字匹配：如果查询中过滤后的关键分词与返回的文章片段有交集
    if tokens and any(token.lower() in snippets for token in tokens):
        return True
        
    # 2. 检索得分质量校验：
    # 如果没有关键字直接重叠，我们需要检查密集检索（dense）或重排（rerank）的得分是否达到合理的相关度阈值，
    # 从而避免非相关对话（如打招呼、问好）的纯随机向量邻居被当作“有证据”的知识返回。
    for source in sources:
        channel = source.get("retrieval_channel", "")
        # 如果是 BM25 检索到了且得分大于 0，说明存在一定的词频重叠
        if "bm25" in channel and source.get("bm25_score", 0.0) > 0:
            return True
        # 如果是 Dense 检索，其余相似度（通常为余弦相似度）必须在合理阈值（>= 0.40）之上才算作真实证据
        if "dense" in channel and source.get("dense_score", 0.0) >= 0.40:
            return True
        # 如果是 Rerank 重排，重排得分通常在相似度范围内，也需要 >= 0.40 算作证据
        if "rerank" in channel and (source.get("score", 0.0) >= 0.40 or source.get("dense_score", 0.0) >= 0.40):
            return True
            
    return False


def _cache_key(db: Session, *, workspace_id: int, knowledge_base_ids: list[int], query: str, config: dict) -> str:
    stats = (
        db.query(
            KnowledgeDocument.knowledge_base_id,
            func.count(KnowledgeDocument.id),
            func.max(KnowledgeDocument.updated_at),
        )
        .filter(KnowledgeDocument.knowledge_base_id.in_(knowledge_base_ids))
        .group_by(KnowledgeDocument.knowledge_base_id)
        .all()
    )
    parts = [f"{kb_id}:{count}:{max_updated.isoformat() if max_updated else '0'}" for kb_id, count, max_updated in sorted(stats, key=lambda x: x[0])]
    version = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    payload = {
        "workspace_id": workspace_id,
        "knowledge_base_ids": sorted(knowledge_base_ids),
        "query": re.sub(r"\s+", " ", query).strip().lower(),
        "version": version,
        "config": config,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"rag:{digest}"
