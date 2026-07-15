"""The journey index, loaded once at startup from shared/route-journeys.json
(built by pipeline/build_journeys.py from OSRM driving routes).

It answers one question: for a trip from town A to town B (which may cross
several highways), which of our weather anchors lie along the drive, in travel
order? The heavy work (routing) happened at build time; here it is a dictionary
lookup, so a request never calls OSRM.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from api.schemas import Waypoint


class TownPoint(BaseModel):
    """One town in the picker directory."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    lat: float
    lon: float
    # Feet at the town's coordinate, from the catalogue (None only for index
    # files from before elevations existed).
    elevation_ft: int | None = Field(default=None, alias="elevationFt")


class JourneyEntry(BaseModel):
    """One drive, ordered from the lexically-smaller town id: its anchor
    towns, the highways it follows (for the seasonal-pass warning), per
    highway each on-road stop's mile measure (build_journeys.leg_anchor_miles,
    what the weather labelling hangs off), and per highway the mile-bin
    ranges the drive's own geometry actually covers
    (build_journeys.driven_bins, what the crash record is scoped to). A road
    absent from `driven` has no measure axis (a spur); its crash record
    covers the whole corridor. Defaults to {} so older index files still
    load."""

    towns: list[str]
    routes: list[str]
    anchors: dict[str, dict[str, float]] = {}
    driven: dict[str, list[tuple[int, int]]] = {}
    miles: float
    minutes: int


class ResolvedJourney(BaseModel):
    """A journey resolved for a specific direction: the ordered stops as
    route-independent waypoints (a journey crosses highways, so no single route
    owns them), the highways travelled in order, their per-road anchor
    measures and driven mile-bin ranges, plus totals."""

    stops: list[Waypoint]
    via: list[str]
    anchors: dict[str, dict[str, float]]
    driven: dict[str, list[tuple[int, int]]]
    miles: float
    minutes: int

    def span_for(self, road: str) -> tuple[float, float] | None:
        """The [first, last] driven mile bin on a road, from the drive's own
        geometry. None when no driven range is known (a spur, or an index
        from before driven ranges existed)."""
        ranges = self.driven.get(road)
        if not ranges:
            return None
        return (float(ranges[0][0]), float(ranges[-1][1]))


class JourneyIndex(BaseModel):
    """All precomputed journeys plus the town directory the picker offers."""

    towns: dict[str, TownPoint]
    journeys: dict[str, JourneyEntry]

    @classmethod
    def load(cls, shared_dir: Path) -> "JourneyIndex":
        path = shared_dir / "route-journeys.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(towns=payload["towns"], journeys=payload["journeys"])

    def resolve(self, from_id: str, to_id: str) -> ResolvedJourney | None:
        """The stops from `from_id` to `to_id` in travel order, or None if either
        id is unknown or the pair was never built (the endpoint makes it a 404)."""
        lo, hi = sorted((from_id, to_id))
        entry = self.journeys.get(f"{lo}|{hi}")
        if entry is None:
            return None
        # Stored order runs from the smaller id; flip it when the trip does.
        # Deliberate simplification: OSRM is only asked for one direction, so
        # the reverse trip reuses the forward stops, miles and minutes. At
        # anchor-town granularity (2.5 mi buffer) a return drive lands on the
        # same anchors; see ADR-0009 for the trade-off.
        forward = from_id == lo
        slugs = entry.towns if forward else list(reversed(entry.towns))
        via = entry.routes if forward else list(reversed(entry.routes))
        stops = [
            Waypoint(
                id=slug,
                name=town.name,
                lat=town.lat,
                lon=town.lon,
                elevation_ft=town.elevation_ft,
            )
            for slug in slugs
            if (town := self.towns.get(slug)) is not None
        ]
        # Anchor measures and driven ranges live on each road's own mile axis,
        # so unlike the stop and road lists they read the same in either
        # direction of travel.
        return ResolvedJourney(
            stops=stops,
            via=via,
            anchors=entry.anchors,
            driven=entry.driven,
            miles=entry.miles,
            minutes=entry.minutes,
        )


def get_journey_index(request: Request) -> JourneyIndex:
    """Dependency: the index loaded at startup (see main.create_app)."""
    return request.app.state.journeys
