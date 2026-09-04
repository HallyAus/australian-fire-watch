"""Parser failures must not manufacture an empty current incident feed."""
import json
import pytest
from custom_components.australian_fire_watch.parsers import FeedParseError, parse_cap, parse_geojson, parse_rfs_fire_danger
from custom_components.australian_fire_watch.regional_parsers import parse_georss, parse_tas_kml, parse_vic_geojson, parse_qld_geojson, parse_qld_warning_geojson, parse_nt_json, fire_incidents_only
from custom_components.australian_fire_watch.model import Incident, ParsedFeed


@pytest.mark.parametrize("parser", [parse_cap, parse_rfs_fire_danger, lambda body: parse_tas_kml(body, official_url="https://example.invalid"), lambda body: parse_georss(body, official_url="https://example.invalid", source="Fixture")])
def test_maintenance_xml_rejected(parser):
    with pytest.raises(FeedParseError):
        parser(b"<html><body>Maintenance</body></html>")


@pytest.mark.parametrize("parser", [parse_geojson, lambda body: parse_vic_geojson(body, official_url="https://example.invalid"), lambda body: parse_qld_geojson(body, official_url="https://example.invalid"), lambda body: parse_qld_warning_geojson(body, official_url="https://example.invalid")])
@pytest.mark.parametrize("collection", [
    {"type": "FeatureCollection"},
    {"type": "FeatureCollection", "features": [None]},
    {"type": "FeatureCollection", "features": [{"properties": {}}]},
    {"type": "FeatureCollection", "features": [], "exceededTransferLimit": True},
])
def test_partial_geojson_rejected(parser, collection):
    with pytest.raises(FeedParseError):
        parser(json.dumps(collection))


def test_valid_empty_feeds_are_accepted():
    assert not parse_geojson('{"type":"FeatureCollection","features":[]}').incidents
    assert not parse_cap('<distribution><distributionID>empty-fixture</distributionID></distribution>').incidents
    assert not parse_tas_kml('<kml><Document/></kml>', official_url="https://example.invalid").incidents
    assert not parse_georss('<rss><channel/></rss>', official_url="https://example.invalid", source="Fixture").incidents


@pytest.mark.parametrize("body", [
    '<distribution><alert><identifier>a</identifier><status>Actual</status></alert></distribution>',
    '<distribution><alert><status>Actual</status><info><event>Bushfire</event></info></alert></distribution>',
])
def test_incomplete_actual_cap_rejected(body):
    with pytest.raises(FeedParseError):
        parse_cap(body)


def test_incomplete_nt_record_rejected():
    with pytest.raises(FeedParseError):
        parse_nt_json(json.dumps({"incidents": {"type": "FeatureCollection", "features": [None]}}), official_url="https://example.invalid")


def test_structured_bushfire_is_not_excluded_by_prose():
    incident = Incident(id="fixture", title="Fixture", incident_type="Bushfire", description="Protect your house from a house fire.")
    assert fire_incidents_only(ParsedFeed((incident,))).incidents == (incident,)


@pytest.mark.parametrize("kind", ["Structure Fire", "Vehicle Fire", "Building Fire", "FIRE STRUCTURE", "FIRE VEHICLE"])
def test_structured_non_bushfire_excluded(kind):
    incident = Incident(id="fixture", title="Fixture", incident_type=kind, is_fire=True)
    assert not fire_incidents_only(ParsedFeed((incident,))).incidents


def test_polygon_holes_preserved():
    data = {"type": "FeatureCollection", "features": [{"properties": {"guid": "fixture", "category": "Emergency Warning"}, "geometry": {"type": "Polygon", "coordinates": [[[-2,-2],[2,-2],[2,2],[-2,2],[-2,-2]],[[-1,-1],[1,-1],[1,1],[-1,1],[-1,-1]]]}}]}
    incident = parse_geojson(json.dumps(data)).incidents[0].with_home(0, 0)
    assert incident.inside_warning_area is False
    assert incident.warning_area_distance_km > 100


def test_invalid_cap_polygon_rejected():
    with pytest.raises(FeedParseError):
        parse_cap('<alert><identifier>a</identifier><status>Actual</status><info><area><polygon>0,0 bad 1,1</polygon></area></info></alert>')
