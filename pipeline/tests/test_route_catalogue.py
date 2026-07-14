"""shared/route-catalogue.json is a copy of pipeline.routes.ROUTES, loaded by
the API at startup (the journey endpoint reads each highway's name and seasonal
note from it). Like the dbt seeds (test_warehouse_seeds.py), it must not drift
from the code it was exported from, so this asserts the two are identical and a
reviewer never has to trust that someone re-ran the export.
"""
from __future__ import annotations

import json
from pathlib import Path

from pipeline.routes import ROUTES

_CATALOGUE = Path(__file__).resolve().parents[2] / "shared" / "route-catalogue.json"


def test_catalogue_matches_the_route_code() -> None:
    catalogue = json.loads(_CATALOGUE.read_text(encoding="utf-8"))["routes"]

    expected = [
        {
            "id": route["id"],
            "name": route["name"],
            "road_no": route["road_no"],
            "seasonal": route["seasonal"],
            "note": route["note"],
            "towns": [{"name": name, "lat": lat, "lon": lon} for name, lat, lon in route["towns"]],
        }
        for route in ROUTES
    ]

    assert catalogue == expected, "shared/route-catalogue.json drifted from pipeline/routes.ROUTES"
