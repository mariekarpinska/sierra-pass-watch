"""The drive's road line for the route-overview map.

The whole drive is stored as one [lat, lon] polyline per town pair
(shared/route-drive-lines.json, built by pipeline/build_journeys.py from OSRM's
driving geometry). The endpoint just looks it up and returns it, so the map
draws one unbroken line from start to finish - side roads and untracked
highways included. Nothing is sliced or routed at request time.

This is deliberately separate from the crash record: the crash bins are scoped
to the tracked major highways (the driven ranges in route-journeys.json), while
the map line is the actual drive.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import Request


class DriveLines:
    """The committed drive lines, loaded once at startup from the shared/
    directory (config.SHARED_DIR) - the same place the journey index loads
    from, so the line and the index it belongs to come from one build."""

    def __init__(self, lines: dict[str, list[list[float]]]) -> None:
        self._lines = lines

    @classmethod
    def load(cls, shared_dir: Path) -> "DriveLines":
        payload = json.loads((shared_dir / "route-drive-lines.json").read_text(encoding="utf-8"))
        return cls(payload["lines"])

    def line_for(self, from_id: str, to_id: str) -> list[list[float]]:
        """The [lat, lon] drive line from `from_id` to `to_id`, or [] if the
        pair was never built. Lines are stored from the lexically-smaller town
        id (like the journey index), so a reverse trip reads the same line
        flipped end to end."""
        lo, hi = sorted((from_id, to_id))
        line = self._lines.get(f"{lo}|{hi}")
        if line is None:
            return []
        return line if from_id == lo else list(reversed(line))


def get_drive_lines(request: Request) -> DriveLines:
    """Dependency: the drive lines loaded at startup (see main.create_app)."""
    return request.app.state.drive_lines
