"""Crash history for a journey: the API's only database access.

The dbt marts hold the crash record at per-mile-bin grain, one row per
(route, mile bin, weather regime): see warehouse/ and ADR-0007. A journey is a
request-time set of highways, so no mart can pre-answer "what happened on THESE
roads in THIS weather"; instead this module composes the marts per request
(ADR-0010):

  * the occupied bins on the journey's routes under the given regime
    (mart_crash_patterns, with each bin's most common cause joined on), and
  * the top recorded causes across all those roads together, grouped over the
    per-crash mart (mart_crash_conditions) because per-bin top-3 lists cannot
    be summed into an honest journey-level ranking.

Reads use psycopg's SYNCHRONOUS pool on purpose, with the endpoint declared
`def` so FastAPI runs it on its worker threadpool instead of the event loop.
Async psycopg refuses Windows' default (Proactor) event loop, so the async
driver would not run on a Windows dev machine at all, and these are two tiny
indexed reads, so a thread is cheap and nothing here can block the loop.

The pool opens lazily: it first connects when the first crash request arrives,
so the app (and its test suite) starts fine with no database, and only this
endpoint depends on one. All SQL is parameterized; the schema name is spliced
as an identifier from Settings, never from request input.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from fastapi import Request
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from api.config import Settings
from api.schemas import CauseStat, CrashBin, CrashPatternsResponse

# The UI shows at most this many cause bars; the mart taxonomy has ~18 causes,
# so a cap keeps the panel readable rather than exhaustive.
TOP_CAUSES = 4

# Below this many matched crashes the record is context, not a pattern; the UI
# must say so. Same threshold the marts use for their per-bin small_sample flag.
SMALL_SAMPLE_THRESHOLD = 8


@dataclass(frozen=True)
class BinRow:
    """One occupied (route, mile bin) under the requested regime."""

    route_id: str
    mile_bin: int
    lat: float
    lon: float
    crash_count: int
    fatal_count: int
    top_cause: str | None
    first_crash_date: date
    last_crash_date: date


@dataclass(frozen=True)
class CauseRow:
    """One recorded cause with its crash count across the whole journey."""

    cause: str
    crash_count: int


class CrashHistoryStore(Protocol):
    """The database seam. Tests inject a fake; production uses Postgres."""

    def bins(self, route_ids: list[str], regime: str) -> list[BinRow]: ...

    def causes(self, route_ids: list[str], regime: str) -> list[CauseRow]: ...


# Occupied per-mile bins on the requested routes under the requested regime,
# each with its rank-1 cause for the map popup. LEFT JOIN so a bin never
# disappears if its causes row is missing (it cannot be, by construction in
# dbt, but a join should not be able to hide crashes).
_BINS_SQL = sql.SQL("""
    select
        patterns.route_id,
        patterns.mile_bin,
        patterns.bin_lat                as lat,
        patterns.bin_lon                as lon,
        patterns.crash_count,
        patterns.fatal_count,
        patterns.first_crash_date,
        patterns.last_crash_date,
        top_cause.cause                 as top_cause
    from {schema}.mart_crash_patterns as patterns
    left join {schema}.mart_pattern_causes as top_cause
        on top_cause.route_id = patterns.route_id
        and top_cause.mile_bin = patterns.mile_bin
        and top_cause.weather_regime = patterns.weather_regime
        and top_cause.cause_rank = 1
    where patterns.route_id = any(%(route_ids)s)
        and patterns.weather_regime = %(regime)s
    order by patterns.route_id, patterns.mile_bin
""")

# Top causes across every crash on the journey's routes under this regime. The
# 'mile_bin is not null' filter matches the aggregate marts: a crash with no
# per-mile position is not part of the per-mile story (ADR-0007). Ties break
# alphabetically so the same data always ranks the same way.
_CAUSES_SQL = sql.SQL("""
    select
        primary_factor                  as cause,
        count(*)                        as crash_count
    from {schema}.mart_crash_conditions
    where route_id = any(%(route_ids)s)
        and weather_regime = %(regime)s
        and mile_bin is not null
    group by primary_factor
    order by count(*) desc, primary_factor
    limit %(limit)s
""")


class PostgresCrashHistoryStore:
    """Reads the crash marts through a small connection pool.

    The pool is created closed (no I/O in the constructor) and opened on the
    first query, guarded by a lock so concurrent first requests open it once.
    """

    def __init__(self, settings: Settings) -> None:
        self._schema = sql.Identifier(settings.warehouse_schema)
        # min_size=1 keeps one warm connection once opened; max_size=4 is
        # plenty for a read-only endpoint at this traffic. timeout is how long
        # a request waits for a connection before failing (the generic 500).
        self._pool = ConnectionPool(
            settings.postgres_dsn, min_size=1, max_size=4, timeout=5, open=False
        )
        self._opened = False
        self._open_lock = threading.Lock()

    def _ensure_open(self) -> None:
        if self._opened:
            return
        with self._open_lock:
            if not self._opened:
                self._pool.open()
                self._opened = True

    def close(self) -> None:
        self._pool.close()

    def _fetch_all(self, query: sql.SQL, params: dict) -> list[dict]:
        self._ensure_open()
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query.format(schema=self._schema), params)
                return cur.fetchall()

    def bins(self, route_ids: list[str], regime: str) -> list[BinRow]:
        rows = self._fetch_all(_BINS_SQL, {"route_ids": route_ids, "regime": regime})
        return [BinRow(**row) for row in rows]

    def causes(self, route_ids: list[str], regime: str) -> list[CauseRow]:
        rows = self._fetch_all(
            _CAUSES_SQL,
            {"route_ids": route_ids, "regime": regime, "limit": TOP_CAUSES},
        )
        return [CauseRow(**row) for row in rows]


def build_crash_patterns(
    route_ids: list[str],
    regime: str,
    bins: list[BinRow],
    causes: list[CauseRow],
) -> CrashPatternsResponse:
    """Assemble the response from the two mart reads. Pure, so the math
    (totals, fatality share, cause percentages) is unit-testable without a
    database."""
    crash_count = sum(row.crash_count for row in bins)
    fatal_count = sum(row.fatal_count for row in bins)
    return CrashPatternsResponse(
        regime=regime,
        route_ids=route_ids,
        crash_count=crash_count,
        fatal_count=fatal_count,
        # None, not 0, when there is nothing to divide: "no crashes" has no
        # fatality share and the UI should not print one.
        pct_fatal=(
            round(100.0 * fatal_count / crash_count, 1) if crash_count else None
        ),
        small_sample=crash_count < SMALL_SAMPLE_THRESHOLD,
        first_crash_date=(
            min(row.first_crash_date for row in bins).isoformat() if bins else None
        ),
        last_crash_date=(
            max(row.last_crash_date for row in bins).isoformat() if bins else None
        ),
        bins=[
            CrashBin(
                route_id=row.route_id,
                mile_bin=row.mile_bin,
                lat=row.lat,
                lon=row.lon,
                crash_count=row.crash_count,
                fatal_count=row.fatal_count,
                top_cause=row.top_cause,
                first_crash_date=row.first_crash_date.isoformat(),
                last_crash_date=row.last_crash_date.isoformat(),
            )
            for row in bins
        ],
        top_causes=[
            CauseStat(
                cause=row.cause,
                crash_count=row.crash_count,
                pct=round(100.0 * row.crash_count / crash_count),
            )
            for row in causes
        ],
    )


def get_crash_store(request: Request) -> CrashHistoryStore:
    """Dependency: the store created at startup (see main.create_app)."""
    return request.app.state.crash_store
