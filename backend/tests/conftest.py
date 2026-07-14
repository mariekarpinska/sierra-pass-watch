from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import create_app


@pytest.fixture()
def app():
    """A fresh application per test - no cross-test state or overrides."""
    return create_app()


@pytest.fixture()
def client(app):
    """TestClient as a context manager runs the app's lifespan (catalogue and
    journey index loaded from the committed shared/ files)."""
    with TestClient(app) as test_client:
        yield test_client
