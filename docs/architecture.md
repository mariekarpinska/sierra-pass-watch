# Architecture

> Filled in as features land.

## Data plane

```mermaid
flowchart LR
  SRC[keyless public sources\nOpen-Meteo, CWWP2, USGS, CCRS, CHP] --> POLL[poll worker\n~1-2 min, no broker]
  SRC -.->|batch backfill| PG
  POLL --> PG[(Postgres bronze\nraw_road_events, crashes, alerts, incidents)]
  PG -->|dbt build| MARTS[(analytics marts\npatterns, causes, incident conditions, active alerts)]
  MARTS --> API[FastAPI\nuvicorn]
  API -->|/api proxied| FE[React + TS SPA]
```

- **Ingestion** lands raw rows in the Postgres bronze layer with no broker
  (ADR-0012): a frequent poll worker writes alerts and live CHP collisions (each
  paired with the weather at its point) straight to Postgres, and a batch
  backfill twin loads history the same idempotent way
  ([ADR-0006](adr/0006-data-plane.md), [ADR-0008](adr/0008-near-realtime-alerts.md),
  [ADR-0012](adr/0012-direct-poll-ingestion.md)).
- **Transformation** is dbt: staging views over bronze, then the marts the API
  queries. Crashes key on a per-mile bin, weather on anchor towns
  ([ADR-0007](adr/0007-spatial-model-per-mile-bins.md)). See
  [warehouse.md](warehouse.md) for the mart lineage and grain.
- **The backend** is a FastAPI app; response models translate snake_case Python
  to the camelCase wire contract in one base class
  ([backend/api/schemas.py](../backend/api/schemas.py)). Journeys and forecasts
  are served from memory and Open-Meteo; crash history is the API's one
  Postgres read, composed from the marts per journey
  ([ADR-0010](adr/0010-crash-history-at-journey-grain.md)).
- **The frontend** calls the backend exclusively through one axios instance with
  documented request/response interceptors
  ([frontend/src/api/client.ts](../frontend/src/api/client.ts)).
