"""Publication-date regressions for unchanged official relative-day feeds."""

from datetime import datetime, timezone
import unittest

from test_reliability import EMPTY_GEO, OFFICIAL, Response, Session
from custom_components.australian_fire_watch.api import OfficialFeedClient
from custom_components.australian_fire_watch.parsers import parse_geojson


class PublicationDateTests(unittest.IsolatedAsyncioTestCase):
    async def test_identical_body_with_new_publication_date_updates_anchor(self):
        old, new = Response(EMPTY_GEO), Response(EMPTY_GEO)
        old.headers["Last-Modified"] = "Fri, 04 Sep 2026 02:00:00 GMT"
        new.headers["Last-Modified"] = "Sat, 05 Sep 2026 02:00:00 GMT"
        client = OfficialFeedClient(Session([old, new]))
        first = await client.async_fetch("fixture", OFFICIAL, validator=parse_geojson)
        second = await client.async_fetch("fixture", OFFICIAL, validator=parse_geojson)
        self.assertEqual(first.body, second.body)
        self.assertGreater(second.changed_at, first.changed_at)
        self.assertEqual(second.changed_at, datetime(2026, 9, 5, 2, tzinfo=timezone.utc))

    async def test_unchanged_body_without_publisher_timestamp_keeps_date(self):
        client = OfficialFeedClient(Session([Response(EMPTY_GEO), Response(EMPTY_GEO)]))
        first = await client.async_fetch("fixture", OFFICIAL, validator=parse_geojson)
        second = await client.async_fetch("fixture", OFFICIAL, validator=parse_geojson)
        self.assertEqual(second.changed_at, first.changed_at)

    async def test_304_revalidation_never_moves_publication_date(self):
        old = Response(EMPTY_GEO)
        old.headers["Last-Modified"] = "Fri, 04 Sep 2026 02:00:00 GMT"
        client = OfficialFeedClient(Session([old, Response(b"", status=304)]))
        first = await client.async_fetch("fixture", OFFICIAL, validator=parse_geojson)
        second = await client.async_fetch("fixture", OFFICIAL, validator=parse_geojson)
        self.assertTrue(second.not_modified)
        self.assertEqual(second.changed_at, first.changed_at)

    async def test_invalid_republication_cannot_change_accepted_date(self):
        old, invalid = Response(EMPTY_GEO), Response(b"<maintenance/>")
        old.headers["Last-Modified"] = "Fri, 04 Sep 2026 02:00:00 GMT"
        invalid.headers["Last-Modified"] = "Sat, 05 Sep 2026 02:00:00 GMT"
        client = OfficialFeedClient(Session([old, invalid]))
        first = await client.async_fetch("fixture", OFFICIAL, validator=parse_geojson)
        second = await client.async_fetch("fixture", OFFICIAL, validator=parse_geojson)
        self.assertFalse(second.response_received)
        self.assertEqual(second.changed_at, first.changed_at)
        self.assertEqual(second.body, first.body)
