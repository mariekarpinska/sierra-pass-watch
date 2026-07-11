"""Postgres access: one async connection pool per process.

Every request borrows a connection from this shared pool instead of opening its
own. min_size=0 means no connections are made until the first query, so the app
starts fine even with no database running (for catalogue-only use).
"""
from __future__ import annotations

from fastapi import Request
from psycopg_pool import AsyncConnectionPool


def create_pool(database_url: str) -> AsyncConnectionPool:
    return AsyncConnectionPool(
        conninfo=database_url,
        min_size=0,  # connect on first use, not at startup
        max_size=10,
        open=False,  # opened in the app's lifespan (main.py)
        # Give up quickly if the database is down instead of hanging.
        timeout=10,
        kwargs={"connect_timeout": 5},
    )


def get_pool(request: Request) -> AsyncConnectionPool:
    """Dependency: the process-wide pool (created in main.create_app)."""
    return request.app.state.pool
