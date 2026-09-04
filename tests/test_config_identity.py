"""Configuration identity regression tests."""

from __future__ import annotations

from pathlib import Path
import sys
from types import ModuleType
import unittest

_PACKAGE = "custom_components.nsw_fire_watch"
if _PACKAGE not in sys.modules:
    package = ModuleType(_PACKAGE)
    package.__path__ = [
        str(Path(__file__).parents[1] / "custom_components" / "nsw_fire_watch")
    ]
    sys.modules[_PACKAGE] = package

from custom_components.nsw_fire_watch.const import config_entry_unique_id  # noqa: E402


class ConfigIdentityTests(unittest.TestCase):
    """Keep legacy migration and YAML import on one stable identity."""

    def test_legacy_nsw_entry_matches_national_yaml_import(self) -> None:
        legacy = {
            "zone": "zone.home",
            "fire_danger_district": "Greater Sydney Region",
        }
        national = {**legacy, "jurisdiction": "NSW"}
        self.assertEqual(
            config_entry_unique_id(legacy), config_entry_unique_id(national)
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
