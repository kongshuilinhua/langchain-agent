# Deployment

Local ports are fixed:

- API: `127.0.0.1:8000`
- Frontend: `127.0.0.1:5174`

If a port is occupied, stop the old process and restart the same port. Do not switch to another port.

## Local Development

```powershell
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm run dev
```

`npm run dev` uses `--strictPort`.

## Docker Compose

```powershell
docker compose up --build
```

Services:

- `api`
- `frontend`
- `postgres`
- `milvus`
- `redis`

Redis is optional for runtime correctness. PostgreSQL is required unless tests explicitly configure another database.

## Security Notes

Before production-like use:

- replace `JWT_SECRET`
- configure `API_KEY_ENCRYPTION_KEY`
- keep `INVITE_API_ENABLED=false` unless a compatibility-only backend invite flow is intentionally enabled
- put the API behind HTTPS/reverse proxy
- add backup and log retention policy
- review upload limits and model gateway policy
