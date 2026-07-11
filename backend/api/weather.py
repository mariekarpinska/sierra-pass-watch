"""The forecast slice: Open-Meteo sampled at each town over the departure
window, summarized into the shape the weather card shows.

A driver picks a departure time, and each town card shows the conditions for a
fixed window (WINDOW_HOURS) from that time, not for one instant: morning and
evening on a pass are different drives. So the service fetches Open-Meteo hourly
data for that window and reduces it per town to a worst-regime label plus a
temperature range and the roughest wind/visibility/precip any hour reaches.

The regime label is not re-implemented here: the API imports ``pipeline.regime``
(the same module that labels live readings and the historical backfill), so the
label on a forecast hour and the label on a crash record come from literally the
same function. shared/weather-regime-cases.json is asserted by this package's
tests as well as the pipeline's.

Outbound-call posture (SECURITY.md): the base URL is fixed configuration and the
query is built from numeric coordinates and a validated time window, so no
user-controlled string reaches the request and there is no SSRF surface. The
HTTP client carries a hard timeout, and an upstream failure degrades that town
to UNKNOWN rather than failing the journey.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Protocol

import httpx
from fastapi import Request
from pydantic import BaseModel

from pipeline.regime import REGIMES, classify_conditions

# One set of conversion factors for both paths: the classifier's thresholds
# (in/hr, mph, mi) must be fed identically-scaled numbers by the forecast and
# by the pipeline's readings, or the same weather gets two different labels.
from pipeline.sources.openmeteo import CM_TO_IN, KMH_TO_MPH, M_TO_MILES

from api.catalog import RouteCatalog, segments_for_route
from api.schemas import ForecastResponse, Segment, SegmentForecast

log = logging.getLogger(__name__)

#: Hours of forecast to summarize, counting from the departure's hour block —
#: a 15:59 departure includes the 15:00 hour on purpose, since the driver is on
#: the road during it. Six hours covers a Sierra corridor drive with room to
#: spare.
WINDOW_HOURS = 6

#: A forecast ages; five minutes matches the frontend's staleTime and keeps
#: repeat journeys from re-hitting Open-Meteo per render.
CACHE_TTL_SECONDS = 300


class HourlySample(BaseModel):
    """One forecast hour at one point, already in pipeline units."""

    time_utc: str
    temperature_c: float | None
    surface_temp_c: float | None
    snowfall_rate_in_hr: float | None
    wind_gust_mph: float | None
    visibility_miles: float | None
    precip_probability_pct: float | None
    weather_code: int | None


class ForecastProvider(Protocol):
    """The seam the forecast service depends on. Tests substitute a fake here,
    exactly like the segments repository. start_hour and end_hour are inclusive
    Open-Meteo hour stamps ("YYYY-MM-DDTHH:MM", UTC)."""

    async def get_hourly(
        self, lat: float, lon: float, start_hour: str, end_hour: str
    ) -> list[HourlySample]: ...


def _utc_stamp(value: object) -> str:
    """Open-Meteo returns naive hour stamps (we request timezone=UTC); make the
    zone explicit so the string can never be misread as local time — JavaScript,
    for one, parses an offset-less ISO string as local."""
    return datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc).isoformat()


def parse_hourly(payload: dict) -> list[HourlySample]:
    """Pure payload to samples parsing, unit-tested without a network."""
    hourly = payload.get("hourly", {})
    times = hourly.get("time") or []

    def number(field: str, index: int) -> float | None:
        values = hourly.get(field) or []
        value = values[index] if index < len(values) else None
        return float(value) if isinstance(value, (int, float)) else None

    def scaled(field: str, index: int, factor: float) -> float | None:
        value = number(field, index)
        return None if value is None else value * factor

    return [
        HourlySample(
            time_utc=_utc_stamp(time_value),
            temperature_c=number("temperature_2m", i),
            surface_temp_c=number("surface_temperature", i),
            snowfall_rate_in_hr=scaled("snowfall", i, CM_TO_IN),
            wind_gust_mph=scaled("wind_gusts_10m", i, KMH_TO_MPH),
            visibility_miles=scaled("visibility", i, M_TO_MILES),
            precip_probability_pct=number("precipitation_probability", i),
            weather_code=(int(code) if (code := number("weather_code", i)) is not None else None),
        )
        for i, time_value in enumerate(times)
    ]


# WMO weather code to the short display text the contract calls shortForecast.
# Descriptive vocabulary only, never a judgment.
_WMO_TEXT: dict[int, str] = (
    {0: "Clear", 3: "Overcast"}
    | {code: "Partly Cloudy" for code in (1, 2)}
    | {code: "Fog" for code in (45, 48)}
    | {code: "Drizzle" for code in (51, 53, 55, 56, 57)}
    | {code: "Rain" for code in (61, 63, 80, 81)}
    | {code: "Heavy Rain" for code in (65, 82)}
    | {code: "Freezing Rain" for code in (66, 67)}
    | {code: "Snow" for code in (71, 73, 77, 85)}
    | {code: "Heavy Snow" for code in (75, 86)}
    | {code: "Thunderstorm" for code in (95, 96, 99)}
)


def short_forecast(weather_code: int | None) -> str | None:
    if weather_code is None:
        return None
    return _WMO_TEXT.get(weather_code, "Mixed Conditions")


def worst_regime(regimes: list[str]) -> str:
    """REGIMES is ordered worst-first, so "worst" is the minimum index — with
    one exception. UNKNOWN sits last in the ordering because it is not a
    weather severity, and ranking it least severe would let a single readable
    hour badge a mostly data-void window as affirmatively clear. So when
    UNKNOWN holds the majority of the window, the summary says UNKNOWN."""
    if not regimes:
        return "UNKNOWN"
    if regimes.count("UNKNOWN") * 2 > len(regimes):
        return "UNKNOWN"
    return min(regimes, key=REGIMES.index)


def _hour_stamp(dt: datetime) -> str:
    """Open-Meteo's start_hour/end_hour format (minute precision, UTC)."""
    return dt.strftime("%Y-%m-%dT%H:%M")


def parse_departure(value: str) -> datetime:
    """Parse the client's departure time into an aware UTC datetime. Accepts a
    trailing "Z" or an offset; a value with no zone is read as UTC. Raises
    ValueError on anything unparseable (the endpoint turns that into a 400)."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class OpenMeteoForecastProvider:
    """Open-Meteo (keyless: the same upstream the pipeline polls). One GET per
    (lat, lon, window); units converted at the edge so nothing downstream
    converts, mirroring pipeline/sources/openmeteo.py."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get_hourly(
        self, lat: float, lon: float, start_hour: str, end_hour: str
    ) -> list[HourlySample]:
        response = await self._client.get(
            "/v1/forecast",
            params={
                "latitude": round(lat, 4),
                "longitude": round(lon, 4),
                "hourly": (
                    "temperature_2m,surface_temperature,snowfall,wind_gusts_10m,"
                    "visibility,weather_code,precipitation_probability"
                ),
                "start_hour": start_hour,
                "end_hour": end_hour,
                "wind_speed_unit": "kmh",
                "timezone": "UTC",
            },
        )
        response.raise_for_status()
        return parse_hourly(response.json())


class _TtlCache:
    """Tiny per-key TTL cache. Two concurrent misses may both fetch, an accepted
    simplification: the point is bounding steady-state upstream traffic, not
    perfect deduplication."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[str, tuple[float, list[HourlySample]]] = {}

    def get(self, key: str) -> list[HourlySample] | None:
        # Look up the key, and return its samples only if the entry exists and
        # has not expired (now is still before the stored expiry time, entry[0]).
        entry = self._entries.get(key)
        if entry and time.monotonic() < entry[0]:
            return entry[1]
        return None

    def set(self, key: str, value: list[HourlySample]) -> None:
        # Store (or replace) the samples under the key, paired with the time
        # they expire: now plus the cache's ttl.
        self._entries[key] = (time.monotonic() + self._ttl, value)


def _regime_for(sample: HourlySample) -> str:
    # Surface (pavement) temperature, the same signal the live RWIS readings and
    # the archive backfill feed the classifier: its -4 °C black-ice threshold is
    # pavement-calibrated, and air temperature can sit degrees away (a sunny
    # subfreezing morning would otherwise read ICE_FREEZING here and CLEAR_DRY
    # on the live path). Air temperature stays on the sample for display.
    return classify_conditions(
        snowfall_rate_in_hr=sample.snowfall_rate_in_hr,
        visibility_miles=sample.visibility_miles,
        wind_gust_mph=sample.wind_gust_mph,
        surface_temp_c=sample.surface_temp_c,
    )


def _max(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


def _min(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return min(present) if present else None


def _round1(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def _round2(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


class ForecastService:
    """Builds the /api/forecast response: resolves the journey span from the
    route catalogue, samples Open-Meteo at each town over the departure window,
    and reduces each town's hours to one card-shaped summary."""

    def __init__(self, catalog: RouteCatalog, provider: ForecastProvider) -> None:
        self._catalog = catalog
        self._provider = provider
        self._cache = _TtlCache(CACHE_TTL_SECONDS)

    async def get(
        self,
        route_id: str,
        from_segment_id: str,
        to_segment_id: str,
        departure: datetime,
    ) -> ForecastResponse | None:
        """None means unknown route or segment (the endpoint turns it into a 404)."""
        route = next((r for r in self._catalog.routes if r.id == route_id), None)
        if route is None:
            return None

        segments = segments_for_route(route)
        ids = [s.id for s in segments]
        if from_segment_id not in ids or to_segment_id not in ids:
            return None
        from_index, to_index = ids.index(from_segment_id), ids.index(to_segment_id)

        # Journeys run either way along the road; slice the town list
        # accordingly and keep travel order.
        lo, hi = sorted((from_index, to_index))
        span = segments[lo : hi + 1]
        if from_index > to_index:
            span = list(reversed(span))

        return ForecastResponse(
            route_id=route.id,
            from_segment_id=from_segment_id,
            to_segment_id=to_segment_id,
            departure_utc=departure.isoformat(),
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            segments=await self.forecast_towns(span, departure),
        )

    async def forecast_towns(
        self, towns: list[Segment], departure: datetime
    ) -> list[SegmentForecast]:
        """Each town's departure-window summary. Shared by the single-route
        forecast and the multi-highway journey, so both label conditions the
        same way. Inclusive hour stamps: WINDOW_HOURS hours starting at the
        departure hour (departure plus five more when WINDOW_HOURS is 6).

        The per-town fetches are independent, so they run concurrently:
        serializing them stacks upstream latency per town — and when Open-Meteo
        hangs, stacks its 10 s timeouts past the frontend's own request
        timeout. _forecast_for never raises (a failed town degrades to
        UNKNOWN), so gather cannot blow up the response."""
        start_hour = _hour_stamp(departure)
        end_hour = _hour_stamp(departure + timedelta(hours=WINDOW_HOURS - 1))
        return list(
            await asyncio.gather(
                *(self._forecast_for(town, start_hour, end_hour) for town in towns)
            )
        )

    async def _forecast_for(
        self, segment: Segment, start_hour: str, end_hour: str
    ) -> SegmentForecast:
        key = f"{segment.lat:.4f}:{segment.lon:.4f}:{start_hour}"
        samples = self._cache.get(key)
        if samples is None:
            try:
                samples = await self._provider.get_hourly(
                    segment.lat, segment.lon, start_hour, end_hour
                )
                # Neither failures nor empty payloads are cached: a transient
                # 200 with no usable hours must not pin the town to UNKNOWN
                # for the whole TTL — the next request should retry upstream.
                if samples:
                    self._cache.set(key, samples)
            except Exception as exc:  # noqa: BLE001 - degrade one town, not the journey
                log.warning("open-meteo fetch failed for %s: %s", segment.id, exc)
                samples = []

        temps_f = [
            None if s.temperature_c is None else s.temperature_c * 9 / 5 + 32 for s in samples
        ]
        regimes = [_regime_for(s) for s in samples]
        worst = worst_regime(regimes)
        # Short text for the worst hour, so the card's words match its label.
        worst_code = next(
            (s.weather_code for s, r in zip(samples, regimes) if r == worst), None
        )

        return SegmentForecast(
            segment=segment,
            regime=worst,
            temperature_high_f=_round1(_max(temps_f)),
            temperature_low_f=_round1(_min(temps_f)),
            wind_gust_mph=_round2(_max([s.wind_gust_mph for s in samples])),
            visibility_miles=_round2(_min([s.visibility_miles for s in samples])),
            precip_probability_pct=(
                None
                if (p := _max([s.precip_probability_pct for s in samples])) is None
                else round(p)
            ),
            short_forecast=short_forecast(worst_code),
        )


def get_forecast_service(request: Request) -> ForecastService:
    """Dependency: the service built at startup (see main.create_app). Tests
    override this to inject a fake upstream provider.

    The `Request` annotation matters: it is what tells FastAPI to hand this
    function the request object rather than to expect a `?request=` query
    parameter."""
    return request.app.state.forecast_service
