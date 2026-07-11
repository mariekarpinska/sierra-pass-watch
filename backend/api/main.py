"""Sierra Safe API: builds the FastAPI app.

Endpoints match the frontend contract (frontend/src/api/types.ts) field for
field. Live now: /api/health, /api/routes, /api/segments, /api/forecast. Later
branches add crash-patterns, hotspots and the alerts feed.

Run locally (the Vite dev server proxies /api here):

    uvicorn api.main:app --port 5080 --no-server-header

--no-server-header hides the server name from responses.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.catalog import RouteCatalog, get_catalog
from api.config import Settings
from api.db import create_pool
from api.journeys import JourneyIndex, get_journey_index
from api.middleware import CorrelationIdFilter, CorrelationIdMiddleware
from api.schemas import ForecastResponse, Health, JourneyResponse, Route, Segment
from api.segments import SegmentRepository, get_segment_repository
from api.weather import (
    ForecastService,
    OpenMeteoForecastProvider,
    get_forecast_service,
    parse_departure,
)

log = logging.getLogger(__name__)

# Add the correlation-id filter to the root logger once, at import, so every log
# record carries the request's id (middleware.py). Done here, not inside
# create_app, so building several apps (as the tests do) does not stack a new
# filter each time.
logging.getLogger().addFilter(CorrelationIdFilter())


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Using a factory (not a module-level app) lets each test
    build its own isolated instance and pass its own Settings."""
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: load the catalogue once and create the pool (lazy, so no
        # database connection is made until the first query).
        app.state.catalog = RouteCatalog.load(settings.shared_dir)
        app.state.journeys = JourneyIndex.load(settings.shared_dir)
        app.state.pool = create_pool(settings.database_url)
        # One HTTP client for Open-Meteo: fixed base URL plus a hard timeout, so
        # the SSRF and timeout guards live here, not at each call site. The
        # service holds the 5-minute per-coordinate cache for the process life.
        app.state.open_meteo_client = httpx.AsyncClient(
            base_url=settings.open_meteo_base_url, timeout=10.0
        )
        app.state.forecast_service = ForecastService(
            catalog=app.state.catalog,
            provider=OpenMeteoForecastProvider(app.state.open_meteo_client),
        )
        try:
            await app.state.pool.open()
            yield
        finally:
            # Close on normal shutdown, and also if open() failed at startup, so
            # a failed start never leaks the pool or the HTTP client.
            await app.state.open_meteo_client.aclose()
            await app.state.pool.close()

    app = FastAPI(title="Sierra Safe API", version="0.1.0", lifespan=lifespan)

    # Every request flows through this to get a correlation id.
    app.add_middleware(CorrelationIdMiddleware)

    # Only add CORS if origins are configured; the default same-origin setup
    # needs none (see config.py). Even when enabled: an explicit origin
    # allowlist, GET only, and only the one header the client sends. No
    # credentials.
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_methods=["GET"],
            allow_headers=["X-Correlation-Id"],
        )

    # Any unhandled error becomes a generic JSON 500. The traceback goes to the
    # server log (tagged with the correlation id), never to the client.
    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

    @app.get("/api/health", response_model=Health)
    def health() -> Health:
        return Health(
            status="healthy",
            service="backend",
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
        )

    # The full route catalogue, served from memory.
    @app.get("/api/routes", response_model=list[Route])
    def routes(catalog: RouteCatalog = Depends(get_catalog)) -> list[Route]:
        return catalog.routes

    # Anchor waypoints from the dbt seed, optionally for one route. An unknown
    # route returns an empty list, not a 404.
    @app.get("/api/segments", response_model=list[Segment])
    async def segments(
        route: str | None = None,
        repository: SegmentRepository = Depends(get_segment_repository),
    ) -> list[Segment]:
        return await repository.get(route)

    # Live forecast along a journey span: Open-Meteo sampled at each town from
    # `from` to `to` (either direction) over a fixed window starting at
    # `departure` (an ISO time), each town's hours reduced to one card summary.
    # Missing/invalid params are the client's error (400); unknown ids are a 404.
    @app.get("/api/forecast", response_model=ForecastResponse)
    async def forecast(
        route: str | None = None,
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = None,
        departure: str | None = None,
        service: ForecastService = Depends(get_forecast_service),
    ):
        if not route or not from_ or not to or not departure:
            return JSONResponse(
                status_code=400,
                content={"error": "route, from, to and departure are required"},
            )
        try:
            departure_at = parse_departure(departure)
        except ValueError:
            return JSONResponse(
                status_code=400, content={"error": "departure must be an ISO 8601 time"}
            )
        response = await service.get(route, from_, to, departure_at)
        if response is None:
            return JSONResponse(
                status_code=404, content={"error": "unknown route or segment"}
            )
        return response

    # The towns the journey picker offers, from the in-memory index (no DB).
    # These are route-independent points, so route_id is blank.
    @app.get("/api/towns", response_model=list[Segment])
    def towns(index: JourneyIndex = Depends(get_journey_index)) -> list[Segment]:
        return [
            Segment(id=slug, route_id="", name=point.name, lat=point.lat, lon=point.lon)
            for slug, point in sorted(index.towns.items(), key=lambda kv: kv[1].name)
        ]

    # Multi-highway journey: the anchor towns along the drive from `from` to `to`
    # (OSRM-routed at build time, so no routing happens here), each with the same
    # departure-window summary as a single-route stop. Missing/invalid params are
    # a 400; an unknown town or an unbuilt pair is a 404.
    @app.get("/api/journey", response_model=JourneyResponse)
    async def journey(
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = None,
        departure: str | None = None,
        service: ForecastService = Depends(get_forecast_service),
        index: JourneyIndex = Depends(get_journey_index),
    ):
        if not from_ or not to or not departure:
            return JSONResponse(
                status_code=400, content={"error": "from, to and departure are required"}
            )
        try:
            departure_at = parse_departure(departure)
        except ValueError:
            return JSONResponse(
                status_code=400, content={"error": "departure must be an ISO 8601 time"}
            )
        resolved = index.resolve(from_, to)
        if resolved is None:
            return JSONResponse(
                status_code=404, content={"error": "unknown town or journey"}
            )
        stops = await service.forecast_towns(resolved.stops, departure_at)
        return JourneyResponse(
            from_id=from_,
            to_id=to,
            departure_utc=departure_at.isoformat(),
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            total_miles=resolved.miles,
            total_minutes=resolved.minutes,
            stops=stops,
        )

    return app


# The instance uvicorn serves (`uvicorn api.main:app`).
app = create_app()
