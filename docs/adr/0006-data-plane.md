# 0006. Data plane: Kafka, dbt — and not Spark

2026-07-08

## Context

The pipeline turns six keyless public APIs (Open-Meteo, NWS, Caltrans
CWWP2, USGS, CCRS crashes) plus a static route catalogue into the marts the
API serves: per-mile crash bins, hotspots, and cause taxonomies grouped by
weather regime (see [architecture.md](../architecture.md)).

Three orthogonal jobs fall out of that:

1. **Move events** from the producer to storage as they arrive — *transport*.
2. **Transform** raw rows into query-shaped marts — *modelling*.
3. **Run the whole thing on a schedule** and in the right order — *orchestration*.

Kafka and dbt own the first two. The third — orchestration — is a plain
scheduled job, not a dedicated engine (the concrete scheduler is a deployment
detail; see [ADR-0011](0011-deployment-and-cicd.md)). This ADR records those
choices, why they stay separate, and — the load-bearing decision — why **Spark**,
which the prior GCP/Streamlit version used, is removed.

The single most important constraint: **the data volume is tiny.** Full-Sierra
scope is ~24 routes and a bounded history of California crash records —
thousands to low-millions of rows, not billions. Every choice below follows
from that.

## Decision

- **Kafka** — the streaming transport between producer and consumer.
- **dbt (dbt-postgres)** — the transformation layer that builds the marts.
- **A scheduled job (a plain cron)** — the orchestrator that runs the batch
  path in order, on a schedule. No dedicated orchestration engine.
- **Not Spark** — replaced by a plain `confluent-kafka` Python consumer that
  batches into Postgres with `INSERT … ON CONFLICT`.

These stay separate on purpose: transport, transformation, and orchestration are
different concerns with different failure modes, and collapsing them into one
engine (which is what Spark tempts you to do) is the thing this ADR exists to
avoid.

---

### Why Kafka (transport)

**What Kafka is:** a distributed, durable, replayable message log. Think of it as a middleman: a "producer" writes events into it, and a "consumer" reads them out, but — crucially — the events aren't deleted the instant they're read. They persist, so if the consumer crashes, it can replay from where it left off instead of losing data.

**Why it's needed:** A durable, replayable log sits between the producer and the consumer so the
two can fail and restart independently. The consumer commits its DB write
first and its Kafka offset second, so a crash-and-replay re-delivers the last
batch and the `ON CONFLICT` upsert makes the replay idempotent — no lost
events, no double-counting. That decoupling is the streaming story this
project is meant to demonstrate.

**Honest caveat:** at this volume Kafka is *not* strictly necessary — the
producer could write to Postgres directly. It is kept because (a) the
producer→log→consumer pattern is the portfolio's real-time-ingestion
showcase, and (b) it models how the system would scale if the source feeds
ever became high-rate. The scheduled batch path (below) deliberately does
**not** need Kafka running, so CI and cron stay simple. This trade-off is the
subject of the "streaming vs scheduled batch" discussion in
[Consequences](#consequences).

**Alternatives considered:**

- **Direct producer → Postgres (no broker).** Simplest, genuinely sufficient at this scale, but rejected as the primary path because it forfeits the streaming demo. Kept as the batch path instead. The project has both and can explain when each applies.
- **A cloud queue (AWS SQS / GCP Pub/Sub).** ess to talk about/demonstrate (fewer moving concepts like consumer groups and partitions), and it locks the design to one cloud provider.
- **Redis Streams / RabbitMQ.** RabbitMQ deletes messages once acknowledged rather than keeping a replayable log, which breaks the "replay from a point in time" property the design relies on. Redis Streams is closer in behavior but less commonly asked about.

### Why dbt (transformation)

**What dbt is:** a tool for writing your data transformations as version-controlled SQL files, with dependencies between them, tests, and auto-generated documentation — rather than as ad hoc scripts or manual database views.

**Why it's needed:** The marts are pure SQL `SELECT`s with dependencies between them
(`stg_crashes` → `mart_crash_patterns` → `mart_hotspots`). dbt is the tool
that lets those live as version-controlled, tested, documented SQL:

- **Dependency graph for free.** `ref()` between models builds the DAG, so
  dbt runs them in the correct order and can rebuild just what changed.
- **Tests as data contracts.**  you can declare rules like "this column must never be null" or "these are the only allowed values," and dbt checks them automatically, catching a broken upstream data feed before it ever reaches the API.
- **Docs and lineage.** `dbt docs` generates the model graph a reviewer can
  read, useful for anyone trying to understand the system.
- **Environment-portable SQL.** The same models target local Postgres and
  cloud Postgres; only the connection profile changes.

**Alternatives considered:**

- **Hand-written SQL migration scripts / stored procedures.** No dependency
  graph, no built-in testing, no lineage — I'd end up rebuilding a worse, ad hoc version of what dbt already provides.
- **SQLMesh.** A genuinely strong dbt competitor (column-level lineage,
  virtual environments, no Jinja for many cases). Rejected on ecosystem
  familiarity: dbt is more common and the project uses
  nothing SQLMesh-specific enough to justify the less-common tool.
- **Doing the transforms in Python (pandas / Polars).** Pulls aggregation work out of the database (which is optimized for exactly this kind of set-based work) and back into application code, losing SQL-level testing and splitting logic across two places. Note: the one exception is the "regime classifier" (categorizing weather conditions), which does stay in Python — the doc's reasoning is that Python is the single source of truth for that piece, imported by the API too, while row-crunching/aggregation belongs in SQL.
- **In-application views only (no dbt).** Postgres views can express the
  models, but with no tests, no seeds, no lineage, and no separation between
  staging and marts. dbt is the thin layer that adds all four.

### Orchestration: a scheduled cron, not an engine

**Why it's needed:** Something has to run "fetch → load → `dbt build`" in order,
on a schedule, so the marts refresh without anyone running scripts by hand. That
is orchestration, and it is a distinct concern from *how* each step moves or
shapes data.

**What runs it:** a plain scheduled job (a cron) that runs those steps in order
on a timer, with no always-on server. `dbt build` failing a data test fails the
run, so a broken upstream feed surfaces immediately. The concrete scheduler is a
deployment detail — recorded in [ADR-0011](0011-deployment-and-cicd.md).

**Alternatives considered:**

- **A dedicated orchestration engine (e.g. Prefect or Dagster).** These add
  first-class retries, backfills, and a DAG UI — genuinely valuable when you
  have many interdependent pipelines and an ops team watching them. At this
  volume (one daily fetch-and-build) that is more operational weight than the
  cadence needs, so the cron is used instead. If the pipeline count grows,
  adopting one becomes a good future ADR.
- **dbt Cloud's scheduler / `dbt build` in CI alone** would only schedule the transformation step, not the ingestion that has to happen before it — so it doesn't cover the whole pipeline.

### Why NOT Spark (the load-bearing removal)

The prior version ran **Spark Structured Streaming** to window events and
feed the (now-deleted) safety-score mart. Spark is removed entirely.

**What Spark is:** a distributed computing engine designed to process huge datasets across a cluster of machines (i.e., when data is too big to fit on a single computer). It was previously used here for "Structured Streaming" — processing data in time windows as it streamed in.

Why I've removed it, argument by argument:

- **It was provisioned for a larger scale.** Spark's reason to
  exist is distributed computation across a cluster when data does not fit on
  one machine.
- **Operational cost.** Spark means a cluster (or EMR/Dataproc), JVM tuning,
  and a serialization/shuffle model to reason about — real complexity and cost.

**What replaces it:** a small, plain Python script using the `confluent-kafka` library — reading batches of messages, tagging each with its weather condition, and writing them into Postgres with an upsert. The aggregation work Spark used to do is now just ordinary SQL inside dbt, where — unlike inside Spark — it's version-controlled and tested.

**When Spark *would* be right (so the trade-off is owned):** if a source feed
became genuinely high-throughput (millions of events/minute) or the
transforms outgrew a single Postgres, Spark (or Flink) back on a cluster
becomes the correct tool. The decision here is scale-specific, not dogmatic.

## Consequences

- **Three small, single-purpose tools instead of one big one.** Each is
  independently testable (mocked-source pytest for ingestion, dbt tests for
  marts, DAG tests for orchestration) and independently explainable.
- **Two ingestion paths, on purpose.** Kafka producer→consumer is the
  *real-time streaming* demonstration; backfill→Postgres→`dbt build` is the
  *hands-off scheduled batch* path that needs no always-on broker (so CI and
  cron stay cheap). The scheduled cron runs those same steps in order. Knowing
  *when* to use each is part of the story.
- **Kafka is arguably above the minimum this volume requires.** Accepted
  deliberately: it is the portfolio's streaming showcase, the batch path proves
  the system also works without it, and it maps onto a real scale-up path (MSK).
  Removing Spark is where the "no over-engineering" rule bites hardest, because
  Spark added operational weight with *nothing left for it to do*.
- **Everything targets Postgres.** One storage engine ([0005](0005-database.md))
  under both paths keeps the mental model small.
- **The API reads dbt's tables with plain SQL, not an ORM (e.g. SQLAlchemy).**
  Because dbt owns the transforms and the analytics schema, the API is a
  read-only window over tables dbt owns, and the queries are simple SELECTs. An
  ORM's main value is managing writes, migrations, and object mapping (none of
  which this layer does), so it would add indirection and a second source of
  truth for the schema, for no benefit. Parameterized psycopg gives the same
  injection safety without it. The queries stay behind a repository (a
  dependency-injection seam) so they remain testable and swappable in tests.
