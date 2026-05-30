# API Design

This document records the final local API contract for Lingshu Agent.

All business endpoints require Bearer JWT except `GET /api/health`, `POST /api/auth/register`, and `POST /api/auth/login`.

## Auth And Members

- `POST /api/auth/register`: register the first admin. The backend still accepts `invite_token` for compatibility, but the final frontend does not expose invite UI.
- `POST /api/auth/login`
- `GET /api/auth/me`
- `PATCH /api/auth/me`: update name and avatar data URL.
- `GET /api/workspaces/current`
- `GET /api/workspaces/members`: admin read-only member list.

Roles are `admin` and `user`. No invite-user page or invite-list page is part of the final UI.

The invite API is disabled by default through `INVITE_API_ENABLED=false`. When disabled, `/api/workspaces/invites` returns 404 and does not expose invite tokens. This is a compatibility surface only, not a final-product path.

## User Private Models

User model configs are the main model path:

- `GET /api/user-models`
- `POST /api/user-models`
- `PATCH /api/user-models/{config_id}`
- `DELETE /api/user-models/{config_id}`
- `POST /api/user-models/{config_id}/test`
- `POST /api/user-models/test`

Create request:

```json
{
  "display_name": "My Qwen",
  "provider": "openai-compatible",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "api_key": "sk-...",
  "chat_model": "qwen-plus",
  "supports_image": false,
  "supports_document": true,
  "supports_reasoning": true,
  "reasoning_type": "prompt",
  "reasoning_label": "提示词增强",
  "max_context": 131072,
  "default_temperature": 0.4,
  "enabled": true,
  "is_default": true
}
```

Responses return `has_api_key` and never return plaintext `api_key` or encrypted secret fields.

Capability tests return `detected_capabilities.image_confirmed`, `image_declared`, and `image_status`. For user-owned model configs, persisted `supports_image` means the backend image probe succeeded for the current `base_url` + `api_key` + `chat_model`; it is diagnostic metadata, not a runtime gate. Chat image attachments are still sent to the selected model even when `supports_image=false`.

The model test action is exposed in the frontend edit dialog for an existing model config. The list row keeps only state/edit/key/delete actions so testing details stay close to editable connection fields.

System model APIs under `/api/admin/models` remain admin-only presets and fallback. Ordinary users should not be guided to the admin model form.

## Agents

- `GET /api/agents`
- `POST /api/agents`
- `GET /api/agents/{agent_id}`
- `PATCH /api/agents/{agent_id}`
- `DELETE /api/agents/{agent_id}`
- `POST /api/agents/{agent_id}/publish`
- `GET /api/agents/{agent_id}/versions`
- `GET /api/agents/{agent_id}/draft`

普通用户发布后状态为 `pending_review`；管理员审核通过后进入市场。

Agent RAG config:

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

## Review And Market

- `GET /api/admin/agent-reviews`
- `POST /api/admin/agent-reviews/{agent_id}/approve`
- `POST /api/admin/agent-reviews/{agent_id}/reject`
- `GET /api/market/agents`
- `POST /api/market/agents/{agent_id}/copy`

## Knowledge And Uploads

- `GET /api/knowledge-bases`
- `POST /api/knowledge-bases`
- `POST /api/knowledge-bases/{kb_id}/documents`
- `GET /api/knowledge-bases/{kb_id}/documents`
- `DELETE /api/knowledge-bases/{kb_id}/documents/{document_id}`
- `POST /api/knowledge-bases/{kb_id}/index`
- `GET /api/knowledge/jobs/{job_id}`
- `POST /api/uploads`

Supported document types: TXT, MD, CSV, PDF, DOCX. Upload limit is `UPLOAD_MAX_BYTES`.

Users may create and write their own knowledge bases. Admins can manage all knowledge bases in the workspace. A normal user cannot write another user's knowledge base.

`POST /api/uploads` returns `preview_url` for image uploads so the chat composer can show an inline image preview before sending. Document uploads return `text_preview` instead.

## Chat Stream

`POST /api/agents/{agent_id}/chat/stream`

```json
{
  "message": "问题内容",
  "session_id": 1,
  "mode": "published",
  "rag_enabled": true,
  "rag_options": {
    "top_k": 4,
    "rerank_enabled": true
  },
  "thinking_enabled": true,
  "variables": {},
  "attachments": [
    {"id": "upload_123", "type": "image", "mime_type": "image/png"}
  ]
}
```

SSE events:

- `rag_status`
- `thinking_status`
- `tool_call`
- `memory_used`
- `run_step`
- `token`
- `sources`
- `done`
- `error`

`sources` are structured citations with `document_id`, `chunk_id`, `parent_id`, `title`, `page`, `section`, `snippet`, `score`, and `retrieval_channel`.

`thinking_enabled` only takes effect when the selected user or system model declares `supports_reasoning=true`. `thinking_status` reports whether the request used prompt-enhanced reasoning, native reasoning, or was disabled because the model does not support it.

Image attachments are not blocked by `supports_image`. The backend sends images to the provider as OpenAI-compatible `{"type":"image_url"}` content. If the provider rejects the payload, the SSE stream emits an `error` event with a sanitized message. Document attachments are different: when the selected model config has `supports_document=false`, the backend rejects document attachments before the model call because document parsing is a local platform capability.

`token` events are emitted from the model provider stream when available. `error` events return a stable `error_code` and user-safe message; provider URLs, API keys, stack traces, and raw gateway bodies must not be exposed.

## Sessions, Runs, Feedback

- `GET /api/agents/{agent_id}/sessions`
- `GET /api/sessions/{session_id}`
- `PATCH /api/sessions/{session_id}`
- `DELETE /api/sessions/{session_id}`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/steps`
- `POST /api/messages/{message_id}/feedback`
