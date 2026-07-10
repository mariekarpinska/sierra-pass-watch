"""CHP CAD incidents — near-real-time collisions, hazards and closures.

The California Highway Patrol publishes live dispatch activity per
communications center. Unlike CCRS (the authoritative annual crash record),
this feed is transient and unverified: it is best-effort "something is
happening now", not a system of record. We use it only to raise alerts and
never to write the crashes table.

Keyless, like every other source. One constant URL (no SSRF surface); a failed
fetch degrades to an empty list, so a CHP outage silences alerts without taking
the producer down.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from pipeline.fetch import get_json

log = logging.getLogger(__name__)

# CHP CAD incident feed. The exact endpoint shape varies by CAD release; confirm
# it against the current site before relying on it. Kept a constant so nothing
# user-supplied ever reaches the fetch (see pipeline/fetch.py).
INCIDENTS_URL = "https://cad.chp.ca.gov/api/incidents"


@dataclass
class Incident:
    """One CHP dispatch record, normalized to the fields alerts need."""

    incident_id: str
    category: str        # COLLISION | HAZARD | CLOSURE | OTHER
    type_text: str       # raw CHP type, carried into the alert detail
    location_text: str   # free text, parsed for a route id downstream
    lat: float | None
    lon: float | None
    log_time: str        # ISO, as reported


# CHP type text → our coarse category. Checked in order; first hit wins, so
# closures and collisions outrank the generic hazard bucket.
_CATEGORY_RULES = (
    ("CLOSURE", ("CLOSURE", "CLOSED")),
    ("COLLISION", ("COLLISION", "TRFC", "FATAL", "INJURY", "HIT AND RUN", "OVERTURN")),
    ("HAZARD", ("HAZARD", "OBJECT", "DEBRIS", "ANIMAL", "FLOOD", "MUD", "ROCK", "ICE", "SNOW", "SPILL")),
)


def classify_incident(type_text: str | None) -> str:
    """Map raw CHP incident text to one of our four categories."""
    t = (type_text or "").upper()
    for category, needles in _CATEGORY_RULES:
        if any(n in t for n in needles):
            return category
    return "OTHER"


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_incidents(payload: dict) -> list[Incident]:
    """Normalize a CHP feed payload into Incidents. Tolerant of missing fields."""
    results = []
    for item in payload.get("incidents", []):
        incident_id = str(item.get("id") or item.get("logNumber") or "").strip()
        if not incident_id:
            continue
        type_text = item.get("type") or item.get("logType") or ""
        results.append(
            Incident(
                incident_id=incident_id,
                category=classify_incident(type_text),
                type_text=type_text,
                location_text=item.get("location") or item.get("locationDesc") or "",
                lat=_num(item.get("latitude") if item.get("latitude") is not None else item.get("lat")),
                lon=_num(item.get("longitude") if item.get("longitude") is not None else item.get("lon")),
                log_time=item.get("logTime") or item.get("timestamp") or "",
            )
        )
    return results


def fetch_incidents() -> list[Incident]:
    """Live CHP incidents, or [] if the feed is unavailable (best-effort)."""
    try:
        return parse_incidents(get_json(INCIDENTS_URL, timeout=10))
    except Exception as exc:  # noqa: BLE001 — CHP is best-effort; never crash the cycle
        log.warning("chp fetch failed: %s", exc)
        return []
