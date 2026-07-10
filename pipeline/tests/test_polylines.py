"""The measure axis: projection math, the polylines file, and the builder.

These pin the product's one spatial invariant — a crash's measure is its
distance along the route polyline — from three sides: the pure geometry, the
committed polylines file (anchors in travel order, sane lengths), and the
build-time OSRM projection that generates it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import build_polylines, polylines
from pipeline.geo import cumulative_miles, point_at_measure, project_to_polyline
from pipeline.routes import ROUTE_BY_ID

REPO = Path(__file__).parents[2]

# A simple eastbound line at constant latitude: ~1° lon ≈ 53.5 mi at 39.3°N.
LINE = [[-120.5, 39.3], [-120.4, 39.3], [-120.3, 39.3]]
LINE_CUM = cumulative_miles(LINE)


class TestGeometry:
    def test_cumulative_starts_at_zero_and_increases(self) -> None:
        assert LINE_CUM[0] == 0.0
        assert LINE_CUM[1] == pytest.approx(5.35, abs=0.1)
        assert LINE_CUM[2] == pytest.approx(10.7, abs=0.2)

    def test_projecting_a_vertex_returns_its_measure(self) -> None:
        measure, offset = project_to_polyline(39.3, -120.4, LINE, LINE_CUM)
        assert measure == pytest.approx(LINE_CUM[1], abs=0.01)
        assert offset == pytest.approx(0.0, abs=0.01)

    def test_projecting_an_offline_point_reports_its_offset(self) -> None:
        # ~0.01° north of the line ≈ 0.69 mi.
        measure, offset = project_to_polyline(39.31, -120.45, LINE, LINE_CUM)
        assert measure == pytest.approx(LINE_CUM[1] / 2, abs=0.2)
        assert offset == pytest.approx(0.69, abs=0.05)

    def test_points_beyond_the_ends_clamp_to_the_ends(self) -> None:
        before, _ = project_to_polyline(39.3, -120.6, LINE, LINE_CUM)
        after, _ = project_to_polyline(39.3, -120.2, LINE, LINE_CUM)
        assert before == 0.0
        assert after == pytest.approx(LINE_CUM[-1], abs=0.01)

    def test_point_at_measure_round_trips(self) -> None:
        lat, lon = point_at_measure(LINE, LINE_CUM, LINE_CUM[-1] / 2)
        measure, offset = project_to_polyline(lat, lon, LINE, LINE_CUM)
        assert measure == pytest.approx(LINE_CUM[-1] / 2, abs=0.01)
        assert offset == pytest.approx(0.0, abs=0.001)
        assert point_at_measure(LINE, LINE_CUM, -5) == (39.3, -120.5)
        assert point_at_measure(LINE, LINE_CUM, 999) == (39.3, -120.3)


class TestPolylinesFile:
    def test_donner_summit_sits_mid_route_on_i80(self) -> None:
        # The committed file is real OSRM geometry; pin the shape loosely
        # (route exists, anchors ordered, summit around mile 44).
        measure = polylines.measure_for("I-80", 39.3163, -120.3208)
        assert measure is not None
        assert measure == pytest.approx(44.1, abs=1.0)

    def test_far_off_route_points_get_no_measure(self) -> None:
        # Sacramento is ~40 mi from the I-80 Sierra polyline's start.
        assert polylines.measure_for("I-80", 38.58, -121.49) is None

    def test_spur_routes_without_polylines_get_no_measure(self) -> None:
        assert polylines.measure_for("US-6", 37.3636, -118.3951) is None
        assert polylines.route_length_miles("US-6") is None

    def test_every_polyline_route_has_ordered_anchors(self) -> None:
        data = json.loads((REPO / "shared" / "route-polylines.json").read_text())
        assert len(data["routes"]) >= 20
        for route_id, entry in data["routes"].items():
            assert route_id in ROUTE_BY_ID
            measures = [a["measureMi"] for a in entry["anchors"]]
            assert measures == sorted(measures), f"{route_id} anchors out of travel order"
            assert entry["lengthMiles"] == pytest.approx(measures[-1], abs=1.0)
            # Towns are catalogue points near the highway, never miles away.
            assert all(a["offsetMi"] < 3.0 for a in entry["anchors"])


class TestBuilder:
    def test_build_route_entry_projects_anchors_onto_the_fetched_line(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            build_polylines,
            "fetch_polyline",
            lambda towns: [[-120.5, 39.3], [-120.4, 39.3], [-120.3, 39.3]],
        )
        entry = build_polylines.build_route_entry(
            {
                "id": "TEST-1",
                "towns": [("West End", 39.3, -120.5), ("Mid Town", 39.302, -120.4)],
            }
        )
        assert entry is not None
        assert entry["lengthMiles"] == pytest.approx(10.7, abs=0.2)
        assert entry["anchors"][0]["measureMi"] == 0.0
        assert entry["anchors"][0]["segmentId"] == "TEST-1:west-end"
        assert entry["anchors"][1]["measureMi"] == pytest.approx(5.35, abs=0.2)

    def test_single_town_routes_are_skipped(self) -> None:
        assert build_polylines.build_route_entry(
            {"id": "TEST-2", "towns": [("Lone Town", 37.0, -118.0)]}
        ) is None
