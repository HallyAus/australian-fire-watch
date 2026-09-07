"""The original card must be loadable independently of official feed timing."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.components.lovelace.const import LOVELACE_DATA

from custom_components.australian_fire_watch import _frontend_module_url
from custom_components.australian_fire_watch.const import DOMAIN, PANEL_SLUG


async def test_original_card_registered_before_first_feed_refresh(hass, entry, feed_client):
    """A cold dashboard must not depend on a successful first network refresh."""
    from custom_components.australian_fire_watch.coordinator import FireWatchCoordinator

    refresh = FireWatchCoordinator.async_config_entry_first_refresh
    observed = []

    async def inspect_before_refresh(coordinator):
        ll = hass.data.get(LOVELACE_DATA)
        resources = list(ll.resources.async_items()) if ll else []
        observed.append({
            "panel": PANEL_SLUG in hass.data.get("frontend_panels", {}),
            "module": any(r.get("url") == _frontend_module_url() and
                          r.get("type") == "module" for r in resources),
        })
        return await refresh(coordinator)

    with patch.object(FireWatchCoordinator, "async_config_entry_first_refresh", inspect_before_refresh):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    try:
        assert observed and all(item["module"] for item in observed), observed
    finally:
        if entry.entry_id in hass.data.get(DOMAIN, {}).get("entries", {}):
            await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()


async def test_original_card_resource_survives_entry_reload(hass, entry, loaded):
    """No manual dashboard resource entry and no duplicate URL on reload."""
    ll = hass.data.get(LOVELACE_DATA)
    assert ll is not None, "Lovelace must be set up before card registration"
    before = [r for r in ll.resources.async_items() if r.get("url") == _frontend_module_url()]
    assert len(before) == 1
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    after = [r for r in ll.resources.async_items() if r.get("url") == _frontend_module_url()]
    assert after == before
