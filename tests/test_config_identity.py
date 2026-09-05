"""Configuration identity regression tests."""

from __future__ import annotations

from pathlib import Path
import sys
from types import ModuleType
import unittest

_PACKAGE = "custom_components.australian_fire_watch"
if _PACKAGE not in sys.modules:
    package = ModuleType(_PACKAGE)
    package.__path__ = [
        str(Path(__file__).parents[1] / "custom_components" / "australian_fire_watch")
    ]
    sys.modules[_PACKAGE] = package

from custom_components.australian_fire_watch.const import (  # noqa: E402
    config_entry_unique_id,
    jurisdiction_codes,
)


class ConfigIdentityTests(unittest.TestCase):
    """Keep UI and YAML configuration on one stable identity."""

    def test_default_nsw_entry_matches_explicit_nsw_entry(self) -> None:
        default = {
            "zone": "zone.home",
            "fire_danger_district": "Greater Sydney Region",
        }
        explicit = {**default, "jurisdiction": "NSW"}
        self.assertEqual(
            config_entry_unique_id(default), config_entry_unique_id(explicit)
        )

    def test_non_nsw_identity_ignores_nsw_district(self) -> None:
        victoria = {
            "zone": "zone.home",
            "jurisdiction": "VIC",
            "fire_danger_district": "Greater Sydney Region",
        }
        self.assertEqual("zone.home|vic|", config_entry_unique_id(victoria))

    def test_cross_border_identity_is_order_independent(self) -> None:
        queensland_nsw = {
            "zone": "zone.home",
            "jurisdictions": ["QLD", "NSW"],
            "fire_danger_district": "Far North Coast",
        }
        nsw_queensland = {
            **queensland_nsw,
            "jurisdictions": ["NSW", "QLD"],
        }
        self.assertEqual(
            "zone.home|nsw,qld|far north coast",
            config_entry_unique_id(queensland_nsw),
        )
        self.assertEqual(
            config_entry_unique_id(queensland_nsw),
            config_entry_unique_id(nsw_queensland),
        )

    def test_legacy_scalar_is_normalized_to_one_selection(self) -> None:
        self.assertEqual(("QLD",), jurisdiction_codes({"jurisdiction": "qld"}))
        self.assertEqual(
            ("QLD", "NSW"),
            jurisdiction_codes({"jurisdictions": ["qld", "NSW", "qld"]}),
        )


if __name__ == "__main__":
    unittest.main()
