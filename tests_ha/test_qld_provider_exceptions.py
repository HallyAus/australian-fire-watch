"""Prevent unexpected Queensland enrichment errors from blocking incident updates.

The ArcGIS provider is deliberately mocked before HA starts the integration.
No live QFD requests are made by this regression test.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from homeassistant.helpers import entity_registry as er

from custom_components.australian_fire_watch.const import DOMAIN
from custom_components.australian_fire_watch.qld_arcgis import QldArcGISProvider

from .conftest import cap, geo, snapshot


@pytest.mark.parametrize(
    "entry", [{"jurisdictions": ["QLD", "NSW"]}], indirect=True
)
async def test_unexpected_qld_provider_error_preserves_cross_border_warnings(
    hass, entry, feeds, feed_client
):
    """A QFD runtime exception must not roll back valid incident updates."""
    qld_warning = {
        "type": "FeatureCollection",
        "features": [
            {
                "properties": {
                    "UniqueID": "qld-incident",
                    "EventType": "Fire",
                    "WarningLevel": "Emergency Warning",
                    "WarningTitle": "QLD fixture bushfire",
                },
                "geometry": {"type": "Point", "coordinates": [151.0, -33.0]},
            }
        ],
    }
    feeds["qld_warnings"] = snapshot(
        "qld_warnings", json.dumps(qld_warning).encode()
    )
    for name in ("rfs_cap", "rfs_incident_alerts"):
        feeds[name] = snapshot(name, cap("nsw-incident", "Watch and Act"))
    feeds["rfs_geojson"] = snapshot(
        "rfs_geojson", geo("nsw-incident", "Watch and Act")
    )

    async def failed_fetch(_self, _latitude, _longitude, *, now=None):
        raise RuntimeError("Simulated unexpected QFD provider failure")

    # Patch before setup; the initial coordinator refresh must not escape
    # to the network or turn an optional enrichment error into setup failure.
    with patch.object(QldArcGISProvider, "async_fetch", new=failed_fetch):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = hass.data[DOMAIN]["entries"][entry.entry_id]
        try:
            # Exercise both initial setup and a subsequent coordinator poll.
            await coordinator.async_refresh()
            await hass.async_block_till_done()

            assert coordinator.last_update_success
            data = coordinator.data
            incident_ids = {item["id"] for item in data["incidents"]}
            assert {"QLD-qld-incident", "nsw-incident"} <= incident_ids
            assert data["status"] == "emergency_warning"
            assert data["feed"]["assessment_complete"] is True
            assert data["feed"]["status"] == "degraded"
            assert data["qld"]["health"] == "unavailable"
            assert data["qld"]["forecast"]["covered"] is None
            assert data["qld"]["local_fire_ban"]["state"] is None
            assert data["danger"]["today"]["total_fire_ban"] is None

            for source_name in ("forecast", "local_fire_ban"):
                assert data["qld"][source_name]["error"] == "provider_exception"
                assert (
                    data["feed"]["sources"][f"qld_{source_name}"]["status"]
                    == "unavailable"
                )

            registry = er.async_get(hass)
            warning_id = registry.async_get_entity_id(
                "binary_sensor", DOMAIN, f"{entry.entry_id}_active_warning"
            )
            problem_id = registry.async_get_entity_id(
                "binary_sensor", DOMAIN, f"{entry.entry_id}_feed_problem"
            )
            assert warning_id is not None
            assert problem_id is not None
            assert hass.states.get(warning_id).state == "on"
            assert hass.states.get(problem_id).state == "on"
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()
