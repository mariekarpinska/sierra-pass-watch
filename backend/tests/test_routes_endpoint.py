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


def test_routes_serve_every_route_and_town_in_catalogue_order(client) -> None:
    """The endpoint serves the catalogue faithfully: every route in order, and
    every route's towns in travel order. test_route_catalogue.py checks that file
    against pipeline/routes.py, so together they cover code -> file -> API."""
    served = client.get("/api/routes").json()
    catalogue = json.loads(_CATALOGUE.read_text(encoding="utf-8"))["routes"]

    # Same routes, same order.
    assert [r["id"] for r in served] == [r["id"] for r in catalogue]

    # Every route's towns preserved in travel order.
    for served_route, source in zip(served, catalogue, strict=True):
        assert [t["name"] for t in served_route["towns"]] == [t["name"] for t in source["towns"]]

    # A concrete anchor so the expectation is readable at a glance.
    (i80,) = [r for r in served if r["id"] == "I-80"]
    assert [t["name"] for t in i80["towns"]] == ["Colfax", "Donner Summit", "Truckee"]


def test_routes_serialize_camel_case_for_the_frontend(client) -> None:
    body = client.get("/api/routes").text

    assert '"roadNo"' in body
    assert '"seasonal"' in body
    assert '"road_no"' not in body
