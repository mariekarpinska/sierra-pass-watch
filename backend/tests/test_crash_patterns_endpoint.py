"""GET /api/crash-patterns: the crash record for a journey, each stretch
matched to its own forecast regime. The three seams are faked - the journey
index, the forecast service and the database store - so these tests pin the
endpoint's contract (param validation, forecast-to-segment plumbing, the wire
shape, the derived numbers) plus segment_legs' cutting math, all without
Postgres or a network. The SQL itself is exercised against a real database by
dbt build in CI and by the manual end-to-end check in the PR.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.crashes import (
    BinRow,
    CauseRow,
    Leg,
    build_crash_patterns,
    get_crash_store,
    segment_legs,
)
from api.journeys import ResolvedJourney, get_journey_index
from api.main import create_app
from api.schemas import Waypoint
from api.weather import get_forecast_service

# The classic crossing, with anchors and driven ranges shaped like the
# committed index (real values from the Colfax - South Lake Tahoe build):
# the drive covers most of I-80 (with the Donner-Summit polyline detour gap),
# SR-89 from Truckee to the lake, and only the last few miles of US-50.
ANCHORS = {
    "I-80": {"colfax": 0.0, "donner-summit": 44.1, "truckee": 54.0},
    "SR-89": {"truckee": 0.0, "tahoe-city": 14.7, "south-lake-tahoe": 41.6},
    "US-50": {"south-lake-tahoe": 59.4},
}
DRIVEN = {
    "I-80": [(0, 40), (45, 52)],
    "SR-89": [(1, 41)],
    "US-50": [(56, 59)],
}
TOWNS = ["colfax", "donner-summit", "truckee", "tahoe-city", "south-lake-tahoe"]

# Snow at the pass, clear everywhere else: the case the feature exists for.
FORECASTS = {
    "colfax": "CLEAR_DRY",
    "donner-summit": "SNOW",
    "truckee": "CLEAR_DRY",
    "tahoe-city": "CLEAR_DRY",
    "south-lake-tahoe": "CLEAR_DRY",
}

# What that journey and forecast must segment into: only driven bins, cut at
# the anchor midpoints (I-80 miles 22 and 49), SR-89 one clear stretch, US-50
# just its driven tail near the lake.
EXPECTED_LEGS = [
    Leg("I-80", 0, 22, "CLEAR_DRY"),
    Leg("I-80", 23, 40, "SNOW"),
    Leg("I-80", 45, 49, "SNOW"),
    Leg("I-80", 50, 52, "CLEAR_DRY"),
    Leg("SR-89", 1, 41, "CLEAR_DRY"),
    Leg("US-50", 56, 59, "CLEAR_DRY"),
]


class TestSegmentLegs:
    """The cutting math on its own: pure inputs, no app."""

    def test_driven_ranges_cut_at_anchor_midpoints(self) -> None:
        legs = segment_legs(["I-80"], DRIVEN, ANCHORS, FORECASTS, fallback="SNOW")
        assert legs == EXPECTED_LEGS[:4]

    def test_a_uniform_forecast_range_stays_one_leg(self) -> None:
        clear = dict.fromkeys(FORECASTS, "CLEAR_DRY")
        legs = segment_legs(["I-80"], DRIVEN, ANCHORS, clear, fallback="CLEAR_DRY")
        # Same-regime pieces merge, but the real gap in the driven ranges
        # (the polyline detour around Donner Summit) stays a gap.
        assert legs == [
            Leg("I-80", 0, 40, "CLEAR_DRY"),
            Leg("I-80", 45, 52, "CLEAR_DRY"),
        ]

    def test_a_barely_touched_road_keeps_only_its_driven_tail(self) -> None:
        legs = segment_legs(["US-50"], DRIVEN, ANCHORS, FORECASTS, fallback="SNOW")
        assert legs == [Leg("US-50", 56, 59, "CLEAR_DRY")]

    def test_a_road_with_no_measure_axis_keeps_its_whole_corridor(self) -> None:
        # A spur has no polyline, so no driven ranges and no bins; the whole
        # corridor matches, labelled by its one anchor when it has one, else
        # by the journey's worst regime.
        spur_anchor = {"SR-207": {"stateline": 3.0}}
        spur_forecast = {"stateline": "HIGH_WIND"}
        assert segment_legs(["SR-207"], {}, spur_anchor, spur_forecast, "SNOW") == [
            Leg("SR-207", None, None, "HIGH_WIND")
        ]
        assert segment_legs(["SR-207"], {}, {}, FORECASTS, "SNOW") == [
            Leg("SR-207", None, None, "SNOW")
        ]

    def test_unknown_stretches_are_dropped_not_guessed(self) -> None:
        gappy = {**FORECASTS, "donner-summit": "UNKNOWN"}
        legs = segment_legs(["I-80"], DRIVEN, ANCHORS, gappy, fallback="CLEAR_DRY")
        # The pass has no forecast, so its stretch matches nothing; the clear
        # ends survive unmerged (the snow bins are honestly absent).
        assert legs == [
            Leg("I-80", 0, 22, "CLEAR_DRY"),
            Leg("I-80", 50, 52, "CLEAR_DRY"),
        ]
        assert segment_legs(["SR-207"], {}, {}, gappy, fallback="UNKNOWN") == []


# Two bins on I-80 (one per matched regime), one on US-50.
BINS = [
    BinRow(
        route_id="I-80",
        mile_bin=12,
        regime="CLEAR_DRY",
        lat=39.31,
        lon=-120.32,
        crash_count=9,
        fatal_count=1,
        top_cause="Unsafe Speed",
        first_crash_date=date(2017, 1, 3),
        last_crash_date=date(2025, 12, 20),
    ),
    BinRow(
        route_id="I-80",
        mile_bin=44,
        regime="SNOW",
        lat=39.32,
        lon=-120.3,
        crash_count=2,
        fatal_count=0,
        top_cause="Unsafe Lane Change",
        first_crash_date=date(2019, 2, 1),
        last_crash_date=date(2021, 11, 5),
    ),
    BinRow(
        route_id="US-50",
        mile_bin=40,
        regime="CLEAR_DRY",
        lat=38.81,
        lon=-120.03,
        crash_count=5,
        fatal_count=0,
        top_cause="Unsafe Speed",
        first_crash_date=date(2016, 6, 9),
        last_crash_date=date(2024, 3, 14),
    ),
]
CAUSES = [
    CauseRow(cause="Unsafe Speed", crash_count=10),
    CauseRow(cause="Unsafe Lane Change", crash_count=4),
    CauseRow(cause="DUI", crash_count=2),
]


class _CannedStore:
    """The store seam with fixed rows; records the legs it was asked for."""

    def __init__(self, bins=BINS, causes=CAUSES):
        self._bins = bins
        self._causes = causes
        self.calls: list[list[Leg]] = []

    def bins(self, legs):
        self.calls.append(legs)
        return self._bins

    def causes(self, legs):
        return self._causes


class _FakeIndex:
    """The journey-index seam: one known journey, everything else a 404."""

    def resolve(self, from_id, to_id):
        if {from_id, to_id} != {"colfax", "south-lake-tahoe"}:
            return None
        return ResolvedJourney(
            stops=[
                Waypoint(id=slug, name=slug.title(), lat=39.0, lon=-120.0)
                for slug in TOWNS
            ],
            via=["I-80", "SR-89", "US-50"],
            anchors=ANCHORS,
            driven=DRIVEN,
            miles=93.5,
            minutes=130,
        )


class _Stop:
    """The two attributes the endpoint reads off a forecast stop."""

    def __init__(self, waypoint, regime):
        self.waypoint = waypoint
        self.regime = regime


class _CannedForecast:
    """The forecast seam: a fixed regime per town, no network."""

    def __init__(self, regimes=FORECASTS):
        self._regimes = regimes

    async def forecast_towns(self, towns, departure):
        return [_Stop(town, self._regimes[town.id]) for town in towns]


DEPARTURE = "departure=2026-01-12T15:00:00Z"


@pytest.fixture()
def store():
    return _CannedStore()


def make_client(store, regimes=FORECASTS):
    app = create_app()
    app.dependency_overrides[get_crash_store] = lambda: store
    app.dependency_overrides[get_journey_index] = lambda: _FakeIndex()
    app.dependency_overrides[get_forecast_service] = lambda: _CannedForecast(regimes)
    return TestClient(app)


@pytest.fixture()
def client(store):
    with make_client(store) as test_client:
        yield test_client


def test_returns_the_record_in_camel_case(client, store) -> None:
    response = client.get(f"/api/crash-patterns?from=colfax&to=south-lake-tahoe&{DEPARTURE}")

    assert response.status_code == 200
    body = response.json()
    # The forecast turned into driven, regime-labelled stretches: snow
    # history around the pass, clear history at the ends, only driven miles
    # anywhere - and both store reads asked for exactly those.
    assert store.calls == [EXPECTED_LEGS]
    # No single journey regime exists any more - each bin carries its own.
    assert "regime" not in body
    assert body["routeIds"] == ["I-80", "SR-89", "US-50"]
    # Journey-level numbers derive from the bins: 9+2+5 crashes, 1 fatal.
    assert body["crashCount"] == 16
    assert body["fatalCount"] == 1
    # 1/16 = 6.25; Python's round() goes to the even neighbour, so 6.2.
    assert body["pctFatal"] == 6.2
    assert body["smallSample"] is False
    # Date bounds span every bin, whichever route holds each end.
    assert body["firstCrashDate"] == "2016-06-09"
    assert body["lastCrashDate"] == "2025-12-20"
    # Bins arrive wire-shaped (camelCase, ISO dates, matched regime).
    assert body["bins"][0] == {
        "routeId": "I-80",
        "mileBin": 12,
        "regime": "CLEAR_DRY",
        "lat": 39.31,
        "lon": -120.32,
        "crashCount": 9,
        "fatalCount": 1,
        "topCause": "Unsafe Speed",
        "firstCrashDate": "2017-01-03",
        "lastCrashDate": "2025-12-20",
    }
    # Cause shares are percentages of ALL matched crashes: 10/16 = 62.5,
    # which Python's round() takes to the even neighbour, 62.
    assert body["topCauses"][0] == {
        "cause": "Unsafe Speed",
        "crashCount": 10,
        "pct": 62,
    }


def test_an_all_unknown_forecast_is_a_503_not_a_quiet_road(store) -> None:
    unknown = dict.fromkeys(FORECASTS, "UNKNOWN")
    with make_client(store, regimes=unknown) as client:
        response = client.get(
            f"/api/crash-patterns?from=colfax&to=south-lake-tahoe&{DEPARTURE}"
        )

    # No weather to match means no database read - and NOT an empty record,
    # which the UI would present as a road with no history. A forecast outage
    # is a service condition, so it answers as one.
    assert store.calls == []
    assert response.status_code == 503
    assert "forecast" in response.json()["error"]


def test_missing_params_are_a_400(client) -> None:
    assert client.get("/api/crash-patterns").status_code == 400
    assert client.get("/api/crash-patterns?from=colfax&to=truckee").status_code == 400
    assert client.get(f"/api/crash-patterns?from=colfax&{DEPARTURE}").status_code == 400


def test_an_unparseable_departure_is_a_400(client) -> None:
    response = client.get(
        "/api/crash-patterns?from=colfax&to=south-lake-tahoe&departure=tomorrow"
    )

    assert response.status_code == 400
    assert "departure" in response.json()["error"]


def test_the_same_town_twice_is_a_400(client) -> None:
    response = client.get(f"/api/crash-patterns?from=colfax&to=colfax&{DEPARTURE}")

    assert response.status_code == 400
    assert "different towns" in response.json()["error"]


def test_an_unknown_town_or_pair_is_a_404(client, store) -> None:
    response = client.get(f"/api/crash-patterns?from=colfax&to=nowhere&{DEPARTURE}")

    assert response.status_code == 404
    # Nothing was queried for a journey we never built.
    assert store.calls == []


def test_small_sample_flags_a_thin_record() -> None:
    """The builder itself: below 8 matched crashes the record is flagged as
    context, not a pattern - same threshold as the marts' per-bin flag."""
    thin = [BINS[1]]  # 2 crashes
    response = build_crash_patterns(["I-80"], thin, [])

    assert response.crash_count == 2
    assert response.small_sample is True
    assert response.pct_fatal == 0.0
