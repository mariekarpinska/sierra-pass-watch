"""The drive's road line for the route-overview map.

The committed route polylines are sliced to the mile ranges the journey
actually drives (the index's driven bins, ADR-0010), so the map draws the
real road - curves and all - without shipping any new geometry: both inputs
are committed build artifacts, and nothing routes or calls out at request
time. A spur with no polyline contributes no path; its stops still mark the
map.
"""
from __future__ import annotations

from pipeline.geo import point_at_measure
from pipeline.polylines import geometry_for


def driven_paths(
    driven: dict[str, list[tuple[int, int]]],
    lookup=None,
) -> list[list[tuple[float, float]]]:
    """One [lat, lon] path per continuously-driven stretch: the road's
    vertices inside the mile range, with interpolated endpoints so each path
    starts and ends exactly at the range's bounds rather than at the nearest
    vertex. ``lookup`` is the polyline accessor, replaceable in tests; it
    defaults to the committed route-polylines.json.
    """
    if lookup is None:
        lookup = geometry_for
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
