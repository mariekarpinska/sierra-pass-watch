"""Alert producer: detect road-state CHANGES and stream them.

Mirrors pipeline/producer.py, but where that emits a reading every poll, this
emits only when the state flips: chains go up or down, or CHP reports a new
incident on a tracked route. It is the one stateful producer — to know what
CHANGED it loads the last-known state from Postgres (road_alert_state), diffs
it (pipeline/alerts.derive_alerts, pure), publishes the diff to Kafka, and
writes the new state back.

Honest scope (same as the readings pipeline): polling CHP every ~60 s and
publishing the diff is near-real-time, not a live socket — CHP offers no push,
so this is as fast as the source allows. The Kafka hop lets one poll of CHP
fan out to many consumers (DB writer, notifier, live map) without any of them
re-polling CHP or a separate relay service. In production at this volume I'd
likely fold detection and delivery into one scheduled worker (Postgres
LISTEN/NOTIFY or a managed pub/sub for the push side) and keep Kafka for when
several consumers or replay actually earn it.

Usage:
    python -m pipeline.alert_producer --once
    python -m pipeline.alert_producer --dry-run --once
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from pipeline.alerts import derive_alerts
from pipeline.sources import chp, cwwp2

log = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "tests" / "fixtures"

_running = True


def _handle_signal(signum: int, _frame) -> None:
    global _running
    log.info("shutdown signal received: %s", signum)
    _running = False


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def poll_once(kafka_producer=None, conn=None, dry_run: bool = False) -> list:
    """One detection cycle. Returns the alerts emitted this cycle.

    Dry run uses fixtures and an empty prior state (so every change reads as
    new) and touches neither Postgres nor Kafka — used by tests and CI.
    """
    now = datetime.now(timezone.utc).isoformat()
    if dry_run:
        chain_controls = cwwp2.parse_chain_control(_load_fixture("cwwp2_cc_sample.json"))
        incidents = chp.parse_incidents(_load_fixture("chp_sample.json"))
        prev_state: dict = {}
    else:
        chain_controls = cwwp2.fetch_chain_control()
        incidents = chp.fetch_incidents()
        from pipeline.database import load_alert_state

        prev_state = load_alert_state(conn)

    derived = derive_alerts(prev_state, chain_controls, incidents, now)

    topic = os.getenv("KAFKA_ALERTS_TOPIC", "sierra.road.alerts")
    for alert in derived.alerts:
        if kafka_producer is not None:
            kafka_producer.produce(
                topic=topic,
                key=(alert.route_id or alert.alert_id),
                value=json.dumps(asdict(alert)).encode("utf-8"),
            )
    if kafka_producer is not None:
        kafka_producer.flush()

    if not dry_run:
        from pipeline.database import save_alert_state

        save_alert_state(conn, derived.next_state)
        conn.commit()

    log.info("alert poll complete: emitted=%d dry_run=%s", len(derived.alerts), dry_run)
    return derived.alerts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Sierra Corridor alert producer")
    parser.add_argument("--dry-run", action="store_true", help="fixtures, no network/Kafka/DB")
    parser.add_argument("--once", action="store_true", help="single cycle then exit")
    args = parser.parse_args()

    dry_run = args.dry_run or os.getenv("DRY_RUN", "").lower() == "true"
    interval = int(os.getenv("ALERT_POLL_INTERVAL_SECONDS", "60"))

    producer = None
    conn = None
    if not dry_run:
        from confluent_kafka import Producer

        from pipeline.database import connect

        producer = Producer(
            {"bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092")}
        )
        conn = connect()

    if args.once:
        alerts = poll_once(kafka_producer=producer, conn=conn, dry_run=dry_run)
        by_cat: dict[str, int] = {}
        for a in alerts:
            by_cat[a.category] = by_cat.get(a.category, 0) + 1
        summary = ", ".join(f"{k}={v}" for k, v in sorted(by_cat.items())) or "none"
        print(f"{len(alerts)} alerts: {summary}")
        if conn is not None:
            conn.close()
        return

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    log.info("alert producer starting: dry_run=%s interval=%ss", dry_run, interval)
    while _running:
        try:
            poll_once(kafka_producer=producer, conn=conn, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001 — a bad cycle must not kill the loop
            log.error("alert poll failed: %s", exc)
        if _running:
            time.sleep(interval)
    if conn is not None:
        conn.close()
    log.info("alert producer stopped")


if __name__ == "__main__":
    main()
