"""Sierra Safe API: builds the FastAPI app.

Endpoints match the frontend contract (frontend/src/api/types.ts) field for
field. Live now: /api/health, /api/routes, /api/segments. Later branches add
forecast, crash-patterns, hotspots and the alerts feed.

Run locally (the Vite dev server proxies /api here):

    uvicorn api.main:app --port 5080 --no-server-header

--no-server-header hides the server name from responses.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.catalog import RouteCatalog, get_catalog
from api.config import Settings
from api.db import create_pool
from api.middleware import CorrelationIdFilter, CorrelationIdMiddleware
from api.schemas import Health, Route, Segment
from api.segments import SegmentRepository, get_segment_repository

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Using a factory (not a module-level app) lets each test
    build its own isolated instance and pass its own Settings."""
    settings = settings or Settings()

    # Every log record carries the request's correlation id (middleware.py).
    logging.getLogger().addFilter(CorrelationIdFilter())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: load the catalogue once and create the pool (lazy, so no
        # database connection is made until the first query).
        app.state.catalog = RouteCatalog.load(settings.shared_dir)
        app.state.pool = create_pool(settings.database_url)
        await app.state.pool.open()
        yield
        # Shutdown: close the pool cleanly.
        await app.state.pool.close()

    app = FastAPI(title="Sierra Safe API", version="0.1.0", lifespan=lifespan)

    # Every request flows through this to get a correlation id.
    app.add_middleware(CorrelationIdMiddleware)

    # Only add CORS if origins are configured; the default same-origin setup
    # needs none (see config.py).
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_methods=["GET"],
            allow_headers=["*"],
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

    return app


# The instance uvicorn serves (`uvicorn api.main:app`).
app = create_app()
