import json
from pathlib import Path

from pipeline.sources.chp import classify_incident, parse_incidents

FIXTURES = Path(__file__).parent / "fixtures"


def test_classify_incident():
    assert classify_incident("1182-Trfc Collision-No Inj") == "COLLISION"
    assert classify_incident("1125-Traffic Hazard") == "HAZARD"
    assert classify_incident("Full Closure of Road") == "CLOSURE"
    assert classify_incident("Assist Other Agency") == "OTHER"
    assert classify_incident(None) == "OTHER"


def test_parse_incidents_fixture():
    payload = json.loads((FIXTURES / "chp_sample.json").read_text(encoding="utf-8"))
    incidents = parse_incidents(payload)
    assert len(incidents) == 4

    by_id = {i.incident_id: i for i in incidents}
    assert by_id["241001"].category == "COLLISION"
    assert by_id["241001"].lat == 39.3163
    assert by_id["241002"].category == "HAZARD"
    assert by_id["241004"].lat is None  # missing coords survive parsing, dropped later
