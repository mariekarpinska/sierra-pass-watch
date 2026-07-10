"""Classifier tests. The golden-case block IS the executable spec:
shared/weather-regime-cases.json is asserted here and (identically) by the
API's test suite — any behaviour change must update the shared file."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.regime import REGIMES, classify_conditions, classify_crash_report

GOLDEN_FILE = Path(__file__).parents[2] / "shared" / "weather-regime-cases.json"
GOLDEN = json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "case", GOLDEN["cases"], ids=[c["name"] for c in GOLDEN["cases"]]
)
def test_golden_contract(case: dict) -> None:
    inputs = case["input"]
    assert classify_conditions(
        snowfall_rate_in_hr=inputs["snowfallRateInHr"],
        visibility_miles=inputs["visibilityMiles"],
        wind_gust_mph=inputs["windGustMph"],
        surface_temp_c=inputs["surfaceTempC"],
        chain_control=inputs["chainControl"],
    ) == case["expected"]


def test_golden_file_covers_every_regime() -> None:
    expected = {case["expected"] for case in GOLDEN["cases"]}
    assert expected == set(REGIMES), "each regime needs at least one golden case"


def test_regimes_are_ordered_worst_first() -> None:
    # The classifier's rule order and every downstream consumer (the API's C#/
    # forecast labelling, the frontend's regime ordering) depend on this exact
    # worst-first sequence; changing it is a contract change.
    assert REGIMES == [
        "HEAVY_SNOW_LOW_VIS", "SNOW", "ICE_FREEZING", "HIGH_WIND",
        "RAIN_FOG_LOW_VIS", "CLEAR_DRY", "UNKNOWN",
    ]


@pytest.mark.parametrize(
    ("weather", "surface", "expected"),
    [
        ("SNOWING", None, "SNOW"),
        ("CLEAR", "SNOWY/ICY", "SNOW"),  # snowy surface counts as snow
        ("FREEZING RAIN", None, "ICE_FREEZING"),
        ("CLEAR", "ICY", "ICE_FREEZING"),
        ("FOG/VISIBILITY", "DRY", "RAIN_FOG_LOW_VIS"),
        ("RAINING", None, "RAIN_FOG_LOW_VIS"),
        ("CLEAR", "WET", "RAIN_FOG_LOW_VIS"),
        ("STRONG WIND", "DRY", "HIGH_WIND"),
        ("CLEAR", "DRY", "CLEAR_DRY"),
        ("CLOUDY", None, "CLEAR_DRY"),
        (None, None, "UNKNOWN"),
        ("NOT STATED", "", "UNKNOWN"),
    ],
)
def test_crash_report_classifier(weather, surface, expected) -> None:
    assert classify_crash_report(weather, surface) == expected


def test_crash_reports_never_produce_heavy_snow() -> None:
    # Report text can't distinguish heavy from light snow; the crash-side
    # vocabulary is deliberately coarser (documented in docs/weather-regimes.md).
    assert classify_crash_report("HEAVY SNOW BLIZZARD", "SNOWY") == "SNOW"
