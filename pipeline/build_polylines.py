"""Build shared/route-polylines.json — the measure axis of the whole product.

For every catalogue route with at least two towns, ask OSRM (the public OSM
router — same keyless posture as every other source) for the driving geometry
through the route's towns in order, then linear-reference each town onto that
polyline. The output file carries, per route:

* ``coordinates``  — the polyline, [[lon, lat], ...] (GeoJSON order)
* ``lengthMiles``  — total length along the line
* ``anchors``      — every town with its ``measureMi`` (distance-along-route)

Crashes are later projected onto the same polyline (backfill), so crashes,
per-mile bins, hotspots and anchor labels all share one coordinate: the
measure. Routes with a single town (short spurs) get no polyline — their
crash record stays at the route grain, an accepted limit noted in ADR-0007.

This is a build-time tool, run rarely and by hand; the JSON it writes is
committed so no build or deploy ever depends on OSRM being up:

    python -m pipeline.build_polylines
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from pipeline.fetch import get_json
from pipeline.geo import cumulative_miles, project_to_polyline
from pipeline.routes import ROUTES, town_slug

log = logging.getLogger(__name__)

OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{coords}"
OUTPUT_FILE = Path(__file__).parents[1] / "shared" / "route-polylines.json"


def fetch_polyline(towns: list[dict]) -> list[list[float]]:
    """OSRM driving geometry through the towns, as [[lon, lat], ...]."""
    coords = ";".join(f"{t['lon']}%2C{t['lat']}" for t in towns)
    # %2C keeps commas out of requests-quoting trouble; OSRM accepts both.
    payload = get_json(
        OSRM_URL.format(coords=coords.replace("%2C", ",")),
        params={"overview": "full", "geometries": "geojson", "steps": "false"},
        timeout=30,
    )
    if payload.get("code") != "Ok" or not payload.get("routes"):
        raise ValueError(f"OSRM returned {payload.get('code')!r}")
    return payload["routes"][0]["geometry"]["coordinates"]


def build_route_entry(route: dict) -> dict | None:
    """Polyline + anchor measures for one catalogue route (None for spurs)."""
    towns = [{"name": n, "lat": lat, "lon": lon} for n, lat, lon in route["towns"]]
    if len(towns) < 2:
        return None
    coordinates = fetch_polyline(towns)
    cumulative = cumulative_miles(coordinates)
    anchors = []
    for town in towns:
        measure, offset = project_to_polyline(
            town["lat"], town["lon"], coordinates, cumulative
        )
        anchors.append(
            {
                "name": town["name"],
                "segmentId": f"{route['id']}:{town_slug(town['name'])}",
                "measureMi": round(measure, 2),
                # How far the town centre sits off the highway line — context
                # for reviewing the data, not used downstream.
                "offsetMi": round(offset, 2),
            }
        )
    return {
        "lengthMiles": round(cumulative[-1], 2),
        "anchors": anchors,
        "coordinates": [[round(lon, 5), round(lat, 5)] for lon, lat in coordinates],
    }


def build(output: Path = OUTPUT_FILE) -> dict:
    routes: dict[str, dict] = {}
    for route in ROUTES:
        try:
            entry = build_route_entry(route)
        except Exception as exc:  # noqa: BLE001 — report and continue; rerun fills gaps
            log.error("polyline failed: route=%s error=%s", route["id"], exc)
            continue
        if entry is None:
            log.info("skipped (single town): %s", route["id"])
            continue
        routes[route["id"]] = entry
        log.info(
            "polyline built: route=%s miles=%.1f anchors=%s",
            route["id"],
            entry["lengthMiles"],
            [(a["name"], a["measureMi"]) for a in entry["anchors"]],
        )
    document = {
        "description": (
            "Route polylines + anchor measures (miles from route start), built by "
            "python -m pipeline.build_polylines from OSRM driving geometry through "
            "each route's catalogue towns. Committed so nothing depends on OSRM at "
            "build/run time. The measure axis here is the one crashes are "
            "linear-referenced onto (backfill) and hotspot bins are keyed by."
        ),
        "routes": routes,
    }
    output.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    log.info("wrote %s (%d routes)", output, len(routes))
    return document


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    build()
