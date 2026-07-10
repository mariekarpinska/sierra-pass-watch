"""The Sierra Nevada route catalogue — the single source of coverage.

Everything the pipeline ingests is anchored here: the producer polls one
waypoint per (route, town); the backfill replays the same waypoints; crash
records are attributed to a route by parsing the report's ``primary_road``
text and kept only if they fall inside the Sierra Nevada range polygon.
Adding a route is a data change in ROUTES — no code changes anywhere.

Segment ids are ``"{route_id}:{town-slug}"`` (e.g. ``I-80:donner-summit``),
the same convention the frontend contract uses end to end.

Pure data + parsing helpers — no network, no database.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pipeline.geo import point_in_ring

_COORDS_FILE = Path(__file__).parent / "data" / "sierra_nevada_coords.json"

# ---------------------------------------------------------------------------
# Route catalogue
#   id       : canonical id (also what primary_road text parses to)
#   name     : the crossing / corridor name
#   road_no  : Caltrans road number (closure lookups)
#   seasonal : True if the pass closes seasonally
#   note     : short context shown in the UI
#   towns    : ordered (name, lat, lon) forecast waypoints along the route
# ---------------------------------------------------------------------------
ROUTES: list[dict] = [
    {"id": "I-80", "name": "Donner Pass", "road_no": "80", "seasonal": False,
     "note": "Only freeway across the range · year-round",
     "towns": [("Colfax", 39.1002, -120.9533), ("Donner Summit", 39.3163, -120.3208), ("Truckee", 39.3280, -120.1833)]},
    {"id": "US-50", "name": "Echo Summit", "road_no": "50", "seasonal": False,
     "note": "Year-round to South Lake Tahoe",
     "towns": [("Placerville", 38.7296, -120.7985), ("Echo Summit", 38.8124, -120.0307), ("South Lake Tahoe", 38.9399, -119.9772)]},
    {"id": "US-395", "name": "Eastern Sierra corridor", "road_no": "395", "seasonal": False,
     "note": "Runs the length of the range's eastern base · year-round",
     "towns": [("Bridgeport", 38.2566, -119.2313), ("Lee Vining", 37.9558, -119.1188), ("Bishop", 37.3636, -118.3951), ("Lone Pine", 36.6061, -118.0626)]},
    {"id": "US-6", "name": "Bishop → Nevada", "road_no": "6", "seasonal": False,
     "note": "Short stretch near Bishop into Nevada",
     "towns": [("Bishop", 37.3636, -118.3951)]},
    {"id": "SR-70", "name": "Feather River Canyon", "road_no": "70", "seasonal": False,
     "note": "Lowest / northernmost crossing · generally year-round",
     "towns": [("Oroville", 39.5138, -121.5564), ("Quincy", 39.9368, -120.9456)]},
    {"id": "SR-88", "name": "Carson Pass", "road_no": "88", "seasonal": True,
     "note": "~8,650 ft · seasonal",
     "towns": [("Jackson", 38.3489, -120.7741), ("Kirkwood", 38.6868, -120.0657), ("Carson Pass", 38.6940, -119.9842)]},
    {"id": "SR-4", "name": "Ebbetts Pass", "road_no": "4", "seasonal": True,
     "note": "~8,730 ft · narrow & seasonal",
     "towns": [("Arnold", 38.2552, -120.3502), ("Bear Valley", 38.4602, -120.0419), ("Ebbetts Pass", 38.5466, -119.8085)]},
    {"id": "SR-108", "name": "Sonora Pass", "road_no": "108", "seasonal": True,
     "note": "~9,620 ft · seasonal",
     "towns": [("Sonora", 37.9841, -120.3822), ("Pinecrest", 38.1929, -119.9876), ("Sonora Pass", 38.3283, -119.6360)]},
    {"id": "SR-120", "name": "Tioga Pass", "road_no": "120", "seasonal": True,
     "note": "~9,945 ft · highest pass · through Yosemite · closed ~Nov–May",
     "towns": [("Groveland", 37.8377, -120.2266), ("Tuolumne Meadows", 37.8736, -119.3500), ("Tioga Pass", 37.9105, -119.2573), ("Lee Vining", 37.9558, -119.1188)]},
    {"id": "SR-178", "name": "Walker Pass", "road_no": "178", "seasonal": False,
     "note": "~5,250 ft · only paved crossing in the southern Sierra",
     "towns": [("Lake Isabella", 35.6188, -118.4729), ("Walker Pass", 35.6597, -118.0290), ("Ridgecrest", 35.6225, -117.6709)]},
    {"id": "SR-49", "name": "Golden Chain Highway", "road_no": "49", "seasonal": False,
     "note": "Western Gold Country foothills",
     "towns": [("Grass Valley", 39.2188, -121.0608), ("Auburn", 38.8966, -121.0769), ("Sonora", 37.9841, -120.3822), ("Mariposa", 37.4849, -119.9663)]},
    {"id": "SR-89", "name": "Tahoe ↔ Monitor Pass", "road_no": "89", "seasonal": True,
     "note": "Links Tahoe to Monitor Pass (~8,310 ft) & Markleeville",
     "towns": [("Tahoe City", 39.1658, -120.1428), ("Markleeville", 38.6952, -119.7782), ("Monitor Pass", 38.6730, -119.6190)]},
    {"id": "SR-28", "name": "North/East Lake Tahoe", "road_no": "28", "seasonal": False,
     "note": "Rings the north/east shore of Lake Tahoe",
     "towns": [("Tahoe City", 39.1658, -120.1428), ("Kings Beach", 39.2377, -120.0263)]},
    {"id": "SR-207", "name": "Kingsbury Grade", "road_no": "207", "seasonal": False,
     "note": "Climbs out of the Tahoe basin",
     "towns": [("Stateline", 38.9596, -119.9398)]},
    {"id": "SR-267", "name": "Brockway Summit", "road_no": "267", "seasonal": False,
     "note": "Climbs out of the Tahoe basin near Truckee",
     "towns": [("Truckee", 39.3280, -120.1833), ("Kings Beach", 39.2377, -120.0263)]},
    {"id": "SR-431", "name": "Mount Rose Highway", "road_no": "431", "seasonal": True,
     "note": "Carson Range, Nevada · no California crash data",
     "towns": [("Incline Village", 39.2510, -119.9460), ("Mount Rose Summit", 39.3140, -119.8970)]},
    {"id": "SR-140", "name": "Yosemite via El Portal", "road_no": "140", "seasonal": False,
     "note": "Merced River canyon · lower snow-free approach",
     "towns": [("Mariposa", 37.4849, -119.9663), ("El Portal", 37.6757, -119.7831)]},
    {"id": "SR-41", "name": "Yosemite via Wawona", "road_no": "41", "seasonal": False,
     "note": "South entrance from Fresno",
     "towns": [("Oakhurst", 37.3277, -119.6493), ("Wawona", 37.5377, -119.6566)]},
    {"id": "SR-180", "name": "Kings Canyon", "road_no": "180", "seasonal": True,
     "note": "Into Kings Canyon (Cedar Grove seasonal)",
     "towns": [("Grant Grove", 36.7409, -118.9618), ("Cedar Grove", 36.7944, -118.6840)]},
    {"id": "SR-198", "name": "Sequoia / Generals Hwy", "road_no": "198", "seasonal": False,
     "note": "Into Sequoia; connects to SR-180 via Generals Highway",
     "towns": [("Three Rivers", 36.4386, -118.9020), ("Giant Forest", 36.5650, -118.7730)]},
    {"id": "SR-168W", "name": "Shaver / Huntington Lakes", "road_no": "168", "seasonal": False,
     "note": "Western SR-168 to Shaver & Huntington Lakes",
     "towns": [("Shaver Lake", 37.1058, -119.3179), ("Huntington Lake", 37.2330, -119.2204)]},
    {"id": "SR-168E", "name": "Bishop → South Lake", "road_no": "168", "seasonal": True,
     "note": "Eastern SR-168 (Bishop to South Lake / Lake Sabrina) · disconnected from west",
     "towns": [("Bishop", 37.3636, -118.3951), ("South Lake", 37.1690, -118.5640)]},
    {"id": "SR-203", "name": "Mammoth Lakes", "road_no": "203", "seasonal": False,
     "note": "Into Mammoth Lakes",
     "towns": [("Mammoth Lakes", 37.6485, -118.9721)]},
    {"id": "SR-158", "name": "June Lake Loop", "road_no": "158", "seasonal": True,
     "note": "June Lake Loop · seasonal",
     "towns": [("June Lake", 37.7805, -119.0718)]},
]

ROUTE_BY_ID = {r["id"]: r for r in ROUTES}


def town_slug(name: str) -> str:
    """"Donner Summit" → "donner-summit" — must match the frontend's townSlug."""
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", name.lower()))


def build_segments() -> list[dict]:
    """One ingestion waypoint per (route, town), with contract-format ids."""
    return [
        {
            "segment_id": f"{route['id']}:{town_slug(town_name)}",
            "segment_name": town_name,
            "route_id": route["id"],
            "lat": lat,
            "lon": lon,
        }
        for route in ROUTES
        for town_name, lat, lon in route["towns"]
    ]


SEGMENTS: list[dict] = build_segments()

# ---------------------------------------------------------------------------
# primary_road parsing — attributing a crash report to a catalogue route
# ---------------------------------------------------------------------------

# Numeric-only route numbers need a prefix to match so "50" in an address
# number can't hit US-50. SR-168 splits into W/E by longitude (disconnected).
_ROUTE_PATTERNS = {
    "I-80": r"\bI[\s-]?80\b",
    "US-50": r"\b(US|HWY|HIGHWAY)[\s-]?50\b",
    "US-395": r"\b(US|HWY|HIGHWAY)[\s-]?395\b",
    "US-6": r"\b(US|HWY|HIGHWAY)[\s-]?6\b",
    **{
        f"SR-{n}": rf"\b(SR|CA|ROUTE|STATE ROUTE|HWY|HIGHWAY)[\s-]?{n}\b"
        for n in (70, 88, 4, 108, 120, 178, 49, 89, 28, 207, 267, 431, 140, 41, 180, 198, 203, 158, 168)
    },
}
_COMPILED = {rid: re.compile(p) for rid, p in _ROUTE_PATTERNS.items()}

# Longer / more specific numbers first, so "SR-267" never matches as "SR-26…".
_MATCH_ORDER = [
    "I-80", "US-395", "US-50", "US-6", "SR-431", "SR-267", "SR-207", "SR-203",
    "SR-198", "SR-180", "SR-178", "SR-168", "SR-158", "SR-140", "SR-120",
    "SR-108", "SR-89", "SR-88", "SR-70", "SR-49", "SR-41", "SR-28", "SR-4",
]

_DIRECTION_RE = re.compile(r"\b(NORTHBOUND|SOUTHBOUND|EASTBOUND|WESTBOUND|[NSEW]/?B)\b")
_DIRECTION_MAP = {"NORTHBOUND": "NB", "SOUTHBOUND": "SB", "EASTBOUND": "EB", "WESTBOUND": "WB"}


def parse_route(primary_road: str | None, lon: float | None = None) -> str | None:
    """Map a crash report's primary_road text to a catalogue route id.

    SR-168's two halves are disconnected by the range itself; longitude picks
    the side (eastern segment sits near -118.5, western near -119.2).
    """
    if not primary_road:
        return None
    text = primary_road.upper()
    for route_id in _MATCH_ORDER:
        if _COMPILED[route_id].search(text):
            if route_id == "SR-168":
                return "SR-168E" if lon is not None and lon > -118.9 else "SR-168W"
            return route_id
    return None


def parse_direction(primary_road: str | None) -> str | None:
    """Extract NB/SB/EB/WB from primary_road text, or None."""
    if not primary_road:
        return None
    match = _DIRECTION_RE.search(primary_road.upper())
    if not match:
        return None
    token = match.group(1).replace("/", "")
    return _DIRECTION_MAP.get(token, token)


def union_route_pattern() -> str:
    """One regex matching ANY tracked route — the coarse crash-file prefilter."""
    return "(" + "|".join(_ROUTE_PATTERNS[rid] for rid in _MATCH_ORDER) + ")"


# ---------------------------------------------------------------------------
# Sierra Nevada range polygon
# ---------------------------------------------------------------------------

# The raw outline traces the high range; on-route crashes also happen on the
# foothill approaches just outside it. The ring is pushed outward from its
# centroid by ~0.28° (~25 km) so approaches count while the Bay Area / deep
# Central Valley stretches of shared route numbers stay out.
_BUFFER_DEG = 0.28
_ring_cache: list[list[float]] = []


def _buffered_ring() -> list[list[float]]:
    if not _ring_cache:
        raw = json.loads(_COORDS_FILE.read_text(encoding="utf-8"))["coordinates"][0]
        cx = sum(p[0] for p in raw) / len(raw)
        cy = sum(p[1] for p in raw) / len(raw)
        for x, y in raw:
            dx, dy = x - cx, y - cy
            d = (dx * dx + dy * dy) ** 0.5 or 1.0
            _ring_cache.append([x + dx / d * _BUFFER_DEG, y + dy / d * _BUFFER_DEG])
    return _ring_cache


def in_sierra(lat: float, lon: float) -> bool:
    """Is this point inside the (buffered) Sierra Nevada range outline?"""
    return point_in_ring(lat, lon, _buffered_ring())


def sierra_bbox() -> tuple[float, float, float, float]:
    """(min_lon, max_lon, min_lat, max_lat) of the buffered ring — fast prefilter."""
    ring = _buffered_ring()
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return min(lons), max(lons), min(lats), max(lats)
