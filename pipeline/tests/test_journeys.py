"""The journey index: the town-selection geometry and the committed file.

Pins the multi-highway invariant - a journey is the catalogue anchors along the
drive, in travel order - from two sides: the pure selection math (no network),
and the committed shared/route-journeys.json (every town pair present once, each
journey ordered and endpoint-inclusive). The OSRM build itself is exercised by
hand (build_journeys.py), not in CI.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

from pipeline.build_journeys import leg_spans, routes_for, towns_along, unique_towns
from pipeline.routes import ROUTES

REPO = Path(__file__).parents[2]

# A straight eastbound line at constant latitude, and four towns: three on it,
# one ~7 mi north (well beyond the 2.5 mi on-route buffer).
LINE = [[-120.5, 39.3], [-120.4, 39.3], [-120.3, 39.3]]
TOWNS = {
    "west": {"name": "West", "lat": 39.3, "lon": -120.5},
    "mid": {"name": "Mid", "lat": 39.3, "lon": -120.4},
    "east": {"name": "East", "lat": 39.3, "lon": -120.3},
    "off": {"name": "Off", "lat": 39.4, "lon": -120.4},
}


class TestSelection:
    def test_orders_on_route_towns_by_distance_along_the_line(self) -> None:
        assert towns_along(LINE, TOWNS) == ["west", "mid", "east"]

    def test_a_town_off_the_line_is_excluded(self) -> None:
        assert "off" not in towns_along(LINE, TOWNS)

    def test_reversed_line_reverses_the_order(self) -> None:
        assert towns_along(list(reversed(LINE)), TOWNS) == ["east", "mid", "west"]

    def test_leg_span_is_bounded_by_the_on_route_stops(self) -> None:
        # West and east sit on the line ~10.7 mi apart; the span runs between
        # their projections, and the far-off town does not stretch it.
        spans = leg_spans(
            ["west", "off", "east"], ["TEST"], TOWNS, geometry_for=lambda road: LINE
        )
        assert set(spans) == {"TEST"}
        lo, hi = spans["TEST"]
        assert lo == 0.0
        assert 10.0 < hi < 11.5

    def test_a_leg_with_one_anchor_gets_no_span(self) -> None:
        # One projected stop cannot bound a stretch; the road stays span-less
        # and the API keeps its whole corridor (the cautious fallback).
        assert leg_spans(["mid"], ["TEST"], TOWNS, geometry_for=lambda road: LINE) == {}

    def test_a_road_without_a_polyline_gets_no_span(self) -> None:
        # The four spur routes have no measure axis (ADR-0007).
        assert leg_spans(["west", "east"], ["SPUR"], TOWNS, geometry_for=lambda road: []) == {}

    def test_routes_for_names_the_highways_in_travel_order(self) -> None:
        # The classic crossing: I-80 to Truckee, SR-89 down the west shore,
        # US-50 into South Lake Tahoe. Tahoe City sits on two roads (SR-28 and
        # SR-89); the closest-approach tie-break must pick the one that heads
        # toward the next stop.
        stops = ["colfax", "donner-summit", "truckee", "tahoe-city", "south-lake-tahoe"]
        assert routes_for(stops, unique_towns()) == ["I-80", "SR-89", "US-50"]


class TestCommittedFile:
    data = json.loads((REPO / "shared" / "route-journeys.json").read_text(encoding="utf-8"))

    def test_town_directory_matches_the_catalogue(self) -> None:
        # Full equality, not just the slug set: a lat/lon or name edited in
        # routes.py must fail here until build_journeys is re-run, or the
        # journey index silently serves stale coordinates.
        assert self.data["towns"] == unique_towns()

    def test_every_town_pair_is_present_exactly_once(self) -> None:
        expected = {f"{a}|{b}" for a, b in itertools.combinations(sorted(self.data["towns"]), 2)}
        assert set(self.data["journeys"]) == expected

    def test_each_journey_is_ordered_endpoint_inclusive_and_sane(self) -> None:
        towns = self.data["towns"]
        for key, entry in self.data["journeys"].items():
            lo, hi = key.split("|")
            assert lo < hi and lo in towns and hi in towns  # sorted pair key
            stops = entry["towns"]
            # The drive starts and ends at the requested towns - no stop past
            # the destination (the on-route buffer used to leak one in).
            assert {stops[0], stops[-1]} == {lo, hi}
            assert len(stops) == len(set(stops))  # no town listed twice
            assert entry["miles"] > 0 and entry["minutes"] > 0

    def test_each_journey_names_the_roads_it_travels(self) -> None:
        known = {route["id"] for route in ROUTES}
        for entry in self.data["journeys"].values():
            assert entry["routes"], "every journey travels at least one road"
            assert set(entry["routes"]) <= known

    def test_spans_are_ordered_and_only_on_travelled_roads(self) -> None:
        # Every span is [lo, hi] miles on a road the journey actually names;
        # a road may lack a span (single anchor, or a spur with no polyline),
        # never the other way around.
        for entry in self.data["journeys"].values():
            assert set(entry["spans"]) <= set(entry["routes"])
            for lo, hi in entry["spans"].values():
                assert 0.0 <= lo <= hi
