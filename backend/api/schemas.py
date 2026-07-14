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


class Segment(CamelModel):
    """An anchor waypoint: a town/pass where weather is sampled.

    Two id forms share this shape. /api/segments serves route-scoped anchors:
    id is "{routeId}:{town-slug}" (e.g. "I-80:donner-summit") with a real
    route_id. /api/towns and journey stops are route-independent: id is the
    bare town slug (e.g. "donner-summit") and route_id is blank, because a
    journey crosses highways. Joining a journey stop to per-route data means
    matching on the slug half of the segment id. Crashes are located by
    per-mile bin (ADR-0007); the anchor is only the weather point."""

    id: str
    route_id: str
    name: str
    lat: float
    lon: float


class SegmentForecast(CamelModel):
    """Forecast for one town over the departure window (a fixed number of hours
    from the driver's start time). The values summarize that window: the worst
    regime, the temperature range, and the roughest wind/visibility/precip an
    hour in the window reaches, so the card can show conditions for the drive
    rather than for one instant. Any field is null when no hour supplied it."""

    segment: Segment
    regime: str
    temperature_high_f: float | None
    temperature_low_f: float | None
    wind_gust_mph: float | None
    visibility_miles: float | None
    precip_probability_pct: int | None
    short_forecast: str | None


class ForecastResponse(CamelModel):
    """GET /api/forecast?route=&from=&to=&departure="""

    route_id: str
    from_segment_id: str
    to_segment_id: str
    departure_utc: str
    generated_at_utc: str
    segments: list[SegmentForecast]


class JourneyLeg(CamelModel):
    """One highway of a journey, with the catalogue's seasonal context so the
    UI can warn when a trip crosses a pass that closes for the winter."""

    id: str
    name: str
    seasonal: bool
    note: str


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
    stops: list[SegmentForecast]
