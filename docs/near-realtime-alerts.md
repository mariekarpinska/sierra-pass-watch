# Real-time alerts

> **Superseded in part by [ADR-0012](adr/0012-direct-poll-ingestion.md):** the
> Kafka stream shown below was removed. One poll worker (`pipeline/poller.py`)
> now derives the same alerts with the unchanged pure logic in
> `pipeline/alerts.py` and writes them straight to the `alerts` table: the
> current shape is `poll worker (detect a change) ──► alerts table ──► notify()`,
> no broker. The alert *model* (change events, chain-control transitions, CHP
> categories, the notify() seam) is exactly as described here.

Alerts carry **changes** rather than snapshots: the events a driver wants pushed
the second they happen. See [ADR-0008](adr/0008-near-realtime-alerts.md) for the
original decision and trade-offs, refined by
[ADR-0012](adr/0012-direct-poll-ingestion.md).

```
poll worker ──► alerts table ──► notify()
  (detect a change, insert, then notify)
```

## Honest scope

This is near-real-time, not a live socket. CHP offers no push, so polling every
~60 s is as fast as the source allows. At this volume a single scheduled worker
polling and pushing directly would meet the same need. The producer/consumer +
Kafka split is a deliberate showcase of the pattern, and it earns its keep as a
decoupling seam: one poll of CHP fans out to any number of consumers (the DB
writer, the notifier, a future live map) without any of them re-polling the
source or a separate relay service. In production at this scale I'd fold
detection and delivery into one worker (Postgres LISTEN/NOTIFY or a managed
pub/sub) and reach for a broker only when several consumers, replay or
backpressure earn it.

## Two layers

| Layer | Source | Reliability | Events |
|---|---|---|---|
| Chain control | Caltrans CWWP2 (already polled) | Solid, official | STARTED, ESCALATED, EASED, LIFTED |
| Incidents | CHP CAD | Best-effort, unofficial | COLLISION, HAZARD, CLOSURE, OTHER |

CHP is transient and unverified, so it only ever raises alerts. CCRS stays the
authoritative crash record. A CHP outage silences incident alerts; the
chain-control layer keeps working on its own.

## How a change is detected

`pipeline/alerts.py` is a pure function: `(previous state, observations) →
(alerts, next state)`. The producer loads the previous state from Postgres
(`road_alert_state`), diffs it, publishes only the diff, and writes the new
state back. Incident ids are remembered for a TTL so the same incident isn't
re-announced every poll and the state table can't grow without bound.

## Run it

```bash
python -m pipeline.alert_producer --dry-run --once   # fixtures: no network, Kafka or DB

# full stack (Postgres + Kafka up, schema applied):
python -m pipeline.alert_consumer                    # terminal A: drain alerts → Postgres
python -m pipeline.alert_producer --once             # terminal B: one detection cycle
```

The `notify()` function in `pipeline/alert_consumer.py` is the single seam a
real push transport (WebSocket, web-push, SMS) would plug into. It logs here.
