"""Build shared/route-journeys.json - the multi-highway journey index.

A trip through the Sierra often crosses highways (I-80 to SR-89 to US-50). The
per-route catalogue cannot express that, and hand-mapping every interchange is a
brittle data project. Instead, for every pair of catalogue towns, ask OSRM (the
public OSM router, the same keyless build-time source build_polylines.py uses)
for the driving route, then keep the catalogue towns that fall along it, in
travel order. The result answers one question at runtime: "which of our weather
anchors lie on the drive from A to B, and in what order?"

Output (committed, read into memory by the API like the route catalogue):

* ``towns``    - the picker's directory: slug -> {name, lat, lon}
* ``journeys`` - "{slugA}|{slugB}" (slugs sorted) -> {towns: [slug ...], miles,
                 minutes}, the anchor towns along that drive in A->B order

This is a build-time tool, run rarely and by hand; nothing at build or run time
depends on OSRM being up. Re-run it only when the catalogue's towns change:

    python -m pipeline.build_journeys
"""
from __future__ import annotations

import itertools
import json
import logging
import time
from pathlib import Path

from pipeline.fetch import get_json
from pipeline.geo import cumulative_miles, project_to_polyline
from pipeline.routes import ROUTES, town_slug

log = logging.getLogger(__name__)

OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{coords}"
OUTPUT_FILE = Path(__file__).parents[1] / "shared" / "route-journeys.json"

# A town counts as "on the drive" if its centre sits within this far of the
# route line. Wider than the 700 m crash buffer (polylines.py): town centres sit
# a mile or two off the highway, and we would rather include a passed-through
# town than miss it. Narrow enough that a town in the next valley stays out.
ON_ROUTE_MILES = 2.5

# Be a polite guest on the public OSRM demo server during the one-time build.
THROTTLE_SECONDS = 0.3


def unique_towns() -> dict[str, dict]:
    """Every catalogue town once, keyed by slug (junction towns collapse to one)."""
    towns: dict[str, dict] = {}
    for route in ROUTES:
        for name, lat, lon in route["towns"]:
            towns.setdefault(town_slug(name), {"name": name, "lat": lat, "lon": lon})
    return towns


def fetch_route(a: dict, b: dict) -> dict:
    """OSRM driving route between two towns: geometry, distance, duration."""
    coords = f"{a['lon']},{a['lat']};{b['lon']},{b['lat']}"
    payload = get_json(
        OSRM_URL.format(coords=coords),
        params={"overview": "full", "geometries": "geojson", "steps": "false"},
        timeout=30,
    )
    if payload.get("code") != "Ok" or not payload.get("routes"):
        raise ValueError(f"OSRM returned {payload.get('code')!r}")
    route = payload["routes"][0]
    return {
        "coordinates": route["geometry"]["coordinates"],
        "miles": route["distance"] / 1609.344,
        "minutes": route["duration"] / 60,
    }


def towns_along(coordinates: list[list[float]], towns: dict[str, dict]) -> list[str]:
    """The town slugs whose centre lies within ON_ROUTE_MILES of the route line,
    ordered by how far along the drive they sit."""
    cumulative = cumulative_miles(coordinates)
    on_route: list[tuple[float, str]] = []
    for slug, town in towns.items():
        measure, offset = project_to_polyline(
            town["lat"], town["lon"], coordinates, cumulative
        )
        if offset <= ON_ROUTE_MILES:
            on_route.append((measure, slug))
    on_route.sort()
    return [slug for _, slug in on_route]


def build(output: Path = OUTPUT_FILE) -> dict:
    towns = unique_towns()
    journeys: dict[str, dict] = {}
    pairs = list(itertools.combinations(sorted(towns), 2))
    log.info("building %d journeys over %d towns", len(pairs), len(towns))

    for done, (slug_a, slug_b) in enumerate(pairs, start=1):
        try:
            route = fetch_route(towns[slug_a], towns[slug_b])
        except Exception as exc:  # noqa: BLE001 - report and continue; a rerun fills gaps
            log.error("journey failed: %s->%s error=%s", slug_a, slug_b, exc)
            continue
        ordered = towns_along(route["coordinates"], towns)
        # Clamp to the endpoints: the on-route buffer can catch a town sitting
        # just past the origin or destination (Stateline is within 2.5 mi of a
        # route that ends at South Lake Tahoe) - the drive never reaches it.
        first, last = sorted((ordered.index(slug_a), ordered.index(slug_b)))
        ordered = ordered[first : last + 1]
        journeys[f"{slug_a}|{slug_b}"] = {
            "towns": ordered,
            "miles": round(route["miles"], 1),
            "minutes": round(route["minutes"]),
        }
        if done % 50 == 0:
            log.info("... %d/%d", done, len(pairs))
        time.sleep(THROTTLE_SECONDS)

    document = {
        "description": (
            "Multi-highway journeys between catalogue towns, built by "
            "python -m pipeline.build_journeys from OSRM driving routes. For each "
            "town pair, the catalogue's weather anchors that fall along the drive, "
            "in travel order. Committed so nothing depends on OSRM at build/run "
            "time; re-run only when the catalogue's towns change."
        ),
        "towns": towns,
        "journeys": journeys,
    }
    output.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    log.info("wrote %s (%d journeys)", output, len(journeys))
    return document


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    build()
