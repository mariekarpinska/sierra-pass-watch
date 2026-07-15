# Full-stack monorepo

A monorepo with a **React + TypeScript** frontend (Vite) and a **FastAPI**
backend (Python), wired together through an explicit, documented HTTP layer.

## Layout

```
├─ frontend/     Vite + React + TypeScript SPA
├─ backend/      FastAPI service (Python 3.13)
├─ pipeline/     Python ingestion: producer → Kafka → consumer → Postgres,
│                plus backfill (weather history + CCRS crashes)
├─ shared/       weather-regime-cases.json — the classifier's golden contract
├─ docs/         Architecture notes, ADRs
├─ SECURITY.md   Running log of security considerations
└─ docker-compose.yml   Local infrastructure (Postgres + Kafka)
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
python -m venv .venv && source .venv/bin/activate    # .venv\Scripts\Activate.ps1 on Windows
pip install -e .                                      # the pipeline package: the API imports pipeline.regime
cd backend && pip install -e ".[dev]"                 # then the API itself
python -m api                                          # serves :5080 (sets the selector loop Windows+psycopg needs)

# 3. Frontend → http://localhost:5173 (proxies /api to the backend)
cd frontend && npm install && npm run dev
```

Open http://localhost:5173 — the page calls `GET /api/health` on the backend
through the frontend's interceptor layer and renders the result.

## Run the data pipeline

Every reading and crash is labelled with a **weather regime**
([docs/weather-regimes.md](docs/weather-regimes.md)) at ingest — the shared
vocabulary that lets the product match crash history to today's forecast.
Each crash is also **linear-referenced onto its route's polyline** to a
distance-along-route (`measure_mi`), so the record resolves to the per-mile
bin, not just the nearest town ([ADR-0007](docs/adr/0007-spatial-model-per-mile-bins.md)).

> **Which shell are you in?** The examples use Unix/bash syntax. On **Windows
> PowerShell**, two things differ: activate the venv with
> `.venv\Scripts\Activate.ps1` (not `source …`), and keep each command on **one
> line** — the trailing `\` that wraps long lines is bash-only (PowerShell uses a
> backtick `` ` ``, or just don't wrap). The `docker`, `python`, and `pytest`
> commands themselves are identical in both shells.

First, set up the Python environment (once):

```bash
python -m venv .venv && source .venv/bin/activate    # .venv\Scripts\Activate.ps1 on Windows
pip install -e ".[dev]"
```

### 1. Offline — no infrastructure

```bash
python -m pipeline.producer --dry-run --once   # 57 events from fixtures: no network, no Kafka
pytest -m "not integration"                    # the full pipeline unit suite
```

### 2. Full streaming stack (Postgres + Kafka)

You only need **Docker Desktop running** (the engine) — `docker compose up -d`
creates *and* starts the containers.

```bash
docker compose up -d          # start Postgres + Kafka; schema.sql auto-applies on first start
docker compose ps             # wait until BOTH show "healthy" (~30–60s) before continuing
```

If one exits, debug with (insert 'kafka' or 'postgres' into name)
```bash
docker compose ps -a                             # confirm kafka/postgres "Exited"
docker compose up -d --force-recreate name       # recreate it, if not kafka then
docker compose logs name --tail 20               # only if it exits AGAIN
```

Then, in two terminals (both with the venv active):

```bash
# terminal A — drain Kafka → Postgres, batched & idempotent (Ctrl+C after it logs a flush)
python -m pipeline.consumer

# terminal B — one live poll of the public sources → Kafka (keyless APIs; needs internet)
python -m pipeline.producer --once
```

Verify the bronze rows landed (one line, so it pastes cleanly in any shell):

```bash
docker compose exec postgres psql -U app -d app -c "select source, count(*), count(distinct weather_regime) as regimes from raw_road_events group by 1;"
```

### 3. Crash backfill → per-mile bins

```bash
python -m pipeline.sources.ccrs --years 2024 2025   # stream statewide CSV, keep Sierra rows → data/ccrs/
python -m pipeline.backfill crashes                 # load crashes, each with measure_mi
python -m pipeline.backfill weather --start 2025-11-01 --end 2026-03-31   # hourly history (no Kafka)

# per-mile grain preview: route × mile bin × regime (single line — paste as-is)
docker compose exec postgres psql -U app -d app -c "select route_id, floor(measure_mi) as mile_bin, weather_regime, count(*) from crashes where measure_mi is not null group by 1,2,3 order by count desc limit 15;"
```

`python -m pipeline.build_polylines` rebuilds `shared/route-polylines.json`
from OSRM — run rarely and by hand; the committed file is what everything reads.

### Stop / reset

```bash
docker compose down       # stop containers, keep the data
docker compose down -v    # also wipe the volume (schema.sql re-applies on next `up`)
```

### Troubleshooting

- **Containers stay "Created" / `docker compose ps` is empty.** Another stack
  is already bound to `127.0.0.1:5432` or `:9092`, so these can't start. Find
  it with `docker ps` and stop it (`docker stop <name>`), or remap this
  project's host ports in `.env` (`POSTGRES_PORT`, `KAFKA_BOOTSTRAP_SERVERS`)
  and `docker-compose.yml`.
- **Tables missing after `up`.** `schema.sql` runs only on an *empty* data
  volume. If you have an older volume, run `docker compose down -v` once, then
  `docker compose up -d`. Confirm with
  `docker compose exec postgres psql -U app -d app -c "\dt"`
  (expect `raw_road_events` and `crashes`).

## How the frontend talks to the backend

All HTTP flows through **one axios instance** with explicit request/response
interceptors: [frontend/src/api/client.ts](frontend/src/api/client.ts).
Requests get a correlation id; responses are timed; failures are normalized to
a single typed `AppError` before any component sees them. In development the
Vite dev server proxies `/api` to the backend (no CORS); in production a
reverse proxy or `VITE_API_BASE_URL` plays that role.

## Tests

The Python suites (backend + pipeline) assume the repo-root `.venv` is active
(`source .venv/bin/activate`, or `.venv\Scripts\Activate.ps1` on Windows).

```bash
cd frontend && npm test        # Vitest + Testing Library
cd backend && pytest           # pytest + FastAPI TestClient
pytest                         # pipeline (add -m integration for Testcontainers)
```

## Docs

- [docs/architecture.md](docs/architecture.md) — system overview
- [docs/weather-regimes.md](docs/weather-regimes.md) — the regime vocabulary and its thresholds
- [docs/adr/](docs/adr/) — architecture decision records
- [SECURITY.md](SECURITY.md) — running log of security considerations
