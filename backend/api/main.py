"""Sierra Corridor API — FastAPI application factory.

Boilerplate stage: one endpoint (GET /api/health) that the frontend calls
through its axios interceptor layer to prove the full round-trip works.
Real endpoints land feature by feature, each matching the contract the
frontend defines in frontend/src/api/types.ts.

Run locally (the Vite dev server proxies /api here):

    uvicorn api.main:app --port 5080 --no-server-header

`--no-server-header` keeps the server implementation out of responses —
the same hardening the reverse proxy applies in production.

→ Serves as the entry point and core configuration file of the web application.  
It initializes the backend server, registers routes, attaches middlewares, and 
coordinates all the distinct pieces of your project.
"""
# pulls in future annotation behavior so type hints stay as strings, no runtime eval
from __future__ import annotations

# datetime for the current time, timezone so we can stamp it as utc
from datetime import datetime, timezone

# the web framework class we build the app instance from
from fastapi import FastAPI

# our response model for the health endpoint, defined next door in schemas
from api.schemas import Health


# factory (function that constructs and returns an obj) that assembles and hands back a fresh app, callable per test
def create_app() -> FastAPI:
    """Build the application. A factory (rather than a module-level app with
    side effects) so tests can construct fresh, isolated instances."""
    # construct the app, title and version just feed the auto generated docs
    app = FastAPI(
        title="Sierra Corridor API",
        version="0.1.0",
        # the SPA is the only intended client, docs pages left on as a dev convenience
    )

    # register a GET route at /api/health, response_model pins and validates the shape
    @app.get("/api/health", response_model=Health)
    # the handler fastapi calls when that path is hit
    def health() -> Health:
        # build and return the health payload, fastapi serializes it to json for us
        return Health(
            # literal ok marker the frontend checks for
            status="healthy",
            # which service answered, useful once there is more than one
            service="backend",
            # now, in utc, as an iso 8601 string with an explicit offset
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
        )

    # give the fully wired app back to whoever called the factory
    return app


# module level instance uvicorn actually serves via api.main:app
app = create_app()
