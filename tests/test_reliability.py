"""Offline regression tests for validation, spatial relevance and delivery."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from functools import partial
import json
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import AsyncMock

_PACKAGE = "custom_components.australian_fire_watch"
if _PACKAGE not in sys.modules:
    package = ModuleType(_PACKAGE)
    package.__path__ = [
        str(Path(__file__).parents[1] / "custom_components" / "australian_fire_watch")
    ]
    sys.modules[_PACKAGE] = package

from custom_components.australian_fire_watch.api import OfficialFeedClient
from custom_components.australian_fire_watch.geometry import warning_area_distance
from custom_components.australian_fire_watch.model import (
    Incident,
    incident_snapshot,
    track_incident_lifecycle,
)
from custom_components.australian_fire_watch.notifications import NotificationOutbox
from custom_components.australian_fire_watch.parsers import (
    FeedParseError,
    parse_cap,
    parse_geojson,
    parse_rfs_fire_danger,
)
from custom_components.australian_fire_watch.regional_parsers import (
    fire_incidents_only,
    parse_georss,
    parse_nt_json,
    parse_qld_geojson,
    parse_qld_warning_geojson,
    parse_tas_kml,
    parse_vic_geojson,
)

NOW = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)
EMPTY_CAP = (
    b"<distribution><dateTimeSent>2026-09-05T00:00:00Z</dateTimeSent></distribution>"
)
EMPTY_GEO = b'{"type":"FeatureCollection","features":[]}'
OFFICIAL = "https://example.invalid/official"


class ValidationTests(unittest.TestCase):
    def test_wrong_xml_product_is_not_an_empty_feed(self):
        parsers = [
            parse_cap,
            parse_rfs_fire_danger,
            partial(parse_tas_kml, official_url=OFFICIAL),
            partial(parse_georss, official_url=OFFICIAL, source="Fixture"),
        ]
        for parser in parsers:
            with self.subTest(parser=parser):
                with self.assertRaises(FeedParseError):
                    parser(b"<html><body>Maintenance</body></html>")

    def test_valid_empty_products_are_distinct_from_errors(self):
        self.assertFalse(parse_cap(EMPTY_CAP).incidents)
        self.assertFalse(parse_geojson(EMPTY_GEO).incidents)
        self.assertFalse(
            parse_tas_kml(b"<kml><Document/></kml>", official_url=OFFICIAL).incidents
        )
        self.assertFalse(
            parse_georss(
                b"<rss><channel/></rss>", official_url=OFFICIAL, source="Fixture"
            ).incidents
        )

    def test_incomplete_cap_record_is_rejected(self):
        with self.assertRaises(FeedParseError):
            parse_cap(
                b"<alert><status>Actual</status><identifier>one</identifier></alert>"
            )
        with self.assertRaises(FeedParseError):
            parse_cap(b"<distribution/>")

    def test_malformed_and_truncated_feature_collections_are_rejected(self):
        parsers = [
            parse_geojson,
            partial(parse_vic_geojson, official_url=OFFICIAL),
            partial(parse_qld_geojson, official_url=OFFICIAL),
            partial(parse_qld_warning_geojson, official_url=OFFICIAL),
        ]
        for parser in parsers:
            for payload in [
                {"type": "FeatureCollection"},
                {"type": "FeatureCollection", "features": [None]},
                {"type": "FeatureCollection", "features": [{"properties": []}]},
                {
                    "type": "FeatureCollection",
                    "features": [],
                    "exceededTransferLimit": True,
                },
                {
                    "type": "FeatureCollection",
                    "features": [{"properties": {"renamed_schema": "fire"}}],
                },
            ]:
                with self.subTest(parser=parser, payload=payload):
                    with self.assertRaises(FeedParseError):
                        parser(json.dumps(payload))

    def test_nt_invalid_features_and_empty_kml_coordinates_fail(self):
        with self.assertRaises(FeedParseError):
            parse_nt_json(
                '{"incidents":{"type":"FeatureCollection","features":[null]}}',
                official_url=OFFICIAL,
            )
        with self.assertRaises(FeedParseError):
            parse_tas_kml(
                "<kml><Document><Placemark><name>Bushfire</name><Point><coordinates/></Point></Placemark></Document></kml>",
                official_url=OFFICIAL,
            )

    def test_nsw_filter_does_not_change_raw_completeness(self):
        payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "properties": {
                        "guid": kind,
                        "title": kind,
                        "description": f"TYPE: {kind}\nFIRE: Yes",
                    }
                }
                for kind in ["Bush Fire", "Structure Fire", "Vehicle Fire"]
            ],
        }
        raw = parse_geojson(json.dumps(payload))
        filtered = fire_incidents_only(raw)
        self.assertEqual(raw.metadata["feature_count"], 3)
        self.assertEqual(filtered.metadata["feature_count"], 3)
        self.assertEqual([item.title for item in filtered.incidents], ["Bush Fire"])


class SpatialTests(unittest.TestCase):
    def test_inside_warning_area_overrides_distant_marker(self):
        ring = ((-34.0, 150.0), (-34.0, 152.0), (-32.0, 152.0), (-32.0, 150.0))
        incident = Incident(
            "area",
            "Fixture bushfire",
            warning_level="Emergency Warning",
            latitude=-35.0,
            longitude=148.0,
            polygons=(ring,),
        ).with_home(-33.0, 151.0)
        self.assertGreater(incident.distance_km, 100)
        self.assertEqual(incident.alert_distance_km, 0)
        self.assertTrue(incident.within_warning_area)

    def test_holes_do_not_become_warning_areas(self):
        outer = ((-34.0, 150.0), (-34.0, 152.0), (-32.0, 152.0), (-32.0, 150.0))
        hole = ((-33.1, 150.9), (-33.1, 151.1), (-32.9, 151.1), (-32.9, 150.9))
        distance, inside = warning_area_distance((-33.0, 151.0), ((outer, hole),))
        self.assertFalse(inside)
        self.assertGreater(distance, 5)
        distance, inside = warning_area_distance((-33.5, 151.0), ((outer, hole),))
        self.assertTrue(inside)
        self.assertEqual(distance, 0)

    def test_nearest_boundary_not_centroid_determines_relevance(self):
        ring = ((-33.1, 151.01), (-33.1, 154.0), (-32.9, 154.0), (-32.9, 151.01))
        item = Incident(
            "boundary",
            "Fixture",
            warning_level="Advice",
            latitude=-33.0,
            longitude=153.0,
            polygons=(ring,),
        ).with_home(-33.0, 151.0)
        self.assertLess(item.alert_distance_km, 2)
        self.assertGreater(item.distance_km, 100)

    def test_polygon_expansion_is_an_escalation_without_marker_movement(self):
        old_ring = ((-33.1, 151.04), (-33.1, 151.1), (-32.9, 151.1), (-32.9, 151.04))
        new_ring = ((-33.1, 150.99), (-33.1, 151.1), (-32.9, 151.1), (-32.9, 150.99))
        old = Incident(
            "expansion",
            "Fixture",
            warning_level="Advice",
            latitude=-33.0,
            longitude=151.05,
            polygons=(old_ring,),
        ).with_home(-33.0, 151.0)
        new = replace(old, polygons=(new_ring,)).with_home(-33.0, 151.0)
        _, events, _ = track_incident_lifecycle(
            {old.id: incident_snapshot(old, qualified=True)},
            (new,),
            {new.id},
            baseline_complete=True,
        )
        self.assertEqual(events[0].lifecycle, "escalated")

    def test_partial_source_cannot_downgrade_or_clear_known_warning(self):
        high = Incident(
            "warning", "Fixture", warning_level="Emergency Warning", distance_km=1
        )
        low = replace(high, warning_level="Advice")
        records, events, _ = track_incident_lifecycle(
            {high.id: incident_snapshot(high, qualified=True)},
            (low,),
            {low.id},
            baseline_complete=True,
            allow_missing_updates=False,
            allow_deescalation=False,
        )
        self.assertFalse(events)
        self.assertEqual(records[high.id]["warning_level"], "Emergency Warning")
        retained, events, _ = track_incident_lifecycle(
            records, (), (), baseline_complete=True, allow_missing_updates=False
        )
        self.assertFalse(events)
        self.assertEqual(retained, records)


class Response:
    def __init__(self, body, status=200, etag='"good"'):
        self.body, self.status = body, status
        self.headers = {"ETag": etag}
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def iter_chunked(self, size):
        yield self.body


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.headers = []

    def get(self, url, *, headers):
        self.headers.append(headers)
        return next(self.responses)


class FeedCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_200_cannot_replace_body_or_etag(self):
        session = Session(
            [
                Response(EMPTY_CAP),
                Response(b"<html/>", etag='"bad"'),
                Response(b"", status=304),
            ]
        )
        client = OfficialFeedClient(session)
        good = await client.async_fetch("cap", OFFICIAL, validator=parse_cap)
        failed = await client.async_fetch("cap", OFFICIAL, validator=parse_cap)
        self.assertEqual(failed.body, good.body)
        self.assertEqual(failed.etag, good.etag)
        self.assertFalse(failed.response_received)
        self.assertEqual(failed.status, "retained")
        client._states["cap"].retry_after_monotonic = 0
        recovered = await client.async_fetch("cap", OFFICIAL, validator=parse_cap)
        self.assertEqual(session.headers[-1]["If-None-Match"], '"good"')
        self.assertTrue(recovered.response_received)
        self.assertEqual(recovered.body, good.body)

    async def test_invalid_first_response_is_unavailable(self):
        client = OfficialFeedClient(Session([Response(b"<maintenance/>")]))
        result = await client.async_fetch("cap", OFFICIAL, validator=parse_cap)
        self.assertIsNone(result.body)
        self.assertEqual(result.status, "unavailable")

    async def test_partial_cap_does_not_replace_valid_cache(self):
        partial_feed = b"<distribution><alert><identifier>x</identifier><info><event>Bush Fire</event></info></alert></distribution>"
        client = OfficialFeedClient(
            Session([Response(EMPTY_CAP), Response(partial_feed)])
        )
        await client.async_fetch("cap", OFFICIAL, validator=parse_cap)
        result = await client.async_fetch("cap", OFFICIAL, validator=parse_cap)
        self.assertEqual(result.body, EMPTY_CAP)
        self.assertFalse(result.response_received)


class OutboxTests(unittest.IsolatedAsyncioTestCase):
    def stage(
        self,
        box,
        *,
        message="Current warning",
        services=("notify.fixture_a", "notify.fixture_b"),
        critical=False,
    ):
        data = {"tag": "fixture-warning"}
        if critical:
            data["push"] = {"interruption-level": "critical"}
        box.stage(
            services, "Fixture alert", message, data, now=NOW, incident_id="fixture"
        )

    async def test_failure_retries_after_restart_only_for_failed_recipient(self):
        box = NotificationOutbox()
        self.stage(box)
        calls = []

        async def send(service, payload):
            calls.append(service)
            if service.endswith("fixture_b"):
                raise RuntimeError("offline")

        save = AsyncMock()
        await box.async_flush(
            send, save, services=("notify.fixture_a", "notify.fixture_b"), now=NOW
        )
        self.assertEqual(len(box.pending), 1)
        restored = NotificationOutbox(box.export())
        recovered_send = AsyncMock()
        await restored.async_flush(
            recovered_send,
            save,
            services=("notify.fixture_a", "notify.fixture_b"),
            now=NOW + timedelta(seconds=31),
        )
        recovered_send.assert_awaited_once()
        self.assertEqual(recovered_send.call_args.args[0], "notify.fixture_b")
        self.assertFalse(restored.pending)

    async def test_backoff_prevents_immediate_retry(self):
        box = NotificationOutbox()
        self.stage(box, services=("notify.fixture_a",))
        send, save = AsyncMock(side_effect=RuntimeError("offline")), AsyncMock()
        await box.async_flush(send, save, services=("notify.fixture_a",), now=NOW)
        await box.async_flush(
            send, save, services=("notify.fixture_a",), now=NOW + timedelta(seconds=1)
        )
        self.assertEqual(send.await_count, 1)

    async def test_obsolete_pending_warning_is_replaced(self):
        box = NotificationOutbox()
        self.stage(box, message="Old warning")
        box.discard_tag("fixture-warning")
        self.stage(box, message="Updated official warning")
        self.assertEqual(len(box.pending), 2)
        self.assertTrue(
            all(
                item["payload"]["message"] == "Updated official warning"
                for item in box.pending.values()
            )
        )

    async def test_expired_warning_is_not_delivered(self):
        box = NotificationOutbox()
        self.stage(box)
        send = AsyncMock()
        await box.async_flush(
            send,
            AsyncMock(),
            services=("notify.fixture_a", "notify.fixture_b"),
            now=NOW + timedelta(minutes=16),
        )
        send.assert_not_awaited()
        self.assertEqual(box.expired_count, 2)
        self.assertTrue(box.last_error)

    async def test_failed_delivery_state_write_keeps_pending_obligation(self):
        box = NotificationOutbox()
        self.stage(box, services=("notify.fixture_a",))
        await box.async_flush(
            AsyncMock(),
            AsyncMock(side_effect=OSError("disk unavailable")),
            services=("notify.fixture_a",),
            now=NOW,
        )
        self.assertEqual(len(box.pending), 1)

    def test_snooze_does_not_suppress_queued_emergency(self):
        box = NotificationOutbox()
        self.stage(box, critical=True)
        box.suppress("fixture")
        self.assertEqual(len(box.pending), 2)
        normal = NotificationOutbox()
        self.stage(normal)
        normal.suppress("fixture")
        self.assertFalse(normal.pending)


if __name__ == "__main__":
    unittest.main()
