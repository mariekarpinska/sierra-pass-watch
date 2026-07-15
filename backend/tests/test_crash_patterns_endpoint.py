"""GET /api/crash-patterns: the crash record for a journey under one weather
regime. The database seam (CrashHistoryStore) is faked, so these tests pin the
endpoint's contract - param validation, journey resolution into span-bounded
legs, the response shape on the wire, and the derived numbers (totals,
fatality share, cause percentages) - without Postgres. The SQL itself is
exercised against a real database by dbt build in CI and by the manual
end-to-end check in the PR.

Journey resolution runs against the real committed shared/route-journeys.json
(the app loads it at startup), so the expected legs below pin real spans:
Colfax-South Lake Tahoe covers I-80 miles 0-54 and SR-89 miles 0-26.9, and
US-50 has no span there (only one anchor town of the drive sits on it), so it
keeps its whole corridor.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.crashes import BinRow, CauseRow, Leg, build_crash_patterns, get_crash_store
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

# What Colfax-South Lake Tahoe resolves to: spans floored to whole-mile bins,
# and span-less US-50 falling back to its whole corridor (None bounds).
COLFAX_SLT_LEGS = [
    Leg(route_id="I-80", lo_bin=0, hi_bin=54),
    Leg(route_id="SR-89", lo_bin=0, hi_bin=26),
    Leg(route_id="US-50", lo_bin=None, hi_bin=None),
]


class _CannedStore:
    """The store seam with fixed rows; records what it was asked for."""

    def __init__(self, bins=BINS, causes=CAUSES):
        self._bins = bins
        self._causes = causes
        self.calls: list[tuple[list[Leg], str]] = []

    def bins(self, legs, regime):
        self.calls.append((legs, regime))
        return self._bins

    def causes(self, legs, regime):
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
    response = client.get(
        "/api/crash-patterns?from=colfax&to=south-lake-tahoe&regime=SNOW"
    )

    assert response.status_code == 200
    body = response.json()
    # The journey resolved into span-bounded legs - the store never sees more
    # road than the drive covers (US-50 excepted: no span, whole corridor).
    assert store.calls == [(COLFAX_SLT_LEGS, "SNOW")]
    # Journey-level numbers derive from the bins: 9+2+5 crashes, 1 fatal.
    assert body["regime"] == "SNOW"
    assert body["routeIds"] == ["I-80", "SR-89", "US-50"]
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


def test_the_reverse_trip_asks_for_the_same_legs(client, store) -> None:
    """Spans live on each road's own mile axis, so direction cannot change
    which stretch of road the record covers. The legs arrive in reverse travel
    order, which the record does not care about - compare as a set."""
    client.get("/api/crash-patterns?from=south-lake-tahoe&to=colfax&regime=SNOW")

    (legs, regime), = store.calls
    assert regime == "SNOW"
    assert set(legs) == set(COLFAX_SLT_LEGS)


def test_an_empty_record_answers_honestly_empty(store) -> None:
    app = create_app()
    app.dependency_overrides[get_crash_store] = lambda: _CannedStore(bins=[], causes=[])
    with TestClient(app) as client:
        body = client.get(
            "/api/crash-patterns?from=colfax&to=truckee&regime=HIGH_WIND"
        ).json()

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
    assert client.get("/api/crash-patterns?from=colfax&to=truckee").status_code == 400
    assert client.get("/api/crash-patterns?from=colfax&regime=SNOW").status_code == 400
    assert client.get("/api/crash-patterns?regime=SNOW").status_code == 400


def test_a_regime_outside_the_vocabulary_is_a_400(client) -> None:
    response = client.get(
        "/api/crash-patterns?from=colfax&to=truckee&regime=BLIZZARD"
    )

    assert response.status_code == 400
    assert "regime" in response.json()["error"]


def test_the_same_town_twice_is_a_400(client) -> None:
    response = client.get("/api/crash-patterns?from=colfax&to=colfax&regime=SNOW")

    assert response.status_code == 400
    assert "different towns" in response.json()["error"]


def test_an_unknown_town_or_pair_is_a_404(client, store) -> None:
    response = client.get(
        "/api/crash-patterns?from=colfax&to=route-66-diner&regime=SNOW"
    )

    assert response.status_code == 404
    # Nothing was queried for a journey we never built.
    assert store.calls == []


def test_small_sample_flags_a_thin_record() -> None:
    """The builder itself: below 8 matched crashes the record is flagged as
    context, not a pattern - same threshold as the marts' per-bin flag."""
    thin = [BINS[1]]  # 2 crashes
    response = build_crash_patterns(["I-80"], "SNOW", thin, [])

    assert response.crash_count == 2
    assert response.small_sample is True
    assert response.pct_fatal == 0.0
