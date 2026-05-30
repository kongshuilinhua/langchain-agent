# Agent Capability Final Scope

This document records the final local-version scope for Agent capabilities: model configuration, custom tools, knowledge/RAG, memory, and builder/debug experience.

This track does not include visual workflow canvas, public App/API/embed publishing, full observability/evaluation platform, billing, OAuth, or complex RBAC/operations features.

## Goal

The target user journey is:

```text
User configures a Qwen/DashScope or OpenAI-compatible model
  -> creates an Agent
  -> binds knowledge bases
  -> adds built-in search or custom HTTP tools
  -> configures session memory and per-user Agent memory
  -> validates behavior in Builder debug mode
  -> publishes the Agent to the internal market
  -> chats with the published Agent inside this platform
```

The result should feel close to the Agent-building center of Coze or Dify, without copying their full workflow engine or external publishing surface.

## Current Baseline

The current project already has:

- Local account and JWT authentication.
- Workspace membership with `admin` and `user` roles.
- Agent draft editing, publishing review, published snapshot, and internal market copy.
- User-private model configs through `/api/user-models`.
- Knowledge base metadata, document chunks, vector retrieval, RAG toggle, and source citations.
- Chat sessions, messages, feedback, run records, and run steps.
- React/Vite main chat page and Coze-style Agent builder.

The final local version also has:

- Qwen/DashScope as the recommended default example. `OpenAI-compatible` is protocol wording only and does not imply GPT as the default.
- User-created HTTP tools, built-in search tools, tool testing, Agent binding, and run-step visibility.
- Knowledge text/file upload for TXT, MD, CSV, PDF, and DOCX, with indexing state and chunk statistics.
- Session summary memory plus per-user per-Agent memory profile through `/memory-profile`.
- Model-declared deep-thinking capability through `supports_reasoning`, `reasoning_type`, and `reasoning_label`.
- Builder debug events for RAG, search, thinking status, tool calls, and memory usage.

## Non-Goals

Do not implement these in this track:

- Visual workflow canvas, node branching, loops, code nodes, or drag-and-drop workflow editing.
- Public App publishing, public API keys, iframe/embed widgets, SDK release, or external share pages.
- Full observability dashboard, evaluation datasets, annotation review, cost charts, or production monitoring.
- Billing, OAuth app authorization, plugin marketplace, organization-level fine-grained RBAC, or tenant operations.

## Public Interface Baseline

### Models

Keep `/api/user-models` as the ordinary-user model configuration flow.

Required behavior:

- Qwen/DashScope preset is the recommended default example.
- `OpenAI-compatible` means protocol compatibility only; it must not imply GPT is the default.
- API responses must not include raw `api_key` or encrypted key values.
- Agent runtime resolution order stays: `agent.user_model_config_id` -> current user's default enabled model config -> environment fallback -> mock LLM.
- Deep thinking is opt-in per turn through `thinking_enabled`; it is applied only when the selected model config declares reasoning support.

### Tools

Tool management endpoints:

```text
GET    /api/tools
POST   /api/tools
PATCH  /api/tools/{tool_id}
DELETE /api/tools/{tool_id}
POST   /api/tools/{tool_id}/test
```

Tool types:

- `builtin_search`: platform-provided web search tool.
- `http`: user-defined HTTP tool.

HTTP tool fields:

- `name`, `label`, `description`
- `method`, `url`
- `headers_schema`, `query_schema`, `body_schema`
- `auth_type`, `encrypted_secret`
- `response_path`, `timeout_seconds`, `enabled`

### Knowledge/RAG

Knowledge document ingestion supports both text payloads and file-derived payloads:

- TXT
- MD
- CSV
- PDF
- DOCX

Document list fields include:

- `status`
- `chunk_count`
- `text_preview`
- `error_message`
- `created_at`

Chat requests continue to use `rag_enabled` for single-turn override.

### Memory

Long-term Agent memory endpoints:

```text
GET    /api/agents/{agent_id}/memory-profile
PATCH  /api/agents/{agent_id}/memory-profile
DELETE /api/agents/{agent_id}/memory-profile
```

Memory is scoped by `workspace_id + user_id + agent_id`.

Stored fields:

- `enabled`
- `summary`
- `facts`
- `preferences`
- `updated_at`

### Debug SSE Events

The existing chat stream keeps `token`, `sources`, `done`, and `error`.

Builder/debug mode may additionally return:

```text
rag_status
thinking_status
tool_call
memory_used
```

The normal chat page can ignore these events.

## Data Baseline

The SQL/data design covers:

- Extending `tools` for custom tool definitions, auth metadata, encrypted secret, ownership, and execution settings.
- Extending `agent_tools` for per-Agent options if needed.
- Adding `agent_memory_profiles`.
- Adding or confirming knowledge document status and error fields.
- Reusing `user_model_configs`, `knowledge_bases`, `knowledge_documents`, `knowledge_chunks`, `sessions`, `messages`, `runs`, and `run_steps`.

Primary database target:

- Product and Docker Compose deployments use PostgreSQL 16 as the business database for users, agents, sessions, messages, model configs, tools, knowledge metadata, memory, runs, and feedback.
- The PostgreSQL SQL baseline lives at `sql/postgresql/001_init_schema.sql`.
- PostgreSQL is the only documented business database for development, Compose, and deployment.

Migration policy:

- The project does not currently require Alembic.
- PostgreSQL schema changes live in `sql/postgresql/001_init_schema.sql` unless the implementation phase adopts a migration tool.
- Every schema change must support the PostgreSQL Docker target.

## Documentation Baseline

These documents must stay consistent with the final scope:

- `README.md`
- `docs/agent-capability-plan.md`
- `docs/api-design.md`
- `docs/storage-design.md`
- `docs/architecture.md`
- `docs/rag-design.md`
- `docs/product-requirements.md`
- `docs/troubleshooting.md`
- all `docs/dispatch/agent-capability-day*.md` task sheets

The docs must not present excluded features as product entry points.

## Security Requirements

Custom tools introduce network and secret-handling risk. Minimum controls:

- HTTP tools allow only `https://` URLs.
- Block localhost, loopback, private IP ranges, link-local IP ranges, and cloud metadata IPs.
- Reject `file://`, `ftp://`, and other non-HTTP protocols.
- Encrypt tool secrets at rest.
- Never return raw secrets in API responses, errors, logs, run steps, or published snapshots.
- Apply request timeout and response-size limits.
- Treat HTTP/search results as untrusted context. Do not execute instructions returned by tools.

## Validation Commands

Backend:

```powershell
python -m pytest -q
```

Frontend:

```powershell
cd frontend
npm run build
```

Docs:

```powershell
python scripts/check_markdown_links.py
python scripts/check_text_encoding.py
```

Full release check when dependencies are available:

```powershell
python scripts/release_check.py --with-frontend
```

If the default Python lacks dependencies, use the project virtual environment before judging failures as product failures.

## Acceptance Criteria

- New users see Qwen/DashScope or user-owned compatible gateway as the recommended model path.
- A user can create an HTTP tool, test it, bind it to an Agent, and see the tool result affect a Builder chat response.
- A user can enable built-in search for an Agent and receive source-aware answers.
- A user can upload supported documents into a knowledge base and verify chunk/index status.
- A user can enable session summary memory and user memory for an Agent, see it used in chat, and delete the user memory profile.
- Builder debug mode shows model, RAG, tool, and memory decisions without exposing secrets.
- Existing Agent create/edit/publish/review/market-copy/session/feedback flows do not regress.

