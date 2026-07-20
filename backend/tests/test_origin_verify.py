"""The origin-verify middleware: the cost guard that pins the API's cheap path
to the CDN. With ORIGIN_VERIFY_SECRET set, only requests carrying the CDN's
X-Origin-Verify header get through; /api/health stays open for App Runner's
health checker; and with the setting unset (local dev, this suite's default
client) nothing changes at all."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.config import Settings
from api.main import create_app

_SECRET = "test-origin-secret"


@pytest.fixture()
def guarded_client():
    app = create_app(Settings(origin_verify_secret=_SECRET))
    with TestClient(app) as test_client:
        yield test_client


def test_request_with_secret_passes(guarded_client) -> None:
    response = guarded_client.get("/api/towns", headers={"X-Origin-Verify": _SECRET})
    assert response.status_code == 200


def test_request_without_secret_is_rejected(guarded_client) -> None:
    response = guarded_client.get("/api/towns")
    assert response.status_code == 403
    assert response.json() == {"error": "Forbidden"}


def test_wrong_secret_is_rejected(guarded_client) -> None:
    response = guarded_client.get("/api/towns", headers={"X-Origin-Verify": "wrong"})
    assert response.status_code == 403


def test_health_stays_open_without_secret(guarded_client) -> None:
    # App Runner's health checker calls the origin directly and can never send
    # the CDN header; a guarded health check would take the whole service down.
    response = guarded_client.get("/api/health")
    assert response.status_code == 200


def test_unset_secret_leaves_api_open(client) -> None:
    # The default client has no secret configured: local dev is unaffected.
    assert client.get("/api/towns").status_code == 200
