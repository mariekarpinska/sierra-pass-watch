"""Consumer tests: parsing, batching, commit ordering — and (with Docker)
true idempotency against a real Postgres."""
from __future__ import annotations

import json

import pytest

import pipeline.consumer as consumer_module
from pipeline.consumer import parse_message, run
from pipeline.database import ROAD_EVENT_COLUMNS


def _event(segment_id: str = "I-80:donner-summit", ts: str = "2026-01-12T15:00:00+00:00") -> dict:
    return {
        "segment_id": segment_id,
        "segment_name": "Donner Summit",
        "route_id": "I-80",
        "lat": 39.3163,
        "lon": -120.3208,
        "event_timestamp": ts,
        "weather_regime": "SNOW",
        "chain_control": "R1",
        "road_closed": None,
        "snowfall_rate_in_hr": 0.3,
        "visibility_miles": 2.0,
        "wind_gust_mph": 18.0,
        "surface_temp_c": -2.0,
        "seismic_mag": None,
        "source": "live",
    }


class TestParseMessage:
    def test_valid_message_maps_to_bronze_columns(self) -> None:
        row = parse_message(json.dumps(_event()).encode())
        assert row is not None
        assert set(row) == set(ROAD_EVENT_COLUMNS)

    def test_malformed_json_is_dropped_not_raised(self) -> None:
        assert parse_message(b"{not json") is None

    def test_message_missing_required_keys_is_dropped(self) -> None:
        assert parse_message(json.dumps({"segment_id": "x"}).encode()) is None

    def test_extra_keys_are_ignored(self) -> None:
        event = _event() | {"unexpected": 1}
        row = parse_message(json.dumps(event).encode())
        assert row is not None and "unexpected" not in row


class _FakeMessage:
    def __init__(self, value: bytes) -> None:
        self._value = value

    def error(self):
        return None

    def value(self) -> bytes:
        return self._value


class _FakeConsumer:
    """Feeds queued messages, records commits, then returns None forever."""

    def __init__(self, events: list[dict]) -> None:
        self.queue = [_FakeMessage(json.dumps(e).encode()) for e in events]
        self.commits: list[int] = []

    def poll(self, _timeout: float):
        return self.queue.pop(0) if self.queue else None

    def commit(self, asynchronous: bool) -> None:
        assert asynchronous is False, "offset commits must be synchronous"
        self.commits.append(1)


class TestRunLoop:
    def test_db_commit_happens_before_kafka_commit(self, monkeypatch) -> None:
        order: list[str] = []

        class FakeConn:
            def commit(self) -> None:
                order.append("db-commit")

        class OrderedConsumer(_FakeConsumer):
            def commit(self, asynchronous: bool) -> None:
                super().commit(asynchronous)
                order.append("kafka-commit")

        monkeypatch.setattr(
            consumer_module, "insert_road_events", lambda conn, batch: len(batch)
        )
        # Flush by size so all three messages land in one batch.
        monkeypatch.setattr(consumer_module, "BATCH_SIZE", 3)

        events = [_event(ts=f"2026-01-12T{h:02d}:00:00+00:00") for h in range(3)]
        inserted = run(OrderedConsumer(events), FakeConn(), max_batches=1)

        assert inserted == 3
        assert order and order[0] == "db-commit"
        assert order.index("db-commit") < order.index("kafka-commit")

    def test_poison_messages_are_skipped(self, monkeypatch) -> None:
        inserted_batches: list[list[dict]] = []
        monkeypatch.setattr(
            consumer_module,
            "insert_road_events",
            lambda conn, batch: inserted_batches.append(batch) or len(batch),
        )
        monkeypatch.setattr(consumer_module, "BATCH_SIZE", 1)

        class FakeConn:
            def commit(self) -> None: ...

        consumer = _FakeConsumer([_event()])
        consumer.queue.insert(0, _FakeMessage(b"garbage"))
        inserted = run(consumer, FakeConn(), max_batches=1)

        assert inserted == 1
        assert len(inserted_batches[0]) == 1


@pytest.mark.integration
class TestIdempotencyAgainstRealPostgres:
    def test_replaying_a_batch_inserts_nothing_new(self) -> None:
        docker = pytest.importorskip("testcontainers.postgres")
        from pathlib import Path

        import psycopg

        schema = (Path(__file__).parents[1] / "db" / "schema.sql").read_text(encoding="utf-8")
        try:
            container = docker.PostgresContainer("postgres:17-alpine")
            container.start()
        except Exception as exc:  # noqa: BLE001 — no Docker → skip, don't fail
            pytest.skip(f"Docker unavailable: {exc}")
        try:
            with psycopg.connect(container.get_connection_url().replace("+psycopg2", "")) as conn:
                conn.execute(schema)
                from pipeline.database import insert_road_events

                batch = [
                    _event(ts="2026-01-12T15:00:00+00:00"),
                    _event(ts="2026-01-12T16:00:00+00:00"),
                ]
                first = insert_road_events(conn, batch)
                conn.commit()
                replay = insert_road_events(conn, batch)  # at-least-once replay
                conn.commit()

                count = conn.execute("select count(*) from raw_road_events").fetchone()[0]
                assert (first, replay, count) == (2, 0, 2)
        finally:
            container.stop()
