# 0012. Direct-poll ingestion: no broker

2026-07-21

## Context

The pipeline started with Kafka between every producer and consumer: a readings
stream ([ADR-0006](0006-data-plane.md)) and a parallel alerts stream
([ADR-0008](0008-near-realtime-alerts.md)). Both ADRs said the same thing in
their own words: at this data volume the broker is above what the workload
needs, and a plain poller writing straight to Postgres would do the same job.
This ADR acts on that.

Two problems pushed the change from "nice to simplify" to "worth doing now":

1. **The daily scheduled job added nothing joinable.** Every weather-bearing
   mart funnels through one join in `mart_crash_conditions`: a crash matches a
   weather reading only when that reading falls in the two hours before the
   crash. The daily cron ([ingest.yml](../../.github/workflows/ingest.yml))
   ingests weather for a rolling ~12-day window, but crash data (CCRS) is an
   annual historical extract with nothing in the last two weeks. So the weather
   ingested today joins to zero crashes. On top of that, Open-Meteo is an
   archive API (any past date can be re-fetched on demand), so pre-accumulating
   weather buys nothing a targeted backfill wouldn't. The daily job was a health
   check dressed up as ingestion.

2. **The CHP feed already gives us live collisions.** The alerts stream
   ([ADR-0008](0008-near-realtime-alerts.md)) already reads CHP, where each
   collision arrives tagged with a route and a position along it: the location
   and timestamp needed to pair a collision with weather. That is a genuinely
   new, joinable row the daily build can fold into a mart.

## Decision

- **Remove Kafka.** Delete both producer/consumer pairs and the shared Kafka
  loop. Ingestion writes straight to Postgres with the same `ON CONFLICT`
  idempotency the consumers had. The local `docker-compose` no longer runs a
  broker; only Postgres remains.
- **One poll worker (`pipeline/poller.py`).** It polls CHP and Caltrans, derives
  alerts with the unchanged pure logic in `pipeline/alerts.py`, writes them to
  the `alerts` table, and, for each new collision on a tracked route, fetches
  live weather for that exact point and stores the enriched record in a new
  bronze table (`incidents`). No broker in the path.
- **Poll frequently, not daily.** CHP is a live feed: it shows what is active
  right now and events age out, so a once-a-day poll would catch almost nothing.
  The worker is meant to run every 1 to 2 minutes as a scheduled serverless
  invocation (EventBridge, then Lambda), which keeps the "no always-on server"
  posture from [ADR-0011](0011-deployment-and-cicd.md). Frequency and transport
  are separate concerns: frequent collection does not require Kafka.
- **New mart `mart_incident_conditions`.** Joins the accumulated collisions to
  their weather, deduped to one row per collision, clearly labelled
  **provisional** and kept separate from the authoritative CCRS history.
- **The daily `dbt build` becomes meaningful.** The poller collects genuinely
  new rows continuously; the daily build folds them into the marts. CCRS refresh
  stays on-demand/annual.

This supersedes the Kafka parts of [ADR-0006](0006-data-plane.md) and
[ADR-0008](0008-near-realtime-alerts.md), and refines the ingestion cadence in
[ADR-0011](0011-deployment-and-cicd.md) (the daily cron still runs `dbt build`;
the poller now feeds it).

### Why get the weather when the collision is collected

Two ways to have weather sitting next to a collision:

- **Continuous ambient sampling.** Keep polling weather at fixed points so
  there is always a recent reading near any future collision. This is what the
  old readings producer did, and it is exactly the approach that added nothing:
  it stores weather that mostly never joins to anything.
- **On-collision fetch (chosen).** When a collision is collected, fetch the
  weather for its own lat/lon at that moment and store them together. This is
  spatially precise (the collision's point, not the nearest sampled town) and
  stores a weather reading only when there is a collision to attach it to.

The trade-off owned: the on-collision fetch is a single point of failure for
that record's weather. Mitigated by storing the collision immediately even if
the weather fetch fails (regime `UNKNOWN`, numeric fields null) and backfilling
the weather later (`python -m pipeline.backfill incidents`).

## Alternatives considered

- **Keep Kafka as a local-only demonstration.** Tempting for the portfolio
  story, but it leaves a broker, a docker-compose service, a dependency, and two
  producer/consumer pairs in the tree with nothing that needs them. The honest
  story ("built it, then removed it because the volume never justified it") is
  stronger than keeping ceremony the data doesn't need. The git history and
  ADR-0006/0008 still show the Kafka design for anyone who wants to read it.
- **Continuous weather sampling (above).** Rejected: stores weather that rarely
  joins, and Open-Meteo's archive makes pre-accumulation pointless.
- **Feed CHP collisions into `mart_crash_patterns` (the authoritative mart).**
  Rejected: CHP is unofficial and thin (no severity, injury, or cause fields),
  so it cannot answer the questions that mart answers. It gets its own
  provisional mart instead.

## Consequences and owned trade-offs

- **Loses the Kafka/streaming showcase.** The repo no longer demonstrates a
  producer/consumer with replay and idempotency at the transport layer. This is
  a deliberate simplification; the `ON CONFLICT` idempotency that made replay
  safe is still there on every write.
- **CHP data is provisional and thin.** It is unofficial, has no severity /
  injury / cause fields, and collisions on ~24 mountain routes are rare, so the
  new mart's `small_sample` flag will be true for a long time. It is a pipeline
  demonstration first, an analytics asset second.
- **Two systems of record, labelled.** CCRS stays authoritative
  (`mart_crash_patterns`); the live mart (`mart_incident_conditions`) is a
  fresh-but-provisional companion. Docs and the UI say which is which.
- **Dedup is required.** One physical collision can emit several CHP updates over
  its life. The bronze table keeps the first update per incident id
  (`ON CONFLICT DO NOTHING`), and the mart collapses again to one row per
  collision (earliest update per route + mile bin + time cluster) as defence in
  depth.
