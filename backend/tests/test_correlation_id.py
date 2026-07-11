"""The correlation-id middleware. It accepts only a canonical UUID (what the
frontend sends); a missing or non-UUID value is replaced with a fresh UUID
instead of crashing, so the id we log and reflect is always a clean UUID."""
from __future__ import annotations

import uuid

# A canonical UUID, the shape crypto.randomUUID() produces on the frontend.
_VALID = "550e8400-e29b-41d4-a716-446655440000"


def test_valid_uuid_is_echoed_back(client) -> None:
    response = client.get("/api/health", headers={"X-Correlation-Id": _VALID})
    assert response.headers["X-Correlation-Id"] == _VALID


def test_missing_id_gets_a_fresh_uuid(client) -> None:
    returned = client.get("/api/health").headers["X-Correlation-Id"]
    uuid.UUID(returned)  # parses, so it is a real UUID


def test_non_uuid_is_replaced_with_a_uuid(client) -> None:
    # "not-a-uuid" is a safe string but not a UUID, so it is dropped for a fresh
    # one, and the request still succeeds.
    response = client.get("/api/health", headers={"X-Correlation-Id": "not-a-uuid"})

    assert response.status_code == 200
    returned = response.headers["X-Correlation-Id"]
    assert returned != "not-a-uuid"
    uuid.UUID(returned)


def test_overly_long_id_is_replaced(client) -> None:
    response = client.get("/api/health", headers={"X-Correlation-Id": "a" * 200})

    assert response.status_code == 200
    assert response.headers["X-Correlation-Id"] != "a" * 200
