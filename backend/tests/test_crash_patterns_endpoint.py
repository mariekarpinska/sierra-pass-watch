"""GET /api/crash-patterns: the crash record for a journey's highways under one
weather regime. The database seam (CrashHistoryStore) is faked, so these tests
pin the endpoint's contract - param validation, the response shape on the wire,
and the derived numbers (totals, fatality share, cause percentages) - without
Postgres. The SQL itself is exercised against a real database by dbt build in
CI and by the manual end-to-end check in the PR.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.crashes import BinRow, CauseRow, build_crash_patterns, get_crash_store
from api.main import create_app

# Two bins on I-80, one on US-50: enough to exercise cross-route totals.
BINS = [
    BinRow(
        route_id="I-80",
        mile_bin=12,
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
        mile_bin=13,
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
    """The store seam with fixed rows; records what it was asked for."""

    def __init__(self, bins=BINS, causes=CAUSES):
        self._bins = bins
        self._causes = causes
        self.calls: list[tuple[list[str], str]] = []

    def bins(self, route_ids, regime):
        self.calls.append((route_ids, regime))
        return self._bins

    def causes(self, route_ids, regime):
        return self._causes


@pytest.fixture()
def store():
    return _CannedStore()


@pytest.fixture()
def client(store):
    app = create_app()
    app.dependency_overrides[get_crash_store] = lambda: store
    with TestClient(app) as test_client:
        yield test_client


def test_returns_the_record_in_camel_case(client, store) -> None:
    response = client.get("/api/crash-patterns?routes=I-80,US-50&regime=SNOW")

    assert response.status_code == 200
    body = response.json()
    # The store was asked for exactly the parsed routes and regime.
    assert store.calls == [(["I-80", "US-50"], "SNOW")]
    # Journey-level numbers derive from the bins: 9+2+5 crashes, 1 fatal.
    assert body["regime"] == "SNOW"
    assert body["routeIds"] == ["I-80", "US-50"]
    assert body["crashCount"] == 16
    assert body["fatalCount"] == 1
    # 1/16 = 6.25; Python's round() goes to the even neighbour, so 6.2.
    assert body["pctFatal"] == 6.2
    assert body["smallSample"] is False
    # Date bounds span every bin, whichever route holds each end.
    assert body["firstCrashDate"] == "2016-06-09"
    assert body["lastCrashDate"] == "2025-12-20"
    # Bins arrive wire-shaped (camelCase, ISO dates).
    assert body["bins"][0] == {
        "routeId": "I-80",
        "mileBin": 12,
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


def test_an_empty_record_answers_honestly_empty(store) -> None:
    app = create_app()
    app.dependency_overrides[get_crash_store] = lambda: _CannedStore(bins=[], causes=[])
    with TestClient(app) as client:
        body = client.get("/api/crash-patterns?routes=SR-4&regime=HIGH_WIND").json()

    assert body["crashCount"] == 0
    assert body["fatalCount"] == 0
    # No crashes means no fatality share - null, never a made-up 0.0.
    assert body["pctFatal"] is None
    assert body["smallSample"] is True
    assert body["firstCrashDate"] is None
    assert body["bins"] == []
    assert body["topCauses"] == []


def test_missing_params_are_a_400(client) -> None:
    assert client.get("/api/crash-patterns").status_code == 400
    assert client.get("/api/crash-patterns?routes=I-80").status_code == 400
    assert client.get("/api/crash-patterns?regime=SNOW").status_code == 400


def test_a_regime_outside_the_vocabulary_is_a_400(client) -> None:
    response = client.get("/api/crash-patterns?routes=I-80&regime=BLIZZARD")

    assert response.status_code == 400
    assert "regime" in response.json()["error"]


def test_a_road_the_catalogue_does_not_track_is_a_404(client, store) -> None:
    response = client.get("/api/crash-patterns?routes=I-80,ROUTE-66&regime=SNOW")

    assert response.status_code == 404
    assert "ROUTE-66" in response.json()["error"]
    # Nothing was queried for a road we do not track.
    assert store.calls == []


def test_a_routes_param_of_only_commas_is_a_404(client) -> None:
    assert client.get("/api/crash-patterns?routes=,,&regime=SNOW").status_code == 404


def test_small_sample_flags_a_thin_record() -> None:
    """The builder itself: below 8 matched crashes the record is flagged as
    context, not a pattern - same threshold as the marts' per-bin flag."""
    thin = [BINS[1]]  # 2 crashes
    response = build_crash_patterns(["I-80"], "SNOW", thin, [])

    assert response.crash_count == 2
    assert response.small_sample is True
    assert response.pct_fatal == 0.0
