"""Alert consumer: Kafka → Postgres alerts table, plus the notify hook.

Shares the exactly-once loop in pipeline/streaming.py with the readings
consumer — poll, batch, insert with ON CONFLICT DO NOTHING, commit the database,
then commit Kafka offsets — so alert_id gives the same exactly-once-rows
guarantee segment_id gives readings. This module adds only the alert specifics:
its columns, its insert function, and the ``notify`` side effect.

``notify`` is the single seam a real push transport would plug into (WebSocket,
web-push, SMS). It logs here; wiring an actual transport is deliberately out of
scope for this showcase. Keeping the notifier a separate consumer is the point —
the producer polls CHP once and any number of consumers act on the same alert
without re-polling the source.

Usage:
    python -m pipeline.alert_consumer
"""
from __future__ import annotations

import logging
import os

from pipeline import streaming
from pipeline.database import ALERT_COLUMNS, connect, insert_alerts

log = logging.getLogger(__name__)

BATCH_SIZE = 200
BATCH_TIMEOUT_S = 2.0

# Minimum keys a message needs before we'll insert it.
_REQUIRED_KEYS = {"alert_id", "kind", "headline"}

parse_message = streaming.make_parser(ALERT_COLUMNS, _REQUIRED_KEYS)


def notify(alert: dict) -> None:
    """The push seam. A real transport (WebSocket/web-push/SMS) plugs in here."""
    log.info("ALERT %s | %s", alert.get("route_id"), alert.get("headline"))


def run(consumer, conn, max_batches: int | None = None) -> int:
    """Drain the alerts topic into the alerts table, notifying after each flush."""
    return streaming.run(
        consumer,
        conn,
        parse_message=parse_message,
        insert_fn=insert_alerts,
        batch_size=BATCH_SIZE,
        batch_timeout=BATCH_TIMEOUT_S,
        on_flush=notify,
        max_batches=max_batches,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    from confluent_kafka import Consumer

    consumer = Consumer(
        {
            "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092"),
            "group.id": os.getenv("KAFKA_ALERTS_GROUP_ID", "sierra-road-alerts"),
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([os.getenv("KAFKA_ALERTS_TOPIC", "sierra.road.alerts")])
    streaming.install_signal_handlers()

    conn = connect()
    log.info("alert consumer started")
    try:
        run(consumer, conn)
    finally:
        consumer.close()
        conn.close()
        log.info("alert consumer stopped")


if __name__ == "__main__":
    main()
