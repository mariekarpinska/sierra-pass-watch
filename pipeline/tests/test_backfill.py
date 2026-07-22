from __future__ import annotations

from datetime import datetime, timezone

from pipeline.backfill import (
    _closest_archive_hour,
    _parse_datetime,
    crash_row,
    weather_events_for_segment,
)
from pipeline.database import ROAD_EVENT_COLUMNS
from pipeline.sources.openmeteo import WeatherReading


def _hour(ts: str) -> WeatherReading:
    return WeatherReading(timestamp=ts, snowfall_rate_in_hr=None,
                          visibility_miles=None, wind_gust_mph=None, temperature_c=None)


class TestClosestArchiveHour:
    def test_matches_the_collision_hour(self) -> None:
        readings = [_hour("2026-07-21T14:00"), _hour("2026-07-21T15:00"), _hour("2026-07-21T16:00")]
        event_time = datetime(2026, 7, 21, 15, 7, tzinfo=timezone.utc)
        assert _closest_archive_hour(readings, event_time).timestamp == "2026-07-21T15:00"

    def test_none_when_the_hour_is_absent(self) -> None:
        readings = [_hour("2026-07-21T14:00")]
        event_time = datetime(2026, 7, 21, 23, 0, tzinfo=timezone.utc)
        assert _closest_archive_hour(readings, event_time) is None


def _ccrs_row(**overrides) -> dict:
    row = {
        "COLLISION_ID": "9001",
        "CRASH_DATE_TIME": "2025-01-12 06:30:00",
        "LATITUDE": "39.3163",
        "LONGITUDE": "-120.3208",
        "PRIMARYROAD": "I-80 EASTBOUND",
        "WEATHER_1": "SNOWING",
        "ROADWAYSURFACECODE": "C",
        "LIGHTINGDESCRIPTION": "DAYLIGHT",
        "MOTORVEHICLEINVOLVEDWITHDESC": "OTHER MOTOR VEHICLE",
        "COLLISION_TYPE_DESCRIPTION": "REAR END",
        "PRIMARY_COLLISION_FACTOR_VIOLATION": "22350 UNSAFE SPEED",
        "DAY_OF_WEEK": "Sunday",
        "NUMBERKILLED": "0",
        "NUMBERINJURED": "2",
    }
    row.update(overrides)
    return row


class TestCrashRow:
    def test_normalizes_a_good_ccrs_row(self) -> None:
        row = crash_row(_ccrs_row())
        assert row is not None
        assert row["case_id"] == "9001"
        assert row["route_id"] == "I-80"
        assert row["direction"] == "EB"
        assert row["severity"] == "Injury"
        assert row["road_surface"] == "Snowy/Icy"
        assert row["weather_regime"] == "SNOW"
        assert row["collision_type"] == "Rear End"
        # primary_factor stays RAW — dbt normalizes it into the taxonomy.
        assert row["primary_factor"] == "22350 UNSAFE SPEED"

    def test_fatal_severity_from_killed_count(self) -> None:
        row = crash_row(_ccrs_row(NUMBERKILLED="1", NUMBERINJURED="0"))
        assert row is not None and row["severity"] == "Fatal"
        assert row["num_killed"] == 1

    def test_rejects_untracked_roads(self) -> None:
        assert crash_row(_ccrs_row(PRIMARYROAD="MAIN STREET")) is None

    def test_rejects_points_outside_the_sierra(self) -> None:
        # I-80 also runs through San Francisco — same road text, not our range.
        assert crash_row(_ccrs_row(LATITUDE="37.79", LONGITUDE="-122.39")) is None

    def test_rejects_unusable_coordinates_and_dates(self) -> None:
        assert crash_row(_ccrs_row(LATITUDE="", LONGITUDE="")) is None
        assert crash_row(_ccrs_row(LATITUDE="0", LONGITUDE="0")) is None
        assert crash_row(_ccrs_row(CRASH_DATE_TIME="not a date")) is None

    def test_reads_older_switrs_style_columns(self) -> None:
        row = crash_row(
            _ccrs_row(
                COLLISION_ID="",
                CASE_ID="old-1",
                CRASH_DATE_TIME="",
                COLLISION_DATE="2019-02-03",
                LATITUDE="",
                POINT_Y="38.8124",
                LONGITUDE="",
                POINT_X="-120.0307",
                PRIMARYROAD="",
                PRIMARY_RD="US-50 WB",
            )
        )
        assert row is not None
        assert row["case_id"] == "old-1"
        assert row["route_id"] == "US-50"


class TestParseDatetime:
    def test_accepts_common_ccrs_formats(self) -> None:
        for raw in ("2025-01-12 06:30:00", "2025-01-12", "2025-01-12T06:30:00", "01/12/2025"):
            parsed = _parse_datetime({"CRASH_DATE_TIME": raw})
            assert parsed is not None and parsed.tzinfo is not None

    def test_parses_live_iso_24_hour_shape(self) -> None:
        # The real CCRS export shape (verified 2016–2025): ISO 8601, 24-hour.
        parsed = _parse_datetime({"CRASH_DATE_TIME": "2024-01-13T16:05:00"})
        assert parsed is not None and (parsed.hour, parsed.minute) == (16, 5)
        assert parsed.tzinfo is not None

    def test_pm_time_maps_to_afternoon_not_morning(self) -> None:
        # 12-hour AM/PM vintages: PM must add 12 h, not be silently dropped.
        pm = _parse_datetime({"CRASH_DATE_TIME": "01/12/2025 06:30:00 PM"})
        assert pm is not None and (pm.hour, pm.minute) == (18, 30)
        am = _parse_datetime({"CRASH_DATE_TIME": "01/12/2025 06:30:00 AM"})
        assert am is not None and am.hour == 6

    def test_rejects_garbage(self) -> None:
        assert _parse_datetime({"CRASH_DATE_TIME": "soon"}) is None
        assert _parse_datetime({}) is None


class TestWeatherEvents:
    SEGMENT = {
        "segment_id": "US-50:echo-summit",
        "segment_name": "Echo Summit",
        "route_id": "US-50",
        "lat": 38.8124,
        "lon": -120.0307,
    }

    def test_classifies_each_hour_with_the_shared_classifier(self) -> None:
        readings = [
            WeatherReading("2026-01-01T00:00", 0.8, None, 20.0, -3.0),
            WeatherReading("2026-01-01T01:00", 0.0, None, 50.0, 2.0),
            WeatherReading("2026-01-01T02:00", 0.0, None, 5.0, 4.0),
        ]
        events = weather_events_for_segment(self.SEGMENT, readings)
        assert [e["weather_regime"] for e in events] == ["SNOW", "HIGH_WIND", "CLEAR_DRY"]
        for event in events:
            assert set(event) == set(ROAD_EVENT_COLUMNS)
            assert event["source"] == "backfill"
            assert event["event_timestamp"].endswith("+00:00")

    def test_skips_readings_without_timestamps(self) -> None:
        events = weather_events_for_segment(self.SEGMENT, [WeatherReading("", 0, None, 0, 0)])
        assert events == []
