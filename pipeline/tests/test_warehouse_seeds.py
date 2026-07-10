"""The dbt seeds are copies of pipeline data, so they must not drift from it.

warehouse/seeds/segments.csv mirrors pipeline.routes.build_segments(), and
warehouse/seeds/route_lengths.csv mirrors the lengthMiles in
shared/route-polylines.json. dbt reads the CSVs; these tests fail the moment a
CSV falls out of step with the source it was exported from, so a reviewer never
has to trust that someone re-ran the export.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from pipeline.routes import build_segments

_ROOT = Path(__file__).resolve().parents[2]
_SEGMENTS_CSV = _ROOT / "warehouse" / "seeds" / "segments.csv"
_ROUTE_LENGTHS_CSV = _ROOT / "warehouse" / "seeds" / "route_lengths.csv"
_POLYLINES = _ROOT / "shared" / "route-polylines.json"


def test_segments_seed_matches_route_catalogue() -> None:
    with _SEGMENTS_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    expected = build_segments()
    assert len(rows) == len(expected), "segments.csv row count drifted from build_segments()"

    for row, segment in zip(rows, expected, strict=True):
        assert row["segment_id"] == segment["segment_id"]
        assert row["segment_name"] == segment["segment_name"]
        assert row["route_id"] == segment["route_id"]
        assert float(row["lat"]) == segment["lat"]
        assert float(row["lon"]) == segment["lon"]


def test_route_lengths_seed_matches_polylines() -> None:
    with _ROUTE_LENGTHS_CSV.open(newline="", encoding="utf-8") as f:
        seeded = {row["route_id"]: float(row["length_miles"]) for row in csv.DictReader(f)}

    routes = json.loads(_POLYLINES.read_text(encoding="utf-8"))["routes"]
    expected = {route_id: entry["lengthMiles"] for route_id, entry in routes.items()}

    assert seeded == expected, "route_lengths.csv drifted from shared/route-polylines.json"
