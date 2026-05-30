# Architecture

Lingshu Agent is a local-first custom Agent platform. The final local version uses React/Vite, FastAPI, SQLAlchemy, PostgreSQL, optional Redis, and Milvus or memory vector search.

## Runtime Shape

```text
React/Vite frontend (127.0.0.1:5174)
  -> FastAPI API (127.0.0.1:8000)
     -> auth/JWT and admin/user permission checks
     -> services layer
     -> PostgreSQL business tables
     -> OpenAI-compatible chat provider
     -> RAG pipeline
        -> PostgreSQL chunk metadata
        -> Milvus or memory vector store
        -> dense + BM25 + RRF + optional qwen3-rerank
        -> Redis cache when available
     -> SSE chat stream
```

## Roles And Product Boundary

Only two roles are used: `admin` and `user`.

- Admin: review agents, manage system presets, view read-only members, manage knowledge/tools.
- User: configure private models, create agents, submit publish review, chat with published agents, copy market agents.

The final frontend does not include invite-user or invite-list pages. Backend invite endpoints are disabled by default with `INVITE_API_ENABLED=false` and may remain only as a compatibility surface.

## Core Data

| Table | Responsibility |
| --- | --- |
| `users` | Local account, profile, avatar. |
| `workspace_members` | `admin` / `user` membership. |
| `user_model_configs` | User private base URL, encrypted API key, model name and capabilities. |
| `model_configs` | Admin system presets and fallback models. |
| `agents` | Draft agent base config. |
| `agent_settings` | Suggested questions, variables, memory, RAG and tool policy. |
| `agent_versions` | Published/review snapshot. |
| `knowledge_documents` | Knowledge document status and preview. |
| `knowledge_chunks` | Parent-child chunk metadata, content hash and embedding dimension. |
| `uploads` | One-turn chat image/document attachment. |
| `sessions`, `messages` | Chat history and citations. |
| `runs`, `run_steps` | Execution trace. |
| `session_memory` | Session summary memory. |
| `feedback` | Message feedback. |

## Chat Flow

```text
POST /api/agents/{agent_id}/chat/stream
  -> require access
  -> create/load session
  -> persist user message
  -> resolve draft or published snapshot
  -> validate document attachment capability
  -> validate and apply model reasoning capability when thinking_enabled is requested
  -> merge variables and memory
  -> if RAG enabled: retrieve bound knowledge
  -> call tools when bound
  -> call selected OpenAI-compatible chat model
  -> refuse if RAG evidence is insufficient and configured
  -> stream events and persist assistant message
```

`token` events are emitted while the OpenAI-compatible provider stream is being consumed. The assistant message is persisted after the run completes, so failed runs do not create a misleading successful assistant message.

Deep thinking is a runtime option, not a separate workflow. The selected user model or system preset must declare `supports_reasoning=true`; prompt-enhanced reasoning injects an additional thinking instruction, while unsupported models return a disabled `thinking_status` event.

Image attachments are passed through to the selected OpenAI-compatible chat model as `image_url` content. The runtime does not use `supports_image` to block sending, because provider capability probes are not reliable enough to be a product gate. `supports_image` remains diagnostic metadata from model tests. Document attachments are still locally validated through `supports_document`; documents are parsed into text by the platform before the model call.

Published mode reads `agent_versions.snapshot`, so draft edits after publish do not affect published chat until republished and approved.

## Fixed Ports

The local contract is fixed:

- API: `127.0.0.1:8000`
- Frontend: `127.0.0.1:5174`

When occupied, stop the old process and restart the same port. Do not silently switch ports.
