"""Deterministic unit tests for Queensland FDR and legal restriction parsing.

Load the pure provider modules without importing Home Assistant's integration
entry point. Compatible with `python -m unittest discover -s tests -v`.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PACKAGE_DIR = (
    Path(__file__).resolve().parents[1]
    / "custom_components" / "australian_fire_watch"
)
PACKAGE = "_afw_qld_unit"
if PACKAGE not in sys.modules:
    pkg = types.ModuleType(PACKAGE)
    pkg.__path__ = [str(PACKAGE_DIR)]
    sys.modules[PACKAGE] = pkg


def load(name):
    fullname = f"{PACKAGE}.{name}"
    if fullname not in sys.modules:
        spec = importlib.util.spec_from_file_location(fullname, PACKAGE_DIR / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[fullname] = module
        spec.loader.exec_module(module)
    return sys.modules[fullname]


parsers = load("qld_parsers")
arcgis = load("qld_arcgis")
NOW = datetime(2026, 10, 27, 23, 5, tzinfo=timezone.utc)


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def forecast_payload(now=NOW):
    base = datetime(2026, 10, 28, 0, tzinfo=parsers.AEST)
    ratings = ["Moderate", "High", "Extreme", "No Rating"]
    row = {"Area_Name": "Southeast Coast", "FMETimeStamp": ms(now - timedelta(hours=1))}
    for n, rating in enumerate(ratings, 1):
        row[f"Day{n}"] = rating
        row[f"Date{n}"] = ms(base + timedelta(days=n - 1))
    return {"features": [{"attributes": row}]}


def ban_payload(state="No Fire Ban"):
    return {"features": [{"attributes": {
        "SHIRE_NAME": "Brisbane City", "HASFIREBAN": state,
        "DATE_FROM": None, "DATE_TO": None, "FMETimestamp": None, "Link": None,
    }}]}




class TestQldParsers(unittest.TestCase):
    def test_calendar_dates_and_no_rating(self):
        data = parsers.parse_forecast(forecast_payload(), now=NOW)
        self.assertTrue(data["covered"])
        self.assertEqual(data["health"], "fresh")
        self.assertEqual([d["date"] for d in data["forecast"]], [
            "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31"
        ])
        self.assertEqual([d["rating"] for d in data["forecast"]], [
            "Moderate", "High", "Extreme", "No Rating"
        ])
        self.assertTrue(data["forecast"][3]["available"])
        danger = parsers.danger_from_forecast(data)
        self.assertEqual(danger["today"]["rating"], "Moderate")
        self.assertIsNone(danger["today"]["total_fire_ban"])

    def test_date_mapping_does_not_assume_day1_today(self):
        payload = forecast_payload()
        later = NOW + timedelta(days=1)
        # A new local day has started without an upstream roll-over.
        data = parsers.parse_forecast(payload, now=later)
        self.assertEqual(data["forecast"][0]["date"], "2026-10-29")
        self.assertEqual(data["forecast"][0]["rating"], "High")

    def test_stale_forecast_never_claims_availability(self):
        payload = forecast_payload()
        payload["features"][0]["attributes"]["FMETimeStamp"] = ms(NOW - timedelta(days=3))
        data = parsers.parse_forecast(payload, now=NOW)
        self.assertEqual(data["health"], "stale")
        self.assertFalse(any(item["available"] for item in data["forecast"]))

    def test_zero_matches_is_explicitly_out_of_coverage(self):
        data = parsers.parse_forecast({"features": []}, now=NOW)
        self.assertIs(data["covered"], False)

    def test_invalid_or_ambiguous_is_not_safe(self):
        with self.assertRaises(parsers.QldDataError):
            parsers.parse_forecast({"error": {"code": 498}}, now=NOW)
        with self.assertRaises(parsers.QldDataError):
            parsers.parse_local_fire_ban({"features": []})
        with self.assertRaises(parsers.QldDataError):
            parsers.parse_local_fire_ban({"features": ban_payload()["features"] * 2})
        with self.assertRaises(parsers.QldDataError):
            parsers.parse_forecast({"features": [{"attributes": {
                **forecast_payload()["features"][0]["attributes"], "Day1": "Very High"
            }}]}, now=NOW)

    def test_restriction_explicit_values(self):
        self.assertFalse(parsers.parse_local_fire_ban(ban_payload())["state"])
        self.assertTrue(parsers.parse_local_fire_ban(ban_payload("Fire Ban"))["state"])
        self.assertRaises(
            parsers.QldDataError,
            parsers.parse_local_fire_ban,
            ban_payload("Maybe"),
        )


class FakeContent:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    async def iter_chunked(self, chunk_size):
        for offset in range(0, len(self.payload), chunk_size):
            yield self.payload[offset:offset + chunk_size]


class FakeResponse:
    def __init__(self, payload, status=200):
        self.status, self.content = status, FakeContent(payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class FakeSession:
    def __init__(self, responses):
        self.responses = responses

    def get(self, url, *, params, headers):
        assert params["geometryType"] == "esriGeometryPoint"
        assert params["returnGeometry"] == "false"
        assert params["f"] == "json"
        return FakeResponse(self.responses[url])


class TestQldProvider(unittest.IsolatedAsyncioTestCase):
    async def test_independent_health_and_statuses(self):
        session = FakeSession({
            arcgis.FDR_URL: forecast_payload(),
            arcgis.BAN_URL: {"error": {"code": 498, "message": "blocked"}},
        })
        result = await arcgis.QldArcGISProvider(session).async_fetch(
            -27.4698, 153.0251, now=NOW
        )
        self.assertEqual(result["health"], "degraded")
        self.assertTrue(result["forecast"]["covered"])
        self.assertIsNone(result["local_fire_ban"]["state"])
        self.assertEqual(result["local_fire_ban"]["health"], "unavailable")
        self.assertNotIn("state_of_emergency", result)

    async def test_failed_fdr_does_not_block_valid_fire_ban(self):
        session = FakeSession({
            arcgis.FDR_URL: {"error": {"code": 400}},
            arcgis.BAN_URL: ban_payload("Fire Ban"),
        })
        result = await arcgis.QldArcGISProvider(session).async_fetch(
            -27.4698, 153.0251, now=NOW
        )
        self.assertIsNone(result["forecast"]["covered"])
        self.assertEqual(result["health"], "degraded")
        self.assertTrue(result["local_fire_ban"]["state"])


class TestQldCompatibility(unittest.TestCase):
    def test_qld_ban_reuses_today_value_even_without_fdr(self):
        danger = parsers.danger_from_forecast(
            {"district": "Southeast Coast", "forecast": [], "health": "unavailable"}
        )
        result = parsers.danger_with_local_fire_ban(
            danger,
            {"health": "fresh", **parsers.parse_local_fire_ban(ban_payload("Fire Ban"))},
        )
        self.assertIs(result["today"]["total_fire_ban"], True)
        self.assertTrue(result["today"]["total_fire_ban_available"])
        self.assertFalse(result["today"]["available"])
        self.assertEqual(result["today"]["fire_ban_lga"], "Brisbane City")
        self.assertIsNone(danger["today"]["total_fire_ban"])

    def test_unavailable_qld_ban_never_claims_no_ban(self):
        danger = parsers.danger_from_forecast(
            parsers.parse_forecast(forecast_payload(), now=NOW)
        )
        result = parsers.danger_with_local_fire_ban(
            danger, {"health": "unavailable", "error": "request failed"}
        )
        self.assertIsNone(result["today"]["total_fire_ban"])
        self.assertFalse(result["today"]["total_fire_ban_available"])
        self.assertTrue(result["today"]["available"])

    def test_qld_feed_failure_uses_existing_feed_health_and_problem(self):
        feed = {
            "status": "fresh", "assessment_complete": True,
            "current_incident_feeds": ["qld_incidents"],
            "sources": {"qld_incidents": {"status": "fresh"}},
            "message": None,
        }
        qld = {
            "health": "degraded",
            "forecast": {"health": "fresh", "checked_at": NOW.isoformat()},
            "local_fire_ban": {"health": "unavailable", "error": "request failed"},
        }
        merged = parsers.merge_qld_feed_health(feed, qld)
        self.assertEqual(merged["status"], "degraded")
        self.assertTrue(merged["assessment_complete"])
        self.assertEqual(merged["current_incident_feeds"], ["qld_incidents"])
        self.assertEqual(merged["sources"]["qld_local_fire_ban"]["status"], "unavailable")
        self.assertIn("local_fire_ban", merged["message"])
        self.assertEqual(feed["status"], "fresh")

    def test_healthy_qld_does_not_change_existing_feed_health(self):
        feed = {"status": "fresh", "assessment_complete": True, "sources": {}}
        qld = {
            "health": "fresh",
            "forecast": {"health": "fresh"},
            "local_fire_ban": {"health": "fresh"},
        }
        merged = parsers.merge_qld_feed_health(feed, qld)
        self.assertEqual(merged["status"], "fresh")
        self.assertEqual(len(merged["sources"]), 2)

    def test_missing_qld_does_not_hide_incident_outage(self):
        feed = {"status": "unavailable", "assessment_complete": False}
        merged = parsers.merge_qld_feed_health(feed, arcgis.empty_qld())
        self.assertEqual(merged["status"], "unavailable")

    def test_removed_entities_are_not_registered(self):
        import ast
        root = PACKAGE_DIR
        sensors = ast.parse((root / "sensor.py").read_text())
        binaries = ast.parse((root / "binary_sensor.py").read_text())
        joined = (root / "sensor.py").read_text() + (root / "binary_sensor.py").read_text()
        self.assertNotIn("FireWatchQldHealthSensor", joined)
        self.assertNotIn("FireWatchQldRestrictionBinarySensor", joined)
        self.assertNotIn("qld_fire_danger_day_3", joined)
        self.assertNotIn("qld_fire_danger_day_4", joined)
        self.assertIn("qld_fire_danger_day_2", joined)
        self.assertTrue(sensors.body)
        self.assertTrue(binaries.body)


if __name__ == "__main__":
    unittest.main()
