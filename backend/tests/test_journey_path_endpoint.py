"""GET /api/journey-path: the drive's road line for the route-overview map.

The slicing math is tested pure (a fake polyline lookup); the endpoint tests
run against the real committed index and polylines, since both are static
build artifacts the app loads at startup - no seams to fake.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.paths import driven_paths
from api.weather import ForecastService, HourlySample, get_forecast_service

DEPARTURE = "2026-01-12T15:00:00Z"

# A straight east-west line at constant latitude, ~10.7 miles long, with a
# vertex every ~2.7 miles (same shape the journey-builder tests use).
LINE = [[-120.5, 39.3], [-120.45, 39.3], [-120.4, 39.3], [-120.35, 39.3], [-120.3, 39.3]]
CUMULATIVE = [0.0, 2.6775, 5.355, 8.0325, 10.71]


def fake_lookup(road):
    return (LINE, CUMULATIVE) if road == "TEST" else None


class TestDrivenPaths:
    def test_a_range_slices_the_line_with_exact_endpoints(self) -> None:
        paths = driven_paths({"TEST": [(2, 8)]}, lookup=fake_lookup)

        assert len(paths) == 1
        path = paths[0]
        # Starts at mile 2 and ends at mile 9 (bins 2..8 cover miles 2 to 9),
        # interpolated onto the line rather than snapped to a vertex...
        assert path[0][0] == pytest.approx(39.3)
        assert path[0][1] == pytest.approx(-120.4626, abs=1e-3)
        assert path[-1][1] == pytest.approx(-120.3319, abs=1e-3)
        # ...with the road's own vertices in between (the curves survive).
        assert (39.3, -120.4) in [(round(lat, 4), round(lon, 4)) for lat, lon in path]

    def test_each_range_is_its_own_path(self) -> None:
        paths = driven_paths({"TEST": [(0, 2), (7, 9)]}, lookup=fake_lookup)
        assert len(paths) == 2

    def test_the_end_clamps_to_the_road(self) -> None:
        # Bin 10 covers miles 10..11 but the road ends at 10.71.
        paths = driven_paths({"TEST": [(10, 10)]}, lookup=fake_lookup)
        assert paths[0][-1] == (39.3, -120.3)

    def test_a_spur_with_no_polyline_contributes_nothing(self) -> None:
        assert driven_paths({"SPUR": [(0, 5)]}, lookup=fake_lookup) == []


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


def test_a_real_journey_returns_its_road_line(client) -> None:
    response = client.get("/api/journey-path?from=colfax&to=truckee")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert paths, "the drive covers I-80, so at least one path"
    lat, lon = paths[0][0]
    # The line starts near Colfax on I-80.
    assert 38.5 < lat < 40.0 and -121.5 < lon < -119.5


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
