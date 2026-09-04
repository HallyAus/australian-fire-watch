"""Real Home Assistant fixtures, deliberately separate from pure unit tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.australian_fire_watch.api import FeedSnapshot
from custom_components.australian_fire_watch.const import DOMAIN


def cap(
    incident_id: str | None = None, level: str = "Advice", kind: str = "Bush Fire"
) -> bytes:
    sent = datetime.now(timezone.utc).isoformat()
    alert = (
        ""
        if incident_id is None
        else f"""<alert><status>Actual</status><identifier>{incident_id}</identifier>
      <incidents>{incident_id}</incidents><sent>{sent}</sent><info><event>{kind}</event><headline>Fixture {kind}</headline>
      <parameter><valueName>AlertLevel</valueName><value>{level}</value></parameter>
      <parameter><valueName>IsFire</valueName><value>Yes</value></parameter>
      <area><circle>-33.0,151.0 1</circle></area></info></alert>"""
    )
    return f"<distribution><dateTimeSent>{sent}</dateTimeSent>{alert}</distribution>".encode()


def geo(incident_id: str | None = None, level: str = "Advice") -> bytes:
    features = (
        []
        if incident_id is None
        else [
            {
                "type": "Feature",
                "properties": {
                    "guid": incident_id,
                    "title": "Fixture Bush Fire",
                    "category": level,
                    "description": "TYPE: Bush Fire\nFIRE: Yes",
                },
                "geometry": {"type": "Point", "coordinates": [151.0, -33.0]},
            }
        ]
    )
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


def snapshot(
    name: str,
    body: bytes | None,
    *,
    current: bool = True,
    fetched_at=None,
    changed_at=None,
) -> FeedSnapshot:
    now = datetime.now(timezone.utc)
    return FeedSnapshot(
        name=name,
        url="https://example.invalid/official",
        body=body,
        status="ok" if current else ("retained" if body else "unavailable"),
        fetched_at=fetched_at or now,
        changed_at=changed_at or now,
        last_modified=None,
        etag=None,
        error=None if current else "Fixture outage",
        from_cache=not current,
        response_received=current,
    )


@pytest.fixture(autouse=True)
def custom_integrations_enabled(enable_custom_integrations):
    yield


@pytest.fixture
def feeds():
    danger = b"""<FireDangerMap><District><Name>Greater Sydney Region</Name>
      <DangerLevelToday>Moderate</DangerLevelToday><FireBanToday>No</FireBanToday>
      <DangerLevelTomorrow>Moderate</DangerLevelTomorrow><FireBanTomorrow>No</FireBanTomorrow>
      </District></FireDangerMap>"""
    return {
        "rfs_cap": snapshot("rfs_cap", cap()),
        "rfs_geojson": snapshot("rfs_geojson", geo()),
        "rfs_incident_alerts": snapshot("rfs_incident_alerts", cap()),
        "rfs_fdr_toban": snapshot("rfs_fdr_toban", danger),
        "qld_incidents": snapshot("qld_incidents", geo()),
        "qld_warnings": snapshot("qld_warnings", geo()),
    }


@pytest.fixture
def feed_client(feeds):
    async def fetch(_self, name, url, *, validator):
        item = feeds[name]
        # Exercise the same strict parser passed by the production coordinator.
        if item.response_received and item.body:
            validator(item.body)
        return replace(item, url=url)

    with patch(
        "custom_components.australian_fire_watch.coordinator.OfficialFeedClient.async_fetch",
        new=fetch,
    ):
        yield


@pytest.fixture
def entry(hass, request):
    hass.config.latitude = -33.0
    hass.config.longitude = 151.0
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Fixture",
        unique_id="zone.home|nsw|fixture",
        data={
            "name": "Fixture",
            "zone": "zone.home",
            "jurisdiction": "NSW",
            "enable_bom_enrichment": False,
            **getattr(request, "param", {}),
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def loaded(hass, entry, feed_client):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = hass.data[DOMAIN]["entries"][entry.entry_id]
    yield coordinator
    if entry.entry_id in hass.data.get(DOMAIN, {}).get("entries", {}):
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
