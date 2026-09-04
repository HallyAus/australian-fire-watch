"""Real HA setup, reload and unload; only external feed/UI boundaries mocked."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch
from custom_components.australian_fire_watch.api import FeedSnapshot
from custom_components.australian_fire_watch.const import DOMAIN


async def test_setup_reload_unload_cancels_retry_listener(hass, entry):
    hass.config_entries.async_update_entry(entry, data={**entry.data, "jurisdiction": "VIC"})
    cancellations = []

    def start_timer(*args, **kwargs):
        cancel = Mock()
        cancellations.append(cancel)
        return cancel

    async def fetch(self, name, url, **kwargs):
        body = b'{"type":"FeatureCollection","features":[]}'
        kwargs["validator"](body)
        now = datetime.now(timezone.utc)
        return FeedSnapshot(name, url, body, "ok", now, now, None, None, None, False, True)

    with (
        patch("custom_components.australian_fire_watch.api.OfficialFeedClient.async_fetch", fetch),
        patch("custom_components.australian_fire_watch._async_register_panel", new=AsyncMock()),
        patch("custom_components.australian_fire_watch.coordinator.async_track_time_interval", side_effect=start_timer),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.entry_id in hass.data[DOMAIN]["entries"]
        assert hass.services.has_service(DOMAIN, "test_alert")
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        cancellations[0].assert_called_once()
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        cancellations[-1].assert_called_once()
        assert entry.entry_id not in hass.data[DOMAIN]["entries"]
        assert not hass.services.has_service(DOMAIN, "test_alert")


async def test_unavailable_feed_entity_state_is_not_off(hass, entry):
    hass.config_entries.async_update_entry(entry, data={**entry.data, "jurisdiction": "VIC"})

    async def fetch(self, name, url, **kwargs):
        return FeedSnapshot(name, url, None, "unavailable", None, None, None, None, "Fixture outage", False, False)

    with (
        patch("custom_components.australian_fire_watch.api.OfficialFeedClient.async_fetch", fetch),
        patch("custom_components.australian_fire_watch._async_register_panel", new=AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        warnings = [state for state in hass.states.async_all("binary_sensor") if state.name.endswith("Official warning in alert radius")]
        assert len(warnings) == 1
        assert warnings[0].state == "unavailable"
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
