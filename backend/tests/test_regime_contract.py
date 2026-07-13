"""The golden contract, asserted from the API's side of the fence.

The API imports pipeline.regime rather than re-implementing it, so there is
exactly one classifier, but this suite still asserts every case in
shared/weather-regime-cases.json independently of the pipeline's tests:
whichever package someone runs, a behaviour change that skipped the shared spec
fails a build."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.regime import REGIMES, classify_conditions

from api.weather import worst_regime

GOLDEN_FILE = Path(__file__).parents[2] / "shared" / "weather-regime-cases.json"
GOLDEN = json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=[c["name"] for c in GOLDEN["cases"]])
def test_golden_contract(case: dict) -> None:
    inputs = case["input"]
    assert classify_conditions(
        snowfall_rate_in_hr=inputs["snowfallRateInHr"],
        visibility_miles=inputs["visibilityMiles"],
        wind_gust_mph=inputs["windGustMph"],
        surface_temp_c=inputs["surfaceTempC"],
        chain_control=inputs["chainControl"],
    ) == case["expected"]


def test_worst_regime_follows_the_worst_first_ordering() -> None:
    assert worst_regime(["CLEAR_DRY", "SNOW", "RAIN_FOG_LOW_VIS"]) == "SNOW"
    assert worst_regime(["SNOW", "HEAVY_SNOW_LOW_VIS"]) == "HEAVY_SNOW_LOW_VIS"
    assert worst_regime([]) == "UNKNOWN"
    # The ordering itself is part of the contract (frontend REGIME_CODES).
    assert REGIMES[0] == "HEAVY_SNOW_LOW_VIS" and REGIMES[-1] == "UNKNOWN"


def test_worst_regime_reports_unknown_when_it_dominates_the_window() -> None:
    # One readable hour must not badge a mostly-unreadable window as clear...
    assert worst_regime(["UNKNOWN"] * 4 + ["CLEAR_DRY"]) == "UNKNOWN"
    # ...but a minority of unreadable hours defers to the known weather.
    assert worst_regime(["UNKNOWN", "CLEAR_DRY", "SNOW"]) == "SNOW"
