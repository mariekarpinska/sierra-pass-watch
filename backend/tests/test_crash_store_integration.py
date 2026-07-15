"""The store's SQL against a real Postgres (Docker via Testcontainers).

The unit suite fakes the store, and the live checks during development ran
mixed leg arrays - so one bind was never exercised anywhere: a journey whose
EVERY leg is whole-corridor puts all-None lo/hi arrays through the unnest
join, leaving psycopg no non-null element to infer an array type from; the
explicit ::int[] casts in _LEGS_JOIN are what resolve it server-side. This
test pins that degenerate bind (and the ordinary bounded one) against the
real driver and database, so a cast removed in a refactor fails here, not in
production. Skips itself when Docker is unavailable, like the pipeline's
consumer idempotency test.
"""
from __future__ import annotations

from datetime import date

import pytest

from api.config import Settings
from api.crashes import Leg, PostgresCrashHistoryStore

# The minimal slice of the dbt marts the store queries (warehouse/models/
# marts define the real ones; dbt's own tests guard those shapes).
_SCHEMA = """
create schema analytics;
create table analytics.mart_crash_patterns (
    route_id text, mile_bin int, weather_regime text,
    bin_lat float, bin_lon float, crash_count int, fatal_count int,
    first_crash_date date, last_crash_date date
);
create table analytics.mart_pattern_causes (
    route_id text, mile_bin int, weather_regime text, cause_rank int, cause text
);
create table analytics.mart_crash_conditions (
    route_id text, mile_bin int, weather_regime text, primary_factor text
);
insert into analytics.mart_crash_patterns values
    ('I-80', 12, 'SNOW',      39.31, -120.32, 9, 1, '2017-01-03', '2025-12-20'),
    ('I-80', 44, 'CLEAR_DRY', 39.32, -120.30, 2, 0, '2019-02-01', '2021-11-05'),
    ('US-50', 58, 'SNOW',     38.81, -120.03, 5, 0, '2016-06-09', '2024-03-14');
insert into analytics.mart_pattern_causes values
    ('I-80', 12, 'SNOW', 1, 'Unsafe Speed');
insert into analytics.mart_crash_conditions
select route_id, mile_bin, weather_regime, 'Unsafe Speed'
from analytics.mart_crash_patterns, generate_series(1, crash_count);
"""


@pytest.mark.integration
class TestStoreAgainstRealPostgres:
    def test_all_whole_corridor_legs_bind_and_match(self) -> None:
        docker = pytest.importorskip("testcontainers.postgres")
        import psycopg

        try:
            container = docker.PostgresContainer("postgres:17-alpine")
            container.start()
        except Exception as exc:  # noqa: BLE001 - no Docker -> skip, don't fail
            pytest.skip(f"Docker unavailable: {exc}")
        try:
            url = container.get_connection_url().replace("+psycopg2", "")
            with psycopg.connect(url) as conn:
                conn.execute(_SCHEMA)
                conn.commit()
            store = PostgresCrashHistoryStore(Settings(database_url=url))
            try:
                # The degenerate bind: every leg unbounded, so lo/hi are
                # all-NULL int arrays with no element to infer a type from.
                legs = [
                    Leg("I-80", None, None, "SNOW"),
                    Leg("US-50", None, None, "SNOW"),
                ]
                bins = store.bins(legs)
                assert [(b.route_id, b.mile_bin) for b in bins] == [
                    ("I-80", 12),
                    ("US-50", 58),
                ]
                assert bins[0].top_cause == "Unsafe Speed"
                assert bins[0].first_crash_date == date(2017, 1, 3)
                causes = store.causes(legs)
                assert [(c.cause, c.crash_count) for c in causes] == [
                    ("Unsafe Speed", 14)
                ]

                # And the ordinary bounded bind alongside it, for parity: a
                # span that excludes I-80's snow bin keeps only US-50's.
                bounded = [
                    Leg("I-80", 40, 50, "SNOW"),
                    Leg("US-50", None, None, "SNOW"),
                ]
                assert [(b.route_id, b.mile_bin) for b in store.bins(bounded)] == [
                    ("US-50", 58)
                ]
            finally:
                store.close()
        finally:
            container.stop()
