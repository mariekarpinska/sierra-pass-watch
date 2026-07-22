"""Crash history for a journey: the API's only database access.

The dbt marts hold the crash record at per-mile-bin grain, one row per
(route, mile bin, weather regime): see warehouse/ and ADR-0007. A journey is a
request-time set of road stretches, each matched to its own forecast: the
committed journey index carries the mile-bin ranges the drive's own geometry
covers on each road (driven_bins) plus every on-road anchor town's mile
measure, and segment_legs labels each driven bin with its nearest anchor's
forecast regime. No mart can pre-answer "what happened on THESE stretches in
THIS weather"; instead this module composes the marts per request (ADR-0010):

  * the occupied bins inside each segment under that segment's regime
    (mart_crash_patterns, with each bin's most common cause joined on), and
  * the top recorded causes across all segments together, grouped over the
    per-crash mart (mart_crash_conditions) because per-bin top-3 lists cannot
    be summed into an honest journey-level ranking.

A road with no measure axis (a spur) keeps its whole corridor - over-including
is the safe direction for a crash record - under its anchor's regime, or the
journey's worst when it has none.

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
from datetime import date, datetime
from typing import Protocol

from fastapi import Request
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from api.config import Settings
from api.schemas import (
    CauseStat,
    CrashBin,
    CrashPatternsResponse,
    Incident,
    IncidentsResponse,
)

# The UI shows at most this many cause bars; the mart taxonomy has ~18 causes,
# so a cap keeps the panel readable rather than exhaustive.
TOP_CAUSES = 4

# The provisional-incidents panel shows at most this many recent collisions.
RECENT_INCIDENTS_LIMIT = 50

# Below this many matched crashes the record is context, not a pattern; the UI
# must say so. Same threshold the marts use for their per-bin small_sample flag.
SMALL_SAMPLE_THRESHOLD = 8


@dataclass(frozen=True)
class Leg:
    """One stretch of a travelled highway with the forecast regime to match
    there, in whole mile bins (driving any part of a mile includes its bin).
    None bounds mean the whole corridor matches (a road with no anchors)."""

    route_id: str
    lo_bin: int | None
    hi_bin: int | None
    regime: str


def segment_legs(
    via: list[str],
    driven: dict[str, list[tuple[int, int]]],
    anchors: dict[str, dict[str, float]],
    regimes: dict[str, str],
    fallback: str,
) -> list[Leg]:
    """Cut each travelled road into stretches, each matched to its own
    forecast. The drive's own geometry decides WHERE (``driven``: the mile-bin
    ranges the journey actually covers on the road, from the committed index);
    the anchor towns decide WHICH WEATHER (each driven bin takes the regime of
    its nearest anchor, so a range is split at the midpoints between anchors).
    Pure, so the cutting math is unit-testable without a database or forecast.

    ``regimes`` maps town slug -> that town's forecast regime; ``fallback`` is
    the journey's worst regime, used for a road with no anchors. A road with
    no driven ranges (a spur with no measure axis) keeps its whole corridor -
    over-including is the safe direction for a crash record. Stretches whose
    regime is UNKNOWN are dropped: there is no weather to match history
    against, and matching UNKNOWN-labelled crashes would present data gaps as
    a forecast. Adjacent same-regime stretches merge, so a uniform-forecast
    range stays one leg.
    """
    legs: list[Leg] = []
    for road in dict.fromkeys(via):
        marks = sorted(
            (mile, regimes[slug])
            for slug, mile in anchors.get(road, {}).items()
            if slug in regimes
        )
        # The road's regime intervals: cuts at anchor midpoints (whole bins,
        # so pieces can never overlap-count a bin); the outermost regimes
        # extend to the road's ends. No anchors -> one fallback interval.
        cuts = [int((marks[i][0] + marks[i + 1][0]) / 2) for i in range(len(marks) - 1)]
        interval_regimes = [regime for _, regime in marks] or [fallback]

        ranges = driven.get(road)
        if not ranges:
            # No measure axis for this road: the whole corridor, one label.
            regime = interval_regimes[0] if len(marks) == 1 else fallback
            if regime != "UNKNOWN":
                legs.append(Leg(road, None, None, regime))
            continue
        pieces: list[Leg] = []
        for lo, hi in ranges:
            start = lo
            for i, regime in enumerate(interval_regimes):
                end = min(cuts[i], hi) if i < len(cuts) else hi
                if end < start:  # interval ends before this range begins
                    continue
                if pieces and pieces[-1].regime == regime and pieces[-1].hi_bin == start - 1:
                    pieces[-1] = Leg(road, pieces[-1].lo_bin, end, regime)
                else:
                    pieces.append(Leg(road, start, end, regime))
                start = end + 1
                if start > hi:
                    break
        legs.extend(piece for piece in pieces if piece.regime != "UNKNOWN")
    return legs


@dataclass(frozen=True)
class BinRow:
    """One occupied (route, mile bin) under its stretch's matched regime."""

    route_id: str
    mile_bin: int
    regime: str
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


@dataclass(frozen=True)
class IncidentRow:
    """One live CHP collision on a tracked route (mart_incident_conditions)."""

    route_id: str
    mile_bin: int
    regime: str
    event_time: datetime
    lat: float
    lon: float


class CrashHistoryStore(Protocol):
    """The database seam. Tests inject a fake; production uses Postgres."""

    def bins(self, legs: list[Leg]) -> list[BinRow]: ...

    def causes(self, legs: list[Leg]) -> list[CauseRow]: ...

    def recent_incidents(self, route_ids: list[str]) -> list[IncidentRow]: ...


# Both queries scope each road stretch to its own regime with the same join:
# unnest() zips the four parallel arrays into an inline (route_id, lo, hi,
# regime) table - one query however many legs, all values parameterized (no
# SQL built per leg). A NULL lo means the leg has no bounds, so the whole
# corridor matches. Legs on one road never overlap (segment_legs cuts at
# whole bins), so no bin can be counted twice. The ::int[] casts are
# load-bearing: a journey whose every leg is whole-corridor binds all-NULL
# lo/hi arrays, leaving the driver no element to infer a type from
# (test_crash_store_integration pins this against real Postgres).
_LEGS_JOIN = """
    join unnest(
            %(route_ids)s::text[], %(lo_bins)s::int[], %(hi_bins)s::int[],
            %(regimes)s::text[]
        ) as leg(route_id, lo_bin, hi_bin, regime)
        on leg.route_id = {table}.route_id
        and leg.regime = {table}.weather_regime
        and (leg.lo_bin is null
             or {table}.mile_bin between leg.lo_bin and leg.hi_bin)
"""

# Occupied per-mile bins inside the journey's stretches, each under that
# stretch's regime and with its rank-1 cause for the map popup. LEFT JOIN so
# a bin never disappears if its causes row is missing (it cannot be, by
# construction in dbt, but a join should not be able to hide crashes).
_BINS_SQL = sql.SQL("""
    select
        patterns.route_id,
        patterns.mile_bin,
        patterns.weather_regime         as regime,
        patterns.bin_lat                as lat,
        patterns.bin_lon                as lon,
        patterns.crash_count,
        patterns.fatal_count,
        patterns.first_crash_date,
        patterns.last_crash_date,
        top_cause.cause                 as top_cause
    from {schema}.mart_crash_patterns as patterns
""" + _LEGS_JOIN.format(table="patterns") + """
    left join {schema}.mart_pattern_causes as top_cause
        on top_cause.route_id = patterns.route_id
        and top_cause.mile_bin = patterns.mile_bin
        and top_cause.weather_regime = patterns.weather_regime
        and top_cause.cause_rank = 1
    order by patterns.route_id, patterns.mile_bin
""")

# Top causes across every crash inside the journey's stretches, each under
# its stretch's regime. The 'mile_bin is not null' filter matches the
# aggregate marts: a crash with no per-mile position is not part of the
# per-mile story (ADR-0007). Ties break alphabetically so the same data
# always ranks the same way.
_CAUSES_SQL = sql.SQL("""
    select
        primary_factor                  as cause,
        count(*)                        as crash_count
    from {schema}.mart_crash_conditions as conditions
""" + _LEGS_JOIN.format(table="conditions") + """
    where conditions.mile_bin is not null
    group by primary_factor
    order by count(*) desc, primary_factor
    limit %(limit)s
""")


# Recent live collisions on the journey's roads, newest first. Scoped to the
# whole route (not the driven stretches): the provisional panel is a plain "what
# has been reported live on these roads lately", not the forecast-matched history
# the crash-patterns endpoint composes. Bounded to the last 90 days so the feed
# stays "recent" and an old provisional collision can't linger in it. All values
# parameterized.
_INCIDENTS_SQL = sql.SQL("""
    select
        route_id,
        mile_bin,
        weather_regime as regime,
        event_time,
        lat,
        lon
    from {schema}.mart_incident_conditions
    where route_id = any(%(route_ids)s)
      and event_time >= now() - interval '90 days'
    order by event_time desc
    limit %(limit)s
""")


def _leg_params(legs: list[Leg]) -> dict:
    """The four parallel arrays the legs join binds."""
    return {
        "route_ids": [leg.route_id for leg in legs],
        "lo_bins": [leg.lo_bin for leg in legs],
        "hi_bins": [leg.hi_bin for leg in legs],
        "regimes": [leg.regime for leg in legs],
    }


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

    def bins(self, legs: list[Leg]) -> list[BinRow]:
        rows = self._fetch_all(_BINS_SQL, _leg_params(legs))
        return [BinRow(**row) for row in rows]

    def causes(self, legs: list[Leg]) -> list[CauseRow]:
        rows = self._fetch_all(
            _CAUSES_SQL, {**_leg_params(legs), "limit": TOP_CAUSES}
        )
        return [CauseRow(**row) for row in rows]

    def recent_incidents(self, route_ids: list[str]) -> list[IncidentRow]:
        rows = self._fetch_all(
            _INCIDENTS_SQL, {"route_ids": route_ids, "limit": RECENT_INCIDENTS_LIMIT}
        )
        return [IncidentRow(**row) for row in rows]


def build_crash_patterns(
    route_ids: list[str],
    bins: list[BinRow],
    causes: list[CauseRow],
) -> CrashPatternsResponse:
    """Assemble the response from the two mart reads. Pure, so the math
    (totals, fatality share, cause percentages) is unit-testable without a
    database."""
    crash_count = sum(row.crash_count for row in bins)
    fatal_count = sum(row.fatal_count for row in bins)
    return CrashPatternsResponse(
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
                regime=row.regime,
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


def build_incidents(route_ids: list[str], rows: list[IncidentRow]) -> IncidentsResponse:
    """Assemble the provisional-incidents response. Pure. `provisional` is always
    true, a constant on the wire so the UI can never drop the label."""
    return IncidentsResponse(
        route_ids=route_ids,
        provisional=True,
        count=len(rows),
        incidents=[
            Incident(
                route_id=row.route_id,
                mile_bin=row.mile_bin,
                regime=row.regime,
                event_time=row.event_time.isoformat(),
                lat=row.lat,
                lon=row.lon,
            )
            for row in rows
        ],
    )


def get_crash_store(request: Request) -> CrashHistoryStore:
    """Dependency: the store created at startup (see main.create_app)."""
    return request.app.state.crash_store
