"""The streaming producer: poll public sources, label the regime, emit JSON.

Every POLL_INTERVAL_SECONDS this process fetches all sources once, builds one
event per catalogue waypoint (nearest chain-control and RWIS stations, the
waypoint's own Open-Meteo cell, the strongest nearby quake), labels it with
``classify_conditions`` and produces it to Kafka keyed by segment_id — same
key, same partition, so per-segment ordering holds.

The event dict IS the bronze schema (see pipeline/db/schema.sql): the
consumer inserts it column-for-column, no reshaping in between.

Honest scope: a 5-minute poll into a queue is near-real-time micro-batch, not
event streaming. At this volume a scheduled poller writing directly to Postgres
would do the same job; the producer/consumer + Kafka split is a deliberate
showcase of the pattern and a decoupling seam (poll each source once, fan out
to many consumers). In production I'd simplify to a scheduled poller unless
multiple consumers, replay or higher velocity earned the queue.

Dry run (DRY_RUN=true or --dry-run): the same code path fed from the JSON
fixtures in tests/fixtures — no network, no Kafka — used by tests and CI.

Usage:
    python -m pipeline.producer            # live loop (needs Kafka)
    python -m pipeline.producer --once     # one live poll, print summary, exit
    python -m pipeline.producer --dry-run --once
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

from pipeline.geo import nearest
from pipeline.regime import classify_conditions
from pipeline.routes import SEGMENTS
from pipeline.sources import cwwp2, nws, openmeteo, usgs

log = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "tests" / "fixtures"

# A station farther than this from a waypoint tells you nothing about it.
STATION_MAX_KM = 30.0

_running = True


def _handle_signal(signum: int, _frame) -> None:
    global _running
    log.info("shutdown signal received: %s", signum)
    _running = False


def _nearest(items: list, lat: float, lon: float, max_km: float = STATION_MAX_KM):
    """Nearest item (with .lat/.lon) within max_km, or None."""
    return nearest(items, lat, lon, max_km, lambda i: (i.lat, i.lon))


def build_event(
    segment: dict,
    chain_controls: list[cwwp2.ChainControl],
    rwis_readings: list[cwwp2.RwisReading],
    quakes: list[usgs.SeismicEvent],
    weather: openmeteo.WeatherReading | None,
    gust_fallback_mph: float | None,
    event_timestamp: str,
) -> dict:
    """Merge all sources into one bronze event for one waypoint. Pure."""
    lat, lon = segment["lat"], segment["lon"]

    station = _nearest(chain_controls, lat, lon)
    chain_control = station.status if station and station.status in ("R1", "R2", "R3") else None

    rwis = _nearest(rwis_readings, lat, lon)
    surface_temp_c = rwis.surface_temp_c if rwis else None
    visibility_miles = rwis.visibility_miles if rwis else None
    wind_gust_mph = rwis.wind_gust_mph if rwis else None

    if weather:
        snowfall_rate_in_hr = weather.snowfall_rate_in_hr
        # RWIS is a physical sensor on this road — prefer it; model fills gaps.
        if visibility_miles is None:
            visibility_miles = weather.visibility_miles
        if wind_gust_mph is None:
            wind_gust_mph = weather.wind_gust_mph
    else:
        snowfall_rate_in_hr = None

    if wind_gust_mph is None:
        wind_gust_mph = gust_fallback_mph

    quake = usgs.strongest_within_km(quakes, lat, lon)

    return {
        "segment_id": segment["segment_id"],
        "segment_name": segment["segment_name"],
        "route_id": segment["route_id"],
        "lat": lat,
        "lon": lon,
        "event_timestamp": event_timestamp,
        "weather_regime": classify_conditions(
            snowfall_rate_in_hr=snowfall_rate_in_hr,
            visibility_miles=visibility_miles,
            wind_gust_mph=wind_gust_mph,
            surface_temp_c=surface_temp_c,
            chain_control=chain_control,
        ),
        "chain_control": chain_control,
        "road_closed": None,  # CWWP2 exposes closures via chain status "closed" text; not modelled yet
        "snowfall_rate_in_hr": snowfall_rate_in_hr,
        "visibility_miles": visibility_miles,
        "wind_gust_mph": wind_gust_mph,
        "surface_temp_c": surface_temp_c,
        "seismic_mag": quake.magnitude if quake else None,
        "source": "live",
    }


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _fetch_all(dry_run: bool):
    """One round of source fetches. Fixtures and live share every parser."""
    if dry_run:
        chain_controls = cwwp2.parse_chain_control(_load_fixture("cwwp2_cc_sample.json"))
        rwis_readings = cwwp2.parse_rwis(_load_fixture("cwwp2_rwis_sample.json"))
        quakes = usgs.parse_events(_load_fixture("usgs_sample.json"))
        reading = openmeteo.parse_current(_load_fixture("openmeteo_sample.json"))
        # One fixture reading fanned out to every waypoint — fine for a dry run.
        weather_by_segment = {s["segment_id"]: reading for s in SEGMENTS}
    else:
        chain_controls = cwwp2.fetch_chain_control()
        rwis_readings = cwwp2.fetch_rwis()
        quakes = usgs.fetch_events()
        weather_by_segment = {}
        for s in SEGMENTS:
            try:
                weather_by_segment[s["segment_id"]] = openmeteo.fetch_current(s["lat"], s["lon"])
            except Exception as exc:  # noqa: BLE001 — one waypoint failing shouldn't stop the sweep
                log.warning("open-meteo failed: segment=%s error=%s", s["segment_id"], exc)
                weather_by_segment[s["segment_id"]] = None
    return chain_controls, rwis_readings, quakes, weather_by_segment


def poll_once(kafka_producer=None, dry_run: bool = False) -> list[dict]:
    """Fetch everything once, emit one event per waypoint. Returns the events."""
    topic = os.getenv("KAFKA_TOPIC", "sierra.road.events")
    chain_controls, rwis_readings, quakes, weather_by_segment = _fetch_all(dry_run)
    now = datetime.now(timezone.utc).isoformat()

    events = []
    for segment in SEGMENTS:
        weather = weather_by_segment.get(segment["segment_id"])
        gust_fallback = None
        if not dry_run and weather is not None and weather.wind_gust_mph is None:
            # NWS only when the primary sources came back empty-handed.
            forecast = nws.fetch_forecast(segment["segment_id"], segment["lat"], segment["lon"])
            gust_fallback = forecast.wind_gust_mph if forecast else None

        event = build_event(
            segment, chain_controls, rwis_readings, quakes, weather, gust_fallback, now
        )
        events.append(event)
        if kafka_producer is not None:
            kafka_producer.produce(
                topic=topic,
                key=event["segment_id"],
                value=json.dumps(event).encode("utf-8"),
            )

    if kafka_producer is not None:
        kafka_producer.flush()
    log.info("poll complete: events=%d dry_run=%s", len(events), dry_run)
    return events


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Sierra Corridor streaming producer")
    parser.add_argument("--dry-run", action="store_true", help="fixtures, no network/Kafka")
    parser.add_argument("--once", action="store_true", help="single poll then exit")
    args = parser.parse_args()

    dry_run = args.dry_run or os.getenv("DRY_RUN", "").lower() == "true"
    poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))

    producer = None
    if not dry_run:
        from confluent_kafka import Producer

        producer = Producer(
            {"bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092")}
        )

    if args.once:
        events = poll_once(kafka_producer=producer, dry_run=dry_run)
        by_regime: dict[str, int] = {}
        for e in events:
            by_regime[e["weather_regime"]] = by_regime.get(e["weather_regime"], 0) + 1
        print(f"{len(events)} events: " + ", ".join(f"{k}={v}" for k, v in sorted(by_regime.items())))
        return

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    log.info("producer starting: dry_run=%s interval=%ss", dry_run, poll_interval)
    while _running:
        try:
            poll_once(kafka_producer=producer, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001 — a bad cycle must not kill the loop
            log.error("poll failed: %s", exc)
        if _running:
            time.sleep(poll_interval)
    log.info("producer stopped")


if __name__ == "__main__":
    main()
