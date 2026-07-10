"""Backfill — the scheduled/batch twin of the streaming path.

Two loaders, both writing the same bronze tables the consumer writes, both
idempotent (natural-key ON CONFLICT), so streaming and batch can never
conflict:

* ``weather``  — replay hourly history for every catalogue waypoint from the
  Open-Meteo archive, label each hour with the SAME classifier the producer
  uses, insert into raw_road_events (source='backfill').
* ``crashes``  — load the CCRS CSV produced by ``python -m
  pipeline.sources.ccrs``: attribute each report to a catalogue route
  (parse_route + range polygon), label it via classify_crash_report, insert
  into crashes.

Usage:
    python -m pipeline.backfill weather --start 2025-11-01 --end 2026-03-31
    python -m pipeline.backfill crashes            # reads data/ccrs/crashes.csv
"""
from __future__ import annotations

import argparse
import csv
import logging
from datetime import date, datetime, timezone
from pathlib import Path

from pipeline.database import connect, insert_crashes, insert_road_events
from pipeline.polylines import measure_for
from pipeline.regime import classify_conditions, classify_crash_report
from pipeline.routes import SEGMENTS, in_sierra, parse_direction, parse_route
from pipeline.sources import ccrs, openmeteo

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# weather history → raw_road_events
# ---------------------------------------------------------------------------

def weather_events_for_segment(segment: dict, readings: list[openmeteo.WeatherReading]) -> list[dict]:
    """Turn archive readings into bronze rows for one waypoint. Pure."""
    events = []
    for reading in readings:
        if not reading.timestamp:
            continue
        events.append(
            {
                "segment_id": segment["segment_id"],
                "segment_name": segment["segment_name"],
                "route_id": segment["route_id"],
                "lat": segment["lat"],
                "lon": segment["lon"],
                # Archive times are UTC ISO without offset; make it explicit.
                "event_timestamp": reading.timestamp + "+00:00",
                "weather_regime": classify_conditions(
                    snowfall_rate_in_hr=reading.snowfall_rate_in_hr,
                    visibility_miles=reading.visibility_miles,  # archive: always None
                    wind_gust_mph=reading.wind_gust_mph,
                    surface_temp_c=reading.temperature_c,
                ),
                "chain_control": None,
                "road_closed": None,
                "snowfall_rate_in_hr": reading.snowfall_rate_in_hr,
                "visibility_miles": reading.visibility_miles,
                "wind_gust_mph": reading.wind_gust_mph,
                "surface_temp_c": reading.temperature_c,
                "seismic_mag": None,
                "source": "backfill",
            }
        )
    return events


def backfill_weather(start: date, end: date) -> int:
    """Fetch + insert hourly history for every waypoint. Returns rows inserted."""
    conn = connect()
    total = 0
    try:
        for segment in SEGMENTS:
            try:
                readings = openmeteo.fetch_archive_hours(segment["lat"], segment["lon"], start, end)
            except Exception as exc:  # noqa: BLE001 — skip a waypoint, keep the sweep
                log.warning("archive failed: segment=%s error=%s", segment["segment_id"], exc)
                continue
            inserted = insert_road_events(conn, weather_events_for_segment(segment, readings))
            conn.commit()
            total += inserted
            log.info("segment backfilled: %s rows=%d", segment["segment_id"], inserted)
    finally:
        conn.close()
    log.info("weather backfill complete: rows=%d", total)
    return total


# ---------------------------------------------------------------------------
# CCRS CSV → crashes
# ---------------------------------------------------------------------------

_SURFACE_CODES = {"A": "Dry", "B": "Wet", "C": "Snowy/Icy", "D": "Slippery"}


def _get(row: dict, *candidates: str) -> str | None:
    """First non-empty value among candidate columns (CCRS names drift by year)."""
    for name in candidates:
        value = (row.get(name) or "").strip()
        if value:
            return value
    return None


def _parse_datetime(row: dict) -> datetime | None:
    """CCRS 2022+ has CRASH_DATE_TIME; older vintages split date and time."""
    raw = _get(row, "CRASH_DATE_TIME", "COLLISION_DATE")
    if raw is None:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%m/%d/%Y %H:%M:%S %p", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # ISO-ish fallback (e.g. "2025-01-12T06:30:00").
    try:
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def crash_row(row: dict) -> dict | None:
    """Normalize one CCRS CSV row into a bronze crash row.

    Returns None for rows that aren't ours: no usable coordinates or date, no
    tracked route in the road text, or outside the Sierra range polygon.
    """
    try:
        lat = float(_get(row, "LATITUDE", "POINT_Y") or "")
        lon = float(_get(row, "LONGITUDE", "POINT_X") or "")
    except ValueError:
        return None
    if lat == 0 or lon == 0:
        return None

    collision_datetime = _parse_datetime(row)
    if collision_datetime is None:
        return None

    primary_road = _get(row, "PRIMARYROAD", "PRIMARY_RD", "ROAD")
    route_id = parse_route(primary_road, lon)
    if route_id is None or not in_sierra(lat, lon):
        return None

    case_id = _get(row, "COLLISION_ID", "CASE_ID", "OBJECTID")
    if case_id is None:
        return None

    def _int(*names: str) -> int:
        value = _get(row, *names)
        try:
            return int(float(value)) if value else 0
        except ValueError:
            return 0

    num_killed = _int("NUMBERKILLED", "NUMBER_KILLED")
    num_injured = _int("NUMBERINJURED", "NUMBER_INJURED")
    if num_killed > 0:
        severity = "Fatal"
    elif num_injured > 0:
        severity = "Injury"
    else:
        severity = "Property Damage Only"

    weather = _get(row, "WEATHER_1", "WEATHER") or "Unknown"
    surface_code = _get(row, "ROADWAYSURFACECODE", "ROAD_SURFACE")
    road_surface = _SURFACE_CODES.get((surface_code or "").upper(), surface_code or "Unknown")

    return {
        "case_id": case_id,
        "collision_datetime": collision_datetime,
        "lat": lat,
        "lon": lon,
        "route_id": route_id,
        "direction": parse_direction(primary_road),
        "severity": severity,
        "collision_type": (_get(row, "COLLISION_TYPE_DESCRIPTION", "TYPE_OF_COLLISION") or "Unknown").title(),
        "primary_factor": _get(row, "PRIMARY_COLLISION_FACTOR_VIOLATION", "PCF_VIOL_CATEGORY") or "Unknown",
        "collided_with": (_get(row, "MOTORVEHICLEINVOLVEDWITHDESC", "MVIW") or "Unknown").title(),
        "primary_road": primary_road,
        "lighting": (_get(row, "LIGHTINGDESCRIPTION", "LIGHTING") or "Unknown").title(),
        "day_of_week": _get(row, "DAY_OF_WEEK", "DAYOFWEEK") or "Unknown",
        "weather": weather,
        "road_surface": road_surface,
        "weather_regime": classify_crash_report(weather, road_surface),
        "num_injured": num_injured,
        "num_killed": num_killed,
        # Distance-along-route: the crash linear-referenced onto its route's
        # polyline (700 m buffer). None = spur route or off the line; the
        # crash still counts for the route, it just joins no per-mile bin.
        "measure_mi": measure_for(route_id, lat, lon),
    }


def backfill_crashes(csv_path: Path = ccrs.OUTPUT_CSV, batch_size: int = 1000) -> int:
    """Load the filtered CCRS CSV into the crashes table. Returns rows inserted."""
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} not found — run `python -m pipeline.sources.ccrs` first"
        )
    conn = connect()
    total = 0
    skipped = 0
    try:
        with csv_path.open(newline="", encoding="utf-8") as f:
            batch: list[dict] = []
            for row in csv.DictReader(f):
                normalized = crash_row(row)
                if normalized is None:
                    skipped += 1
                    continue
                batch.append(normalized)
                if len(batch) >= batch_size:
                    total += insert_crashes(conn, batch)
                    conn.commit()
                    batch = []
            total += insert_crashes(conn, batch)
            conn.commit()
    finally:
        conn.close()
    log.info("crash backfill complete: inserted=%d skipped=%d", total, skipped)
    return total


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Sierra Corridor backfill")
    sub = parser.add_subparsers(dest="command", required=True)

    weather = sub.add_parser("weather", help="hourly weather history → raw_road_events")
    weather.add_argument("--start", type=date.fromisoformat, required=True)
    weather.add_argument("--end", type=date.fromisoformat, required=True)

    crashes = sub.add_parser("crashes", help="CCRS CSV → crashes")
    crashes.add_argument("--csv", type=Path, default=ccrs.OUTPUT_CSV)

    args = parser.parse_args()
    if args.command == "weather":
        count = backfill_weather(args.start, args.end)
    else:
        count = backfill_crashes(args.csv)
    print(f"{args.command}: {count} rows inserted")


if __name__ == "__main__":
    main()
