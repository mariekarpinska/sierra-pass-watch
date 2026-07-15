"""Response models: the shape of the JSON the API returns.

Python code is snake_case; the JSON on the wire is camelCase (what the frontend's
TypeScript types expect). CamelModel does that translation in one place, so no
endpoint has to spell out an alias.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model that turns snake_case fields into camelCase JSON keys
    (`timestamp_utc` becomes `timestampUtc`)."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        # Also accept the snake_case name as input, so tests can build models
        # with pythonic names.
        populate_by_name=True,
    )


class Health(CamelModel):
    """Contract for GET /api/health, mirrored by the frontend."""

    status: str
    service: str
    timestamp_utc: str


class Town(CamelModel):
    """A forecast point / populated place along a route."""

    name: str
    lat: float
    lon: float


class Route(CamelModel):
    """One tracked Sierra Nevada road, from the shared catalogue."""

    id: str
    name: str
    road_no: str
    seasonal: bool
    note: str
    towns: list[Town]


class Waypoint(CamelModel):
    """A point where weather is sampled: a town or pass, with its coordinates.

    This is all a forecast needs — every WaypointForecast wraps a Waypoint. The
    id is the bare town slug (e.g. "donner-summit"), route-independent on
    purpose: a journey crosses highways, so no single route owns a stop. The
    crash-history branches work at a different grain entirely — per-mile bins
    along a route (ADR-0007) — and will bring their own route-scoped contract;
    the waypoint is only the weather point."""

    id: str
    name: str
    lat: float
    lon: float


class WaypointForecast(CamelModel):
    """Forecast for one town over the departure window (a fixed number of hours
    from the driver's start time). The values summarize that window: the worst
    regime, the temperature range, and the roughest wind/visibility/precip an
    hour in the window reaches, so the card can show conditions for the drive
    rather than for one instant. Any field is null when no hour supplied it."""

    waypoint: Waypoint
    regime: str
    temperature_high_f: float | None
    temperature_low_f: float | None
    wind_gust_mph: float | None
    visibility_miles: float | None
    precip_probability_pct: int | None
    short_forecast: str | None


class JourneyLeg(CamelModel):
    """One highway of a journey, with the catalogue's seasonal context so the
    UI can warn when a trip crosses a pass that closes for the winter."""

    id: str
    name: str
    seasonal: bool
    note: str
    # The [first, last] mile the drive covers on this road (the road's own
    # measure axis, ADR-0007), bounded by the journey's anchor towns at build
    # time. None when the build could not bound it (fewer than two anchors on
    # the road, or a spur with no polyline); the crash record then covers the
    # road's whole corridor.
    span: tuple[float, float] | None = None


class CauseStat(CamelModel):
    """One recorded cause and its share of the matched crashes. `cause` is the
    normalized CCRS taxonomy label from the warehouse (e.g. "Unsafe Speed")."""

    cause: str
    crash_count: int
    # Share of all matched crashes, 0-100, rounded to a whole number.
    pct: int


class CrashBin(CamelModel):
    """One occupied per-mile bin (ADR-0007): mile `mile_bin` of `route_id`,
    with what the record says happened there under the requested regime. The
    lat/lon is the mean crash location in the bin - a representative point for
    the map, not an exact crash site."""

    route_id: str
    mile_bin: int
    lat: float
    lon: float
    crash_count: int
    fatal_count: int
    # The bin's most common recorded cause (rank 1 of the top-3 mart).
    top_cause: str | None
    # ISO dates bounding this bin's record.
    first_crash_date: str
    last_crash_date: str


class CrashPatternsResponse(CamelModel):
    """GET /api/crash-patterns?from=&to=&regime=

    The crash record for a journey under one weather regime: journey-level
    totals, the occupied per-mile bins for the map, and the top recorded
    causes. Scoped to the mile span the drive covers on each highway (a leg
    with no span keeps its whole corridor). Historical and descriptive only -
    counts, dates and causes, never a judgement (test_forbidden_keys.py holds
    the line).
    """

    regime: str
    route_ids: list[str]
    crash_count: int
    fatal_count: int
    # 0-100, one decimal. None when crash_count is 0 (no share of nothing).
    pct_fatal: float | None
    # True below the same <8 threshold the marts flag; the UI must present the
    # record as context, not a pattern (ADR-0007).
    small_sample: bool
    # ISO dates bounding the whole matched record, null when it is empty.
    first_crash_date: str | None
    last_crash_date: str | None
    bins: list[CrashBin]
    top_causes: list[CauseStat]


class JourneyResponse(CamelModel):
    """GET /api/journey?from=&to=&departure=

    A multi-highway trip: the anchor towns along the drive (OSRM-routed at build
    time), each with the same departure-window summary as a single-route stop,
    plus the highways travelled (`via`), in order.
    """

    from_id: str
    to_id: str
    via: list[JourneyLeg]
    departure_utc: str
    generated_at_utc: str
    total_miles: float
    total_minutes: int
    stops: list[WaypointForecast]
