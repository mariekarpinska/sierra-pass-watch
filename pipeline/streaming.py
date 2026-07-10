"""Shared runtime for the Kafka → Postgres consumers.

The exactly-once-rows recipe — batch → insert → commit the database → commit
Kafka offsets — is the most safety-critical loop in the pipeline. It lives here
once so the readings consumer (pipeline/consumer.py) and the alerts consumer
(pipeline/alert_consumer.py) can't drift apart. Each consumer supplies only what
differs: the columns and required keys of its message, its insert function, its
batch sizing, and an optional per-row side effect run after each flush (the
alert consumer's notify()).

Offsets are committed only after the database commit. A crash between the two
replays messages whose rows already exist; the table's natural primary key (via
ON CONFLICT DO NOTHING) swallows them, turning at-least-once delivery into
exactly-once rows.
"""
from __future__ import annotations

import json
import logging
import signal
import time
from collections.abc import Callable

log = logging.getLogger(__name__)

_running = True


def _handle_signal(signum: int, _frame) -> None:
    global _running
    log.info("shutdown signal received: %s", signum)
    _running = False


def install_signal_handlers() -> None:
    """Stop the run loop cleanly on SIGTERM/SIGINT. Call once from main()."""
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)


def make_parser(columns: tuple[str, ...], required_keys: set[str]) -> Callable[[bytes], dict | None]:
    """Build a ``parse_message(raw) -> row | None`` for one message shape.

    A poison message is logged and skipped, never raised — one producer bug must
    not wedge the partition behind an unparseable message.
    """
    required = set(required_keys)

    def parse_message(raw: bytes) -> dict | None:
        try:
            event = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.warning("dropping malformed message: %s", exc)
            return None
        if not isinstance(event, dict) or not required.issubset(event):
            log.warning("dropping message missing required keys")
            return None
        return {column: event.get(column) for column in columns}

    return parse_message


def run(
    consumer,
    conn,
    *,
    parse_message: Callable[[bytes], dict | None],
    insert_fn: Callable[[object, list[dict]], int],
    batch_size: int,
    batch_timeout: float,
    on_flush: Callable[[dict], None] | None = None,
    max_batches: int | None = None,
) -> int:
    """Consume → batch → insert → commit DB → commit offsets, until stopped.

    ``consumer`` needs poll/commit (confluent_kafka.Consumer or a test fake).
    ``on_flush`` runs once per row after each committed batch (e.g. notify()).
    ``max_batches`` lets tests run a bounded number of flushes. Returns the
    total rows written.
    """
    total_inserted = 0
    batch: list[dict] = []
    batches_done = 0
    deadline = time.monotonic() + batch_timeout

    def flush() -> None:
        nonlocal batch, total_inserted, batches_done, deadline
        if batch:
            inserted = insert_fn(conn, batch)
            conn.commit()
            # Only now is it safe to move the offset past these messages.
            consumer.commit(asynchronous=False)
            total_inserted += inserted
            if on_flush is not None:
                for row in batch:
                    on_flush(row)
            log.info("batch flushed: messages=%d inserted=%d", len(batch), inserted)
            batch = []
        batches_done += 1
        deadline = time.monotonic() + batch_timeout

    while _running:
        message = consumer.poll(1.0)
        if message is not None:
            if message.error():
                log.error("kafka error: %s", message.error())
            else:
                row = parse_message(message.value())
                if row is not None:
                    batch.append(row)

        if len(batch) >= batch_size or (batch and time.monotonic() >= deadline):
            flush()
            if max_batches is not None and batches_done >= max_batches:
                break

    flush()  # drain whatever is left on shutdown
    return total_inserted
