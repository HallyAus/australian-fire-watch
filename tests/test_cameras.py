"""Public camera catalogue and distance boundary regression tests."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys
from types import ModuleType
from urllib.parse import unquote, urlparse

_PACKAGE = "custom_components.australian_fire_watch"
if _PACKAGE not in sys.modules:
    package = ModuleType(_PACKAGE)
    package.__path__ = [
        str(Path(__file__).parents[1] / "custom_components" / "australian_fire_watch")
    ]
    sys.modules[_PACKAGE] = package

from custom_components.australian_fire_watch.cameras import (  # noqa: E402
    CAMERA_SITES,
    camera_catalogue,
    camera_url,
    nearby_camera_sites,
)
from custom_components.australian_fire_watch.model import haversine_km  # noqa: E402


class CameraTests(unittest.TestCase):
    def test_provider_catalogue_groups_25_views_at_16_sites(self):
        self.assertEqual(len(camera_catalogue()), 16)
        self.assertEqual(sum(len(site[5]) for site in CAMERA_SITES), 25)
        for site_id, name, _region, _lat, _lon, views in CAMERA_SITES:
            for view in views:
                parsed = urlparse(camera_url(site_id, view))
                self.assertEqual(parsed.netloc, "centralwatch.watchtowers.io")
                self.assertEqual(
                    unquote(unquote(parsed.query.removeprefix("camera="))),
                    f"{name} - {view}",
                )
        self.assertEqual(
            camera_url("kowen", "Guard"),
            "https://centralwatch.watchtowers.io/au?camera=Kowen%2520Forest%2520-%2520Guard",
        )

    def test_matches_are_grouped_sorted_and_independent_of_jurisdiction(self):
        # A public point just west of the ACT boundary can match ACT cameras.
        matches = nearby_camera_sites(-35.307321, 148.80)
        self.assertEqual(matches[0]["site_id"], "coree")
        self.assertEqual(len({item["site_id"] for item in matches}), len(matches))
        self.assertLessEqual(len(matches), 3)
        self.assertEqual(
            [item["distance_km"] for item in matches],
            sorted(item["distance_km"] for item in matches),
        )

    def test_radius_is_checked_before_rounding(self):
        distance = haversine_km(-35.30, 149.0, -35.275066, 149.275159)

        def ids(radius):
            return {
                item["site_id"]
                for item in nearby_camera_sites(-35.30, 149.0, radius, limit=16)
            }

        self.assertIn("kowen", ids(distance))
        self.assertNotIn("kowen", ids(distance - 0.00001))

    def test_missing_invalid_and_distant_points_do_not_match(self):
        for lat, lon in [
            (None, 149),
            (-35, None),
            (float("nan"), 149),
            (-35, float("inf")),
            (91, 149),
            (-35, 181),
            (-31.95, 115.86),
        ]:
            self.assertEqual(nearby_camera_sites(lat, lon), [])
        self.assertEqual(nearby_camera_sites(-35.3, 149, float("nan")), [])

    def test_configured_radius_changes_matches(self):
        self.assertEqual(
            nearby_camera_sites(-35.275066, 149.275159, 1),
            [{"site_id": "kowen", "distance_km": 0.0}],
        )
        self.assertGreater(len(nearby_camera_sites(-35.275066, 149.275159, 30)), 1)
