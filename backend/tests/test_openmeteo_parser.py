"""parse_hourly: payload to samples in pipeline units, no network involved."""
from __future__ import annotations

import pytest

from api.weather import parse_hourly, short_forecast


def _payload(**hourly_overrides) -> dict:
    hourly = {
        "time": ["2026-01-12T15:00", "2026-01-12T16:00"],
        "temperature_2m": [-2.0, -2.5],
        "snowfall": [1.5, 0.0],
        "wind_gusts_10m": [40.0, 20.0],
        "visibility": [800.0, 16000.0],
        "weather_code": [73, 1],
    }
    hourly.update(hourly_overrides)
    return {"hourly": hourly}


def test_converts_units_at_the_edge() -> None:
    first, second = parse_hourly(_payload())

    assert first.snowfall_rate_in_hr == pytest.approx(1.5 * 0.393701)  # cm/h to in/h
    assert first.wind_gust_mph == pytest.approx(40.0 * 0.621371)  # km/h to mph
    assert first.visibility_miles == pytest.approx(800.0 * 0.000621371)  # m to miles
    assert first.weather_code == 73
    assert second.temperature_c == -2.5


def test_missing_fields_become_none_not_zero() -> None:
    samples = parse_hourly(_payload(snowfall=None, visibility=[None, None]))

    assert all(s.snowfall_rate_in_hr is None for s in samples)
    assert all(s.visibility_miles is None for s in samples)


def test_empty_or_malformed_payloads_yield_no_samples() -> None:
    assert parse_hourly({}) == []
    assert parse_hourly({"hourly": {}}) == []


def test_wmo_codes_map_to_descriptive_text_only() -> None:
    assert short_forecast(0) == "Clear"
    assert short_forecast(73) == "Snow"
    assert short_forecast(86) == "Heavy Snow"
    assert short_forecast(95) == "Thunderstorm"
    assert short_forecast(42) == "Mixed Conditions"  # unmapped code
    assert short_forecast(None) is None
