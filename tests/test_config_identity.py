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

from custom_components.australian_fire_watch.const import config_entry_unique_id  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
