"""Poll worker tests: all offline, driven by the recorded CHP/Caltrans fixtures.

The worker's pure pieces (incident_row) are tested directly; the cycle
(poll_once) is tested against fixtures with the database and network stubbed, so
these run with no broker, no Postgres and no outbound calls.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pipeline import poller
from pipeline.alerts import Alert
from pipeline.sources import openmeteo

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _collision_alert() -> Alert:
    return Alert(
        alert_id="chp:12345",
        kind="INCIDENT",
        category="COLLISION",
        route_id="I-80",
        segment_id="I-80:donner-summit",
        headline="Collision reported on I-80 near Donner Summit",
        detail="Trfc Collision-1141 Enrt",
        lat=39.3163,
        lon=-120.3208,
        measure_mi=12.4,
        event_time="2026-07-21T15:00:00+00:00",
        source="chp",
    )


class TestIncidentRow:
    def test_strips_chp_prefix_and_carries_weather(self) -> None:
        weather = openmeteo.WeatherReading(
            timestamp="2026-07-21T15:00",
            snowfall_rate_in_hr=0.2,
            visibility_miles=0.4,
            wind_gust_mph=10.0,
            temperature_c=-1.0,
        )
        row = poller.incident_row(_collision_alert(), weather)

        assert row["incident_id"] == "12345"  # "chp:" prefix stripped
        assert row["route_id"] == "I-80"
        assert row["category"] == "COLLISION"
        assert row["measure_mi"] == 12.4
        assert row["snowfall_rate_in_hr"] == 0.2
        # snowing (>=0.1) wins the regime.
        assert row["weather_regime"] == "SNOW"

    def test_missing_weather_is_unknown_with_null_numbers(self) -> None:
        row = poller.incident_row(_collision_alert(), None)

        assert row["weather_regime"] == "UNKNOWN"
        assert row["snowfall_rate_in_hr"] is None
        assert row["visibility_miles"] is None
        assert row["wind_gust_mph"] is None
        assert row["surface_temp_c"] is None


class TestPollOnceDryRun:
    def test_collects_only_collisions_on_tracked_routes(self) -> None:
        alerts, rows = poller.poll_once(dry_run=True)

        # Something fired from the fixtures.
        assert alerts
        # Every collected row is a collision on a tracked route, keyed on a bare
        # CHP id (no "chp:" prefix), with a valid regime.
        for row in rows:
            assert row["category"] == "COLLISION"
            assert row["route_id"]
            assert not row["incident_id"].startswith("chp:")
            # Dry run does no weather fetch, so the regime is UNKNOWN.
            assert row["weather_regime"] == "UNKNOWN"

        collision_alerts = [a for a in alerts if a.kind == "INCIDENT" and a.category == "COLLISION"]
        assert len(rows) == len(collision_alerts)


class _FakeConn:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class TestPollOnceWrites:
    def test_writes_alerts_incidents_and_state_then_commits(self, monkeypatch) -> None:
        import pipeline.database as db

        captured: dict = {}
        monkeypatch.setattr(db, "load_alert_state", lambda conn: {})
        monkeypatch.setattr(
            db, "insert_alerts", lambda conn, rows: captured.__setitem__("alerts", rows) or len(rows)
        )
        monkeypatch.setattr(
            db, "insert_incidents", lambda conn, rows: captured.__setitem__("incidents", rows) or len(rows)
        )
        monkeypatch.setattr(db, "save_alert_state", lambda conn, state: captured.__setitem__("state", state))

        # Feed the same fixtures the dry run uses, but through the live code path,
        # and never touch the network for weather.
        from pipeline.sources import chp, cwwp2

        cc = cwwp2.parse_chain_control(poller._load_fixture("cwwp2_cc_sample.json"))
        incidents = chp.parse_incidents((FIXTURES_DIR / "chp_sample.xml").read_text(encoding="utf-8"))
        monkeypatch.setattr(poller.cwwp2, "fetch_chain_control", lambda: cc)
        monkeypatch.setattr(poller.chp, "fetch_incidents", lambda: incidents)
        monkeypatch.setattr(poller, "fetch_point_weather", lambda lat, lon: None)

        conn = _FakeConn()
        alerts, rows = poller.poll_once(conn=conn, dry_run=False)

        assert captured["alerts"]  # alert rows handed to the writer
        assert captured["incidents"] == rows
        assert "state" in captured
        assert conn.commits == 1


def _incident(incident_id: str) -> dict:
    return {
        "incident_id": incident_id,
        "category": "COLLISION",
        "type_text": "Trfc Collision",
        "route_id": "I-80",
        "lat": 39.3163,
        "lon": -120.3208,
        "measure_mi": 44.1,
        "event_time": "2026-01-12T15:00:00+00:00",
        "weather_regime": "SNOW",
        "snowfall_rate_in_hr": 0.3,
        "visibility_miles": 1.0,
        "wind_gust_mph": 20.0,
        "surface_temp_c": -2.0,
        "source": "chp",
    }


@pytest.mark.integration
class TestIncidentIdempotencyAgainstRealPostgres:
    """The incidents writer against a throwaway real Postgres: re-inserting the
    same collision (a re-poll) only ever no-ops, so ON CONFLICT gives one row per
    incident. Replaces the old Kafka-consumer idempotency test (ADR-0012)."""

    def test_re_inserting_a_collision_adds_nothing_new(self) -> None:
        docker = pytest.importorskip("testcontainers.postgres")
        import psycopg

        from pipeline.database import insert_incidents

        schema = (Path(__file__).parents[1] / "db" / "schema.sql").read_text(encoding="utf-8")
        try:
            container = docker.PostgresContainer("postgres:17-alpine")
            container.start()
        except Exception as exc:  # noqa: BLE001: no Docker means skip, never fail
            pytest.skip(f"Docker unavailable: {exc}")
        try:
            with psycopg.connect(container.get_connection_url().replace("+psycopg2", "")) as conn:
                conn.execute(schema)
                batch = [_incident("inc-a"), _incident("inc-b")]
                first = insert_incidents(conn, batch)
                conn.commit()
                replay = insert_incidents(conn, batch)  # a re-poll of the same collisions
                conn.commit()
                count = conn.execute("select count(*) from incidents").fetchone()[0]
                assert (first, replay, count) == (2, 0, 2)
        finally:
            container.stop()
