"""End-to-end tests of the API without a socket: TestClient drives the real
application object in-process, middleware and serialization included."""
# string type hints, no runtime eval
from __future__ import annotations

# used to parse and check the timestamp we get back
from datetime import datetime

# drives the app in process, no real socket or running server needed
from fastapi.testclient import TestClient

# our factory, so each test file spins up its own isolated app
from api.main import create_app

# one client wrapping a fresh app, reused across the tests below
client = TestClient(create_app())


# the happy path, hitting health should just answer 200
def test_health_returns_200() -> None:
    # fire the request and assert the status code in one line
    assert client.get("/api/health").status_code == 200


# locks down the exact json the endpoint promises the frontend
def test_health_returns_the_expected_contract() -> None:
    # call the endpoint and decode the json body into a dict
    body = client.get("/api/health").json()

    # exact wire shape, camelCase keys mirrored by the frontend types
    assert set(body) == {"status", "service", "timestampUtc"}
    # the ok marker value
    assert body["status"] == "healthy"
    # names which service answered
    assert body["service"] == "backend"
    # pin the timestamp format, iso 8601 with an explicit offset
    parsed = datetime.fromisoformat(body["timestampUtc"])
    # tzinfo present proves the offset was actually there
    assert parsed.tzinfo is not None


# unknown routes should fail cleanly, no leaking of framework internals
def test_unknown_paths_return_json_not_internals() -> None:
    # request a path that was never registered
    response = client.get("/api/nope")

    # missing route, so a 404
    assert response.status_code == 404
    # body is json, not an html error page
    assert response.headers["content-type"].startswith("application/json")
    # and it carries no python stack trace
    assert "Traceback" not in response.text
