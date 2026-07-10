# Security log

A running record of how security was considered as this repository evolved.
Each change that touches the security posture appends a dated section.

## 2026-07-09 — feat/data-plane (pipeline posture)

- **Keyless sources by design.** Every upstream (Caltrans CWWP2, NWS,
  Open-Meteo, USGS, data.ca.gov CKAN, and the OSRM router used at build time
  to trace route geometry) is public and unauthenticated — there are no API
  keys to leak, rotate, or scope. 
- **Build-time geometry is committed, not fetched at runtime.** Route
  polylines are generated once by `pipeline/build_polylines.py` and checked
  in as `shared/route-polylines.json`; no build, deploy, or request path
  depends on OSRM being reachable.
- **No SSRF surface.** Every outbound URL is a constant in its client module
  ([pipeline/fetch.py](pipeline/fetch.py) documents the posture); no user- or
  data-supplied value is ever interpolated into a host. Every request carries
  an explicit timeout so a hung API cannot hang a poll cycle.
- **Credentials via environment only.** The pipeline reads Postgres/Kafka
  settings from env (`.env` locally, secrets in CI later); nothing is
  hardcoded beyond documented local-dev defaults. `data/ccrs/` (downloaded
  crash CSVs) is gitignored.
- **Kafka and Postgres bind to loopback** in docker-compose — neither is
  reachable from the local network. Single-broker PLAINTEXT is a deliberate
  local-dev trade-off.
- **Parameterized SQL only.** All inserts go through two parameterized
  statements in [pipeline/database.py](pipeline/database.py); nothing
  concatenates SQL.
- **Poison-message tolerance.** The consumer validates and drops malformed
  Kafka messages (logged) instead of crashing — a producer bug can't wedge
  the partition or take the consumer down.
- **Crash data is public record.** CCRS publishes collision-level data with
  no personal identifiers; we further reduce it to the fields the product
  needs.

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
