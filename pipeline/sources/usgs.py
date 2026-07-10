"""USGS earthquake feed — quakes near the range (rockfall/landslide context).

The all-hour GeoJSON feed is global; we keep events inside a bounding box
around the full Sierra Nevada and let the producer ask for the strongest
event near each waypoint.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from pipeline.fetch import get_json
from pipeline.geo import haversine_km

log = logging.getLogger(__name__)

FEED_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"

# Full Sierra Nevada + margins (Walker Pass in the south to SR-70 in the north).
LAT_MIN, LAT_MAX = 35.0, 40.5
LON_MIN, LON_MAX = -122.0, -117.4


@dataclass
class SeismicEvent:
    event_id: str
    magnitude: float
    lat: float
    lon: float


def parse_events(payload: dict) -> list[SeismicEvent]:
    events = []
    for feature in payload.get("features", []):
        coords = feature.get("geometry", {}).get("coordinates", [])
        magnitude = feature.get("properties", {}).get("mag")
        if len(coords) < 2 or magnitude is None:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        if LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX:
            events.append(
                SeismicEvent(
                    event_id=feature.get("id", ""),
                    magnitude=float(magnitude),
                    lat=lat,
                    lon=lon,
                )
            )
    return events


def fetch_events() -> list[SeismicEvent]:
    events = parse_events(get_json(FEED_URL))
    log.info("seismic events fetched: count=%d", len(events))
    return events


def strongest_within_km(
    events: list[SeismicEvent], lat: float, lon: float, radius_km: float = 80.0
) -> SeismicEvent | None:
    """Highest-magnitude event within radius of a point, or None."""
    nearby = [e for e in events if haversine_km(lat, lon, e.lat, e.lon) <= radius_km]
    return max(nearby, key=lambda e: e.magnitude) if nearby else None
