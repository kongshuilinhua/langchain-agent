# Storage Design

Lingshu Agent final local version uses PostgreSQL for business data, Milvus or memory fallback for vectors, and optional Redis for cache/job state.

## PostgreSQL

PostgreSQL is the source of truth for:

- users, workspace members and roles
- user private model configs and system model presets
- agents, agent settings and agent versions
- knowledge bases, documents and chunk metadata
- tools and agent-tool bindings
- sessions, messages, runs, run steps, feedback
- session summary memory
- uploads used as one-turn chat attachments

`knowledge_chunks` stores parent-child metadata:

- `parent_id`
- `chunk_id`
- `title`
- `page`
- `section`
- `content_hash`
- `embedding_model`
- `embedding_dimension`
- `metadata`

## Milvus

Milvus stores vector payloads for knowledge chunks. Collection name is `MILVUS_COLLECTION`, default `lingshu_chunks`.

`MILVUS_DIMENSION` can be left empty. If empty, the backend creates a new collection with the first real embedding vector dimension.

The memory vector backend remains available for tests and local fallback through `LINGSHU_VECTOR_BACKEND=memory`.

## Redis

Redis is optional and not required for login, sessions or chat persistence.

Current Redis uses:

- RAG query cache
- knowledge index job status

If Redis is unavailable, the system still runs and returns cache/job fallback status.

## Uploads

`UPLOAD_MAX_BYTES` controls both chat attachment and knowledge document upload limits. Documents uploaded in chat are stored as one-turn attachment context and do not automatically enter a knowledge base.
