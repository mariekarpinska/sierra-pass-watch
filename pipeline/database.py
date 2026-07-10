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


def insert_road_events(conn: psycopg.Connection, events: list[dict]) -> int:
    """Insert a batch of road events; duplicates no-op. Returns rows inserted.

    Caller owns the transaction: commit AFTER this returns, and only then
    acknowledge upstream (Kafka offsets) — commit-db-then-commit-offsets is
    the consumer's exactly-once-rows recipe.
    """
    if not events:
        return 0
    rows = [tuple(e.get(c) for c in ROAD_EVENT_COLUMNS) for e in events]
    with conn.cursor() as cur:
        cur.executemany(_ROAD_EVENT_SQL, rows)
        return cur.rowcount if cur.rowcount >= 0 else 0


def insert_crashes(conn: psycopg.Connection, crashes: list[dict]) -> int:
    """Insert crash rows; existing case_ids no-op. Returns rows inserted."""
    if not crashes:
        return 0
    rows = [tuple(c.get(col) for col in CRASH_COLUMNS) for c in crashes]
    with conn.cursor() as cur:
        cur.executemany(_CRASH_SQL, rows)
        return cur.rowcount if cur.rowcount >= 0 else 0
