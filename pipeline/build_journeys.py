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
* ``journeys`` - "{slugA}|{slugB}" (slugs sorted) -> {towns: [slug ...], routes,
                 anchors, driven, miles, minutes}, the anchor towns along that
                 drive in A->B order, the highways it follows, per highway each
                 on-road stop's mile measure (leg_anchor_miles), and per highway
                 the mile-bin ranges the drive actually covers (driven_bins)

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
from pipeline.geo import cumulative_miles, point_at_measure, project_to_polyline
from pipeline.polylines import BUFFER_MILES
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


def _roads_of(slug: str) -> set[str]:
    """Every catalogue route this town sits on (junction towns sit on two)."""
    return {
        route["id"]
        for route in ROUTES
        if any(town_slug(name) == slug for name, _, _ in route["towns"])
    }


POLYLINES_FILE = Path(__file__).parents[1] / "shared" / "route-polylines.json"

_geometries: dict[str, list[list[float]]] | None = None


def _route_geometry(road: str) -> list[list[float]]:
    """The road's committed polyline (built by build_polylines.py), loaded once."""
    global _geometries
    if _geometries is None:
        payload = json.loads(POLYLINES_FILE.read_text(encoding="utf-8"))
        _geometries = {rid: entry["coordinates"] for rid, entry in payload["routes"].items()}
    return _geometries.get(road, [])


def _closest_approach(road: str, lat: float, lon: float) -> float:
    """How near (squared degrees; comparison only) this road's geometry gets to
    a point. Geometry rather than town lists on purpose: SR-89 and SR-28 both
    contain Tahoe City, and across the lake Kings Beach is straight-line closer
    to South Lake Tahoe than Markleeville - but only SR-89's line actually runs
    down toward it."""
    geometry = _route_geometry(road)[::5]  # every 5th point is plenty
    if not geometry:
        return float("inf")
    return min((p_lat - lat) ** 2 + (p_lon - lon) ** 2 for p_lon, p_lat in geometry)


def routes_for(slugs: list[str], towns: dict[str, dict]) -> list[str]:
    """The highways a journey travels, in stop order - ["I-80", "SR-89",
    "US-50"] for Colfax to South Lake Tahoe. Derived from route membership:
    stay on the current road until a stop is not on it; when switching, prefer
    a road shared with the next stop, and if none is (a junction town like
    Tahoe City sits on two roads and the next stop is on neither), take the
    road whose committed polyline gets closest to the next stop. A heuristic,
    but it names the passes a trip crosses, which is what the seasonal warning
    needs."""
    slug_roads = [_roads_of(slug) for slug in slugs]
    via: list[str] = []
    for i, roads in enumerate(slug_roads):
        if via and via[-1] in roads:
            continue
        upcoming = slug_roads[i + 1] if i + 1 < len(slug_roads) else roads
        if roads & upcoming:
            via.append(min(roads & upcoming))
            continue
        target = towns[slugs[min(i + 1, len(slugs) - 1)]]
        via.append(
            # The road id breaks exact ties, so the result never depends on
            # set iteration order.
            min(roads, key=lambda road: (_closest_approach(road, target["lat"], target["lon"]), road))
        )
    return via


def leg_anchor_miles(
    slugs: list[str],
    roads: list[str],
    towns: dict[str, dict],
    geometry_for=None,
) -> dict[str, dict[str, float]]:
    """For each travelled road, the journey's stops that sit on it (within
    ON_ROUTE_MILES) with their mile measure along the road's committed
    polyline - the same measure axis crashes and bins live on (ADR-0007).

    The measures are what the API needs to work at sub-journey grain: the
    outermost two bound the stretch the drive covers on that road (its span),
    and the points between them are where the drive's weather is actually
    known, so the crash match can follow the forecast along the road. The
    bounds are stop-based, so the mile or two between the last anchor and the
    actual interchange is not counted; anchors are the journey's unit of
    position, and the product claims nothing finer. Spur routes with no
    polyline get no entry.

    ``geometry_for`` is the polyline lookup, replaceable in tests; it defaults
    to the committed route-polylines.json.
    """
    if geometry_for is None:
        geometry_for = _route_geometry
    anchors: dict[str, dict[str, float]] = {}
    for road in dict.fromkeys(roads):
        geometry = geometry_for(road)
        if len(geometry) < 2:
            continue
        cumulative = cumulative_miles(geometry)
        on_road: dict[str, float] = {}
        for slug in slugs:
            measure, offset = project_to_polyline(
                towns[slug]["lat"], towns[slug]["lon"], geometry, cumulative
            )
            if offset <= ON_ROUTE_MILES:
                on_road[slug] = round(measure, 1)
        if on_road:
            anchors[road] = on_road
    return anchors


# The mile-by-mile distance test below runs against a THINNED copy of the
# drive line - every 3rd point of OSRM's ~thousands - which makes it ~3x
# faster. The cost: straight lines between kept points cut across the inside
# of sharp bends, so at a hairpin the thinned line can sit up to ~0.25 mi
# away from where the car actually drove. The second constant widens the
# test by exactly that much. One knob: keep fewer points and the allowance
# must grow, or miles on switchbacks stop counting as driven.
_DRIVE_DECIMATE = 3  # keep every 3rd point of the drive line
_DECIMATION_SLACK_MILES = 0.25  # worst gap between thinned and real line

# A road mile counts as driven when its centre point lies within BUFFER_MILES
# of the thinned drive line (the same 700 m that attaches a crash to a road,
# so the marks and the drive agree on what "on the road" means), plus the
# thinning allowance above.
_DRIVEN_TOLERANCE_MILES = BUFFER_MILES + _DECIMATION_SLACK_MILES


def driven_bins(
    coordinates: list[list[float]],
    roads: list[str],
    geometry_for=None,
) -> dict[str, list[list[int]]]:
    """For each travelled road, the contiguous ranges of whole-mile bins the
    drive actually covers on it - the drive's own OSRM geometry decides, not
    the road's corridor. Each road mile's centre point is tested against the
    drive line; miles within the buffer are driven. Neighbouring ranges a
    single empty bin apart merge (sampling wobble); wider gaps are real (the
    drive left the road and came back) and stay separate ranges.

    Roads with no polyline (spurs) get no entry; the API falls back to their
    whole corridor. ``geometry_for`` is the polyline lookup, replaceable in
    tests.
    """
    if geometry_for is None:
        geometry_for = _route_geometry
    drive = coordinates[::_DRIVE_DECIMATE]
    if drive[-1] != coordinates[-1]:
        drive.append(coordinates[-1])
    drive_cumulative = cumulative_miles(drive)
    driven: dict[str, list[list[int]]] = {}
    for road in dict.fromkeys(roads):
        geometry = geometry_for(road)
        if len(geometry) < 2:
            continue
        cumulative = cumulative_miles(geometry)
        bins: list[int] = []
        for mile in range(int(cumulative[-1]) + 1):
            lat, lon = point_at_measure(geometry, cumulative, mile + 0.5)
            _, offset = project_to_polyline(lat, lon, drive, drive_cumulative)
            if offset <= _DRIVEN_TOLERANCE_MILES:
                bins.append(mile)
        ranges: list[list[int]] = []
        for mile in bins:
            if ranges and mile - ranges[-1][1] <= 2:
                ranges[-1][1] = mile
            else:
                ranges.append([mile, mile])
        if ranges:
            driven[road] = ranges
    return driven


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
        via = routes_for(ordered, towns)
        journeys[f"{slug_a}|{slug_b}"] = {
            "towns": ordered,
            "routes": via,
            "anchors": leg_anchor_miles(ordered, via, towns),
            "driven": driven_bins(route["coordinates"], via),
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
            "in travel order, the highways it follows, each on-road stop's mile "
            "measure, and the mile-bin ranges the drive actually covers per "
            "highway (all on the same measure axis as the crash bins). Committed "
            "so nothing depends on OSRM at build/run time; re-run when the "
            "catalogue's towns or the route polylines change."
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
