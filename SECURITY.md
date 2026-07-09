# Security log

A running record of how security was considered as this repository evolved.
Each change that touches the security posture appends a dated section.

## Boilerplate (initial commit)

- **No secrets in the repo.** Local configuration comes from a single
  root-level `.env` (gitignored), read by both docker compose and the
  frontend dev server (Vite's `envDir` points at the repo root);
  `.env.example` documents every variable with safe defaults. Only
  `VITE_`-prefixed variables are ever bundled into the browser build —
  nothing sensitive may use that prefix.
- **Error responses don't leak internals.** The frontend's response
  interceptor ([frontend/src/api/client.ts](frontend/src/api/client.ts))
  normalizes failures into a typed `AppError` whose messages are written for
  users; server error bodies (stack traces, internal details) are never
  rendered. A unit test enforces this.
- **Backend hides implementation details.** The API returns typed Pydantic
  models (unhandled errors become a generic JSON 500, never a stack trace),
  and uvicorn runs with `--no-server-header` so the server implementation is
  not advertised in responses.
- **Same-origin by default.** In development the Vite proxy forwards `/api`
  to the backend, so no CORS policy is opened; production is expected to sit
  behind a reverse proxy the same way. CORS will only be enabled with an
  explicit allowlist if cross-origin deployment becomes necessary.
- **Dev database credentials are placeholders.** The compose file's Postgres
  password is a documented local-only default, overridable via `.env`, and
  the port is published on **loopback only** (`127.0.0.1:5432`) so the dev
  database is never reachable from the local network.
