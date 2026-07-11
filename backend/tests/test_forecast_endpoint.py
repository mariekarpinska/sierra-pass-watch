"""/api/forecast behaviour with the upstream faked at the provider seam:
span resolution over the real catalogue, regime labelling, error semantics,
and graceful degradation when Open-Meteo is down."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.catalog import RouteCatalog
from api.config import Settings
from api.main import create_app
from api.weather import ForecastService, HourlySample, get_forecast_service


class FakeForecastProvider:
    """Snowy at Echo Summit (lat approx 38.81), clear everywhere else: enough
    signal to assert per-town classification without a network."""

    def __init__(self) -> None:
        self.throw = False

    async def get_hourly(self, lat: float, lon: float) -> list[HourlySample]:
        if self.throw:
            raise RuntimeError("upstream down")
        snowy = abs(lat - 38.8124) < 0.001
        return [
            HourlySample(
                time_utc="2026-01-12T15:00",
                temperature_c=-2.0,
                snowfall_rate_in_hr=0.7 if snowy else 0.0,
                wind_gust_mph=12.0,
                visibility_miles=2.0 if snowy else 9.0,
                weather_code=73 if snowy else 1,
            ),
            HourlySample(
                time_utc="2026-01-12T16:00",
                temperature_c=-2.5,
                snowfall_rate_in_hr=0.0,
                wind_gust_mph=10.0,
                visibility_miles=9.0,
                weather_code=1,
            ),
        ]


@pytest.fixture()
def provider() -> FakeForecastProvider:
    return FakeForecastProvider()


@pytest.fixture()
def client(provider):
    app = create_app()
    service = ForecastService(
        catalog=RouteCatalog.load(Settings().shared_dir), provider=provider
    )
    app.dependency_overrides[get_forecast_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client


def test_missing_params_are_a_400(client) -> None:
    response = client.get("/api/forecast", params={"route": "US-50"})

    assert response.status_code == 400
    assert "error" in response.json()


def test_real_di_wiring_resolves_without_query_param_leakage() -> None:
    """Regression: get_forecast_service must receive the Request object, not
    surface as a `?request=` query field. Uses the REAL dependency (no
    override); missing params return our 400 before any upstream call."""
    with TestClient(create_app()) as real_client:
        response = real_client.get("/api/forecast")

    assert response.status_code == 400
    assert response.json() == {"error": "route, from and to are required"}


def test_unknown_route_or_segment_is_a_404(client) -> None:
    unknown_route = client.get(
        "/api/forecast", params={"route": "SR-0", "from": "SR-0:a", "to": "SR-0:b"}
    )
    unknown_segment = client.get(
        "/api/forecast",
        params={"route": "US-50", "from": "US-50:placerville", "to": "US-50:narnia"},
    )

    assert unknown_route.status_code == 404
    assert unknown_segment.status_code == 404


def test_journey_span_keeps_travel_order_and_labels_each_town(client) -> None:
    forecast = client.get(
        "/api/forecast",
        params={"route": "US-50", "from": "US-50:placerville", "to": "US-50:south-lake-tahoe"},
    ).json()

    assert [s["segment"]["id"] for s in forecast["segments"]] == [
        "US-50:placerville",
        "US-50:echo-summit",
        "US-50:south-lake-tahoe",
    ]
    # Echo Summit gets the fake's snow hour; regime = worst across points.
    assert forecast["segments"][0]["regime"] == "CLEAR_DRY"
    assert forecast["segments"][1]["regime"] == "SNOW"
    snowy_point = forecast["segments"][1]["points"][0]
    assert snowy_point["regime"] == "SNOW"
    assert snowy_point["shortForecast"] == "Snow"
    assert snowy_point["temperatureF"] == 28.4  # -2 C


def test_reversed_journeys_come_back_in_reversed_travel_order(client) -> None:
    forecast = client.get(
        "/api/forecast",
        params={"route": "US-50", "from": "US-50:south-lake-tahoe", "to": "US-50:placerville"},
    ).json()

    assert [s["segment"]["id"] for s in forecast["segments"]] == [
        "US-50:south-lake-tahoe",
        "US-50:echo-summit",
        "US-50:placerville",
    ]


def test_upstream_failure_degrades_to_unknown_not_a_500(client, provider) -> None:
    provider.throw = True

    response = client.get(
        "/api/forecast",
        params={"route": "I-80", "from": "I-80:colfax", "to": "I-80:truckee"},
    )

    assert response.status_code == 200
    for segment in response.json()["segments"]:
        assert segment["regime"] == "UNKNOWN"
        assert segment["points"] == []
