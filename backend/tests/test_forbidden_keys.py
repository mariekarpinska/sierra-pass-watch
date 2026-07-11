"""Guardrail: the API is historical and descriptive, never prescriptive. No
response may carry a score, rating, or drive/do-not-drive verdict - the product
states what the record says and lets the user decide. The frontend has the
mirror of this test. If someone adds a `safetyScore` field, this fails.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.schemas import Segment
from api.segments import get_segment_repository

# Substrings that would signal a judgement leaking into the contract.
_FORBIDDEN = ("score", "rating", "recommend", "verdict", "grade", "shoulddrive")


def _keys(payload: object) -> set[str]:
    """Every JSON key anywhere in the payload, recursively."""
    found: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            found.add(key)
            found |= _keys(value)
    elif isinstance(payload, list):
        for item in payload:
            found |= _keys(item)
    return found


class _FakeSegments:
    async def get(self, route_id: str | None) -> list[Segment]:
        return [Segment(id="I-80:colfax", route_id="I-80", name="Colfax", lat=39.1, lon=-120.9)]


@pytest.fixture()
def client():
    app = create_app()
    app.dependency_overrides[get_segment_repository] = _FakeSegments
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("path", ["/api/health", "/api/routes", "/api/segments"])
def test_no_response_carries_a_safety_judgement(client, path) -> None:
    keys = {k.lower() for k in _keys(client.get(path).json())}
    leaked = {k for k in keys if any(word in k for word in _FORBIDDEN)}
    assert not leaked, f"{path} leaked judgement-shaped keys: {leaked}"
