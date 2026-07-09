# 0005. Storage: PostgreSQL

## Context

The data is relational and the questions asked of it are joins: crashes ↔
weather readings ↔ route, grouped by weather regime.

## Decision

Use PostgreSQL.

Familiarity, plus the access pattern is aggregate-heavy analytics — exactly
where a relational engine and SQL win. dbt-postgres builds the marts on top
of it, and PostGIS is available if the hotspot math ever needs real
geospatial queries.

## Alternatives considered

- **A document/NoSQL store (MongoDB, DynamoDB)** — would push the
  crash/weather/stop joins into application code instead of letting the
  database handle them. Aggregate-heavy, ad-hoc grouped queries (by regime,
  by route, by bin) are exactly what these stores are weak at compared to
  SQL.
- **BigQuery** — what the prior Streamlit/GCP version used. Great for
  large-scale analytical scans, but it's a warehouse, not an
  application-serving database: no row-level transactional writes, higher
  per-query latency, and it doesn't fit an API backend that needs fast
  point/range lookups per request.
- **MySQL / MariaDB** — comparable relational fit, but weaker native
  geospatial story than PostGIS and less common in the dbt/analytics
  ecosystem this project already leans on.
- **SQLite** — fine for a single-process prototype, but no concurrent
  writers, which the Kafka consumer needs, and no real path to PostGIS.

Postgres wins because the workload is joins and aggregations over related
tables (crashes, weather, stops), dbt-postgres is a first-class target, and
PostGIS is a drop-in upgrade rather than a migration if the hotspot math
ever needs true geospatial queries (e.g. proximity search, polyline
buffering).

## Consequences

Schema and joins are enforced at the database layer. Geospatial features can
grow into PostGIS without a storage migration if needed.

## Hosting

Planned target is **AWS RDS for PostgreSQL** (small instance, e.g.
`db.t4g.micro`) per `infra/terraform/aws/` — keeps the whole stack in one
cloud/IAM boundary and lets the Terraform double as an AWS-skills artifact,
which matters since this is a portfolio/display project.

Cst tradeoff: an always-on RDS instance bills ~$15-30+/mo for `db.t4g.micro` plus
storage/backups, which is not cheap compared to most of my projects (<$0.01/month). If idle cost becomes a real concern later,
the cheaper levers are RDS-native: scheduling stop/start via
EventBridge + Lambda, or switching to Aurora Serverless v2 for the Postgres engine,
which does scale down (though not fully to zero) under an ACU floor. Not
adopted now — default is to keep the always-on `db.t4g.micro` for
simplicity and revisit later.
