"""Guardrail: the API is historical and descriptive, never prescriptive. No
response may carry a score, rating, or drive/do-not-drive verdict - the product
states what the record says and lets the user decide. The frontend has the
mirror of this test. If someone adds a `safetyScore` field, this fails.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from datetime import date

from api.crashes import BinRow, CauseRow, get_crash_store
from api.main import create_app
from api.weather import ForecastService, HourlySample, get_forecast_service

# Substrings that would signal a judgement leaking into the contract.
_FORBIDDEN = ("score", "rating", "recommend", "verdict", "grade", "shoulddrive")


def _keys(payload: object) -> set[str]:
    """Every JSON key anywhere in the payload, recursively."""
    found: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            found.add(key)
            found |= _keys(value)
    elif isinstance(payload, list):
        for item in payload:
            found |= _keys(item)
    return found


class _OneClearHour:
    """The provider seam faked with one benign hour, so /api/journey returns a
    fully-populated stop (every contract field present) without a network."""

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


class _OnePopulatedBin:
    """The database seam faked with one fully-populated bin and cause, so
    /api/crash-patterns returns every contract field without Postgres."""

    def bins(self, route_ids, regime):
        return [
            BinRow(
                route_id="I-80",
                mile_bin=12,
                lat=39.31,
                lon=-120.32,
                crash_count=9,
                fatal_count=1,
                top_cause="Unsafe Speed",
                first_crash_date=date(2017, 1, 3),
                last_crash_date=date(2025, 12, 20),
            )
        ]

    def causes(self, route_ids, regime):
        return [CauseRow(cause="Unsafe Speed", crash_count=9)]


@pytest.fixture()
def client():
    app = create_app()
    service = ForecastService(provider=_OneClearHour())
    app.dependency_overrides[get_forecast_service] = lambda: service
    app.dependency_overrides[get_crash_store] = lambda: _OnePopulatedBin()
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    "path",
    [
        "/api/health",
        "/api/towns",
        "/api/journey?from=colfax&to=south-lake-tahoe&departure=2026-01-12T15:00:00Z",
        "/api/crash-patterns?routes=I-80,US-50&regime=SNOW",
    ],
)
def test_no_response_carries_a_safety_judgement(client, path) -> None:
    keys = {k.lower() for k in _keys(client.get(path).json())}
    leaked = {k for k in keys if any(word in k for word in _FORBIDDEN)}
    assert not leaked, f"{path} leaked judgement-shaped keys: {leaked}"
