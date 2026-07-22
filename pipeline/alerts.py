"""Derive push-worthy alerts from road-state observations. Pure, no I/O.

An alert is a CHANGE, not a snapshot. The readings pipeline records the state
of the road every poll; this fires only when that state flips in a way a driver
would want the second it happens:

* chain control going up, escalating, easing or lifting (Caltrans — the reliable
  layer, from data the readings producer already fetches);
* a new CHP incident, collision, hazard or closure, on a tracked route (the
  best-effort near-real-time layer).

``derive_alerts`` is a pure fold: (previous state, current observations) →
(alerts to emit, next state). The runner (pipeline/poller.py) owns the I/O and
writes the alerts straight to Postgres (no broker, ADR-0012), so all the logic
here is unit-testable against fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from pipeline.geo import nearest
from pipeline.polylines import measure_for
from pipeline.routes import SEGMENTS, in_sierra, parse_route

# A chain-control check farther than this from any waypoint isn't on a route we
# track (mirrors the producer's station-matching radius).
_MATCH_MAX_KM = 30.0

# Chain-control severity order, for start / escalate / ease classification.
_CHAIN_RANK = {"None": 0, "R1": 1, "R2": 2, "R3": 3}

# Keep a seen CHP incident id this long before it may alert again, so the state
# store can't grow without bound and a lingering incident isn't re-announced.
_INCIDENT_TTL_HOURS = 6


@dataclass(frozen=True)
class Alert:
    """One push-worthy change. Written by the poll worker to the alerts table."""

    alert_id: str        # idempotency key: re-emitting only ever no-ops
    kind: str            # CHAIN_CONTROL | INCIDENT
    category: str        # STARTED/ESCALATED/EASED/LIFTED | COLLISION/HAZARD/CLOSURE/OTHER
    route_id: str | None
    segment_id: str | None
    headline: str        # one line, ready to show or notify
    detail: str | None
    lat: float | None
    lon: float | None
    measure_mi: float | None  # distance-along-route (incidents only), null off the line
    event_time: str      # when it happened upstream (ISO, UTC)
    source: str          # caltrans | chp


@dataclass
class Derived:
    """Result of one derivation: what to emit, and the state to persist."""

    alerts: list[Alert]
    next_state: dict[str, str]


def _nearest_segment(lat: float, lon: float, max_km: float = _MATCH_MAX_KM) -> dict | None:
    return nearest(SEGMENTS, lat, lon, max_km, lambda s: (s["lat"], s["lon"]))


def _chain_transition(prev: str, now: str) -> str | None:
    """Name the chain-control change, or None if nothing changed."""
    if prev == now:
        return None
    if now == "None":
        return "LIFTED"
    if prev == "None":
        return "STARTED"
    return "ESCALATED" if _CHAIN_RANK[now] > _CHAIN_RANK.get(prev, 0) else "EASED"


def derive_chain_alerts(prev_state: dict, chain_controls: list, now: str) -> tuple[list[Alert], dict]:
    """Chain-control transitions since last poll. ``chain_controls`` are cwwp2.ChainControl."""
    alerts: list[Alert] = []
    # Carry forward the last-known status of stations NOT seen this poll: a
    # station briefly missing from the feed (a district fetch failed) must not
    # be re-announced as a fresh STARTED when it returns unchanged. A real lift
    # arrives as the station present with status "None", not as a disappearance.
    state: dict[str, str] = {k: v for k, v in prev_state.items() if k.startswith("cc:")}
    for cc in chain_controls:
        status = cc.status if cc.status in _CHAIN_RANK else "None"
        seg = _nearest_segment(cc.lat, cc.lon)
        if seg is None:  # not on a catalogue route
            continue
        # Identify a station by route + coordinates, not location_name (which
        # cwwp2 can leave blank — two blank-named controls would otherwise
        # collide on one key and overwrite each other's status).
        key = f"cc:{seg['route_id']}:{round(cc.lat, 4)},{round(cc.lon, 4)}"
        prev = prev_state.get(key, "None")
        state[key] = status
        category = _chain_transition(prev, status)
        if category is None:
            continue
        where = f"{seg['route_id']} near {seg['segment_name']}"
        headline = {
            "STARTED": f"Chain controls in effect ({status}) on {where}",
            "ESCALATED": f"Chain controls raised to {status} on {where}",
            "EASED": f"Chain controls eased to {status} on {where}",
            "LIFTED": f"Chain controls lifted on {where}",
        }[category]
        alerts.append(
            Alert(
                # Deterministic id — identifies the transition, not the poll.
                # A re-poll re-derives the same prev->status and so the same id,
                # which the alerts table's ON CONFLICT (alert_id) DO NOTHING
                # dedups (no duplicate row). The incident id chp:{id} is stable
                # the same way. Trade-off:
                # an identical transition that genuinely recurs (chains lift,
                # then re-form to the same level) collapses to one alerts row.
                alert_id=f"{key}:{prev}->{status}",
                kind="CHAIN_CONTROL",
                category=category,
                route_id=seg["route_id"],
                segment_id=seg["segment_id"],
                headline=headline,
                detail=cc.location_name,
                lat=cc.lat,
                lon=cc.lon,
                measure_mi=None,
                event_time=now,
                source="caltrans",
            )
        )
    return alerts, state


def _within_ttl(seen_iso: str, now_iso: str) -> bool:
    try:
        return datetime.fromisoformat(now_iso) - datetime.fromisoformat(seen_iso) <= timedelta(
            hours=_INCIDENT_TTL_HOURS
        )
    except ValueError:
        return True  # unparseable → keep, safer than re-announcing


def derive_incident_alerts(prev_state: dict, incidents: list, now: str) -> tuple[list[Alert], dict]:
    """New CHP incidents on a tracked route. ``incidents`` are chp.Incident."""
    alerts: list[Alert] = []
    # Carry forward recently-seen incident ids so we don't re-announce each poll.
    state = {
        key: seen
        for key, seen in prev_state.items()
        if key.startswith("chp:") and _within_ttl(seen, now)
    }
    for inc in incidents:
        if inc.lat is None or inc.lon is None or not in_sierra(inc.lat, inc.lon):
            continue
        route_id = parse_route(inc.location_text, inc.lon)
        if route_id is None:
            continue
        key = f"chp:{inc.incident_id}"
        if key in prev_state:  # already announced; keep it marked seen
            state[key] = prev_state[key]
            continue
        state[key] = now
        seg = _nearest_segment(inc.lat, inc.lon)
        where = route_id if seg is None else f"{route_id} near {seg['segment_name']}"
        alerts.append(
            Alert(
                alert_id=key,
                kind="INCIDENT",
                category=inc.category,
                route_id=route_id,
                segment_id=seg["segment_id"] if seg else None,
                headline=f"{inc.category.title()} reported on {where}",
                detail=inc.type_text or None,
                lat=inc.lat,
                lon=inc.lon,
                measure_mi=measure_for(route_id, inc.lat, inc.lon),
                event_time=inc.log_time or now,
                source="chp",
            )
        )
    return alerts, state


def derive_alerts(prev_state: dict, chain_controls: list, incidents: list, now: str) -> Derived:
    """Fold both layers into one batch of alerts plus the state to persist."""
    chain_alerts, chain_state = derive_chain_alerts(prev_state, chain_controls, now)
    incident_alerts, incident_state = derive_incident_alerts(prev_state, incidents, now)
    return Derived(alerts=chain_alerts + incident_alerts, next_state={**chain_state, **incident_state})
