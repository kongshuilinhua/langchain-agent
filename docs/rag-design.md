# Knowledge And Retrieval Design

RAG 是智能体能力之一，但 embedding、rerank、Milvus、Redis 缓存等运行参数由后端统一配置。用户私有模型只负责主聊天模型，不负责知识库向量化。

## 当前链路

```text
knowledge document
  -> text extraction
  -> parent-child chunk
  -> backend embedding model
  -> PostgreSQL knowledge_chunks metadata
  -> Milvus or memory vector index
  -> dense retrieval
  -> Chinese BM25
  -> RRF fusion
  -> optional qwen3-rerank
  -> structured sources + rag_status
  -> answer or no-evidence refusal
```

## 配置项

所有默认值通过 `.env` 或 settings 管理：

```env
RAG_TOP_K=4
RAG_DENSE_TOP_K=12
RAG_BM25_TOP_K=12
RAG_RRF_K=60
RAG_RERANK_ENABLED=true
RAG_RERANK_MODEL=qwen3-rerank
RAG_RERANK_TOP_N=6
RAG_CACHE_ENABLED=true
RAG_CACHE_TTL_SECONDS=3600
RAG_REFUSE_WHEN_NO_EVIDENCE=true
MILVUS_COLLECTION=lingshu_chunks
MILVUS_DIMENSION=
UPLOAD_MAX_BYTES=8388608
```

`MILVUS_DIMENSION` 可以留空。留空时新 collection 会使用首次 upsert 的真实 embedding 维度，避免写死 32 维。

## 请求开关

智能体 settings 保存默认 RAG 配置：

```json
{
  "enabled_by_default": true,
  "top_k": 4,
  "dense_top_k": 12,
  "bm25_top_k": 12,
  "rrf_k": 60,
  "rerank_enabled": true,
  "rerank_top_n": 6,
  "cache_enabled": true,
  "refuse_when_no_evidence": true
}
```

聊天请求可以单轮覆盖：

```json
{
  "message": "请基于知识库回答",
  "mode": "published",
  "rag_enabled": true,
  "rag_options": {
    "top_k": 4,
    "rerank_enabled": true
  }
}
```

关闭 RAG 只跳过知识库检索，不影响附件上下文和工具调用。

## 结构化引用

`sources` 返回：

```json
{
  "document_id": 1,
  "chunk_id": "kb1-doc1-parent0-child0",
  "parent_id": "kb1-doc1-parent0",
  "title": "manual.pdf",
  "page": 3,
  "section": "故障码",
  "snippet": "引用片段",
  "score": 0.82,
  "retrieval_channel": "rerank"
}
```

## RAG 状态

`rag_status` SSE 事件包含：

- `enabled`, `effective_source`, `top_k`
- `dense.matched`
- `bm25.matched`
- `rrf.matched`
- `rerank.enabled`, `rerank.applied`, `rerank.error`
- `cache.enabled`, `cache.hit`, `cache.backend`
- `no_evidence`, `refuse_when_no_evidence`

## Redis

Redis 是增强组件，不是硬依赖：

- RAG 查询缓存使用 normalized query、workspace、knowledge base、content hash 和 retrieval config 生成 key。
- 知识库索引 job 状态写入 Redis；Redis 不可用时接口仍返回同步兼容状态。
- 默认 TTL 为 `RAG_CACHE_TTL_SECONDS`。

## 限制

- PDF 文本抽取不做 OCR。
- `qwen3-rerank` 调用失败会自动降级到 RRF 排序。
- 第一版证据不足判断以检索结果和关键词覆盖为主，不做复杂事实校验。
