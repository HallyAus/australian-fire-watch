"""Pure incident ranking and lifecycle regression tests."""

from __future__ import annotations

import unittest
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

from custom_components.australian_fire_watch.model import (  # noqa: E402
    Incident,
    authoritative_incident_snapshot_valid,
    classify_transition,
    incident_event_summary,
    incident_entity_id,
    incident_notification_priority,
    incident_snapshot,
    sort_incidents,
    sort_incidents_by_distance,
    track_incident_lifecycle,
)


class IncidentModelTests(unittest.TestCase):
    def test_geo_entity_id_is_valid_lowercase(self) -> None:
        entity_id = incident_entity_id("01M16G3T2VNK", "incident-1")
        self.assertEqual(entity_id, entity_id.lower())
        self.assertTrue(entity_id.startswith("geo_location.australian_fire_watch_"))

    def test_authoritative_snapshot_rejects_partial_or_unexpected_empty(self) -> None:
        self.assertFalse(
            authoritative_incident_snapshot_valid(
                response_received=True,
                parsed_count=2,
                advertised_count=3,
                existing_record_count=1,
            )
        )
        self.assertFalse(
            authoritative_incident_snapshot_valid(
                response_received=True,
                parsed_count=0,
                advertised_count=0,
                existing_record_count=1,
            )
        )
        self.assertTrue(
            authoritative_incident_snapshot_valid(
                response_received=True,
                parsed_count=3,
                advertised_count=3,
                existing_record_count=1,
            )
        )
        self.assertTrue(
            authoritative_incident_snapshot_valid(
                response_received=True,
                parsed_count=0,
                advertised_count=0,
                existing_record_count=1,
                empty_corroborated=True,
            )
        )

    def test_warning_ranks_before_distance(self) -> None:
        advice = Incident(
            id="advice",
            title="Advice fire",
            warning_level="Advice",
            distance_km=40,
            is_fire=True,
        )
        unclassified = Incident(
            id="near",
            title="Near fire",
            warning_level="Not Applicable",
            distance_km=2,
            is_fire=True,
        )
        self.assertEqual(sort_incidents((unclassified, advice))[0].id, "advice")

    def test_display_list_is_nearest_without_changing_alert_priority(self) -> None:
        emergency = Incident(
            id="emergency",
            title="Distant emergency",
            warning_level="Emergency Warning",
            distance_km=40,
            is_fire=True,
        )
        nearby = Incident(
            id="nearby",
            title="Nearby unclassified fire",
            warning_level="Not Applicable",
            distance_km=2,
            is_fire=True,
        )
        unknown = Incident(
            id="unknown",
            title="Unknown distance",
            warning_level="Watch and Act",
            distance_km=None,
            is_fire=True,
        )

        incidents = (nearby, unknown, emergency)
        self.assertEqual(
            [item.id for item in sort_incidents_by_distance(incidents)],
            ["nearby", "emergency", "unknown"],
        )
        self.assertEqual(sort_incidents(incidents)[0].id, "emergency")

    def test_planned_display_list_is_nearest_first(self) -> None:
        farther = Incident(
            id="farther",
            title="Far hazard reduction",
            distance_km=30,
            is_planned=True,
        )
        nearer = Incident(
            id="nearer",
            title="Near hazard reduction",
            distance_km=5,
            is_planned=True,
        )
        unknown = Incident(
            id="unknown-planned",
            title="Unlocated hazard reduction",
            distance_km=None,
            is_planned=True,
        )
        self.assertEqual(
            [
                item.id
                for item in sort_incidents_by_distance((farther, unknown, nearer))
            ],
            ["nearer", "farther", "unknown-planned"],
        )

    def test_small_size_changes_do_not_create_update_churn(self) -> None:
        original = Incident(id="fire-1", title="Fire", size_ha=1.0)
        changed_size = Incident(id="fire-1", title="Fire", size_ha=1.1)
        self.assertIsNone(
            classify_transition(incident_snapshot(original), changed_size)
        )

    def test_resolution_retains_previous_qualification(self) -> None:
        incident = Incident(id="fire-1", title="Ridge fire", distance_km=4)
        records, events, baseline = track_incident_lifecycle(
            {}, (incident,), {incident.id}, baseline_complete=False
        )
        self.assertTrue(baseline)
        self.assertEqual(events, ())
        self.assertTrue(records[incident.id]["qualified"])

        records, events, _ = track_incident_lifecycle(
            records, (), (), baseline_complete=True
        )
        self.assertEqual(events, ())
        self.assertEqual(records[incident.id]["missing_count"], 1)

        records, events, _ = track_incident_lifecycle(
            records, (), (), baseline_complete=True
        )
        self.assertEqual(records, {})
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.lifecycle, "resolved")
        self.assertTrue(event.qualifies_for_alert)
        self.assertIn("no longer in current feed", incident_event_summary(event))
        self.assertNotIn("all clear", incident_event_summary(event).casefold())
        self.assertEqual(incident_notification_priority(event), "normal")

    def test_incident_outside_monitor_radius_is_not_resolved(self) -> None:
        inside = Incident(id="fire-1", title="Ridge fire", distance_km=5)
        outside = Incident(id="fire-1", title="Ridge fire", distance_km=180)
        records, _, _ = track_incident_lifecycle(
            {}, (inside,), {inside.id}, baseline_complete=False
        )
        records, events, _ = track_incident_lifecycle(
            records,
            (),
            (),
            baseline_complete=True,
            authoritative_incidents=(outside,),
        )
        self.assertEqual(records, {})
        self.assertEqual(events[0].lifecycle, "left_radius")
        self.assertNotIn("no longer in current feed", incident_event_summary(events[0]))
        self.assertEqual(incident_notification_priority(events[0]), "normal")

    def test_reappearance_resets_missing_counter_persistently(self) -> None:
        incident = Incident(id="fire-1", title="Fire")
        records, _, _ = track_incident_lifecycle(
            {}, (incident,), (), baseline_complete=False
        )
        records, _, _ = track_incident_lifecycle(
            records, (), (), baseline_complete=True
        )
        self.assertEqual(records[incident.id]["missing_count"], 1)
        records, events, _ = track_incident_lifecycle(
            records, (incident,), (), baseline_complete=True
        )
        self.assertEqual(events, ())
        self.assertEqual(records[incident.id]["missing_count"], 0)

    def test_exact_configured_radius_entry_escalates(self) -> None:
        outside = Incident(
            id="fire-1", title="Fire", warning_level="Advice", distance_km=31
        )
        inside = Incident(
            id="fire-1", title="Fire", warning_level="Advice", distance_km=29
        )
        records, _, _ = track_incident_lifecycle(
            {}, (outside,), (), baseline_complete=False
        )
        _, events, _ = track_incident_lifecycle(
            records, (inside,), {inside.id}, baseline_complete=True
        )
        self.assertEqual("escalated", events[0].lifecycle)
        self.assertTrue(events[0].qualifies_for_alert)

    def test_missing_does_not_advance_without_source_quorum(self) -> None:
        incident = Incident(id="fire-1", title="Fire")
        records, _, _ = track_incident_lifecycle(
            {}, (incident,), {incident.id}, baseline_complete=False
        )
        records, events, _ = track_incident_lifecycle(
            records,
            (),
            (),
            baseline_complete=True,
            allow_missing_updates=False,
        )
        self.assertEqual((), events)
        self.assertEqual(0, records[incident.id]["missing_count"])

    def test_lifecycle_snapshot_retains_incident_official_url(self) -> None:
        incident = Incident(
            "qld-one",
            "Border fire",
            official_url="https://www.fire.qld.gov.au/Current-Incidents",
        )
        self.assertEqual(
            incident.official_url,
            incident_snapshot(incident)["official_url"],
        )


if __name__ == "__main__":
    unittest.main()
