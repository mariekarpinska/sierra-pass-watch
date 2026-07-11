from __future__ import annotations

import asyncio
import sys

import pytest
from fastapi.testclient import TestClient

from api.main import create_app


@pytest.fixture(scope="session")
def event_loop_policy():
    """Async tests use psycopg, which needs a selector loop; Windows defaults to
    a proactor loop. Mirrors what api/__main__.py does for the dev server."""
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture()
def app():
    """A fresh application per test - no cross-test state or overrides."""
    return create_app()


@pytest.fixture()
def client(app):
    """TestClient as a context manager runs the app's lifespan (catalogue
    loaded, pool created - lazily, so no database is required)."""
    with TestClient(app) as test_client:
        yield test_client
