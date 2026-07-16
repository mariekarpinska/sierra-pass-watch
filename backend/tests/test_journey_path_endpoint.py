"""GET /api/journey-path: the drive's road line for the route-overview map.

The endpoint returns the whole drive as one committed polyline per town pair
(shared/route-drive-lines.json). These run against the real committed files,
since both the index and the drive lines are static build artifacts the app
loads at startup - no seams to fake.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.weather import ForecastService, HourlySample, get_forecast_service

DEPARTURE = "2026-01-12T15:00:00Z"


class _ClearProvider:
    """One benign forecast hour, so /api/journey returns stops without a
    network call. Only the elevation test needs the forecast; the path tests
    ignore it."""

    async def get_hourly(self, lat, lon, start_hour, end_hour):
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
    service = ForecastService(provider=_ClearProvider())
    app.dependency_overrides[get_forecast_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client


def test_a_real_journey_returns_the_whole_drive_line(client) -> None:
    response = client.get("/api/journey-path?from=colfax&to=truckee")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert len(paths) == 1, "the whole drive is one continuous line"
    line = paths[0]
    assert len(line) > 20, "a resampled ~40 mi drive is many points"
    # The line runs from Colfax to Truckee, in that order.
    assert 39.0 < line[0][0] < 39.2 and -121.1 < line[0][1] < -120.8
    assert 39.2 < line[-1][0] < 39.45 and -120.4 < line[-1][1] < -120.0


def test_the_reverse_trip_returns_the_same_line_flipped(client) -> None:
    forward = client.get("/api/journey-path?from=colfax&to=truckee").json()["paths"][0]
    back = client.get("/api/journey-path?from=truckee&to=colfax").json()["paths"][0]

    assert back == list(reversed(forward))


def test_missing_params_and_unknown_towns_mirror_the_journey_endpoint(client) -> None:
    assert client.get("/api/journey-path").status_code == 400
    assert client.get("/api/journey-path?from=colfax&to=colfax").status_code == 400
    assert client.get("/api/journey-path?from=colfax&to=nowhere").status_code == 404


def test_towns_and_journey_stops_carry_elevation(client) -> None:
    # /api/towns builds its Waypoints one way; journey stops go through
    # JourneyIndex.resolve. Assert both, so a refactor that drops elevation on
    # either path (it defaults to None, so it would not error) is caught here.
    towns = client.get("/api/towns").json()
    colfax = next(t for t in towns if t["id"] == "colfax")
    assert colfax["elevationFt"] == 2421

    journey = client.get(f"/api/journey?from=colfax&to=truckee&departure={DEPARTURE}").json()
    colfax_stop = next(s for s in journey["stops"] if s["waypoint"]["id"] == "colfax")
    assert colfax_stop["waypoint"]["elevationFt"] == 2421
