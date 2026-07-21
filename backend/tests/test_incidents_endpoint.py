"""GET /api/incidents: the provisional live-collision feed (ADR-0012).

The journey-index and database seams are faked, so these pin the endpoint's
contract: param validation, the wire shape, the always-on `provisional` label,
and the empty case, without Postgres or a network. The SQL itself is exercised
against a real database by dbt build and the manual end-to-end check.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from api.crashes import IncidentRow, get_crash_store
from api.journeys import ResolvedJourney, get_journey_index
from api.main import create_app
from api.schemas import Waypoint

ROWS = [
    IncidentRow("I-80", 44, "SNOW", datetime(2026, 1, 11, 8, 5, tzinfo=timezone.utc), 39.32, -120.32),
    IncidentRow("SR-89", 12, "CLEAR_DRY", datetime(2026, 1, 10, 17, 0, tzinfo=timezone.utc), 39.20, -120.14),
]


class _FakeStore:
    """The store seam: fixed rows, records the route_ids it was asked for."""

    def __init__(self, rows=ROWS):
        self._rows = rows
        self.calls: list[list[str]] = []

    def recent_incidents(self, route_ids):
        self.calls.append(route_ids)
        return self._rows


class _FakeIndex:
    """One known journey, everything else a 404."""

    def resolve(self, from_id, to_id):
        if {from_id, to_id} != {"colfax", "south-lake-tahoe"}:
            return None
        return ResolvedJourney(
            stops=[Waypoint(id="colfax", name="Colfax", lat=39.0, lon=-120.0)],
            via=["I-80", "SR-89", "US-50"],
            anchors={},
            driven={},
            miles=93.5,
            minutes=130,
        )


def make_client(store):
    app = create_app()
    app.dependency_overrides[get_crash_store] = lambda: store
    app.dependency_overrides[get_journey_index] = lambda: _FakeIndex()
    return TestClient(app)


def test_returns_provisional_incidents_in_camel_case() -> None:
    store = _FakeStore()
    with make_client(store) as client:
        response = client.get("/api/incidents?from=colfax&to=south-lake-tahoe")

    assert response.status_code == 200
    body = response.json()
    # Scoped to the journey's roads, deduped in order.
    assert store.calls == [["I-80", "SR-89", "US-50"]]
    assert body["routeIds"] == ["I-80", "SR-89", "US-50"]
    assert body["provisional"] is True
    assert body["count"] == 2
    assert body["incidents"][0] == {
        "routeId": "I-80",
        "mileBin": 44,
        "regime": "SNOW",
        "eventTime": "2026-01-11T08:05:00+00:00",
        "lat": 39.32,
        "lon": -120.32,
    }


def test_no_incidents_is_an_empty_but_still_provisional_feed() -> None:
    store = _FakeStore(rows=[])
    with make_client(store) as client:
        response = client.get("/api/incidents?from=colfax&to=south-lake-tahoe")

    body = response.json()
    assert body["count"] == 0
    assert body["incidents"] == []
    # Empty is the normal case; it must still carry the provisional label.
    assert body["provisional"] is True


def test_missing_params_are_a_400() -> None:
    store = _FakeStore()
    with make_client(store) as client:
        assert client.get("/api/incidents").status_code == 400
        assert client.get("/api/incidents?from=colfax").status_code == 400
    assert store.calls == []


def test_an_unknown_pair_is_a_404() -> None:
    store = _FakeStore()
    with make_client(store) as client:
        response = client.get("/api/incidents?from=colfax&to=nowhere")

    assert response.status_code == 404
    assert store.calls == []
