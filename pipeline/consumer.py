"""The streaming consumer: Kafka → Postgres, batched, idempotent.

Honest scope: at this volume this is near-real-time micro-batch, not
high-throughput streaming, and a plain scheduled poller writing straight to
Postgres would meet the same dashboard need. The producer/consumer + Kafka
split is here to practise the pattern and to keep ingestion decoupled from
storage. In production at this scale I'd simplify to a scheduled poller and
reach for Kafka only when several independent consumers, replay, or
backpressure actually demand it. The delivery guarantee below is real either
way, and the pattern scales up unchanged.

This is the whole Spark replacement. At this data volume (57 waypoints ×
one reading per poll) a distributed engine buys nothing; a batched insert
loop is simpler, cheaper and easier to reason about (ADR-0002).

Delivery semantics — exactly-once *rows* from at-least-once *messages*:

    poll → batch (500 msgs or 5 s, whichever first)
        → INSERT … ON CONFLICT (segment_id, event_timestamp) DO NOTHING
        → db COMMIT
        → kafka commit (offsets)

Offsets are committed only after the database commit. A crash between the
two replays messages whose rows already exist — the primary key swallows
them. The PK is the checkpoint, exactly like Spark's checkpoint dir was.

Usage:
    python -m pipeline.consumer
"""
from __future__ import annotations

import json
import logging
import os
import signal
import time

from pipeline.database import ROAD_EVENT_COLUMNS, connect, insert_road_events

log = logging.getLogger(__name__)

BATCH_SIZE = 500
BATCH_TIMEOUT_S = 5.0

# Keys the bronze insert requires; anything else in the message is ignored.
_REQUIRED_KEYS = {"segment_id", "event_timestamp", "weather_regime"}

_running = True


def _handle_signal(signum: int, _frame) -> None:
    global _running
    log.info("shutdown signal received: %s", signum)
    _running = False


def parse_message(raw: bytes) -> dict | None:
    """Decode one Kafka message into a bronze row, or None if malformed.

    A poison message is logged and skipped — one producer bug must never
    wedge the whole partition behind an unparseable message.
    """
    try:
        event = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        log.warning("dropping malformed message: %s", exc)
        return None
    if not isinstance(event, dict) or not _REQUIRED_KEYS.issubset(event):
        log.warning("dropping message missing required keys: got=%s", sorted(event)[:8] if isinstance(event, dict) else type(event))
        return None
    return {column: event.get(column) for column in ROAD_EVENT_COLUMNS}


def run(consumer, conn, max_batches: int | None = None) -> int:
    """Consume → batch → insert → commit, until stopped. Returns rows written.

    ``consumer`` needs poll/commit (confluent_kafka.Consumer or a test fake);
    ``max_batches`` lets tests run a bounded number of flushes.
    """
    total_inserted = 0
    batch: list[dict] = []
    batches_done = 0
    deadline = time.monotonic() + BATCH_TIMEOUT_S

    def flush() -> None:
        nonlocal batch, total_inserted, batches_done, deadline
        if batch:
            inserted = insert_road_events(conn, batch)
            conn.commit()
            # Only now is it safe to move the offset past these messages.
            consumer.commit(asynchronous=False)
            total_inserted += inserted
            log.info("batch flushed: messages=%d inserted=%d", len(batch), inserted)
            batch = []
        batches_done += 1
        deadline = time.monotonic() + BATCH_TIMEOUT_S

    while _running:
        message = consumer.poll(1.0)
        if message is not None:
            if message.error():
                log.error("kafka error: %s", message.error())
            else:
                event = parse_message(message.value())
                if event is not None:
                    batch.append(event)

        if len(batch) >= BATCH_SIZE or (batch and time.monotonic() >= deadline):
            flush()
            if max_batches is not None and batches_done >= max_batches:
                break

    flush()  # drain whatever is left on shutdown
    return total_inserted


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    from confluent_kafka import Consumer

    consumer = Consumer(
        {
            "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092"),
            "group.id": os.getenv("KAFKA_GROUP_ID", "sierra-road-events"),
            # Offsets are committed manually after the DB commit — never before.
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([os.getenv("KAFKA_TOPIC", "sierra.road.events")])

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    conn = connect()
    log.info("consumer started")
    try:
        run(consumer, conn)
    finally:
        consumer.close()
        conn.close()
        log.info("consumer stopped")


if __name__ == "__main__":
    main()
