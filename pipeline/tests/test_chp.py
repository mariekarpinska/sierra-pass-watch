from pathlib import Path

from pytest import approx

from pipeline.sources.chp import classify_incident, parse_incidents

FIXTURES = Path(__file__).parent / "fixtures"


def test_classify_incident():
    assert classify_incident("1183-Trfc Collision-Unkn Inj") == "COLLISION"
    assert classify_incident("1125-Traffic Hazard") == "HAZARD"
    assert classify_incident("Full Closure of Road") == "CLOSURE"
    assert classify_incident("Assist Other Agency") == "OTHER"
    assert classify_incident(None) == "OTHER"


def test_parse_incidents_fixture():
    xml_text = (FIXTURES / "chp_sample.xml").read_text(encoding="utf-8")
    incidents = parse_incidents(xml_text)
    assert len(incidents) == 4  # flattened across both Centers

    by_id = {i.incident_id: i for i in incidents}

    donner = by_id["260710ST0001"]
    assert donner.category == "COLLISION"
    assert donner.lat == approx(39.3163)      # packed micro-degrees decoded
    assert donner.lon == approx(-120.3208)    # longitude negated (west)
    assert donner.location_text == "I80 E of Donner Pass Rd"  # wrapping quotes stripped
    assert donner.log_time == "2026-07-10T07:04:00+00:00"     # 00:04 PDT → 07:04 UTC

    assert by_id["260710ST0002"].category == "HAZARD"
    assert by_id["260710ST0004"].lat is None  # empty LATLON → dropped downstream
    assert by_id["260710LA0003"].category == "COLLISION"


def test_parse_incidents_bad_xml_is_empty():
    assert parse_incidents("<not-valid") == []
