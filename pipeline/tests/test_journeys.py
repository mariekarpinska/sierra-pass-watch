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

from pipeline.build_journeys import (
    driven_bins,
    leg_anchor_miles,
    routes_for,
    towns_along,
    unique_towns,
)
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

    def test_anchor_miles_measure_the_on_route_stops(self) -> None:
        # West sits at the line's start, east ~10.7 mi along it; the far-off
        # town projects beyond the buffer and gets no measure.
        anchors = leg_anchor_miles(
            ["west", "off", "east"], ["TEST"], TOWNS, geometry_for=lambda road: LINE
        )
        assert set(anchors) == {"TEST"}
        assert set(anchors["TEST"]) == {"west", "east"}
        assert anchors["TEST"]["west"] == 0.0
        assert 10.0 < anchors["TEST"]["east"] < 11.5

    def test_a_road_without_a_polyline_gets_no_anchors(self) -> None:
        # The four spur routes have no measure axis (ADR-0007).
        assert leg_anchor_miles(["west", "east"], ["SPUR"], TOWNS, geometry_for=lambda road: []) == {}

    def test_driven_bins_cover_only_the_miles_the_drive_lies_on(self) -> None:
        # The road runs ~10.7 mi along the line; the drive covers only its
        # middle (roughly miles 2.7 to 8), so the outer miles are not driven.
        drive = [[-120.45, 39.3], [-120.35, 39.3]]
        driven = driven_bins(drive, ["TEST"], geometry_for=lambda road: LINE)
        assert driven == {"TEST": [[2, 8]]}

    def test_leaving_and_rejoining_a_road_makes_two_ranges(self) -> None:
        # The drive follows the road, detours ~7 mi north (well past the
        # buffer), and rejoins further along: the gap must stay a gap, not be
        # bridged into one range.
        drive = [
            [-120.5, 39.3], [-120.44, 39.3],   # on the road, ~miles 0-3
            [-120.44, 39.4], [-120.36, 39.4],  # off north, parallel
            [-120.36, 39.3], [-120.3, 39.3],   # back on, ~miles 7.5-10.7
        ]
        driven = driven_bins(drive, ["TEST"], geometry_for=lambda road: LINE)
        ranges = driven["TEST"]
        assert len(ranges) == 2
        assert ranges[0][0] == 0 and ranges[1][1] == 10
        assert ranges[0][1] < 5 < ranges[1][0]  # the detour stays undriven

    def test_a_road_without_a_polyline_gets_no_driven_ranges(self) -> None:
        assert driven_bins([[-120.5, 39.3], [-120.3, 39.3]], ["SPUR"], geometry_for=lambda road: []) == {}

    def test_routes_for_names_the_highways_in_travel_order(self) -> None:
        # The classic crossing: I-80 to Truckee, SR-89 down the west shore,
        # US-50 into South Lake Tahoe. Tahoe City sits on two roads (SR-28 and
        # SR-89); the closest-approach tie-break must pick the one that heads
        # toward the next stop.
        stops = ["colfax", "donner-summit", "truckee", "tahoe-city", "south-lake-tahoe"]
        assert routes_for(stops, unique_towns()) == ["I-80", "SR-89", "US-50"]


class TestCommittedFile:
    data = json.loads((REPO / "shared" / "route-journeys.json").read_text(encoding="utf-8"))

    def test_every_town_has_a_sane_elevation(self) -> None:
        # Every catalogue town carries its elevation (unique_towns raises on a
        # missing one); sane bounds catch a metres/feet mix-up or a typo.
        for slug, town in unique_towns().items():
            assert 0 < town["elevationFt"] < 15000, slug

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

    def test_anchors_sit_on_travelled_roads_at_sane_miles(self) -> None:
        # Every anchor measure belongs to a road the journey names and a stop
        # the journey makes; a road may lack anchors (a spur with no
        # polyline), never the other way around.
        for entry in self.data["journeys"].values():
            assert set(entry["anchors"]) <= set(entry["routes"])
            for road_anchors in entry["anchors"].values():
                assert road_anchors, "an anchors entry is never empty"
                assert set(road_anchors) <= set(entry["towns"])
                for mile in road_anchors.values():
                    assert mile >= 0.0

    def test_driven_ranges_are_ordered_and_on_travelled_roads(self) -> None:
        # Every driven range sits on a road the journey names, and a road's
        # ranges are ascending, non-overlapping [lo, hi] whole-mile bins.
        for entry in self.data["journeys"].values():
            assert set(entry["driven"]) <= set(entry["routes"])
            for ranges in entry["driven"].values():
                assert ranges, "a driven entry is never empty"
                previous_hi = -1
                for lo, hi in ranges:
                    assert previous_hi < lo <= hi
                    previous_hi = hi
