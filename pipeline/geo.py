"""Small geographic helpers shared across the pipeline. Pure math, no I/O."""
from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in kilometres."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


MILES_PER_DEG_LAT = 69.172  # one degree of latitude, in miles (spherical)


def cumulative_miles(coords: list[list[float]]) -> list[float]:
    """Running distance along a polyline. ``coords`` is [[lon, lat], ...].

    Index i is the distance from the start of the line to vertex i, in miles
    — the "measure" axis every crash, bin and anchor lives on.
    """
    km_to_miles = 0.621371
    cumulative = [0.0]
    for i in range(1, len(coords)):
        lon1, lat1 = coords[i - 1]
        lon2, lat2 = coords[i]
        cumulative.append(cumulative[-1] + haversine_km(lat1, lon1, lat2, lon2) * km_to_miles)
    return cumulative


def project_to_polyline(
    lat: float,
    lon: float,
    coords: list[list[float]],
    cumulative: list[float],
) -> tuple[float, float]:
    """Linear-reference a point onto a polyline.

    Returns ``(measure_mi, offset_mi)``: the distance along the line of the
    nearest point on it, and how far off the line the input point sits. The
    caller decides what offset still counts as "on this road" (the crash
    loader uses 700 m ≈ 0.435 mi).

    Uses a local equirectangular projection per vertex segment — at road-buffer
    scales (< 1 km) the error vs. true geodesics is negligible.
    """
    best_offset_sq = float("inf")
    best_measure = 0.0
    y = lat * MILES_PER_DEG_LAT
    for i in range(1, len(coords)):
        lon1, lat1 = coords[i - 1]
        lon2, lat2 = coords[i]
        # Miles-per-degree of longitude shrinks with latitude; use the
        # segment's own latitude so east-west distances stay honest.
        mx = MILES_PER_DEG_LAT * math.cos(math.radians((lat1 + lat2) / 2))
        ax, ay = lon1 * mx, lat1 * MILES_PER_DEG_LAT
        bx, by = lon2 * mx, lat2 * MILES_PER_DEG_LAT
        px = lon * mx
        dx, dy = bx - ax, by - ay
        seg_len_sq = dx * dx + dy * dy
        t = 0.0 if seg_len_sq == 0 else max(
            0.0, min(1.0, ((px - ax) * dx + (y - ay) * dy) / seg_len_sq)
        )
        cx, cy = ax + t * dx, ay + t * dy
        offset_sq = (px - cx) ** 2 + (y - cy) ** 2
        if offset_sq < best_offset_sq:
            best_offset_sq = offset_sq
            best_measure = cumulative[i - 1] + t * (cumulative[i] - cumulative[i - 1])
    return best_measure, math.sqrt(best_offset_sq)


def point_at_measure(
    coords: list[list[float]],
    cumulative: list[float],
    measure_mi: float,
) -> tuple[float, float]:
    """The (lat, lon) on a polyline at a given measure, clamped to its ends."""
    if measure_mi <= 0:
        return coords[0][1], coords[0][0]
    if measure_mi >= cumulative[-1]:
        return coords[-1][1], coords[-1][0]
    for i in range(1, len(cumulative)):
        if cumulative[i] >= measure_mi:
            span = cumulative[i] - cumulative[i - 1]
            t = 0.0 if span == 0 else (measure_mi - cumulative[i - 1]) / span
            lon = coords[i - 1][0] + t * (coords[i][0] - coords[i - 1][0])
            lat = coords[i - 1][1] + t * (coords[i][1] - coords[i - 1][1])
            return lat, lon
    return coords[-1][1], coords[-1][0]


def point_in_ring(lat: float, lon: float, ring: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon test. ``ring`` is [[lon, lat], ...]."""
    x, y = lon, lat
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside
