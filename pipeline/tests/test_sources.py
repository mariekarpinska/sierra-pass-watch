"""Source-client parsing against recorded API payloads (no network)."""
from __future__ import annotations

import responses

from pipeline.sources import cwwp2, nws, openmeteo, usgs


class TestCwwp2:
    def test_parses_chain_control_locations(self, fixture_json) -> None:
        stations = cwwp2.parse_chain_control(fixture_json("cwwp2_cc_sample.json"))
        assert stations, "fixture should yield at least one location"
        for station in stations:
            assert station.status in ("None", "R1", "R2", "R3")
            assert -125 < station.lon < -114 and 32 < station.lat < 42

    def test_parses_rwis_with_ntcip_decoding(self, fixture_json) -> None:
        readings = cwwp2.parse_rwis(fixture_json("cwwp2_rwis_sample.json"))
        assert readings
        for reading in readings:
            # NTCIP sentinels must never leak: 1001 tenths-°C, 65535 wind,
            # 100001 m visibility all decode to None, and real values are sane.
            if reading.surface_temp_c is not None:
                assert -50 < reading.surface_temp_c < 80
            if reading.wind_gust_mph is not None:
                assert 0 <= reading.wind_gust_mph < 250
            if reading.visibility_miles is not None:
                assert 0 <= reading.visibility_miles < 70

    def test_skips_entries_without_coordinates(self) -> None:
        payload = {"data": [{"location": {"latitude": "", "longitude": ""}, "status": {}}]}
        assert cwwp2.parse_chain_control(payload) == []


class TestUsgs:
    def test_keeps_only_sierra_bbox_events(self, fixture_json) -> None:
        events = usgs.parse_events(fixture_json("usgs_sample.json"))
        for event in events:
            assert usgs.LAT_MIN <= event.lat <= usgs.LAT_MAX
            assert usgs.LON_MIN <= event.lon <= usgs.LON_MAX

    def test_strongest_within_radius(self) -> None:
        events = [
            usgs.SeismicEvent("a", 2.0, 39.3, -120.3),
            usgs.SeismicEvent("b", 4.5, 39.4, -120.2),
            usgs.SeismicEvent("far", 6.0, 35.5, -118.0),
        ]
        strongest = usgs.strongest_within_km(events, 39.3163, -120.3208, radius_km=80)
        assert strongest is not None and strongest.event_id == "b"
        assert usgs.strongest_within_km([], 39.3, -120.3) is None


class TestOpenMeteo:
    def test_parse_current_converts_units(self, fixture_json) -> None:
        reading = openmeteo.parse_current(fixture_json("openmeteo_sample.json"))
        current = fixture_json("openmeteo_sample.json")["current"]
        if current.get("snowfall") is not None:
            assert reading.snowfall_rate_in_hr == current["snowfall"] * 0.393701
        if current.get("visibility") is not None:
            assert reading.visibility_miles == current["visibility"] * 0.000621371

    def test_parse_current_batch_wraps_single_and_maps_list(self, fixture_json) -> None:
        one = fixture_json("openmeteo_sample.json")
        assert len(openmeteo.parse_current_batch(one)) == 1       # bare object -> 1
        assert len(openmeteo.parse_current_batch([one, one])) == 2  # array -> one each

    @responses.activate
    def test_fetch_current_batch_parses_array_in_order(self) -> None:
        responses.get(
            openmeteo.CURRENT_URL,
            json=[
                {"current": {"time": "t0", "wind_gusts_10m": 10.0}},
                {"current": {"time": "t1", "wind_gusts_10m": 80.0}},
            ],
        )
        readings = openmeteo.fetch_current_batch([(39.3, -120.3), (38.8, -120.0)])
        assert len(readings) == 2
        assert readings[0].wind_gust_mph == 10.0 * 0.621371
        assert readings[1].wind_gust_mph == 80.0 * 0.621371

    @responses.activate
    def test_fetch_archive_hours_shapes_rows(self) -> None:
        responses.get(
            openmeteo.ARCHIVE_URL,
            json={
                "hourly": {
                    "time": ["2026-01-01T00:00", "2026-01-01T01:00"],
                    "snowfall": [1.5, 0.0],
                    "wind_gusts_10m": [50.0, None],
                    "surface_temperature": [-6.0, 2.0],
                }
            },
        )
        from datetime import date

        readings = openmeteo.fetch_archive_hours(39.3, -120.3, date(2026, 1, 1), date(2026, 1, 1))
        assert len(readings) == 2
        assert readings[0].snowfall_rate_in_hr == 1.5 * 0.393701
        assert readings[0].visibility_miles is None  # archive has no visibility
        assert readings[1].wind_gust_mph is None


class TestNws:
    def test_parse_mph_handles_both_shapes(self) -> None:
        assert nws._parse_mph("25 mph") == 25.0
        assert nws._parse_mph({"value": 32.0}) == 32.0
        assert nws._parse_mph(None) is None
        assert nws._parse_mph("calm") is None

    @responses.activate
    def test_fetch_forecast_resolves_grid_then_reads_first_period(self, fixture_json) -> None:
        responses.get(
            "https://api.weather.gov/points/39.3163,-120.3208",
            json={"properties": {"gridId": "REV", "gridX": 98, "gridY": 90}},
        )
        responses.get(
            "https://api.weather.gov/gridpoints/REV/98,90/forecast/hourly",
            json=fixture_json("nws_forecast_sample.json"),
        )
        forecast = nws.fetch_forecast("I-80:donner-summit", 39.3163, -120.3208)
        assert forecast is not None
        assert forecast.temperature_f is not None

    @responses.activate
    def test_grid_lookup_failure_returns_none(self) -> None:
        responses.get("https://api.weather.gov/points/1.0,2.0", status=500)
        assert nws.fetch_forecast("R:x", 1.0, 2.0) is None
