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
import math
import time
from pathlib import Path

from pipeline.fetch import get_json
from pipeline.geo import cumulative_miles, point_at_measure, project_to_polyline
from pipeline.polylines import BUFFER_MILES
from pipeline.routes import ROUTES, TOWN_ELEVATIONS_FT, town_slug

log = logging.getLogger(__name__)

OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{coords}"
OUTPUT_FILE = Path(__file__).parents[1] / "shared" / "route-journeys.json"
# The drive itself as a drawable [lat, lon] line, one per journey, for the
# route-overview map. Kept in its own file: it is bulky geometry, unlike the
# small per-journey summary in route-journeys.json.
DRIVE_LINES_FILE = Path(__file__).parents[1] / "shared" / "route-drive-lines.json"
# The whole OSRM drive is thousands of points. Resample to one every ~0.3 mi,
# then drop the redundant points on straight stretches (Douglas-Peucker below),
# so the file stays small while the road's shape (curves and all) survives.
DRIVE_LINE_STEP_MILES = 0.3
# Douglas-Peucker tolerance in degrees (~220 m) - a point is dropped when it
# sits closer than this to the line between its kept neighbours. Below a pixel
# at the overview zoom, so the drawn road looks the same with far fewer points.
DRIVE_LINE_TOLERANCE_DEG = 0.002

# A town counts as "on the drive" if its centre sits within this far of the
# route line. Wider than the 700 m crash buffer (polylines.py): town centres sit
# a mile or two off the highway, and we would rather include a passed-through
# town than miss it. Narrow enough that a town in the next valley stays out.
ON_ROUTE_MILES = 2.5

# Be a polite guest on the public OSRM demo server during the one-time build.
THROTTLE_SECONDS = 0.3


def unique_towns() -> dict[str, dict]:
    """Every catalogue town once, keyed by slug (junction towns collapse to
    one), each with its elevation (a KeyError here means a town was added to
    the catalogue without one)."""
    towns: dict[str, dict] = {}
    for route in ROUTES:
        for name, lat, lon in route["towns"]:
            slug = town_slug(name)
            towns.setdefault(
                slug,
                {"name": name, "lat": lat, "lon": lon,
                 "elevationFt": TOWN_ELEVATIONS_FT[slug]},
            )
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


# Miles of a road the drive must cover for that road to count as travelled.
# Enough to catch a connector highway the drive genuinely follows (US-395
# carries ~20 mi of the June Lake -> Mammoth Lakes drive) while ignoring the
# mile or two two highways share at an interchange.
MIN_CONNECTOR_MILES = 5


def _covered_miles(ranges: list[list[int]]) -> int:
    """Whole-mile bins a road's driven ranges cover (bin lo..hi is hi-lo+1)."""
    return sum(hi - lo + 1 for lo, hi in ranges)


def travelled_roads(
    coordinates: list[list[float]],
    ordered: list[str],
    towns: dict[str, dict],
    geometry_for=None,
) -> list[str]:
    """The highways a journey travels, in travel order.

    Starts from the town-membership roads (routes_for), then adds any catalogue
    road with a polyline that the drive actually runs along for at least
    MIN_CONNECTOR_MILES. routes_for names roads only from the towns' catalogue
    membership, so a connector highway no trip town is listed on is missed -
    US-395 carries the June Lake -> Mammoth Lakes drive, but neither town is in
    its town list. Without this the highway's miles are dropped and the
    route-overview map has no line to draw for that pair.

    ``geometry_for`` is the polyline lookup, replaceable in tests.
    """
    if geometry_for is None:
        geometry_for = _route_geometry
    base = routes_for(ordered, towns)
    cumulative = cumulative_miles(coordinates)
    # Only weigh roads whose polyline passes near a stop - a cheap filter that
    # skips the far-off highways the drive never approaches.
    candidates = []
    for road in dict.fromkeys(route["id"] for route in ROUTES):
        geometry = geometry_for(road)
        if road in base or len(geometry) < 2:
            continue
        road_cumulative = cumulative_miles(geometry)
        near = any(
            project_to_polyline(
                towns[slug]["lat"], towns[slug]["lon"], geometry, road_cumulative
            )[1]
            <= ON_ROUTE_MILES
            for slug in ordered
        )
        if near:
            candidates.append(road)
    covered = driven_bins(coordinates, candidates, geometry_for)
    connectors = [
        road
        for road, ranges in covered.items()
        if _covered_miles(ranges) >= MIN_CONNECTOR_MILES
    ]
    if not connectors:
        return base

    def drive_position(road: str) -> float:
        """Drive-mile where the road is first met, so it sorts into travel order."""
        geometry = geometry_for(road)
        if road in covered:  # polylined and driven: where its stretch begins
            lo = covered[road][0][0]
            lat, lon = point_at_measure(geometry, cumulative_miles(geometry), lo + 0.5)
        else:  # a spur with no polyline: its earliest trip town along the drive
            slug = next((s for s in ordered if road in _roads_of(s)), ordered[0])
            lat, lon = towns[slug]["lat"], towns[slug]["lon"]
        return project_to_polyline(lat, lon, coordinates, cumulative)[0]

    return sorted(dict.fromkeys(base + connectors), key=drive_position)


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


def _point_line_distance(p: list[float], a: list[float], b: list[float]) -> float:
    """Distance from point ``p`` to the segment ``a``-``b``, in degrees (a
    planar approximation, fine over the short spans between kept points)."""
    (ay, ax), (by, bx), (py, px) = a, b, p
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def simplify_line(points: list[list[float]], tolerance: float) -> list[list[float]]:
    """Douglas-Peucker: keep the endpoints and every point that bows more than
    ``tolerance`` from the line between its kept neighbours; drop the rest.
    Iterative (an explicit stack) so a long line cannot blow the recursion
    limit."""
    if len(points) < 3:
        return points[:]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        farthest, worst = -1.0, -1
        for i in range(lo + 1, hi):
            d = _point_line_distance(points[i], points[lo], points[hi])
            if d > farthest:
                farthest, worst = d, i
        if worst != -1 and farthest > tolerance:
            keep[worst] = True
            stack.append((lo, worst))
            stack.append((worst, hi))
    return [p for p, k in zip(points, keep) if k]


def drive_line(coordinates: list[list[float]]) -> list[list[float]]:
    """The whole drive as a [lat, lon] polyline for the route-overview map.

    This is the drive itself (OSRM's geometry), not the committed route
    polylines sliced to it, so the map draws one unbroken line from start to
    finish - including the miles on side roads and untracked highways that no
    committed polyline covers. It is resampled to an even ~DRIVE_LINE_STEP_MILES
    shape, rounded to 4 decimals (~11 m), then Douglas-Peucker simplified to
    drop the redundant points on straight stretches - small on disk, same shape
    on screen.
    """
    cumulative = cumulative_miles(coordinates)
    total = cumulative[-1]
    steps = max(1, round(total / DRIVE_LINE_STEP_MILES))
    line = [point_at_measure(coordinates, cumulative, total * i / steps) for i in range(steps + 1)]
    rounded = [[round(lat, 4), round(lon, 4)] for lat, lon in line]
    return simplify_line(rounded, DRIVE_LINE_TOLERANCE_DEG)


def build(output: Path = OUTPUT_FILE, lines_output: Path = DRIVE_LINES_FILE) -> dict:
    towns = unique_towns()
    journeys: dict[str, dict] = {}
    drive_lines: dict[str, list[list[float]]] = {}
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
        via = travelled_roads(route["coordinates"], ordered, towns)
        driven = driven_bins(route["coordinates"], via)
        if not driven:
            # No mile of this drive falls on a tracked highway with a polyline,
            # so it gets no crash-scoped bins (the crash record is major-routes
            # only). The map still draws the full drive line below. Rare;
            # flagged so the data case is seen here, not puzzled over later.
            log.warning("journey has no crash-scoped miles: %s->%s", slug_a, slug_b)
        key = f"{slug_a}|{slug_b}"
        journeys[key] = {
            "towns": ordered,
            "routes": via,
            "anchors": leg_anchor_miles(ordered, via, towns),
            "driven": driven,
            "miles": round(route["miles"], 1),
            "minutes": round(route["minutes"]),
        }
        drive_lines[key] = drive_line(route["coordinates"])
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

    lines_document = {
        "description": (
            "The drive itself as a [lat, lon] polyline for the route-overview "
            "map, one per town pair (key '{slugA}|{slugB}', slugs sorted), "
            "resampled from OSRM's driving geometry to ~0.3 mi spacing. This is "
            "the whole drive - side roads and untracked highways included - so "
            "the map draws an unbroken line, unlike the crash-scoped route "
            "polylines. Built alongside route-journeys.json."
        ),
        "lines": drive_lines,
    }
    lines_output.write_text(json.dumps(lines_document) + "\n", encoding="utf-8")
    log.info("wrote %s (%d lines)", lines_output, len(drive_lines))
    return document


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    build()
