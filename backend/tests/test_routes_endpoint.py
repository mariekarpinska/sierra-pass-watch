"""/api/routes serves the shared catalogue (shared/route-catalogue.json) from
memory. These tests pin what the frontend planner relies on: full-Sierra
coverage, town ordering, and the camelCase wire format its TypeScript types
declare."""
from __future__ import annotations

import json
from pathlib import Path

_CATALOGUE = Path(__file__).resolve().parents[2] / "shared" / "route-catalogue.json"


def test_routes_returns_the_full_sierra_catalogue(client) -> None:
    routes = client.get("/api/routes").json()

    # 24 named crossings/corridors (SR-168 split W/E). Full-Sierra scope is a
    # product requirement, not an implementation detail.
    assert len(routes) == 24
    assert all(route["towns"] for route in routes)


def test_endpoint_serves_the_catalogue_faithfully(client) -> None:
    """Returns every route and town in the catalogue's order, unchanged. This
    only checks the endpoint does not reorder or drop anything; that the file
    itself matches pipeline/routes.py is a separate check in the pipeline job
    (pipeline/tests/test_route_catalogue.py)."""
    served = client.get("/api/routes").json()
    catalogue = json.loads(_CATALOGUE.read_text(encoding="utf-8"))["routes"]

    # Same routes, same order.
    assert [r["id"] for r in served] == [r["id"] for r in catalogue]

    # Every route's towns preserved in travel order.
    for served_route, source in zip(served, catalogue, strict=True):
        assert [t["name"] for t in served_route["towns"]] == [t["name"] for t in source["towns"]]


def test_known_route_facts_are_served(client) -> None:
    """A few facts pinned here directly, not read from the catalogue file, so a
    hand-edited or corrupted file is caught by this test too, not only by the
    pipeline drift test."""
    routes = {r["id"]: r for r in client.get("/api/routes").json()}

    # I-80 runs Colfax -> Donner Summit -> Truckee, and is year-round.
    assert [t["name"] for t in routes["I-80"]["towns"]] == ["Colfax", "Donner Summit", "Truckee"]
    assert routes["I-80"]["seasonal"] is False

    # US-395 has its four eastern-Sierra towns in order.
    assert [t["name"] for t in routes["US-395"]["towns"]] == [
        "Bridgeport", "Lee Vining", "Bishop", "Lone Pine",
    ]

    # SR-168 is split into disconnected west and east halves.
    assert "SR-168W" in routes and "SR-168E" in routes

    # A seasonal pass is flagged as such.
    assert routes["SR-120"]["seasonal"] is True


def test_routes_serialize_camel_case_for_the_frontend(client) -> None:
    body = client.get("/api/routes").text

    assert '"roadNo"' in body
    assert '"seasonal"' in body
    assert '"road_no"' not in body
