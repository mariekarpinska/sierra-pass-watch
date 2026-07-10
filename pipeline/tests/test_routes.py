from __future__ import annotations

import pytest

from pipeline.routes import (
    ROUTES,
    SEGMENTS,
    in_sierra,
    parse_direction,
    parse_route,
    sierra_bbox,
    town_slug,
)


def test_catalogue_covers_the_full_sierra() -> None:
    assert len(ROUTES) == 24
    assert len(SEGMENTS) == sum(len(r["towns"]) for r in ROUTES)


def test_segment_ids_are_unique_and_contract_shaped() -> None:
    ids = [s["segment_id"] for s in SEGMENTS]
    assert len(ids) == len(set(ids))
    # Same convention the frontend contract uses: "{route}:{town-slug}".
    assert "I-80:donner-summit" in ids
    assert "US-50:south-lake-tahoe" in ids


def test_town_slug_matches_frontend_convention() -> None:
    assert town_slug("Donner Summit") == "donner-summit"
    assert town_slug("Tahoe ↔ Monitor Pass") == "tahoe-monitor-pass"


@pytest.mark.parametrize(
    ("primary_road", "lon", "expected"),
    [
        ("I-80 EASTBOUND", None, "I-80"),
        ("INTERSTATE I 80 WB", None, "I-80"),
        ("US-50 WESTBOUND AT ECHO SUMMIT", None, "US-50"),
        ("HWY 395 NB", None, "US-395"),
        ("SR-120 EASTBOUND", None, "SR-120"),
        ("STATE ROUTE 88", None, "SR-88"),
        ("SR-168", -118.5, "SR-168E"),
        ("SR-168", -119.3, "SR-168W"),
        ("SR-168", None, "SR-168W"),
        ("MAIN STREET", None, None),
        # A bare number must not match — an address, not a route. US-395 now
        # requires a prefix too (a bare "395" previously matched it wrongly).
        ("120 OAK AVE", None, None),
        ("395 PINE ST", None, None),
        ("US 395 SB", None, "US-395"),
        (None, None, None),
    ],
)
def test_parse_route(primary_road, lon, expected) -> None:
    assert parse_route(primary_road, lon) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("I-80 EASTBOUND", "EB"),
        ("US-50 WESTBOUND", "WB"),
        ("SR-89 N/B", "NB"),
        ("SR-89 SB", "SB"),
        ("SR-89", None),
        (None, None),
    ],
)
def test_parse_direction(text, expected) -> None:
    assert parse_direction(text) == expected


# Forecast waypoints may extend past the range into gateway towns; crash
# filtering (which uses the polygon) simply won't attribute crashes there.
# Ridgecrest sits in the Mojave at SR-178's desert end — the one known case.
WAYPOINTS_OUTSIDE_RANGE = {"SR-178:ridgecrest"}


def test_waypoints_sit_inside_the_range_polygon_except_known_gateways() -> None:
    outside = {
        s["segment_id"] for s in SEGMENTS if not in_sierra(s["lat"], s["lon"])
    }
    assert outside == WAYPOINTS_OUTSIDE_RANGE


def test_far_away_points_are_outside() -> None:
    assert not in_sierra(37.7749, -122.4194)  # San Francisco
    assert not in_sierra(34.0522, -118.2437)  # Los Angeles


def test_bbox_contains_all_waypoints() -> None:
    min_lon, max_lon, min_lat, max_lat = sierra_bbox()
    for segment in SEGMENTS:
        assert min_lat <= segment["lat"] <= max_lat
        assert min_lon <= segment["lon"] <= max_lon
