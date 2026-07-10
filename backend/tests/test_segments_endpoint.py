"""Tests the /api/segments HTTP endpoint (status, filtering, JSON shape).

Instead of a real database, these tests swap in a fake repository that returns a
fixed list, so no Postgres is needed and the tests stay fast. The real SQL is
covered separately in test_segment_repository.py against a real Postgres.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.schemas import Segment
from api.segments import get_segment_repository

# The fixed set of segments the fake repository returns, so every test knows
# exactly what to expect back.
_ALL = [
    Segment(id="I-80:colfax", route_id="I-80", name="Colfax", lat=39.1002, lon=-120.9533),
    Segment(id="I-80:donner-summit", route_id="I-80", name="Donner Summit", lat=39.3163, lon=-120.3208),
    Segment(id="SR-88:kirkwood", route_id="SR-88", name="Kirkwood", lat=38.6868, lon=-120.0657),
]


class FakeSegmentRepository:
    """Stand-in for the real repository: returns the list above instead of
    querying Postgres. No route id returns all of them; a route id returns only
    that route's segments."""

    async def get(self, route_id: str | None) -> list[Segment]:
        if route_id is None:
            return _ALL
        return [s for s in _ALL if s.route_id == route_id]


@pytest.fixture()
def client():
    app = create_app()
    # Tell FastAPI to use the fake wherever the endpoint asks for the real
    # repository, so requests never touch a database.
    app.dependency_overrides[get_segment_repository] = FakeSegmentRepository
    with TestClient(app) as test_client:
        yield test_client


def test_segments_without_a_route_returns_everything(client) -> None:
    # No route id: all three segments come back.
    assert len(client.get("/api/segments").json()) == 3


def test_segments_filters_by_route(client) -> None:
    # A route id narrows the result to that route.
    (segment,) = client.get("/api/segments", params={"route": "SR-88"}).json()
    assert segment["id"] == "SR-88:kirkwood"


def test_segments_for_an_unknown_route_is_an_empty_list_not_404(client) -> None:
    # A route with no segments is a normal empty list, not an error.
    response = client.get("/api/segments", params={"route": "SR-0"})

    assert response.status_code == 200
    assert response.json() == []


def test_segments_serialize_camel_case_for_the_frontend(client) -> None:
    # The JSON uses camelCase keys (routeId), which is what the frontend expects.
    body = client.get("/api/segments").text

    assert '"routeId"' in body
    assert '"route_id"' not in body
