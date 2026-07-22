"""The poll worker: collect road-state changes and live collisions. No broker.

This replaces the Kafka producer/consumer pairs (ADR-0012). Every cycle it:

  1. fetches Caltrans chain control and CHP incidents (the same sources the
     alerts stream used);
  2. derives alerts with the unchanged pure fold in pipeline/alerts.py, writes
     them to the `alerts` table, and runs the notify() hook;
  3. for each NEW collision on a tracked route, fetches the weather for that
     exact point and stores the enriched row in `incidents`.

It writes straight to Postgres with the same `ON CONFLICT` idempotency the Kafka
consumers had: a re-poll or a re-run only ever no-ops on rows that already
landed, so removing the broker costs nothing in correctness. "New collision"
means one not seen last cycle: derive_alerts already emits an incident alert
only the first time it sees an incident, so we fetch weather once per collision.

Honest scope: CHP has no push, so polling every ~1–2 minutes is as fast as the
source allows. Meant to run as a scheduled serverless invocation (EventBridge →
Lambda) so nothing stays switched on; see docs/deployment.md.

Usage:
    python -m pipeline.poller --once
    python -m pipeline.poller --dry-run --once
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

from pipeline.alerts import Alert, derive_alerts
from pipeline.regime import classify_conditions
from pipeline.sources import chp, cwwp2, openmeteo

log = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "tests" / "fixtures"

_running = True


def _handle_signal(signum: int, _frame) -> None:
    global _running
    log.info("shutdown signal received: %s", signum)
    _running = False


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def notify(alert: Alert) -> None:
    """The push seam. A real transport (WebSocket/web-push/SMS) plugs in here."""
    log.info("ALERT %s | %s", alert.route_id, alert.headline)


def fetch_point_weather(lat: float, lon: float) -> openmeteo.WeatherReading | None:
    """Live weather for one collision's exact point, or None if the fetch fails.

    This is the weather NOW, at collection time, not necessarily at the
    collision's event_time (CHP log_time can lag by hours). For a freshly polled
    collision the two are close; for a failed fetch, the incidents backfill fills
    it later from the archive keyed on the event hour. A single-point call, so
    one failed collision never nulls another's weather.
    """
    try:
        readings = openmeteo.fetch_current_batch([(lat, lon)])
    except Exception as exc:  # noqa: BLE001: a missed fetch must not drop the collision
        log.warning("open-meteo point fetch failed: %s", exc)
        return None
    return readings[0] if readings else None


def incident_row(alert: Alert, weather: openmeteo.WeatherReading | None) -> dict:
    """Build a bronze `incidents` row from a COLLISION alert and its weather. Pure.

    weather is None when the on-collision fetch failed; the regime then falls to
    UNKNOWN (all-None inputs) and the numeric fields stay null, so the backfill
    can find and fill the row later.
    """
    return {
        # The alert id is "chp:<incident_id>"; the incidents table keys on the
        # bare CHP id, matching the feed.
        "incident_id": alert.alert_id.removeprefix("chp:"),
        "category": alert.category,
        "type_text": alert.detail,
        "route_id": alert.route_id,
        "lat": alert.lat,
        "lon": alert.lon,
        "measure_mi": alert.measure_mi,
        "event_time": alert.event_time,
        "weather_regime": classify_conditions(
            snowfall_rate_in_hr=weather.snowfall_rate_in_hr if weather else None,
            visibility_miles=weather.visibility_miles if weather else None,
            wind_gust_mph=weather.wind_gust_mph if weather else None,
            surface_temp_c=weather.temperature_c if weather else None,
        ),
        "snowfall_rate_in_hr": weather.snowfall_rate_in_hr if weather else None,
        "visibility_miles": weather.visibility_miles if weather else None,
        "wind_gust_mph": weather.wind_gust_mph if weather else None,
        "surface_temp_c": weather.temperature_c if weather else None,
        "source": "chp",
    }


def poll_once(conn=None, dry_run: bool = False) -> tuple[list[Alert], list[dict]]:
    """One detection cycle. Returns (alerts emitted, collision rows collected).

    Dry run uses fixtures and an empty prior state (so every change reads as new)
    and touches neither Postgres nor the network; used by tests and CI.
    """
    now = datetime.now(timezone.utc).isoformat()
    if dry_run:
        chain_controls = cwwp2.parse_chain_control(_load_fixture("cwwp2_cc_sample.json"))
        incidents = chp.parse_incidents((FIXTURES_DIR / "chp_sample.xml").read_text(encoding="utf-8"))
        prev_state: dict = {}
    else:
        from pipeline.database import load_alert_state

        chain_controls = cwwp2.fetch_chain_control()
        incidents = chp.fetch_incidents()
        prev_state = load_alert_state(conn)

    derived = derive_alerts(prev_state, chain_controls, incidents, now)

    # New collisions this cycle get the weather at their point, now. Hazards and
    # closures still become alerts, but only collisions become incident rows.
    incident_rows = [
        incident_row(alert, None if dry_run else fetch_point_weather(alert.lat, alert.lon))
        for alert in derived.alerts
        if alert.kind == "INCIDENT" and alert.category == "COLLISION"
    ]

    if conn is not None:
        from pipeline.database import (
            insert_alerts,
            insert_incidents,
            save_alert_state,
        )

        insert_alerts(conn, [asdict(alert) for alert in derived.alerts])
        insert_incidents(conn, incident_rows)
        save_alert_state(conn, derived.next_state)
        conn.commit()

    for alert in derived.alerts:
        notify(alert)

    log.info(
        "poll complete: alerts=%d collisions=%d dry_run=%s",
        len(derived.alerts), len(incident_rows), dry_run,
    )
    return derived.alerts, incident_rows


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Sierra Pass Watch poll worker")
    parser.add_argument("--dry-run", action="store_true", help="fixtures, no network/DB")
    parser.add_argument("--once", action="store_true", help="single cycle then exit")
    args = parser.parse_args()

    dry_run = args.dry_run or os.getenv("DRY_RUN", "").lower() == "true"
    interval = int(os.getenv("POLL_INTERVAL_SECONDS", "90"))

    conn = None
    if not dry_run:
        from pipeline.database import connect

        conn = connect()

    if args.once:
        alerts, collisions = poll_once(conn=conn, dry_run=dry_run)
        print(f"{len(alerts)} alerts, {len(collisions)} collisions collected")
        if conn is not None:
            conn.close()
        return

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    log.info("poll worker starting: dry_run=%s interval=%ss", dry_run, interval)
    # This long-lived loop is a local convenience. Production runs one cycle per
    # EventBridge -> Lambda invocation (--once above), which opens a fresh
    # connection every tick, so a dropped connection self-heals there. In the
    # loop we reopen the connection after a failed cycle so it recovers too.
    while _running:
        try:
            poll_once(conn=conn, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001: a bad cycle must not kill the loop
            log.error("poll failed: %s", exc)
            if not dry_run:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001: already-dead connection
                    pass
                try:
                    conn = connect()
                except Exception as reconnect_exc:  # noqa: BLE001: retry next cycle
                    log.error("reconnect failed: %s", reconnect_exc)
                    conn = None
        if _running:
            time.sleep(interval)
    if conn is not None:
        conn.close()
    log.info("poll worker stopped")


if __name__ == "__main__":
    main()
