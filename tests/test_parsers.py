"""Official product parser contract tests."""

from __future__ import annotations

import json
import unittest
from datetime import timezone
from pathlib import Path
import sys
from types import ModuleType

_PACKAGE = "custom_components.nsw_fire_watch"
if _PACKAGE not in sys.modules:
    package = ModuleType(_PACKAGE)
    package.__path__ = [
        str(Path(__file__).parents[1] / "custom_components" / "nsw_fire_watch")
    ]
    sys.modules[_PACKAGE] = package

from custom_components.nsw_fire_watch.parsers import (  # noqa: E402
    FeedParseError,
    parse_cap,
    parse_geojson,
    parse_rfs_fire_danger,
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


if __name__ == "__main__":
    unittest.main()
