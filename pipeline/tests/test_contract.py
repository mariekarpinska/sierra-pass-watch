"""Opt-in contract tests that hit the REAL upstream APIs (marked ``network``).

Excluded from the default suite — external services are slow and can be down.
Run explicitly:

    pytest -m network

Purpose: catch UPSTREAM SHAPE DRIFT (a renamed field, a changed date format)
that captured fixtures can't detect — a fixture just goes stale while the test
stays green. On a network/API outage these SKIP (an outage isn't drift); they
FAIL only when the live shape breaks an assumption our parsers depend on.
"""
from __future__ import annotations

import pytest
import requests

from pipeline.backfill import _parse_datetime
from pipeline.sources import openmeteo

pytestmark = pytest.mark.network


class TestCcrsContract:
    # 2025 statewide crash resource (data.ca.gov CKAN); see pipeline/sources/ccrs.py.
    RESOURCE = "9f4fc839-122d-4595-a146-43bc4ed16f46"

    def test_crash_datetime_field_present_and_parseable(self) -> None:
        try:
            resp = requests.get(
                "https://data.ca.gov/api/3/action/datastore_search",
                params={"resource_id": self.RESOURCE, "limit": 3},
                timeout=30,
            )
        except requests.RequestException as exc:
            pytest.skip(f"CCRS API unreachable: {exc}")
        if resp.status_code != 200 or not resp.json().get("success"):
            pytest.skip(f"CCRS API returned {resp.status_code}")

        records = resp.json()["result"]["records"]
        assert records, "CCRS returned no records"
        for rec in records:
            raw = rec.get("Crash Date Time")
            assert raw, "field 'Crash Date Time' missing — CCRS schema changed"
            assert _parse_datetime({"CRASH_DATE_TIME": raw}) is not None, (
                f"_parse_datetime could not parse a live value {raw!r} — format drifted"
            )


class TestOpenMeteoContract:
    def test_current_batch_shape_and_order(self) -> None:
        points = [(39.3163, -120.3208), (38.8124, -120.0307)]  # Donner, Echo Summit
        try:
            readings = openmeteo.fetch_current_batch(points)
        except requests.RequestException as exc:
            pytest.skip(f"Open-Meteo unreachable: {exc}")

        assert len(readings) == len(points), "batch length/order changed"
        # The `current` object should still populate at least one field we read.
        first = readings[0]
        assert any(
            v is not None
            for v in (first.temperature_c, first.wind_gust_mph, first.snowfall_rate_in_hr)
        ), "no expected fields populated — Open-Meteo `current` keys changed"
