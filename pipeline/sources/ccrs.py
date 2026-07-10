"""CCRS crash-data downloader — California's public crash reporting system.

data.ca.gov publishes one statewide CSV per year through CKAN (keyless).
Statewide is ~1M rows/year; we stream it and keep only rows that are
plausibly ours — inside the Sierra bounding box AND mentioning a tracked
route — writing a small local CSV. Precise attribution (route id, direction,
range polygon) happens in the backfill loader, so this stage stays a dumb,
re-runnable filter.

Usage:
    python -m pipeline.sources.ccrs               # last two calendar years
    python -m pipeline.sources.ccrs --years 2023 2024 2025
"""
from __future__ import annotations

import argparse
import csv
import io
import logging
import re
from datetime import date
from pathlib import Path

import requests

from pipeline.fetch import USER_AGENT, get_json
from pipeline.routes import sierra_bbox, union_route_pattern

log = logging.getLogger(__name__)

CKAN_RESOURCE_URL = "https://data.ca.gov/api/3/action/resource_show"

# CKAN resource ids per year — verify at https://data.ca.gov/dataset/ccrs
# when adding a year. This is data, not logic; update freely.
RESOURCE_IDS: dict[int, str] = {
    2026: "b8ce0ca4-b4e9-490d-b4d1-1f4ec48cbefb",
    2025: "9f4fc839-122d-4595-a146-43bc4ed16f46",
    2024: "f775df59-b89b-4f82-bd3d-8807fa3a22a0",
    2023: "436642c0-cd04-4a4c-b45e-564b66437476",
    2022: "7828780b-117b-455e-9275-986ad3ffde50",
    2021: "d08692e2-6d36-487e-bca0-28cd127a626f",
    2020: "a2e0605d-0695-4bce-806d-4d0dda7ace68",
    2019: "2b4c7d03-e684-435e-80da-17935de9499f",
    2018: "a4b57216-5110-43d3-884c-d95366b19158",
    2017: "4784664d-b7cf-4427-af25-7c7307bad56c",
    2016: "3d5f2586-cf68-4213-aa1c-60df37399d10",
}

OUTPUT_CSV = Path("data/ccrs/crashes.csv")

# Column-name candidates across CCRS publication vintages.
_ROAD_COLUMNS = ("PRIMARYROAD", "PRIMARY_RD", "ROAD")
_LAT_COLUMNS = ("LATITUDE", "POINT_Y")
_LON_COLUMNS = ("LONGITUDE", "POINT_X")


def normalize_header(name: str) -> str:
    return name.upper().strip().replace(" ", "_")


def _first_index(header: list[str], candidates: tuple[str, ...]) -> int | None:
    for candidate in candidates:
        if candidate in header:
            return header.index(candidate)
    return None


def _resolve_download_url(resource_id: str) -> str:
    result = get_json(CKAN_RESOURCE_URL, params={"id": resource_id}, timeout=20).get("result", {})
    url = result.get("url")
    if not url:
        raise ValueError(f"CKAN resource {resource_id} has no download URL")
    return url


def stream_filter_year(url: str, writer: csv.writer, write_header: bool) -> tuple[list[str], int]:
    """Stream one year's statewide CSV; write matching rows through ``writer``.

    Returns (normalized header, rows kept). The text stream is wrapped rather
    than split on lines so quoted fields containing newlines survive.
    """
    min_lon, max_lon, min_lat, max_lat = sierra_bbox()
    route_re = re.compile(union_route_pattern())

    response = requests.get(url, stream=True, timeout=180, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    response.raw.decode_content = True
    text = io.TextIOWrapper(response.raw, encoding="utf-8", errors="replace", newline="")

    reader = csv.reader(text)
    header = [normalize_header(h) for h in next(reader)]
    road_i = _first_index(header, _ROAD_COLUMNS)
    lat_i = _first_index(header, _LAT_COLUMNS)
    lon_i = _first_index(header, _LON_COLUMNS)
    if road_i is None or lat_i is None or lon_i is None:
        raise ValueError(f"CCRS file missing road/lat/lon columns; header={header[:20]}…")

    if write_header:
        writer.writerow(header)

    kept = 0
    for row in reader:
        if len(row) <= max(road_i, lat_i, lon_i):
            continue
        try:
            lat, lon = float(row[lat_i]), float(row[lon_i])
        except ValueError:
            continue
        if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
            continue
        if not route_re.search(row[road_i].upper()):
            continue
        writer.writerow(row)
        kept += 1
    return header, kept


def download(years: list[int] | None = None, output: Path = OUTPUT_CSV) -> int:
    """Download + filter the given years into one local CSV. Returns rows kept.

    Re-running overwrites the file — the loader de-duplicates on case id, so
    the whole path is idempotent end to end.
    """
    if years is None:
        this_year = date.today().year
        years = [this_year - 1, this_year]

    output.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        first = True
        for year in sorted(years):
            resource_id = RESOURCE_IDS.get(year)
            if resource_id is None:
                log.warning("no CKAN resource id for %s — add it to RESOURCE_IDS", year)
                continue
            try:
                url = _resolve_download_url(resource_id)
                _, kept = stream_filter_year(url, writer, write_header=first)
                first = False
                total += kept
                log.info("ccrs year filtered: year=%s kept=%d", year, kept)
            except Exception as exc:  # noqa: BLE001 — one bad year shouldn't lose the rest
                log.error("ccrs year failed: year=%s error=%s", year, exc)
    log.info("ccrs download complete: rows=%d file=%s", total, output)
    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Download CCRS crashes filtered to the Sierra")
    parser.add_argument("--years", nargs="+", type=int, help="calendar years (default: last two)")
    args = parser.parse_args()
    download(years=args.years)
