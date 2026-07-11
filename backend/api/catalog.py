"""The route catalogue, loaded once at startup from shared/route-catalogue.json
(exported from pipeline/routes.py).

Pydantic validates it on load, so a bad file fails the app immediately instead of
erroring mid-request. Kept in memory for the app's lifetime and injected via the
dependency below so tests can swap it.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import Request
from pydantic import BaseModel

from api.schemas import Route


class RouteCatalog(BaseModel):
    """All tracked routes (Sierra roads like I-80, US-395, SR-120), in catalogue order."""

    routes: list[Route]

    @classmethod
    def load(cls, shared_dir: Path) -> "RouteCatalog":
        path = shared_dir / "route-catalogue.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        # The file also has a human "description" key; we only need "routes".
        return cls(routes=payload["routes"])


def get_catalog(request: Request) -> RouteCatalog:
    """Dependency: the catalogue loaded at startup (see main.create_app)."""
    return request.app.state.catalog
