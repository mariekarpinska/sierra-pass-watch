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

The loop itself lives in pipeline/streaming.py, shared with the alerts consumer
so the commit ordering exists in exactly one place. This module supplies only
the road-events specifics: the bronze columns, the insert function, and the
batch sizing.

Usage:
    python -m pipeline.consumer
"""
from __future__ import annotations

import logging
import os

from pipeline import streaming
from pipeline.database import ROAD_EVENT_COLUMNS, connect, insert_road_events

log = logging.getLogger(__name__)

BATCH_SIZE = 500
BATCH_TIMEOUT_S = 5.0

# Keys the bronze insert requires; anything else in the message is ignored.
_REQUIRED_KEYS = {"segment_id", "event_timestamp", "weather_regime"}

parse_message = streaming.make_parser(ROAD_EVENT_COLUMNS, _REQUIRED_KEYS)


def run(consumer, conn, max_batches: int | None = None) -> int:
    """Drain the road-events topic into raw_road_events. See streaming.run."""
    return streaming.run(
        consumer,
        conn,
        parse_message=parse_message,
        insert_fn=insert_road_events,
        batch_size=BATCH_SIZE,
        batch_timeout=BATCH_TIMEOUT_S,
        max_batches=max_batches,
    )


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
    streaming.install_signal_handlers()

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
