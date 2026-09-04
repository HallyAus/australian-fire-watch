"""Official product parser contract tests."""

from __future__ import annotations

import json
import unittest
from datetime import timezone
from pathlib import Path
import sys
from types import ModuleType

_PACKAGE = "custom_components.australian_fire_watch"
if _PACKAGE not in sys.modules:
    package = ModuleType(_PACKAGE)
    package.__path__ = [
        str(Path(__file__).parents[1] / "custom_components" / "australian_fire_watch")
    ]
    sys.modules[_PACKAGE] = package

from custom_components.australian_fire_watch.parsers import (  # noqa: E402
    FeedParseError,
    parse_cap,
    parse_geojson,
    parse_rfs_fire_danger,
)
from custom_components.australian_fire_watch.regional_parsers import (  # noqa: E402
    fire_incidents_only,
    parse_georss,
    parse_nt_json,
    parse_qld_geojson,
    parse_qld_warning_geojson,
    parse_tas_kml,
    parse_vic_geojson,
)
from custom_components.australian_fire_watch.jurisdictions import (  # noqa: E402
    JURISDICTIONS,
)


class ParserTests(unittest.TestCase):
    def test_rfs_danger_and_total_fire_ban_are_normalized(self) -> None:
        parsed = parse_rfs_fire_danger(
            """
            <FireDangerMap>
              <District>
                <Name>Greater Sydney Region</Name>
                <DangerLevelToday>Very High</DangerLevelToday>
                <FireBanToday>Yes</FireBanToday>
                <DangerLevelTomorrow>Severe</DangerLevelTomorrow>
                <FireBanTomorrow>No</FireBanTomorrow>
              </District>
            </FireDangerMap>
            """
        )
        district = parsed["Greater Sydney Region"]
        self.assertEqual(district["today"]["rating"], "High")
        self.assertIs(district["today"]["total_fire_ban"], True)
        self.assertEqual(district["tomorrow"]["rating"], "Extreme")
        self.assertIs(district["tomorrow"]["total_fire_ban"], False)

    def test_cap_keeps_warning_and_control_status_separate(self) -> None:
        parsed = parse_cap(
            """
            <distribution>
              <dateTimeSent>2026-08-29T01:00:00Z</dateTimeSent>
              <alert>
                <identifier>alert-1</identifier><incidents>incident-1</incidents>
                <status>Actual</status><sent>2026-08-29T01:00:00Z</sent>
                <info>
                  <event>Bush Fire</event><headline>Ridge Road</headline>
                  <parameter><valueName>AlertLevel</valueName><value>Watch and Act</value></parameter>
                  <parameter><valueName>Status</valueName><value>Being controlled</value></parameter>
                  <area><areaDesc>Ridge Road</areaDesc><circle>-33.1,151.2 1</circle></area>
                </info>
              </alert>
            </distribution>
            """
        )
        incident = parsed.incidents[0]
        self.assertEqual(incident.id, "incident-1")
        self.assertEqual(incident.warning_level, "Watch and Act")
        self.assertEqual(incident.control_status, "Being controlled")

    def test_cap_exercise_test_and_missing_status_are_not_live(self) -> None:
        parsed = parse_cap(
            """
            <distribution>
              <alert><identifier>live</identifier><status>Actual</status>
                <info><event>Bush Fire</event><headline>Live</headline></info>
              </alert>
              <alert><identifier>test</identifier><status>Test</status>
                <info><event>Bush Fire</event><headline>Test</headline></info>
              </alert>
              <alert><identifier>exercise</identifier><status>Exercise</status>
                <info><event>Bush Fire</event><headline>Exercise</headline></info>
              </alert>
              <alert><identifier>unknown</identifier>
                <info><event>Bush Fire</event><headline>Unknown</headline></info>
              </alert>
            </distribution>
            """
        )
        self.assertEqual(["live"], [incident.id for incident in parsed.incidents])

    def test_geojson_reports_raw_feature_count_for_snapshot_validation(self) -> None:
        payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "guid": "https://example.invalid/incidents/abc",
                        "title": "Creek fire",
                        "category": "Advice",
                    },
                    "geometry": {"type": "Point", "coordinates": [151.2, -33.1]},
                }
            ],
        }
        parsed = parse_geojson(json.dumps(payload))
        self.assertEqual(parsed.metadata["feature_count"], 1)
        self.assertEqual(len(parsed.incidents), 1)

    def test_geojson_naive_updated_time_is_nsw_local(self) -> None:
        payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "guid": "https://example.invalid/incidents/time-test",
                        "title": "Fixture incident",
                        "category": "Advice",
                        # This is the live RFS description format. Python's
                        # email-date parser accepts it as a naive datetime, so
                        # it must retain the explicit NSW-local assumption.
                        "description": "UPDATED: 29 Aug 2026 18:30\nTYPE: Bush Fire",
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [151.0, -33.0],
                    },
                }
            ],
        }
        incident = parse_geojson(json.dumps(payload)).incidents[0]
        self.assertEqual(timezone.utc, incident.updated_at.tzinfo)
        self.assertEqual("2026-08-29T08:30:00+00:00", incident.updated_at.isoformat())

    def test_xml_entity_declarations_are_rejected(self) -> None:
        with self.assertRaises(FeedParseError):
            parse_rfs_fire_danger(
                '<!DOCTYPE x [<!ENTITY bad "value">]><FireDangerMap />'
            )

    def test_every_australian_jurisdiction_has_an_official_profile(self) -> None:
        self.assertEqual(
            {"ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"},
            set(JURISDICTIONS),
        )
        for profile in JURISDICTIONS.values():
            self.assertTrue(profile.official_url.startswith("https://"))
            self.assertTrue(profile.agency)

    def test_victoria_keeps_bushfire_and_excludes_structure_fire(self) -> None:
        payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "properties": {
                        "id": "warning-1",
                        "feedType": "warning",
                        "category1": "Watch and Act",
                        "category2": "Bushfire",
                        "name": "Ridge fire",
                        "status": "Going",
                    },
                    "geometry": {"type": "Point", "coordinates": [144.2, -37.1]},
                },
                {
                    "properties": {
                        "id": "house-1",
                        "feedType": "incident",
                        "category1": "Fire",
                        "category2": "Structure Fire",
                        "name": "Building fire",
                    },
                    "geometry": {"type": "Point", "coordinates": [144.3, -37.2]},
                },
            ],
        }
        parsed = parse_vic_geojson(
            json.dumps(payload), official_url="https://emergency.vic.gov.au/"
        )
        self.assertEqual(1, len(parsed.incidents))
        self.assertEqual("Watch and Act", parsed.incidents[0].warning_level)

    def test_queensland_keeps_vegetation_and_planned_burns(self) -> None:
        payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "properties": {
                        "Master_Incident_Number": "Q1",
                        "GroupedType": "FIRE VEGETATION",
                        "CurrentStatus": "Going",
                        "Location": "Range Road",
                    },
                    "geometry": {"type": "Point", "coordinates": [153.1, -27.2]},
                },
                {
                    "properties": {
                        "Master_Incident_Number": "Q2",
                        "GroupedType": "FIRE STRUCTURE",
                        "Location": "Town",
                    },
                    "geometry": {"type": "Point", "coordinates": [153.2, -27.3]},
                },
            ],
        }
        parsed = parse_qld_geojson(
            json.dumps(payload), official_url="https://www.fire.qld.gov.au/"
        )
        self.assertEqual(["QLD-Q1"], [item.id for item in parsed.incidents])

    def test_queensland_warning_layer_preserves_official_warning_level(self) -> None:
        payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "properties": {
                        "UniqueID": "W1",
                        "EventType": "Fire",
                        "WarningTitle": "Bushfire warning",
                        "WarningLevel": "Watch and Act",
                        "WarningArea": "Example locality",
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [152.8, -27.4],
                    },
                }
            ],
        }
        parsed = parse_qld_warning_geojson(
            json.dumps(payload), official_url="https://www.fire.qld.gov.au/"
        )
        self.assertEqual("Watch and Act", parsed.incidents[0].warning_level)

    def test_georss_can_read_an_official_warning_level_from_the_title(self) -> None:
        parsed = parse_georss(
            """
            <rss xmlns:georss="http://www.georss.org/georss"><channel><item>
              <guid>W1</guid><title>Bushfire Watch and Act - Example locality</title>
              <description>TYPE: Bushfire</description>
              <georss:point>-31.9 115.9</georss:point>
            </item></channel></rss>
            """,
            official_url="https://www.emergency.wa.gov.au/",
            source="Department of Fire and Emergency Services WA",
        )
        self.assertEqual("Watch and Act", parsed.incidents[0].warning_level)

    def test_nt_closed_fire_is_not_current(self) -> None:
        payload = {
            "incidents": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "properties": {
                            "_id": "N1",
                            "_category": "Fire",
                            "_eventtype": "Bushfire",
                            "_status": "Closed",
                        },
                        "geometry": {"type": "Point", "coordinates": [131.0, -12.5]},
                    }
                ],
            }
        }
        parsed = parse_nt_json(
            json.dumps(payload), official_url="https://pfes.nt.gov.au/incidentmap"
        )
        self.assertFalse(parsed.incidents)

    def test_tasmania_current_feed_coordinate_order_is_detected(self) -> None:
        parsed = parse_tas_kml(
            """
            <kml><Document><Placemark><name>Bushfire - Lake Road</name>
              <description>TYPE: Bushfire\nSTATUS: Going\nALERT LEVEL: Advice</description>
              <Point><coordinates>-41.5,146.6,0</coordinates></Point>
            </Placemark></Document></kml>
            """,
            official_url="https://www.fire.tas.gov.au/",
        )
        self.assertEqual(1, len(parsed.incidents))
        self.assertEqual(
            (-41.5, 146.6),
            (parsed.incidents[0].latitude, parsed.incidents[0].longitude),
        )

    def test_tasmania_escaped_table_fields_are_parsed_and_structure_fires_filtered(
        self,
    ) -> None:
        parsed = parse_tas_kml(
            """
            <kml><Document><Placemark><name>Example incident</name>
              <description>&amp;lt;table&amp;gt;
                &amp;lt;tr&amp;gt;&amp;lt;th&amp;gt;Alert Level&amp;lt;/th&amp;gt;&amp;lt;td&amp;gt;Advice&amp;lt;/td&amp;gt;&amp;lt;/tr&amp;gt;
                &amp;lt;tr&amp;gt;&amp;lt;th&amp;gt;Type&amp;lt;/th&amp;gt;&amp;lt;td&amp;gt;STRUCTURE FIRE&amp;lt;/td&amp;gt;&amp;lt;/tr&amp;gt;
                &amp;lt;tr&amp;gt;&amp;lt;th&amp;gt;Status&amp;lt;/th&amp;gt;&amp;lt;td&amp;gt;Going&amp;lt;/td&amp;gt;&amp;lt;/tr&amp;gt;
              &amp;lt;/table&amp;gt;</description>
              <Point><coordinates>-41.5,146.6,0</coordinates></Point>
            </Placemark></Document></kml>
            """,
            official_url="https://www.fire.tas.gov.au/",
        )
        self.assertEqual("Advice", parsed.incidents[0].warning_level)
        self.assertEqual("Going", parsed.incidents[0].control_status)
        self.assertFalse(fire_incidents_only(parsed).incidents)


if __name__ == "__main__":
    unittest.main()
