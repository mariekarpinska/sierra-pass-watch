"""The drive's road line for the route-overview map.

The committed route polylines are sliced to the mile ranges the journey
actually drives (the index's driven bins, ADR-0010), so the map draws the
real road - curves and all - without shipping any new geometry: both inputs
are committed build artifacts, and nothing routes or calls out at request
time. A spur with no polyline contributes no path; its stops still mark the
map.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Request

from pipeline.geo import point_at_measure
from pipeline.polylines import load_route_geometries

Geometry = tuple[list[list[float]], list[float]]


class RouteGeometry:
    """The committed route polylines, loaded once at startup from the same
    shared/ directory as the journey index (config.SHARED_DIR). Loading it
    here - rather than from a file path baked into the source tree - keeps the
    road line and the journey index it slices coming from one build, the same
    way JourneyIndex.load reads its directory."""

    def __init__(self, routes: dict[str, Geometry]) -> None:
        self._routes = routes

    @classmethod
    def load(cls, shared_dir: Path) -> "RouteGeometry":
        return cls(load_route_geometries(shared_dir / "route-polylines.json"))

    def geometry_for(self, road: str) -> Geometry | None:
        """The road's polyline and cumulative measures, or None (a spur)."""
        return self._routes.get(road)


def get_geometry(request: Request) -> RouteGeometry:
    """Dependency: the geometry loaded at startup (see main.create_app)."""
    return request.app.state.geometry


def driven_paths(
    driven: dict[str, list[tuple[int, int]]],
    lookup,
) -> list[list[tuple[float, float]]]:
    """One [lat, lon] path per continuously-driven stretch: the road's
    vertices inside the mile range, with interpolated endpoints so each path
    starts and ends exactly at the range's bounds rather than at the nearest
    vertex. ``lookup`` is the polyline accessor - RouteGeometry.geometry_for in
    the app, a fake in tests - so the file location is never hard-coded here.
    """
    paths: list[list[tuple[float, float]]] = []
    for road, ranges in driven.items():
        entry = lookup(road)
        if entry is None:
            continue
        coords, cumulative = entry
        for lo, hi in ranges:
            # A range of bins lo..hi covers miles lo to hi+1 (a bin is the
            # whole mile it starts); clamp to the road's end.
            end_mile = min(float(hi + 1), cumulative[-1])
            path = [point_at_measure(coords, cumulative, float(lo))]
            path.extend(
                (lat, lon)
                for (lon, lat), measure in zip(coords, cumulative)
                if lo < measure < end_mile
            )
            path.append(point_at_measure(coords, cumulative, end_mile))
            paths.append(path)
    return paths
