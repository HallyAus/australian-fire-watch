"""AFDRS and Total Fire Ban lifecycle tests."""

from __future__ import annotations

import unittest
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

from custom_components.nsw_fire_watch.model import (  # noqa: E402
    danger_notification_priority,
    track_danger_lifecycle,
)


def danger(
    today_rating: str = "Moderate",
    tomorrow_rating: str = "Moderate",
    *,
    today_ban: bool | None = False,
    tomorrow_ban: bool | None = False,
    today_date: str = "2026-08-29",
    tomorrow_date: str = "2026-08-30",
) -> dict:
    return {
        "district": "Greater Sydney Region",
        "today": {
            "date": today_date,
            "rating": today_rating,
            "total_fire_ban": today_ban,
            "issued_at": "2026-08-29T00:00:00+00:00",
            "rating_source": "NSW RFS fdrToban.xml",
        },
        "tomorrow": {
            "date": tomorrow_date,
            "rating": tomorrow_rating,
            "total_fire_ban": tomorrow_ban,
            "issued_at": "2026-08-29T00:00:00+00:00",
            "rating_source": "NSW RFS fdrToban.xml",
        },
    }


class DangerLifecycleTests(unittest.TestCase):
    def test_initial_baseline_suppresses_existing_danger(self) -> None:
        records, events, baseline = track_danger_lifecycle(
            {}, danger("Catastrophic", today_ban=True), baseline_complete=False
        )
        self.assertTrue(baseline)
        self.assertEqual(events, ())
        self.assertTrue(records["2026-08-29"]["qualifies"])

    def test_unchanged_refresh_is_deduplicated(self) -> None:
        records, _, _ = track_danger_lifecycle(
            {}, danger("High"), baseline_complete=False
        )
        _, events, _ = track_danger_lifecycle(
            records, danger("High"), baseline_complete=True
        )
        self.assertEqual(events, ())

    def test_tomorrow_becoming_today_does_not_duplicate_same_date(self) -> None:
        records, _, _ = track_danger_lifecycle(
            {}, danger("Moderate", "High"), baseline_complete=False
        )
        rolled = danger(
            "High",
            "Moderate",
            today_date="2026-08-30",
            tomorrow_date="2026-08-31",
        )
        _, events, _ = track_danger_lifecycle(records, rolled, baseline_complete=True)
        self.assertEqual(events, ())

    def test_high_extreme_and_clear_transitions(self) -> None:
        records, _, _ = track_danger_lifecycle(
            {}, danger("Moderate"), baseline_complete=False
        )
        records, events, _ = track_danger_lifecycle(
            records, danger("High"), baseline_complete=True
        )
        self.assertEqual(events[0].lifecycle, "escalated")
        self.assertTrue(events[0].qualifies_for_alert)
        self.assertEqual(
            danger_notification_priority(events[0].danger, events[0].lifecycle),
            "normal",
        )

        records, events, _ = track_danger_lifecycle(
            records, danger("Extreme"), baseline_complete=True
        )
        self.assertEqual(events[0].lifecycle, "escalated")
        self.assertEqual(
            danger_notification_priority(events[0].danger, events[0].lifecycle),
            "time_sensitive",
        )

        _, events, _ = track_danger_lifecycle(
            records, danger("No Rating"), baseline_complete=True
        )
        self.assertEqual(events[0].lifecycle, "resolved")
        self.assertTrue(events[0].qualifies_for_alert)
        self.assertEqual(
            danger_notification_priority(events[0].danger, events[0].lifecycle),
            "normal",
        )

    def test_total_fire_ban_today_is_critical_but_tomorrow_is_not(self) -> None:
        records, _, _ = track_danger_lifecycle({}, danger(), baseline_complete=False)
        _, events, _ = track_danger_lifecycle(
            records, danger(today_ban=True, tomorrow_ban=True), baseline_complete=True
        )
        by_period = {event.danger["period"]: event for event in events}
        today = by_period["today"]
        tomorrow = by_period["tomorrow"]
        self.assertEqual(
            danger_notification_priority(today.danger, today.lifecycle), "critical"
        )
        self.assertEqual(
            danger_notification_priority(tomorrow.danger, tomorrow.lifecycle),
            "time_sensitive",
        )

    def test_tomorrow_ban_becoming_today_upgrades_to_critical(self) -> None:
        records, _, _ = track_danger_lifecycle(
            {}, danger(tomorrow_ban=True), baseline_complete=False
        )
        rolled = danger(
            "Moderate",
            "Moderate",
            today_ban=True,
            tomorrow_ban=False,
            today_date="2026-08-30",
            tomorrow_date="2026-08-31",
        )
        _, events, _ = track_danger_lifecycle(records, rolled, baseline_complete=True)
        event = next(item for item in events if item.danger_id == "2026-08-30")
        self.assertEqual("escalated", event.lifecycle)
        self.assertEqual(
            "critical",
            danger_notification_priority(event.danger, event.lifecycle),
        )

    def test_unknown_field_does_not_clear_previous_known_declaration(self) -> None:
        records, _, _ = track_danger_lifecycle(
            {}, danger("High", today_ban=True), baseline_complete=False
        )
        records, events, _ = track_danger_lifecycle(
            records,
            danger("Unknown", today_ban=None),
            baseline_complete=True,
        )
        self.assertEqual(events, ())
        self.assertEqual(records["2026-08-29"]["rating"], "High")
        self.assertTrue(records["2026-08-29"]["total_fire_ban"])

    def test_tests_are_never_critical(self) -> None:
        detail = {
            "period": "today",
            "rating": "Catastrophic",
            "total_fire_ban": True,
        }
        self.assertEqual(
            danger_notification_priority(detail, "escalated", test=True), "normal"
        )


if __name__ == "__main__":
    unittest.main()
