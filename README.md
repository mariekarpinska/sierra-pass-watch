# Full-stack monorepo

A monorepo with a **React + TypeScript** frontend (Vite) and a **FastAPI**
backend (Python), wired together through an explicit, documented HTTP layer.

## Layout

```
├─ frontend/     Vite + React + TypeScript SPA
├─ backend/      FastAPI service (Python 3.13)
├─ docs/         Architecture notes, ADRs
├─ SECURITY.md   Running log of security considerations
└─ docker-compose.yml   Local infrastructure (Postgres)
```

## Prerequisites

- Node.js ≥ 22
- Python ≥ 3.12
- Docker Desktop

## Run it

```bash
# 1. Infrastructure
docker compose up -d

# 2. Backend  → http://localhost:5080
cd backend && pip install -e ".[dev]"
uvicorn api.main:app --port 5080 --no-server-header

# 3. Frontend → http://localhost:5173 (proxies /api to the backend)
cd frontend && npm install && npm run dev
```

Open http://localhost:5173 — the page calls `GET /api/health` on the backend
through the frontend's interceptor layer and renders the result.

## How the frontend talks to the backend

All HTTP flows through **one axios instance** with explicit request/response
interceptors: [frontend/src/api/client.ts](frontend/src/api/client.ts).
Requests get a correlation id; responses are timed; failures are normalized to
a single typed `AppError` before any component sees them. In development the
Vite dev server proxies `/api` to the backend (no CORS); in production a
reverse proxy or `VITE_API_BASE_URL` plays that role.

## Tests

```bash
cd frontend && npm test        # Vitest + Testing Library
cd backend && pytest           # pytest + FastAPI TestClient
```

## Docs

- [docs/architecture.md](docs/architecture.md) — system overview
- [docs/adr/](docs/adr/) — architecture decision records
- [SECURITY.md](SECURITY.md) — running log of security considerations
