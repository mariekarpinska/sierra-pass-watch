"""Postgres access for the pipeline — one connection helper, two writers.

psycopg (v3) with plain parameterized SQL. Both writers are idempotent by
`ON CONFLICT DO NOTHING` against the table's natural key, which is what makes
the consumer's at-least-once delivery and the backfill's re-runs safe.
"""
from __future__ import annotations

import os

import psycopg

# Column order shared by the INSERT and every row builder.
ROAD_EVENT_COLUMNS = (
    "segment_id", "segment_name", "route_id", "lat", "lon", "event_timestamp",
    "weather_regime", "chain_control", "road_closed", "snowfall_rate_in_hr",
    "visibility_miles", "wind_gust_mph", "surface_temp_c", "seismic_mag", "source",
)

CRASH_COLUMNS = (
    "case_id", "collision_datetime", "lat", "lon", "route_id", "direction",
    "severity", "collision_type", "primary_factor", "collided_with",
    "primary_road", "lighting", "day_of_week", "weather", "road_surface",
    "weather_regime", "num_injured", "num_killed", "measure_mi",
)

_ROAD_EVENT_SQL = (
    f"insert into raw_road_events ({', '.join(ROAD_EVENT_COLUMNS)}) "
    f"values ({', '.join('%s' for _ in ROAD_EVENT_COLUMNS)}) "
    "on conflict (segment_id, event_timestamp) do nothing"
)

_CRASH_SQL = (
    f"insert into crashes ({', '.join(CRASH_COLUMNS)}) "
    f"values ({', '.join('%s' for _ in CRASH_COLUMNS)}) "
    "on conflict (case_id) do nothing"
)


def connect() -> psycopg.Connection:
    """Connect from DATABASE_URL, or the POSTGRES_* parts docker-compose uses."""
    url = os.getenv("DATABASE_URL")
    if url:
        return psycopg.connect(url)
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.getenv("POSTGRES_USER", "app"),
        password=os.getenv("POSTGRES_PASSWORD", "app_dev_password"),
        dbname=os.getenv("POSTGRES_DB", "app"),
    )


def _insert_batch(conn: psycopg.Connection, sql: str, columns: tuple[str, ...], rows: list[dict]) -> int:
    """Executemany one idempotent INSERT; returns rows actually inserted.

    Shared by all three writers — they differ only in their SQL and columns.
    Each dict is projected to a tuple in column order; ON CONFLICT DO NOTHING
    makes re-inserts (Kafka replays, backfill re-runs) no-op.
    """
    if not rows:
        return 0
    values = [tuple(r.get(c) for c in columns) for r in rows]
    with conn.cursor() as cur:
        cur.executemany(sql, values)
        return cur.rowcount if cur.rowcount >= 0 else 0


def insert_road_events(conn: psycopg.Connection, events: list[dict]) -> int:
    """Insert a batch of road events; duplicates no-op. Returns rows inserted.

    Caller owns the transaction: commit AFTER this returns, and only then
    acknowledge upstream (Kafka offsets) — commit-db-then-commit-offsets is
    the consumer's exactly-once-rows recipe.
    """
    return _insert_batch(conn, _ROAD_EVENT_SQL, ROAD_EVENT_COLUMNS, events)


def insert_crashes(conn: psycopg.Connection, crashes: list[dict]) -> int:
    """Insert crash rows; existing case_ids no-op. Returns rows inserted."""
    return _insert_batch(conn, _CRASH_SQL, CRASH_COLUMNS, crashes)


# --- alerts (feat/near-realtime-alerts) -----------------------------------------

ALERT_COLUMNS = (
    "alert_id", "kind", "category", "route_id", "segment_id", "headline",
    "detail", "lat", "lon", "measure_mi", "event_time", "source",
)

_ALERT_SQL = (
    f"insert into alerts ({', '.join(ALERT_COLUMNS)}) "
    f"values ({', '.join('%s' for _ in ALERT_COLUMNS)}) "
    "on conflict (alert_id) do nothing"
)


def insert_alerts(conn: psycopg.Connection, alerts: list[dict]) -> int:
    """Insert alert rows; existing alert_ids no-op. Returns rows inserted."""
    return _insert_batch(conn, _ALERT_SQL, ALERT_COLUMNS, alerts)


def load_alert_state(conn: psycopg.Connection) -> dict:
    """The alert producer's last-known state (key → value), for change detection."""
    with conn.cursor() as cur:
        cur.execute("select state_key, state_value from road_alert_state")
        return {key: value for key, value in cur.fetchall()}


def save_alert_state(conn: psycopg.Connection, state: dict) -> None:
    """Replace the state table with ``state``. Caller commits.

    A wholesale replace is fine at this volume (dozens of rows) and keeps the
    write trivially correct: whatever derive_alerts returns IS the new state,
    including the TTL-pruned incident keys. Caller commits after this returns.
    """
    with conn.cursor() as cur:
        cur.execute("delete from road_alert_state")
        if state:
            cur.executemany(
                "insert into road_alert_state (state_key, state_value) values (%s, %s)",
                list(state.items()),
            )
