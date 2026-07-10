"""Alert consumer: Kafka → Postgres alerts table, plus the notify hook.

Mirrors pipeline/consumer.py exactly — poll, batch, insert with ON CONFLICT
DO NOTHING, commit the database, then commit Kafka offsets — so alert_id gives
the same exactly-once-rows guarantee segment_id gives readings.

This is also where "deliver ASAP" happens: ``notify`` is the single seam a real
push transport would plug into (WebSocket, web-push, SMS). It logs here; wiring
an actual transport is deliberately out of scope for this showcase. Keeping the
notifier a separate consumer is the point — the producer polls CHP once and any
number of consumers act on the same alert without re-polling the source.

Usage:
    python -m pipeline.alert_consumer
"""
from __future__ import annotations

import json
import logging
import os
import signal
import time

from pipeline.database import ALERT_COLUMNS, connect, insert_alerts

log = logging.getLogger(__name__)

BATCH_SIZE = 200
BATCH_TIMEOUT_S = 2.0

# Minimum keys a message needs before we'll insert it.
_REQUIRED_KEYS = {"alert_id", "kind", "headline"}

_running = True


def _handle_signal(signum: int, _frame) -> None:
    global _running
    log.info("shutdown signal received: %s", signum)
    _running = False


def parse_message(raw: bytes) -> dict | None:
    """Decode one Kafka message into an alert row, or None if malformed."""
    try:
        alert = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        log.warning("dropping malformed alert: %s", exc)
        return None
    if not isinstance(alert, dict) or not _REQUIRED_KEYS.issubset(alert):
        log.warning("dropping alert missing required keys")
        return None
    return {column: alert.get(column) for column in ALERT_COLUMNS}


def notify(alert: dict) -> None:
    """The push seam. A real transport (WebSocket/web-push/SMS) plugs in here."""
    log.info("ALERT %s | %s", alert.get("route_id"), alert.get("headline"))


def run(consumer, conn, max_batches: int | None = None) -> int:
    """Consume → batch → insert → commit → notify. Returns rows written."""
    total_inserted = 0
    batch: list[dict] = []
    batches_done = 0
    deadline = time.monotonic() + BATCH_TIMEOUT_S

    def flush() -> None:
        nonlocal batch, total_inserted, batches_done, deadline
        if batch:
            inserted = insert_alerts(conn, batch)
            conn.commit()
            consumer.commit(asynchronous=False)
            total_inserted += inserted
            for alert in batch:
                notify(alert)
            log.info("alert batch flushed: messages=%d inserted=%d", len(batch), inserted)
            batch = []
        batches_done += 1
        deadline = time.monotonic() + BATCH_TIMEOUT_S

    while _running:
        message = consumer.poll(1.0)
        if message is not None:
            if message.error():
                log.error("kafka error: %s", message.error())
            else:
                alert = parse_message(message.value())
                if alert is not None:
                    batch.append(alert)

        if len(batch) >= BATCH_SIZE or (batch and time.monotonic() >= deadline):
            flush()
            if max_batches is not None and batches_done >= max_batches:
                break

    flush()
    return total_inserted


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

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

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
