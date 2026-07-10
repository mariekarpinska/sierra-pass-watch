"""Route polylines + the measure axis — read side of build_polylines.py.

Loads shared/route-polylines.json once, precomputes cumulative distances, and
answers the one question the crash loader asks: *where along its route is
this point?* A crash is only given a measure when it sits within the 700 m
buffer of the polyline — the same idea as buffering the route and keeping
what falls inside, expressed as a distance test (ADR-0007).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from pipeline.geo import cumulative_miles, project_to_polyline

POLYLINES_FILE = Path(__file__).parents[1] / "shared" / "route-polylines.json"

# 700 m: wide enough for GPS scatter, ramps and divided carriageways; narrow
# enough that a parallel local road two blocks over stays out.
BUFFER_MILES = 700 / 1609.344

_cache: dict[str, tuple[list[list[float]], list[float]]] | None = None


def _polylines() -> dict[str, tuple[list[list[float]], list[float]]]:
    global _cache  # noqa: PLW0603 — module-level lazy load, like routes.py's ring
    if _cache is None:
        raw = json.loads(POLYLINES_FILE.read_text(encoding="utf-8"))["routes"]
        _cache = {
            route_id: (entry["coordinates"], cumulative_miles(entry["coordinates"]))
            for route_id, entry in raw.items()
        }
    return _cache


def route_length_miles(route_id: str) -> float | None:
    """Total polyline length, or None for routes without one (spurs)."""
    entry = _polylines().get(route_id)
    return None if entry is None else entry[1][-1]


def measure_for(route_id: str, lat: float, lon: float) -> float | None:
    """Distance-along-route (miles) for a point, or None.

    None means either the route has no polyline (single-town spur) or the
    point is outside the 700 m buffer — in both cases the crash keeps its
    route attribution but joins no per-mile bin.
    """
    entry = _polylines().get(route_id)
    if entry is None:
        return None
    coords, cumulative = entry
    measure, offset = project_to_polyline(lat, lon, coords, cumulative)
    if offset > BUFFER_MILES or math.isinf(offset):
        return None
    return round(measure, 3)
