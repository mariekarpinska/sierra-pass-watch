# 0008. Near real-time alerts: change events on a second stream

**Status:** 2026-07-09

> **Superseded in part by [ADR-0012](0012-direct-poll-ingestion.md) (2026-07-21):**
> the Kafka alerts stream has been removed. One poll worker now derives the same
> alerts (with the unchanged pure logic in `pipeline/alerts.py`) and writes them
> straight to the `alerts` table: the "poll CHP directly from a single worker
> and push, no Kafka" alternative this ADR weighed and predicted it would pick in
> production. The alert model (change events, chain-control transitions, CHP
> categories) is unchanged.

## Context

The readings pipeline (ADR-0006) emits a snapshot of every waypoint every five
minutes. A snapshot is not urgent, which left the streaming machinery looking
heavier than the workload justified. The thing a driver actually wants pushed
the second it happens is a *change*: chains going up on Donner, a pass closing,
a fresh collision on the road ahead. That is a different signal with a different
clock, and the readings snapshot does not carry it.

Two change sources are available under the project's keyless posture:

- **Caltrans chain control** — already fetched by the readings producer. The
  transition (None → R2, R2 → lifted) is thrown away today; detecting it costs
  nothing new and is fully reliable.
- **CHP CAD incidents** — near-real-time collisions, hazards and closures.
  Transient and unverified: a best-effort "something is happening now", not a
  system of record. CCRS remains the authoritative crash history.

## Decision

A second, parallel stream carrying **change events**, not readings.

```
alert_producer ──► sierra.road.alerts ──► alert_consumer ──► alerts table
                                                       └────► notify() hook
```

- `pipeline/alerts.py` holds the logic as a **pure function**: give it the
  previous state and the current observations, and it returns the alerts to send
  plus the new state. "Pure" means it does no I/O of its own (no database, no
  network), so it is easy to unit-test. Chain transitions are named STARTED /
  ESCALATED / EASED / LIFTED; CHP incidents are classified COLLISION / HAZARD /
  CLOSURE / OTHER, matched to a route with the existing `parse_route` + range
  polygon and placed at a distance along it (`measure_mi`, ADR-0007).
- `pipeline/alert_producer.py` is the one producer that **remembers** (it is
  "stateful"). To know what *changed*, it loads the previous state from Postgres
  (`road_alert_state`), compares it to what's happening now, publishes only the
  differences, and saves the new state. The readings producer, by contrast, is
  "stateless": it re-sends every reading each cycle and needs no memory. Seen
  incidents are forgotten after a time limit (a TTL, "time to live"), so the
  saved state can't grow forever.
- `pipeline/alert_consumer.py` does exactly one job: read a batch of messages,
  insert them, commit. It is the same shape as the readings consumer (insert
  `on conflict (alert_id) do nothing`, commit the database, then commit the Kafka
  offsets, so a message delivered twice can never create a duplicate row). A
  consumer this simple, with no branching or decision. `notify()` is the single plug-in point where a real push transport would go.

## Alternatives considered

- **One stream for readings and alerts.** Rejected: a reading and an alert are
  different products that only share sources. Multiplexing them onto one topic
  saves two processes but forces one consumer to branch on message type, write
  two tables, and fire `notify()` for one of them. Two topics let each consumer
  stay simple: one job, no branching. The concrete differences:

  | | Readings (`sierra.road.events`) | Alerts (`sierra.road.alerts`) |
  |---|---|---|
  | Message | snapshot: full waypoint state | change: chains up, new collision |
  | Emitted | every cycle, unconditionally | only on a state change |
  | Cadence | 5 min | ~60 s |
  | Shape | 15-column bronze row | headline / category / kind |
  | Key | `segment_id` | `route_id` |
  | Batching | 500 msgs / 5 s | 200 msgs / 2 s |
  | Downstream | insert `raw_road_events` | insert `alerts` + `notify()` |
  | Producer | stateless (re-sends all) | stateful (remembers last state) |
  | Retention | disposable, latest wins | a record, may replay/notify |

  At this volume one topic with a `type` field would work; the split is a
  clarity and failure-isolation choice (CHP is the fragile source), not a
  scaling necessity.
- **Let the consumer detect changes, keep the producer simple.** The alert
  consumer could do the remembering and comparing instead, leaving the producer
  stateless like the readings one. But then the two consumers would look
  different: one a plain inserter, one that holds memory. We kept both consumers
  as plain inserters and put the memory in the alert producer, so every consumer
  in the system has the same simple shape.
- **Poll CHP directly from a single worker and push, no Kafka.** Simpler, and
  honestly what this volume warrants. The stream is kept so one poll of CHP fans
  out to many consumers (DB, notifier, future live map) without re-polling the
  source or a separate relay if many consumers were warranted. That decoupling is the value, not throughput.

## Consequences and owned trade-offs

- **Near-real-time, not live.** CHP has no push; ~60 s polling is as fast as the
  source allows. Honest framing lives in the module docstrings.
- **CHP is best-effort and fragile.** The feed is unofficial and its shape can
  change; a failed fetch degrades to no alerts, never a crash. The reliable
  chain-control layer stands alone if CHP breaks.
- **The alert producer needs memory.** Unlike the readings producer, it reads
  and writes Postgres: you can only tell chains *just* changed if you remember
  what they were last poll.
- **A dropped-then-returned chain station can re-announce.** State only tracks
  currently-present locations, so a station that vanishes and reappears is read
  as a fresh start. Acceptable at this cadence.
- **In production I'd likely drop Kafka here** and run one scheduled worker with
  Postgres LISTEN/NOTIFY or a managed pub/sub, reaching for a broker only when
  multiple consumers, replay, or backpressure (consumers falling behind the
  incoming rate) actually earn it.
