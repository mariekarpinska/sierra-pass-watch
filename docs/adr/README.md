# Architecture Decision Records

One file per significant decision, numbered in order. Each records the
context, the decision, the alternatives considered, and the trade-offs — so
the "why" survives long after the commit messages scroll away.

Format: `NNNN-short-title.md` with sections **Context / Decision /
Alternatives considered / Consequences**.

| # | Title | Status |
|---|-------|--------|
| [0001](0001-frontend-framework.md) | Frontend framework | Accepted |
| [0002](0002-typescript.md) | TypeScript | Accepted |
| [0003](0003-http-client.md) | HTTP client | Accepted |
| [0004](0004-backend-framework.md) | Backend framework | Accepted |
| [0005](0005-database.md) | Database | Accepted |
| [0006](0006-data-plane.md) | Data plane: Kafka, dbt — and not Spark | Accepted |
| [0007](0007-spatial-model-per-mile-bins.md) | Spatial model: linear referencing + per-mile bins | Accepted |
| [0008](0008-near-realtime-alerts.md) | Near real-time alerts: change events on a second stream | Accepted |
| [0009](0009-journey-routing.md) | Multi-highway journeys: build-time OSRM precompute | Accepted |
| [0010](0010-crash-history-at-journey-grain.md) | Crash history at journey grain: compose the marts per request | Accepted |
| [0011](0011-deployment-and-cicd.md) | Deployment & CI/CD: AWS, OIDC, scheduled batch ingestion | Accepted |
