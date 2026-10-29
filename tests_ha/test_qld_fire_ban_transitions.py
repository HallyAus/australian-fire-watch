"""Test Queensland fire ban entity transitions without modifying live QFD data.

Run in this repository with the Home Assistant pytest dependencies installed:
    python -m pytest -q tests_ha/test_qld_fire_ban_transitions.py --asyncio-mode=auto

The repository's existing tests_ha/conftest.py supplies hass, entry and feed_client.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from homeassistant.helpers import entity_registry as er

from custom_components.australian_fire_watch.const import DOMAIN
from custom_components.australian_fire_watch.qld_arcgis import QldArcGISProvider
from custom_components.australian_fire_watch.coordinator import FireWatchCoordinator

AEST = timezone(timedelta(hours=10))


def _entity_id(hass, entry, domain: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert entity_id is not None, f"Missing {domain} entity: {key}"
    return entity_id


@pytest.mark.parametrize("entry", [{"jurisdiction": "QLD"}], indirect=True)
async def test_qld_total_fire_ban_lifecycle_and_feed_problem(hass, entry, feed_client):
    """Exercise the real HA entities with deterministic QLD provider responses."""
    hass.config.latitude = -27.4698
    hass.config.longitude = 153.0251
    current = {"status": "No Fire Ban"}

    async def fake_fetch(self, latitude, longitude, *, now=None):
        assert abs(latitude + 27.4698) < 0.0001
        assert abs(longitude - 153.0251) < 0.0001
        now = datetime.now(timezone.utc)
        today = now.astimezone(AEST).date()
        forecast = {
            "covered": True,
            "health": "fresh",
            "district": "Southeast Coast",
            "source_updated_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "forecast": [
                {"date": today.isoformat(), "rating": "Moderate", "available": True},
                {"date": (today + timedelta(days=1)).isoformat(),
                 "rating": "Moderate", "available": True},
            ],
        }
        ban_status = current["status"]
        ban = (
            {
                "state": None,
                "health": "unavailable",
                "error": "Fixture QFD API failure",
                "checked_at": now.isoformat(),
            }
            if ban_status == "API_ERROR"
            else {
                "state": ban_status == "Fire Ban",
                "raw_status": ban_status,
                "health": "fresh",
                "lga": "Brisbane City",
                "effective_from": None,
                "effective_to": None,
                "checked_at": now.isoformat(),
            }
        )
        return {
            "forecast": forecast,
            "local_fire_ban": ban,
            "health": "degraded" if ban_status == "API_ERROR" else "fresh",
        }

    # Patch before setup so no test accidentally calls the live ArcGIS endpoint.
    with (
        patch.object(FireWatchCoordinator, "_home_coordinates", return_value=(-27.4698, 153.0251)),
        patch.object(QldArcGISProvider, "async_fetch", new=fake_fetch),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = hass.data[DOMAIN]["entries"][entry.entry_id]
        ban_id = _entity_id(hass, entry, "binary_sensor", "total_fire_ban_today")
        problem_id = _entity_id(hass, entry, "binary_sensor", "feed_problem")

        try:
            for source_status, expected_ban, expected_problem in (
                ("No Fire Ban", "off", "off"),
                ("Fire Ban", "on", "off"),
                ("API_ERROR", "unavailable", "on"),
                ("No Fire Ban", "off", "off"),
            ):
                current["status"] = source_status
                await coordinator.async_refresh()
                await hass.async_block_till_done()
                ban = hass.states.get(ban_id)
                problem = hass.states.get(problem_id)
                assert ban is not None
                assert problem is not None
                assert ban.state == expected_ban, (source_status, ban)
                assert problem.state == expected_problem, (source_status, problem)

            assert ban.attributes["lga"] == "Brisbane City"
            assert ban.attributes["restriction_type"] == "QLD Local Fire Ban"
        finally:
            await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()
