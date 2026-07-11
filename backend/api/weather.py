"""The forecast slice: Open-Meteo sampled along a journey, regime-labelled.

The classifier is not re-implemented here: the API imports ``pipeline.regime``
(the same module that labels live readings and the historical backfill), so the
label on a forecast hour and the label on a crash record come from literally the
same function. The golden contract (shared/weather-regime-cases.json) is still
asserted by this package's tests as well as the pipeline's: the file is the spec
either suite would catch a behaviour change against.

Outbound-call posture (SECURITY.md): the base URL is fixed configuration and the
query string is built from numeric coordinates, so no user-controlled string
ever reaches the request and there is no SSRF surface. The HTTP client carries a
hard timeout, and an upstream failure degrades that town to UNKNOWN rather than
failing the journey.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Protocol

import httpx
from fastapi import Request
from pydantic import BaseModel

from pipeline.regime import REGIMES, classify_conditions

from api.catalog import RouteCatalog, segments_for_route
from api.schemas import ForecastPoint, ForecastResponse, Segment, SegmentForecast

log = logging.getLogger(__name__)

_CM_TO_IN = 0.393701
_KMH_TO_MPH = 0.621371
_M_TO_MILES = 0.000621371

#: Hours of forecast to return. The strip shows a 6-hour window.
FORECAST_HOURS = 6

#: A forecast ages; five minutes matches the frontend's staleTime and keeps
#: repeat journeys from re-hitting Open-Meteo per render.
CACHE_TTL_SECONDS = 300


class HourlySample(BaseModel):
    """One forecast hour at one point, already in pipeline units."""

    time_utc: str
    temperature_c: float | None
    snowfall_rate_in_hr: float | None
    wind_gust_mph: float | None
    visibility_miles: float | None
    weather_code: int | None


class ForecastProvider(Protocol):
    """The seam the forecast service depends on. Tests substitute a fake here,
    exactly like the segments repository."""

    async def get_hourly(self, lat: float, lon: float) -> list[HourlySample]: ...


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
            time_utc=str(time_value),
            temperature_c=number("temperature_2m", i),
            snowfall_rate_in_hr=scaled("snowfall", i, _CM_TO_IN),
            wind_gust_mph=scaled("wind_gusts_10m", i, _KMH_TO_MPH),
            visibility_miles=scaled("visibility", i, _M_TO_MILES),
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
    """REGIMES is ordered worst-first, so "worst" is the minimum index."""
    if not regimes:
        return "UNKNOWN"
    return min(regimes, key=REGIMES.index)


class OpenMeteoForecastProvider:
    """Open-Meteo (keyless: the same upstream the pipeline polls). One GET per
    (lat, lon); units converted at the edge so nothing downstream converts,
    mirroring pipeline/sources/openmeteo.py."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get_hourly(self, lat: float, lon: float) -> list[HourlySample]:
        response = await self._client.get(
            "/v1/forecast",
            params={
                "latitude": round(lat, 4),
                "longitude": round(lon, 4),
                "hourly": "temperature_2m,snowfall,wind_gusts_10m,visibility,weather_code",
                "forecast_hours": FORECAST_HOURS,
                "wind_speed_unit": "kmh",
                "timezone": "UTC",
            },
        )
        response.raise_for_status()
        return parse_hourly(response.json())


class _TtlCache:
    """Tiny per-coordinate TTL cache. Two concurrent misses may both fetch, an
    accepted simplification: the point is bounding steady-state upstream
    traffic, not perfect deduplication."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[str, tuple[float, list[HourlySample]]] = {}

    def get(self, key: str) -> list[HourlySample] | None:
        entry = self._entries.get(key)
        if entry and time.monotonic() < entry[0]:
            return entry[1]
        return None

    def set(self, key: str, value: list[HourlySample]) -> None:
        self._entries[key] = (time.monotonic() + self._ttl, value)


class ForecastService:
    """Builds the /api/forecast response: resolves the journey span from the
    route catalogue, samples Open-Meteo at each town, and labels every hour with
    the shared regime classifier."""

    def __init__(self, catalog: RouteCatalog, provider: ForecastProvider) -> None:
        self._catalog = catalog
        self._provider = provider
        self._cache = _TtlCache(CACHE_TTL_SECONDS)

    async def get(
        self, route_id: str, from_segment_id: str, to_segment_id: str
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
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            segments=[await self._forecast_for(segment) for segment in span],
        )

    async def _forecast_for(self, segment: Segment) -> SegmentForecast:
        key = f"{segment.lat:.4f}:{segment.lon:.4f}"
        samples = self._cache.get(key)
        if samples is None:
            try:
                samples = await self._provider.get_hourly(segment.lat, segment.lon)
                self._cache.set(key, samples)  # failures are never cached
            except Exception as exc:  # noqa: BLE001 - degrade one town, not the journey
                log.warning("open-meteo fetch failed for %s: %s", segment.id, exc)
                samples = []

        points = [
            ForecastPoint(
                valid_time_utc=sample.time_utc,
                temperature_f=(
                    round(sample.temperature_c * 9 / 5 + 32, 1)
                    if sample.temperature_c is not None
                    else None
                ),
                wind_gust_mph=_round2(sample.wind_gust_mph),
                snowfall_rate_in_hr=_round2(sample.snowfall_rate_in_hr),
                visibility_miles=_round2(sample.visibility_miles),
                short_forecast=short_forecast(sample.weather_code),
                # Air temperature stands in for road-surface temperature in a
                # forecast (RWIS pavement sensors only exist for live readings).
                regime=classify_conditions(
                    snowfall_rate_in_hr=sample.snowfall_rate_in_hr,
                    visibility_miles=sample.visibility_miles,
                    wind_gust_mph=sample.wind_gust_mph,
                    surface_temp_c=sample.temperature_c,
                ),
            )
            for sample in samples
        ]

        return SegmentForecast(
            segment=segment,
            regime=worst_regime([p.regime for p in points]),
            points=points,
        )


def _round2(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def get_forecast_service(request: Request) -> ForecastService:
    """Dependency: the service built at startup (see main.create_app). Tests
    override this to inject a fake upstream provider.

    The `Request` annotation matters: it is what tells FastAPI to hand this
    function the request object rather than to expect a `?request=` query
    parameter."""
    return request.app.state.forecast_service
