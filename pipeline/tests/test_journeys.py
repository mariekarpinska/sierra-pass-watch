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

from pipeline.build_journeys import towns_along, unique_towns

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


class TestCommittedFile:
    data = json.loads((REPO / "shared" / "route-journeys.json").read_text(encoding="utf-8"))

    def test_town_directory_matches_the_catalogue(self) -> None:
        assert set(self.data["towns"]) == set(unique_towns())

    def test_every_town_pair_is_present_exactly_once(self) -> None:
        expected = {f"{a}|{b}" for a, b in itertools.combinations(sorted(self.data["towns"]), 2)}
        assert set(self.data["journeys"]) == expected

    def test_each_journey_is_ordered_endpoint_inclusive_and_sane(self) -> None:
        towns = self.data["towns"]
        for key, entry in self.data["journeys"].items():
            lo, hi = key.split("|")
            assert lo < hi and lo in towns and hi in towns  # sorted pair key
            stops = entry["towns"]
            assert lo in stops and hi in stops  # both endpoints are on the drive
            assert len(stops) == len(set(stops))  # no town listed twice
            assert entry["miles"] > 0 and entry["minutes"] > 0
