"""Caltrans CWWP2 — chain control status and RWIS road-weather stations.

Keyless public JSON, refreshed every 1–5 minutes. Districts covering the
Sierra: D3 (Sacramento valley → Tahoe), D10 (central foothills), D9 (eastern
Sierra / US-395), D6 (southern Sierra). One fetch returns every station in a
district; the producer matches stations to waypoints by distance.

RWIS values arrive NTCIP-1204-encoded (tenths of °C, tenths of m/s, sentinel
values for "unknown") — decoded here so nothing downstream ever sees raw NTCIP.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from pipeline.fetch import get_json

log = logging.getLogger(__name__)

# (path segment, file suffix) per district — Caltrans zero-pads single digits.
_DISTRICTS = (("d3", "D03"), ("d6", "D06"), ("d9", "D09"), ("d10", "D10"))
_CC_URL = "https://cwwp2.dot.ca.gov/data/{d}/cc/ccStatus{D}.json"
_RWIS_URL = "https://cwwp2.dot.ca.gov/data/{d}/rwis/rwisStatus{D}.json"


@dataclass
class ChainControl:
    """Chain-control status at one Caltrans check location."""

    location_name: str
    route: str
    lat: float
    lon: float
    status: str  # "None" | "R1" | "R2" | "R3"


@dataclass
class RwisReading:
    """One road-weather station: sensors embedded in the pavement."""

    station_id: str
    location_name: str
    route: str
    lat: float
    lon: float
    surface_temp_c: float | None  # pavement temperature — the black-ice signal
    visibility_miles: float | None
    wind_gust_mph: float | None


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ntcip_temp_c(value) -> float | None:
    """NTCIP temperature: tenths of °C; 1001 = sensor has no reading."""
    v = _num(value)
    return None if v is None or v == 1001 else v / 10.0


def _ntcip_wind_mph(value) -> float | None:
    """NTCIP wind: tenths of m/s; 65535 = no reading. Converted to mph."""
    v = _num(value)
    return None if v is None or v == 65535 else (v / 10.0) * 2.23694


def _ntcip_visibility_miles(value) -> float | None:
    """NTCIP visibility: metres; ≥100001 = no reading. Converted to miles."""
    v = _num(value)
    return None if v is None or v >= 100001 else v / 1609.344


def parse_chain_control(payload: dict) -> list[ChainControl]:
    results = []
    for item in payload.get("data", []):
        location = item.get("location", {})
        lat, lon = _num(location.get("latitude")), _num(location.get("longitude"))
        if lat is None or lon is None:
            continue
        results.append(
            ChainControl(
                location_name=location.get("locationName", ""),
                route=location.get("route", ""),
                lat=lat,
                lon=lon,
                status=item.get("status", {}).get("ccStatus", "None"),
            )
        )
    return results


def parse_rwis(payload: dict) -> list[RwisReading]:
    results = []
    for item in payload.get("data", []):
        rwis = item.get("rwis", {})
        location = rwis.get("location", {})
        lat, lon = _num(location.get("latitude")), _num(location.get("longitude"))
        if lat is None or lon is None:
            continue
        data = rwis.get("rwisData", {})
        pavement_table = data.get("pavementSensorData", {}).get("essPavementSensorTable", [])
        pavement = pavement_table[0].get("essPavementSensorEntry", {}) if pavement_table else {}
        results.append(
            RwisReading(
                station_id=str(rwis.get("index", "")),
                location_name=location.get("locationName", ""),
                route=location.get("route", ""),
                lat=lat,
                lon=lon,
                surface_temp_c=_ntcip_temp_c(pavement.get("essSurfaceTemperature")),
                visibility_miles=_ntcip_visibility_miles(
                    data.get("visibilityData", {}).get("essVisibility")
                ),
                wind_gust_mph=_ntcip_wind_mph(
                    data.get("windData", {}).get("essMaxWindGustSpeed")
                ),
            )
        )
    return results


def _fetch_districts(url_template: str, parse, label: str) -> list:
    """Fetch + parse one feed across all Sierra districts; a district failing
    only narrows coverage for this cycle, it never fails the poll."""
    results = []
    for d, suffix in _DISTRICTS:
        try:
            batch = parse(get_json(url_template.format(d=d, D=suffix)))
            results.extend(batch)
            log.info("%s fetched: district=%s count=%d", label, d, len(batch))
        except Exception as exc:  # noqa: BLE001 — degrade per district, never crash the cycle
            log.warning("%s fetch failed: district=%s error=%s", label, d, exc)
    return results


def fetch_chain_control() -> list[ChainControl]:
    return _fetch_districts(_CC_URL, parse_chain_control, "chain control")


def fetch_rwis() -> list[RwisReading]:
    return _fetch_districts(_RWIS_URL, parse_rwis, "rwis")
