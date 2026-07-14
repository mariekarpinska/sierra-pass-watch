"""/api/journey and /api/towns behaviour with the upstream faked at the
provider seam. The journey index is the real committed route-journeys.json, so
these also assert the build output stays usable (from/to are endpoints, the span
is ordered, and a known crossing threads the expected towns)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.weather import ForecastService, HourlySample, get_forecast_service

DEPARTURE = "2026-01-12T15:00:00Z"


class ClearProvider:
    """Two benign hours everywhere; enough to exercise the response shape
    without a network. The window stamps are ignored."""

    async def get_hourly(
        self, lat: float, lon: float, start_hour: str, end_hour: str
    ) -> list[HourlySample]:
        return [
            HourlySample(
                time_utc="2026-01-12T15:00",
                temperature_c=4.0,
                surface_temp_c=4.0,
                snowfall_rate_in_hr=0.0,
                wind_gust_mph=8.0,
                visibility_miles=9.0,
                precip_probability_pct=10.0,
                weather_code=1,
            ),
        ]


@pytest.fixture()
def client():
    app = create_app()
    service = ForecastService(provider=ClearProvider())
    app.dependency_overrides[get_forecast_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client


def _journey(client, **params):
    return client.get("/api/journey", params=params)


def test_towns_directory_lists_named_points(client) -> None:
    towns = client.get("/api/towns").json()

    ids = {t["id"] for t in towns}
    assert {"colfax", "south-lake-tahoe", "truckee"} <= ids
    colfax = next(t for t in towns if t["id"] == "colfax")
    assert colfax["name"] == "Colfax"


def test_missing_params_are_a_400(client) -> None:
    response = _journey(client, **{"from": "colfax"})

    assert response.status_code == 400
    assert response.json() == {"error": "from, to and departure are required"}


def test_unparseable_departure_is_a_400(client) -> None:
    response = _journey(
        client, departure="soon", **{"from": "colfax", "to": "south-lake-tahoe"}
    )

    assert response.status_code == 400
    assert response.json() == {"error": "departure must be an ISO 8601 time"}


def test_same_town_twice_is_a_400_not_a_confusing_404(client) -> None:
    # "colfax|colfax" is never built, so without the explicit check this
    # would 404 as "unknown town" for a town the picker offers.
    response = _journey(
        client, departure=DEPARTURE, **{"from": "colfax", "to": "colfax"}
    )

    assert response.status_code == 400
    assert response.json() == {"error": "from and to must be different towns"}


def test_unknown_town_is_a_404(client) -> None:
    response = _journey(
        client, departure=DEPARTURE, **{"from": "colfax", "to": "narnia"}
    )

    assert response.status_code == 404


def test_crossing_threads_the_expected_towns_in_order(client) -> None:
    journey = _journey(
        client, departure=DEPARTURE, **{"from": "colfax", "to": "south-lake-tahoe"}
    ).json()

    ids = [s["waypoint"]["id"] for s in journey["stops"]]
    # A real I-80 -> SR-89 -> US-50 crossing: the origin leads, and both the
    # destination and Truckee are threaded along the way. (The destination is
    # not always dead last: a town right at it, like Stateline by South Lake
    # Tahoe, can project a hair further along the line.)
    assert ids[0] == "colfax"
    assert "south-lake-tahoe" in ids
    assert "truckee" in ids
    assert journey["totalMiles"] > 0 and journey["totalMinutes"] > 0
    # The highways travelled, in order, with the catalogue's seasonal context
    # (the UI names the roads and warns when a leg is a seasonal pass).
    assert [leg["id"] for leg in journey["via"]] == ["I-80", "SR-89", "US-50"]
    assert all("seasonal" in leg and "name" in leg for leg in journey["via"])
    # Each stop carries the per-town window summary. Assert the values, not
    # just the keys: a broken provider fake degrades every town to UNKNOWN
    # with null fields, which mere key-presence checks would wave through.
    assert all(s["regime"] == "CLEAR_DRY" for s in journey["stops"])
    assert all(s["temperatureHighF"] == 39.2 for s in journey["stops"])  # 4.0 °C


def test_reversed_journey_reverses_the_span(client) -> None:
    forward = _journey(
        client, departure=DEPARTURE, **{"from": "colfax", "to": "south-lake-tahoe"}
    ).json()
    back = _journey(
        client, departure=DEPARTURE, **{"from": "south-lake-tahoe", "to": "colfax"}
    ).json()

    forward_ids = [s["waypoint"]["id"] for s in forward["stops"]]
    back_ids = [s["waypoint"]["id"] for s in back["stops"]]
    assert back_ids == list(reversed(forward_ids))
    # The highways flip with the stops.
    forward_via = [leg["id"] for leg in forward["via"]]
    back_via = [leg["id"] for leg in back["via"]]
    assert back_via == list(reversed(forward_via))
