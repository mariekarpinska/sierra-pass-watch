"""National Weather Service — hourly forecast per waypoint (gap filler).

Open-Meteo and RWIS carry the primary numerics; NWS fills wind gusts when
both miss. Grids resolve per waypoint through the points API and are cached
for the process lifetime, so full-Sierra coverage costs one lookup per
waypoint ever, then one forecast call per poll.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from pipeline.fetch import get_json

log = logging.getLogger(__name__)

POINTS_URL = "https://api.weather.gov/points/{lat},{lon}"
FORECAST_URL = "https://api.weather.gov/gridpoints/{office}/{x},{y}/forecast/hourly"

# segment_id → (office, x, y); populated on first resolve, per process.
_grid_cache: dict[str, tuple[str, int, int]] = {}


@dataclass
class NwsForecast:
    start_time: str
    temperature_f: float | None
    wind_gust_mph: float | None
    short_forecast: str


def _parse_mph(value) -> float | None:
    """NWS wind comes as '25 mph' strings or {'value': …} objects."""
    if isinstance(value, dict):
        return value.get("value")
    if isinstance(value, str):
        match = re.search(r"[\d.]+", value)
        return float(match.group()) if match else None
    return None


def _resolve_grid(segment_id: str, lat: float, lon: float) -> tuple[str, int, int] | None:
    if segment_id in _grid_cache:
        return _grid_cache[segment_id]
    try:
        properties = get_json(
            POINTS_URL.format(lat=round(lat, 4), lon=round(lon, 4)), timeout=10
        ).get("properties", {})
        office, x, y = properties.get("gridId"), properties.get("gridX"), properties.get("gridY")
        if office and x is not None and y is not None:
            _grid_cache[segment_id] = (office, int(x), int(y))
            return _grid_cache[segment_id]
    except Exception as exc:  # noqa: BLE001 — a missing grid only loses the NWS fallback
        log.warning("nws grid lookup failed: segment=%s error=%s", segment_id, exc)
    return None


def fetch_forecast(segment_id: str, lat: float, lon: float) -> NwsForecast | None:
    """Next-hour NWS forecast for one waypoint, or None if unavailable."""
    grid = _resolve_grid(segment_id, lat, lon)
    if grid is None:
        return None
    office, x, y = grid
    try:
        payload = get_json(FORECAST_URL.format(office=office, x=x, y=y))
    except Exception as exc:  # noqa: BLE001
        log.warning("nws forecast failed: segment=%s error=%s", segment_id, exc)
        return None
    periods = payload.get("properties", {}).get("periods", [])
    if not periods:
        return None
    period = periods[0]
    return NwsForecast(
        start_time=period.get("startTime", ""),
        temperature_f=float(period["temperature"]) if period.get("temperature") is not None else None,
        wind_gust_mph=_parse_mph(period.get("windGust")),
        short_forecast=period.get("shortForecast", ""),
    )
