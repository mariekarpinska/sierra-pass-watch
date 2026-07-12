"""Open-Meteo — keyless weather, current conditions and hourly history.

Two endpoints, one shape: ``fetch_current_batch`` feeds the live producer (all
waypoints in one request), ``fetch_archive_hours`` feeds the backfill. Both
convert to the pipeline's units (inches/hr, miles, mph, °C) at the edge so
nothing downstream converts.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from pipeline.fetch import get_json

log = logging.getLogger(__name__)

CURRENT_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Public on purpose: the API's forecast parser (backend/api/weather.py) imports
# these, so both paths feed the shared classifier identically-scaled numbers.
CM_TO_IN = 0.393701
KMH_TO_MPH = 0.621371
M_TO_MILES = 0.000621371


@dataclass
class WeatherReading:
    """One point-in-time weather sample at a waypoint, pipeline units."""

    timestamp: str  # ISO, as reported by the API
    snowfall_rate_in_hr: float | None
    visibility_miles: float | None
    wind_gust_mph: float | None
    temperature_c: float | None


def _reading(time: str, snowfall_cm, visibility_m, gust_kmh, temp_c) -> WeatherReading:
    return WeatherReading(
        timestamp=time,
        snowfall_rate_in_hr=None if snowfall_cm is None else snowfall_cm * CM_TO_IN,
        visibility_miles=None if visibility_m is None else visibility_m * M_TO_MILES,
        wind_gust_mph=None if gust_kmh is None else gust_kmh * KMH_TO_MPH,
        temperature_c=temp_c,
    )


def parse_current(payload: dict) -> WeatherReading:
    """Parse a /v1/forecast?current=… payload into pipeline units."""
    current = payload.get("current", {})
    return _reading(
        time=current.get("time", ""),
        snowfall_cm=current.get("snowfall"),
        visibility_m=current.get("visibility"),
        gust_kmh=current.get("wind_gusts_10m"),
        temp_c=current.get("temperature_2m"),
    )


def parse_current_batch(payload) -> list[WeatherReading]:
    """Parse a multi-coordinate /v1/forecast payload into readings.

    Open-Meteo returns a JSON array (one entry per coordinate, in request order)
    for comma-separated coordinates, and a bare object for a single one — which
    we wrap, so callers always get a list.
    """
    entries = payload if isinstance(payload, list) else [payload]
    return [parse_current(entry) for entry in entries]


def fetch_current_batch(points: list[tuple[float, float]]) -> list[WeatherReading]:
    """Current conditions for many waypoints in ONE request, order preserved.

    Comma-separated coordinates collapse ~57 sequential GETs into a single call.
    """
    payload = get_json(
        CURRENT_URL,
        params={
            "latitude": ",".join(f"{lat}" for lat, _ in points),
            "longitude": ",".join(f"{lon}" for _, lon in points),
            "current": "temperature_2m,snowfall,wind_gusts_10m,visibility",
            "wind_speed_unit": "kmh",
        },
    )
    return parse_current_batch(payload)


def fetch_archive_hours(lat: float, lon: float, start: date, end: date) -> list[WeatherReading]:
    """Hourly historical weather for one waypoint over [start, end].

    The archive has no visibility field; those readings come back None and the
    classifier simply can't trigger its visibility rules for backfilled hours
    — a documented limit, not a bug (docs/weather-regimes.md).
    """
    payload = get_json(
        ARCHIVE_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": "snowfall,wind_gusts_10m,surface_temperature",
            "wind_speed_unit": "kmh",
        },
        timeout=30,
    )
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    snowfall = hourly.get("snowfall", [])
    gusts = hourly.get("wind_gusts_10m", [])
    surface = hourly.get("surface_temperature", [])

    readings = []
    for i, time in enumerate(times):
        readings.append(
            _reading(
                time=time,
                snowfall_cm=snowfall[i] if i < len(snowfall) else None,
                visibility_m=None,
                gust_kmh=gusts[i] if i < len(gusts) else None,
                temp_c=surface[i] if i < len(surface) else None,
            )
        )
    log.info("archive fetched: lat=%s lon=%s hours=%d", lat, lon, len(readings))
    return readings
