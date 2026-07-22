"""Sierra Pass Watch API: builds the FastAPI app.

Endpoints match the frontend contract (frontend/src/api/types.ts) field for
field, and only what the UI consumes exists: /api/health, /api/towns,
/api/journey, /api/journey-path, /api/crash-patterns, /api/incidents (the
provisional live-collision feed, ADR-0012).

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
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.catalog import RouteCatalog, get_catalog
from api.config import Settings
from api.crashes import (
    CrashHistoryStore,
    PostgresCrashHistoryStore,
    build_crash_patterns,
    build_incidents,
    get_crash_store,
    segment_legs,
)
from api.journeys import JourneyIndex, ResolvedJourney, get_journey_index
from api.middleware import (
    CorrelationIdFilter,
    CorrelationIdMiddleware,
    OriginVerifyMiddleware,
)
from api.paths import DriveLines, get_drive_lines
from api.schemas import (
    CrashPatternsResponse,
    Health,
    IncidentsResponse,
    JourneyLeg,
    JourneyPathResponse,
    JourneyResponse,
    Waypoint,
)
from api.weather import (
    ForecastService,
    OpenMeteoForecastProvider,
    get_forecast_service,
    parse_departure,
    worst_regime,
)

log = logging.getLogger(__name__)

# Add the correlation-id filter to the root logger once, at import, so every log
# record carries the request's id (middleware.py). Done here, not inside
# create_app, so building several apps (as the tests do) does not stack a new
# filter each time.
logging.getLogger().addFilter(CorrelationIdFilter())


def resolve_or_error(
    index: JourneyIndex, from_: str | None, to: str | None
) -> ResolvedJourney | JSONResponse:
    """The front door the three journey endpoints share: turn a from/to town
    pair into a resolved journey, or the matching error response. from and to
    must both be present and different, and the pair must exist in the index.
    Endpoints that also take a departure validate that themselves. Returning
    the error as a value (not raising) keeps each endpoint a flat read, and
    puts the one validation ladder in one place so the three cannot drift.
    """
    if not from_ or not to:
        return JSONResponse(
            status_code=400, content={"error": "from and to are required"}
        )
    # The index stores no self-pairs, so without this check a same-town request
    # would fall through to a misleading 404 "unknown town".
    if from_ == to:
        return JSONResponse(
            status_code=400, content={"error": "from and to must be different towns"}
        )
    resolved = index.resolve(from_, to)
    if resolved is None:
        return JSONResponse(
            status_code=404, content={"error": "unknown town or journey"}
        )
    return resolved


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Using a factory (not a module-level app) lets each test
    build its own isolated instance and pass its own Settings."""
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: load the committed catalogue and journey index once; every
        # request after that is served from memory.
        app.state.catalog = RouteCatalog.load(settings.shared_dir)
        app.state.journeys = JourneyIndex.load(settings.shared_dir)
        # The drive lines load from the same directory as the journey index, so
        # /api/journey-path serves the line built alongside the index it is
        # given (not a copy baked into the source).
        app.state.drive_lines = DriveLines.load(settings.shared_dir)
        # One HTTP client for Open-Meteo: fixed base URL plus a hard timeout, so
        # the SSRF and timeout guards live here, not at each call site. The
        # service holds the 5-minute per-coordinate cache for the process life.
        app.state.open_meteo_client = httpx.AsyncClient(
            base_url=settings.open_meteo_base_url, timeout=10.0
        )
        app.state.forecast_service = ForecastService(
            provider=OpenMeteoForecastProvider(app.state.open_meteo_client),
        )
        # Crash history is the one thing served from Postgres (the dbt marts).
        # The store's pool opens on the first crash request, not here, so the
        # app still starts (and every other endpoint works) with no database.
        app.state.crash_store = PostgresCrashHistoryStore(settings)
        try:
            yield
        finally:
            await app.state.open_meteo_client.aclose()
            app.state.crash_store.close()

    app = FastAPI(title="Sierra Pass Watch API", version="0.1.0", lifespan=lifespan)

    # Cost guard: when configured, only requests carrying the CDN's secret
    # header get through (middleware.py). Added first so CorrelationIdMiddleware
    # (added after, therefore outermost) still stamps rejected requests.
    if settings.origin_verify_secret:
        app.add_middleware(OriginVerifyMiddleware, secret=settings.origin_verify_secret)

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

    # The towns the journey picker offers, from the in-memory index (no DB).
    # Route-independent points, so they are plain Waypoints (no route_id).
    @app.get("/api/towns", response_model=list[Waypoint])
    def towns(index: JourneyIndex = Depends(get_journey_index)) -> list[Waypoint]:
        return [
            point.to_waypoint(slug)
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
        catalog: RouteCatalog = Depends(get_catalog),
    ):
        # Departure is this endpoint's own required param, checked before the
        # shared town-pair resolve so a missing one is a 400, not a 404.
        if not departure:
            return JSONResponse(
                status_code=400, content={"error": "from, to and departure are required"}
            )
        resolved = resolve_or_error(index, from_, to)
        if isinstance(resolved, JSONResponse):
            return resolved
        try:
            departure_at = parse_departure(departure)
        except ValueError:
            return JSONResponse(
                status_code=400, content={"error": "departure must be an ISO 8601 time"}
            )
        stops = await service.forecast_towns(resolved.stops, departure_at)
        # The highways travelled, with the catalogue's seasonal context, so
        # the UI can name the roads and warn about passes that close.
        routes_by_id = {route.id: route for route in catalog.routes}
        via = [
            JourneyLeg(
                id=r.id,
                name=r.name,
                seasonal=r.seasonal,
                note=r.note,
                span=resolved.span_for(r.id),
            )
            for road in resolved.via
            if (r := routes_by_id.get(road)) is not None
        ]
        return JourneyResponse(
            from_id=from_,
            to_id=to,
            via=via,
            departure_utc=departure_at.isoformat(),
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            total_miles=resolved.miles,
            total_minutes=resolved.minutes,
            stops=stops,
        )

    # The drive's road line for the route-overview map: the whole drive, stored
    # as one committed polyline per town pair (api/paths.py). A plain in-memory
    # lookup - no database and no outbound call - so a plain `def` on the worker
    # threadpool is plenty. Params mirror /api/journey. The pair is validated
    # against the same index the other endpoints use, so an unknown town or an
    # unbuilt pair is a 404 here too.
    @app.get("/api/journey-path", response_model=JourneyPathResponse)
    def journey_path(
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = None,
        index: JourneyIndex = Depends(get_journey_index),
        lines: DriveLines = Depends(get_drive_lines),
    ):
        resolved = resolve_or_error(index, from_, to)
        if isinstance(resolved, JSONResponse):
            return resolved
        # One continuous line for the whole drive; wrapped in a list so the
        # response shape (a list of paths) is unchanged for the frontend.
        line = lines.line_for(from_, to)
        return JourneyPathResponse(paths=[line] if line else [])

    # The crash record for a journey, each stretch matched to its own
    # forecast: totals, occupied per-mile bins, top causes (from the dbt
    # marts, composed per request - ADR-0010). The journey is named by its
    # towns, exactly like /api/journey, and the server resolves it against the
    # same committed index and samples the same forecast service - so the
    # roads, the mile stretches and their regimes all come from one place,
    # never from request input. Missing/invalid params are a 400; an unknown
    # town or an unbuilt pair is a 404, mirroring /api/journey.
    # `async def` for the forecast await; the two store reads hop to the
    # worker threadpool explicitly, which is what lets them block on the sync
    # database driver without stalling the event loop (see crashes.py for why
    # the driver is sync).
    @app.get("/api/crash-patterns", response_model=CrashPatternsResponse)
    async def crash_patterns(
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = None,
        departure: str | None = None,
        store: CrashHistoryStore = Depends(get_crash_store),
        index: JourneyIndex = Depends(get_journey_index),
        service: ForecastService = Depends(get_forecast_service),
    ):
        # Departure is this endpoint's own required param, checked before the
        # shared town-pair resolve so a missing one is a 400, not a 404.
        if not departure:
            return JSONResponse(
                status_code=400,
                content={"error": "from, to and departure are required"},
            )
        resolved = resolve_or_error(index, from_, to)
        if isinstance(resolved, JSONResponse):
            return resolved
        try:
            departure_at = parse_departure(departure)
        except ValueError:
            return JSONResponse(
                status_code=400, content={"error": "departure must be an ISO 8601 time"}
            )
        # Each stop's departure-window forecast; the journey request just made
        # the same calls, so the service's 5-minute cache usually answers.
        stops = await service.forecast_towns(resolved.stops, departure_at)
        regimes = {stop.waypoint.id: stop.regime for stop in stops}
        legs = segment_legs(
            resolved.via,
            resolved.driven,
            resolved.anchors,
            regimes,
            fallback=worst_regime(list(regimes.values())),
        )
        route_ids = list(dict.fromkeys(resolved.via))
        if not legs:
            # Nothing but UNKNOWN forecasts: there is no weather to match, and
            # an empty record would read as "a quiet road" when the truth is
            # "the forecast is unavailable". Say so: the client's error path
            # already presents exactly that ("back when the service is").
            return JSONResponse(
                status_code=503,
                content={"error": "no forecast to match the crash history against"},
            )
        bins = await run_in_threadpool(store.bins, legs)
        causes = await run_in_threadpool(store.causes, legs)
        return build_crash_patterns(route_ids, bins, causes)

    # Live collisions collected on the journey's roads (ADR-0012), newest
    # first, always labelled provisional. Named by its towns like the other
    # journey endpoints; no departure, because this is "what's been reported
    # live on these roads lately", not the forecast-matched crash history.
    # `def` on the worker threadpool for the one sync database read, same as
    # crash-patterns. Missing params are a 400; an unknown town or unbuilt pair
    # is a 404.
    @app.get("/api/incidents", response_model=IncidentsResponse)
    async def incidents(
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = None,
        store: CrashHistoryStore = Depends(get_crash_store),
        index: JourneyIndex = Depends(get_journey_index),
    ):
        resolved = resolve_or_error(index, from_, to)
        if isinstance(resolved, JSONResponse):
            return resolved
        route_ids = list(dict.fromkeys(resolved.via))
        rows = await run_in_threadpool(store.recent_incidents, route_ids)
        return build_incidents(route_ids, rows)

    return app


# The instance uvicorn serves (`uvicorn api.main:app`).
app = create_app()
