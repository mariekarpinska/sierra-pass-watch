"""CHP CAD incidents — near-real-time collisions, hazards and closures.

The California Highway Patrol publishes live dispatch activity as a statewide
XML feed (https://media.chp.ca.gov/sa_xml/sa.xml, the machine-readable twin of
the cad.chp.ca.gov page). Unlike CCRS (the authoritative annual crash record),
this feed is transient and unverified: it is best-effort "something is happening
now", not a system of record. We use it only to raise alerts and never to write
the crashes table.

The document nests ``State → Center → Dispatch → Log``; we flatten to one
incident per ``Log``. Coordinates arrive packed as ``"lat:lon"`` in
micro-degrees (``"39316300:120320800"`` → ``39.3163, -120.3208``); longitude is
always west, so we negate it. Times are Pacific wall-clock and converted to UTC.

Keyless, like every other source. One constant URL (no SSRF surface); a failed
fetch or parse degrades to an empty list, so a CHP outage silences alerts
without taking the producer down.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pipeline.fetch import get_text

log = logging.getLogger(__name__)

INCIDENTS_URL = "https://media.chp.ca.gov/sa_xml/sa.xml"


@dataclass
class Incident:
    """One CHP dispatch record, normalized to the fields alerts need."""

    incident_id: str
    category: str        # COLLISION | HAZARD | CLOSURE | OTHER
    type_text: str       # raw CHP LogType, carried into the alert detail
    location_text: str   # free text, parsed for a route id downstream
    lat: float | None
    lon: float | None
    log_time: str        # ISO UTC, or "" if the feed's time was unparseable


# CHP LogType text → our coarse category. Checked in order; first hit wins, so
# closures and collisions outrank the generic hazard bucket.
_CATEGORY_RULES = (
    ("CLOSURE", ("CLOSURE", "CLOSED")),
    ("COLLISION", ("COLLISION", "TRFC", "FATAL", "INJURY", "HIT AND RUN", "OVERTURN")),
    ("HAZARD", ("HAZARD", "OBJECT", "DEBRIS", "ANIMAL", "FLOOD", "MUD", "ROCK", "ICE", "SNOW", "SPILL")),
)


def classify_incident(type_text: str | None) -> str:
    """Map raw CHP LogType text to one of our four categories."""
    t = (type_text or "").upper()
    for category, needles in _CATEGORY_RULES:
        if any(n in t for n in needles):
            return category
    return "OTHER"


def _text(log_el: ET.Element, tag: str) -> str:
    """Child element text, stripped of whitespace and the feed's wrapping quotes."""
    child = log_el.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip().strip('"')


def _parse_latlon(raw: str) -> tuple[float | None, float | None]:
    """"39316300:120890411" → (39.316473, -120.890411). West, so lon is negated."""
    if not raw or ":" not in raw:
        return None, None
    lat_s, lon_s = raw.split(":", 1)
    try:
        lat = int(lat_s) / 1_000_000
        lon = -abs(int(lon_s) / 1_000_000)
    except ValueError:
        return None, None
    if lat == 0 or lon == 0:  # feed's "unknown" sentinel
        return None, None
    return lat, lon


def _pacific_offset(dt: datetime) -> timezone:
    """US Pacific offset for a naive local datetime, no tz database needed.

    PDT (UTC-7) from the 2nd Sunday of March to the 1st Sunday of November,
    otherwise PST (UTC-8).
    """
    mar = datetime(dt.year, 3, 8)  # 2nd Sunday = first Sunday on/after the 8th
    dst_start = mar + timedelta(days=(6 - mar.weekday()) % 7)
    nov = datetime(dt.year, 11, 1)  # 1st Sunday of November
    dst_end = nov + timedelta(days=(6 - nov.weekday()) % 7)
    return timezone(timedelta(hours=-7 if dst_start <= dt < dst_end else -8))


def _parse_logtime(raw: str) -> str:
    """"Jul 10 2026 12:04AM" (Pacific) → ISO 8601 UTC, or "" if unparseable."""
    if not raw:
        return ""
    try:
        naive = datetime.strptime(raw, "%b %d %Y %I:%M%p")
    except ValueError:
        return ""
    return naive.replace(tzinfo=_pacific_offset(naive)).astimezone(timezone.utc).isoformat()


def parse_incidents(xml_text: str) -> list[Incident]:
    """Flatten the CHP XML feed into Incidents. Tolerant of missing fields."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.warning("chp xml parse failed: %s", exc)
        return []
    results = []
    for log_el in root.iter("Log"):
        incident_id = (log_el.get("ID") or log_el.get("id") or "").strip()
        if not incident_id:
            continue
        type_text = _text(log_el, "LogType")
        lat, lon = _parse_latlon(_text(log_el, "LATLON"))
        results.append(
            Incident(
                incident_id=incident_id,
                category=classify_incident(type_text),
                type_text=type_text,
                location_text=_text(log_el, "Location") or _text(log_el, "LocationDesc"),
                lat=lat,
                lon=lon,
                log_time=_parse_logtime(_text(log_el, "LogTime")),
            )
        )
    return results


def fetch_incidents() -> list[Incident]:
    """Live CHP incidents, or [] if the feed is unavailable (best-effort)."""
    try:
        return parse_incidents(get_text(INCIDENTS_URL, timeout=10))
    except Exception as exc:  # noqa: BLE001 — CHP is best-effort; never crash the cycle
        log.warning("chp fetch failed: %s", exc)
        return []
