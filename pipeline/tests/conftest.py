from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_json():
    """Loader for the recorded API payloads in tests/fixtures."""

    def load(name: str) -> dict:
        return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))

    return load
