"""/api/forecast behaviour with the upstream faked at the provider seam:
span resolution over the real catalogue, per-town window summary, error
semantics, and graceful degradation when Open-Meteo is down."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.catalog import RouteCatalog
from api.config import Settings
from api.main import create_app
from api.weather import ForecastService, HourlySample, get_forecast_service

DEPARTURE = "2026-01-12T15:00:00Z"


class FakeForecastProvider:
    """Snowy at Echo Summit (lat approx 38.81), clear everywhere else: enough
    signal to assert per-town classification without a network. The window
    stamps are ignored; the fake always returns the same two hours."""

    def __init__(self) -> None:
        self.throw = False
        self.empty = False

    async def get_hourly(
        self, lat: float, lon: float, start_hour: str, end_hour: str
    ) -> list[HourlySample]:
        if self.throw:
            raise RuntimeError("upstream down")
        if self.empty:
            return []
        snowy = abs(lat - 38.8124) < 0.001
        return [
            HourlySample(
                time_utc="2026-01-12T15:00",
                temperature_c=-2.0,
                surface_temp_c=-2.0,
                snowfall_rate_in_hr=0.7 if snowy else 0.0,
                wind_gust_mph=12.0,
                visibility_miles=2.0 if snowy else 9.0,
                precip_probability_pct=80.0 if snowy else 20.0,
                weather_code=73 if snowy else 1,
            ),
            HourlySample(
                time_utc="2026-01-12T16:00",
                temperature_c=-2.5,
                surface_temp_c=-2.5,
                snowfall_rate_in_hr=0.0,
                wind_gust_mph=10.0,
                visibility_miles=9.0,
                precip_probability_pct=10.0,
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


def _forecast(client, **params):
    return client.get("/api/forecast", params=params)


def test_missing_params_are_a_400(client) -> None:
    # departure is required alongside route/from/to.
    response = _forecast(
        client, route="US-50", **{"from": "US-50:placerville", "to": "US-50:echo-summit"}
    )

    assert response.status_code == 400
    assert "error" in response.json()


def test_unparseable_departure_is_a_400(client) -> None:
    response = _forecast(
        client,
        route="US-50",
        departure="not-a-time",
        **{"from": "US-50:placerville", "to": "US-50:echo-summit"},
    )

    assert response.status_code == 400
    assert response.json() == {"error": "departure must be an ISO 8601 time"}


def test_real_di_wiring_resolves_without_query_param_leakage() -> None:
    """Regression: get_forecast_service must receive the Request object, not
    surface as a `?request=` query field. Uses the REAL dependency (no
    override); missing params return our 400 before any upstream call."""
    with TestClient(create_app()) as real_client:
        response = real_client.get("/api/forecast")

    assert response.status_code == 400
    assert response.json() == {"error": "route, from, to and departure are required"}


def test_unknown_route_or_segment_is_a_404(client) -> None:
    unknown_route = _forecast(
        client, route="SR-0", departure=DEPARTURE, **{"from": "SR-0:a", "to": "SR-0:b"}
    )
    unknown_segment = _forecast(
        client,
        route="US-50",
        departure=DEPARTURE,
        **{"from": "US-50:placerville", "to": "US-50:narnia"},
    )

    assert unknown_route.status_code == 404
    assert unknown_segment.status_code == 404


def test_span_keeps_order_and_summarizes_each_town(client) -> None:
    forecast = _forecast(
        client,
        route="US-50",
        departure=DEPARTURE,
        **{"from": "US-50:placerville", "to": "US-50:south-lake-tahoe"},
    ).json()

    assert forecast["departureUtc"] == "2026-01-12T15:00:00+00:00"
    assert [s["segment"]["id"] for s in forecast["segments"]] == [
        "US-50:placerville",
        "US-50:echo-summit",
        "US-50:south-lake-tahoe",
    ]
    # Placerville is clear; Echo Summit gets the fake's snow hour.
    assert forecast["segments"][0]["regime"] == "CLEAR_DRY"
    echo = forecast["segments"][1]
    assert echo["regime"] == "SNOW"
    assert echo["shortForecast"] == "Snow"  # the worst hour's text
    # Window summary: high/low across the two hours, roughest wind/vis/precip.
    assert echo["temperatureHighF"] == 28.4  # -2.0 C
    assert echo["temperatureLowF"] == 27.5  # -2.5 C
    assert echo["windGustMph"] == 12.0  # max of 12, 10
    assert echo["visibilityMiles"] == 2.0  # min of 2, 9
    assert echo["precipProbabilityPct"] == 80  # max of 80, 10


def test_reversed_journeys_come_back_in_reversed_travel_order(client) -> None:
    forecast = _forecast(
        client,
        route="US-50",
        departure=DEPARTURE,
        **{"from": "US-50:south-lake-tahoe", "to": "US-50:placerville"},
    ).json()

    assert [s["segment"]["id"] for s in forecast["segments"]] == [
        "US-50:south-lake-tahoe",
        "US-50:echo-summit",
        "US-50:placerville",
    ]


def test_an_empty_upstream_payload_is_not_cached(client, provider) -> None:
    """A 200 with no usable hours degrades that request to UNKNOWN, but must
    not be cached: the next request should hit upstream again and recover."""
    params = dict(
        route="US-50",
        departure=DEPARTURE,
        **{"from": "US-50:echo-summit", "to": "US-50:echo-summit"},
    )

    provider.empty = True
    degraded = _forecast(client, **params).json()
    assert degraded["segments"][0]["regime"] == "UNKNOWN"

    provider.empty = False
    recovered = _forecast(client, **params).json()
    assert recovered["segments"][0]["regime"] == "SNOW"


def test_upstream_failure_degrades_to_unknown_not_a_500(client, provider) -> None:
    provider.throw = True

    response = _forecast(
        client,
        route="I-80",
        departure=DEPARTURE,
        **{"from": "I-80:colfax", "to": "I-80:truckee"},
    )

    assert response.status_code == 200
    for segment in response.json()["segments"]:
        assert segment["regime"] == "UNKNOWN"
        assert segment["temperatureHighF"] is None
        assert segment["precipProbabilityPct"] is None
        assert segment["shortForecast"] is None
