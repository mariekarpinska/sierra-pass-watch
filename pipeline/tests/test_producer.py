"""Producer tests — dry-run end to end, merge logic, and the no-score guard."""
from __future__ import annotations

from pipeline.database import ROAD_EVENT_COLUMNS
from pipeline.producer import build_event, poll_once
from pipeline.regime import REGIMES
from pipeline.routes import SEGMENTS
from pipeline.sources.cwwp2 import ChainControl, RwisReading
from pipeline.sources.openmeteo import WeatherReading

DONNER = next(s for s in SEGMENTS if s["segment_id"] == "I-80:donner-summit")


def _weather(**overrides) -> WeatherReading:
    values = dict(
        timestamp="2026-01-12T15:00",
        snowfall_rate_in_hr=0.0,
        visibility_miles=8.0,
        wind_gust_mph=10.0,
        temperature_c=5.0,
    )
    values.update(overrides)
    return WeatherReading(**values)


class TestBuildEvent:
    def test_merges_nearest_station_data(self) -> None:
        rwis = RwisReading("1", "Donner Lake", "80", 39.32, -120.32, -6.5, 0.4, 35.0)
        cc = ChainControl("Kingvale", "80", 39.31, -120.35, "R2")
        event = build_event(DONNER, [cc], [rwis], [], _weather(snowfall_rate_in_hr=0.8), None, "t")
        assert event["chain_control"] == "R2"
        assert event["surface_temp_c"] == -6.5
        assert event["visibility_miles"] == 0.4  # RWIS sensor preferred over model
        assert event["weather_regime"] == "HEAVY_SNOW_LOW_VIS"

    def test_ignores_stations_beyond_30km(self) -> None:
        far_rwis = RwisReading("1", "Bishop", "395", 37.36, -118.40, -6.5, 0.4, 35.0)
        far_cc = ChainControl("Bishop", "395", 37.36, -118.40, "R3")
        event = build_event(DONNER, [far_cc], [far_rwis], [], _weather(), None, "t")
        assert event["chain_control"] is None
        assert event["surface_temp_c"] is None
        # Open-Meteo still fills the gaps the distant stations couldn't.
        assert event["visibility_miles"] == 8.0

    def test_inactive_chain_status_is_null(self) -> None:
        cc = ChainControl("Kingvale", "80", 39.31, -120.35, "None")
        event = build_event(DONNER, [cc], [], [], _weather(), None, "t")
        assert event["chain_control"] is None

    def test_nws_gust_fallback_only_fills_gaps(self) -> None:
        event = build_event(DONNER, [], [], [], _weather(wind_gust_mph=None), 44.0, "t")
        assert event["wind_gust_mph"] == 44.0
        assert event["weather_regime"] == "HIGH_WIND"


class TestNwsFallbackDecision:
    def test_nws_is_consulted_when_openmeteo_is_down(self, monkeypatch) -> None:
        # Open-Meteo returned nothing for every waypoint (weather is None) — the
        # exact case where NWS must still be tried, not skipped.
        import pipeline.producer as producer_module
        from pipeline.sources.nws import NwsForecast

        monkeypatch.setattr(
            producer_module,
            "_fetch_all",
            lambda dry_run: ([], [], [], {s["segment_id"]: None for s in SEGMENTS}),
        )
        consulted: list[str] = []

        def fake_forecast(segment_id, lat, lon):
            consulted.append(segment_id)
            return NwsForecast(start_time="t", temperature_f=None, wind_gust_mph=44.0, short_forecast="")

        monkeypatch.setattr(producer_module.nws, "fetch_forecast", fake_forecast)

        events = poll_once(kafka_producer=None, dry_run=False)

        assert len(consulted) == len(SEGMENTS)  # tried for every down waypoint
        donner = next(e for e in events if e["segment_id"] == "I-80:donner-summit")
        assert donner["wind_gust_mph"] == 44.0  # NWS gust reached the event
        assert donner["weather_regime"] == "HIGH_WIND"


class TestDryRunPoll:
    def test_emits_one_event_per_catalogue_waypoint(self) -> None:
        events = poll_once(kafka_producer=None, dry_run=True)
        assert len(events) == len(SEGMENTS)
        assert {e["segment_id"] for e in events} == {s["segment_id"] for s in SEGMENTS}

    def test_events_match_the_bronze_schema_exactly(self) -> None:
        events = poll_once(kafka_producer=None, dry_run=True)
        for event in events:
            assert set(event) == set(ROAD_EVENT_COLUMNS)
            assert event["weather_regime"] in REGIMES

    def test_no_score_or_judgment_fields_ever(self) -> None:
        # The old pipeline emitted score/band/penalties; the reframe removed
        # them. This guard keeps them from creeping back into any message.
        events = poll_once(kafka_producer=None, dry_run=True)
        for event in events:
            for key in event:
                for banned in ("score", "band", "risk", "verdict", "penalt", "safe", "level"):
                    assert banned not in key.lower(), f"forbidden key fragment: {key}"

    def test_produces_to_kafka_with_segment_key(self) -> None:
        class RecordingProducer:
            def __init__(self) -> None:
                self.produced: list[dict] = []
                self.flushed = False

            def produce(self, topic: str, key: str, value: bytes) -> None:
                self.produced.append({"topic": topic, "key": key, "value": value})

            def flush(self) -> None:
                self.flushed = True

        producer = RecordingProducer()
        events = poll_once(kafka_producer=producer, dry_run=True)
        assert len(producer.produced) == len(events)
        assert producer.flushed
        assert producer.produced[0]["key"] == events[0]["segment_id"]
