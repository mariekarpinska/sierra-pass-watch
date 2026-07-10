from pipeline.alerts import derive_alerts, derive_chain_alerts, derive_incident_alerts
from pipeline.sources.chp import Incident, classify_incident
from pipeline.sources.cwwp2 import ChainControl

DONNER = (39.3163, -120.3208)  # I-80 : Donner Summit waypoint
NOW = "2026-07-09T21:00:00+00:00"
CC_KEY = "cc:I-80:39.3163,-120.3208"  # station identified by route + coords


def _cc(status: str) -> ChainControl:
    return ChainControl(location_name="CC Donner", route="I-80", lat=DONNER[0], lon=DONNER[1], status=status)


def _inc(incident_id: str, type_text: str, lat, lon, location: str) -> Incident:
    return Incident(
        incident_id=incident_id,
        category=classify_incident(type_text),
        type_text=type_text,
        location_text=location,
        lat=lat,
        lon=lon,
        log_time=NOW,
    )


# --- chain-control transitions -------------------------------------------------

def test_chain_started():
    alerts, state = derive_chain_alerts({}, [_cc("R2")], NOW)
    assert len(alerts) == 1
    assert alerts[0].category == "STARTED"
    assert alerts[0].route_id == "I-80"
    assert state[CC_KEY] == "R2"


def test_chain_escalated():
    alerts, _ = derive_chain_alerts({CC_KEY: "R2"}, [_cc("R3")], NOW)
    assert alerts[0].category == "ESCALATED"


def test_chain_eased():
    alerts, _ = derive_chain_alerts({CC_KEY: "R3"}, [_cc("R1")], NOW)
    assert alerts[0].category == "EASED"


def test_chain_lifted():
    alerts, _ = derive_chain_alerts({CC_KEY: "R1"}, [_cc("None")], NOW)
    assert alerts[0].category == "LIFTED"


def test_chain_unchanged_emits_nothing():
    alerts, _ = derive_chain_alerts({CC_KEY: "R2"}, [_cc("R2")], NOW)
    assert alerts == []


def test_station_missing_one_poll_is_not_re_announced():
    # R2 seen, then the station drops out of one poll (a district fetch gap),
    # then returns unchanged. It must carry its state forward and NOT re-alert.
    _, after_seen = derive_chain_alerts({}, [_cc("R2")], NOW)
    _, after_gap = derive_chain_alerts(after_seen, [], NOW)   # feed gap: absent
    assert after_gap.get(CC_KEY) == "R2"                       # state preserved
    alerts, _ = derive_chain_alerts(after_gap, [_cc("R2")], NOW)
    assert alerts == []                                        # no false STARTED


def test_blank_named_stations_on_one_route_do_not_collide():
    # Two distinct I-80 stations, both with blank names — must not share a key.
    donner = ChainControl(location_name="", route="I-80", lat=39.3163, lon=-120.3208, status="R2")
    truckee = ChainControl(location_name="", route="I-80", lat=39.3280, lon=-120.1833, status="R1")
    alerts, state = derive_chain_alerts({}, [donner, truckee], NOW)
    assert len(alerts) == 2
    assert len([k for k in state if k.startswith("cc:")]) == 2


# --- CHP incidents -------------------------------------------------------------

def test_new_incident_emits_once():
    inc = _inc("100", "Traffic Collision", DONNER[0], DONNER[1], "I80 at Donner")
    alerts, state = derive_incident_alerts({}, [inc], NOW)
    assert len(alerts) == 1
    assert alerts[0].route_id == "I-80"
    assert "chp:100" in state
    # A later poll that still sees the same incident must not re-announce it.
    alerts_again, _ = derive_incident_alerts(state, [inc], NOW)
    assert alerts_again == []


def test_incident_off_route_dropped():
    inc = _inc("101", "Traffic Collision", 34.05, -118.25, "I5 in Los Angeles")
    alerts, _ = derive_incident_alerts({}, [inc], NOW)
    assert alerts == []


def test_incident_without_coords_dropped():
    inc = _inc("102", "Traffic Collision", None, None, "SR88 near Kirkwood")
    alerts, _ = derive_incident_alerts({}, [inc], NOW)
    assert alerts == []


# --- both layers together ------------------------------------------------------

def test_derive_alerts_combines_layers():
    derived = derive_alerts(
        {},
        [_cc("R2")],
        [_inc("200", "Traffic Collision", DONNER[0], DONNER[1], "I80 at Donner")],
        NOW,
    )
    assert sorted(a.kind for a in derived.alerts) == ["CHAIN_CONTROL", "INCIDENT"]
