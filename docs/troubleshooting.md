# Troubleshooting

## Port Already In Use

Ports are fixed: backend `8000`, frontend `5174`.

```powershell
Get-NetTCPConnection -LocalPort 8000,5174 -State Listen -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,OwningProcess
```

Stop the old Lingshu Agent process and restart the same port.

## Model Does Not Answer

Recommended path: configure your own Qwen/DashScope or OpenAI-compatible gateway in “我的模型”.

For backend fallback, check:

```env
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_API_KEY=...
OPENAI_MODEL=qwen-plus
```

## Image Upload Sends But The Model Fails

This is expected when the selected upstream model or gateway does not accept OpenAI-compatible `image_url` content. The app no longer blocks image sending based on pre-detected `supports_image`; it forwards the image and shows the sanitized provider error or model response.

Check:

- the selected “我的模型” config points to the intended `chat_base_url`
- `chat_model` is the exact model name from the provider console
- the provider supports image input through the OpenAI Chat Completions compatible endpoint
- the edit dialog's “测试连接” result for `chat` and image probe; image probe failure is diagnostic and does not disable sending

If a model is text-only, either switch to a vision-capable model or let the provider return the unsupported-image message in chat.

## RAG Has No Sources

Check:

- the agent has bound knowledge bases
- `rag_enabled` is on in the chat composer
- documents are indexed
- backend embedding config is available or mock mode is enabled
- `rag_status` shows dense/BM25/RRF matches

## Redis Unavailable

Redis is optional. Cache and job state degrade to miss/unknown, while chat and RAG still run.

## Health Is Degraded

Open `GET /api/health` first. The response reports database, Redis, vector store, model, embedding, CORS and startup status separately.

- `database.available=false`: PostgreSQL is unreachable or initialization failed.
- `vector_store.fallback=true`: Milvus is configured but unavailable; vectors are using in-memory fallback.
- `embedding.available=false`: real RAG embedding is not available because the model key/model name/vector backend is missing or degraded.
- `model.mock=true`: chat is using the deterministic local mock path.

The API still starts when database initialization fails so the frontend can show the degraded state instead of a silent connection failure.

## Running Tests Safely

`pytest` needs `TEST_DATABASE_URL` and resets that database's `public` schema. Do not point it at the local business database.

## Upload Too Large

Change `UPLOAD_MAX_BYTES` in `.env` and restart the API.

## Markdown Looks Wrong

Assistant messages use Markdown/GFM. User messages are rendered as safe plain text by design.
