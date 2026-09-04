"""Home Assistant runtime, lifecycle, availability, and persistence tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

import pytest
from homeassistant.helpers import entity_registry as er

from custom_components.australian_fire_watch.binary_sensor import (
    FireWatchActiveWarningBinarySensor,
    FireWatchTotalFireBanBinarySensor,
)
from custom_components.australian_fire_watch.const import DOMAIN
from custom_components.australian_fire_watch.model import Incident

from .conftest import cap, geo, snapshot


def entity_id(hass, entry, domain, key):
    return er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{entry.entry_id}_{key}"
    )


async def test_setup_reload_unload_and_services(hass, entry, loaded):
    assert hass.services.has_service(DOMAIN, "test_alert")
    assert (
        hass.states.get(entity_id(hass, entry, "binary_sensor", "active_warning")).state
        == "off"
    )
    assert (
        hass.states.get(
            entity_id(hass, entry, "binary_sensor", "notification_delivery_problem")
        )
        is not None
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.services.has_service(DOMAIN, "test_alert")
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not hass.services.has_service(DOMAIN, "test_alert")
    assert not hass.data[DOMAIN]["entries"]


async def test_active_warning_outage_is_unavailable_not_off(hass, entry, loaded, feeds):
    for name in ("rfs_cap", "rfs_incident_alerts"):
        feeds[name] = snapshot(name, cap("one", "Emergency Warning"))
    feeds["rfs_geojson"] = snapshot("rfs_geojson", geo("one", "Emergency Warning"))
    await loaded.async_refresh()
    await hass.async_block_till_done()
    warning_id = entity_id(hass, entry, "binary_sensor", "active_warning")
    assert hass.states.get(warning_id).state == "on"
    for name, item in tuple(feeds.items()):
        feeds[name] = replace(
            item,
            response_received=False,
            status="retained",
            fetched_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
    await loaded.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(warning_id).state == "unavailable"
    assert loaded.data["official_warning_level"] == "Emergency Warning"


@pytest.mark.parametrize("healthy", ["rfs_cap", "rfs_geojson"])
async def test_healthy_nsw_source_can_raise_alert_while_other_is_down(
    loaded, feeds, healthy
):
    other = "rfs_geojson" if healthy == "rfs_cap" else "rfs_cap"
    feeds[other] = snapshot(
        other,
        feeds[other].body,
        current=False,
        fetched_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    body = (
        cap("new", "Emergency Warning")
        if healthy == "rfs_cap"
        else geo("new", "Emergency Warning")
    )
    feeds[healthy] = snapshot(healthy, body)
    await loaded.async_refresh()
    assert any(
        event.incident_id == "new" and event.qualifies_for_alert
        for event in loaded.last_events
    )
    assert loaded.data["status"] == "emergency_warning"
    assert loaded.data["feed"]["status"] == "degraded"
    assert not loaded.data["feed"]["assessment_complete"]


async def test_partial_assessment_cannot_publish_no_warning(loaded, feeds):
    feeds["rfs_geojson"] = snapshot("rfs_geojson", None, current=False)
    await loaded.async_refresh()
    assert loaded.data["status"] == "unavailable"
    assert FireWatchActiveWarningBinarySensor(loaded).is_on is None


async def test_first_missing_snapshot_does_not_clear_warning(
    hass, entry, loaded, feeds
):
    for name in ("rfs_cap", "rfs_incident_alerts"):
        feeds[name] = snapshot(name, cap("one", "Emergency Warning"))
    feeds["rfs_geojson"] = snapshot("rfs_geojson", geo("one", "Emergency Warning"))
    await loaded.async_refresh()
    for name in ("rfs_cap", "rfs_incident_alerts"):
        feeds[name] = snapshot(name, cap())
    feeds["rfs_geojson"] = snapshot("rfs_geojson", geo())
    await loaded.async_refresh()
    assert loaded.data["status"] == "unavailable"
    assert loaded.data["last_known_warning_records"][0]["incident_id"] == "one"
    await loaded.async_refresh()
    assert loaded.data["status"] == "no_current_warning"
    assert loaded.last_events[0].lifecycle == "resolved"


@pytest.mark.parametrize("entry", [{"jurisdiction": "QLD"}], indirect=True)
async def test_regional_warning_survives_incident_feed_outage(
    hass, entry, loaded, feeds
):
    feeds["qld_incidents"] = snapshot("qld_incidents", None, current=False)
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "properties": {
                    "UniqueID": "new",
                    "EventType": "Fire",
                    "WarningLevel": "Emergency Warning",
                    "WarningTitle": "Fixture bushfire",
                },
                "geometry": {"type": "Point", "coordinates": [151.0, -33.0]},
            }
        ],
    }
    feeds["qld_warnings"] = snapshot("qld_warnings", json.dumps(payload).encode())
    await loaded.async_refresh()
    assert loaded.data["status"] == "emergency_warning"
    assert any(
        item.incident_id == "QLD-new" and item.qualifies_for_alert
        for item in loaded.last_events
    )


async def test_old_danger_is_not_relabelled_after_midnight(loaded, feeds):
    now = datetime.now(timezone.utc)
    previous = now - timedelta(days=1)
    districts = {
        "Greater Sydney Region": {
            "today": {"rating": "Moderate", "total_fire_ban": False},
            "tomorrow": {"rating": "Extreme", "total_fire_ban": True},
        }
    }
    feeds["rfs_fdr_toban"] = snapshot(
        "rfs_fdr_toban",
        b"retained",
        current=False,
        fetched_at=previous,
        changed_at=previous,
    )
    danger = loaded._compose_danger(districts, None, feeds)
    assert danger["today"]["rating"] == "Unknown"
    assert danger["today"]["total_fire_ban"] is None
    loaded.data = {**loaded.data, "danger": danger}
    assert not FireWatchTotalFireBanBinarySensor(loaded).available


async def test_revalidated_relative_forecast_keeps_its_original_date(loaded, feeds):
    previous = datetime.now(timezone.utc) - timedelta(days=1)
    districts = {
        "Greater Sydney Region": {
            "today": {"rating": "Moderate", "total_fire_ban": False},
            "tomorrow": {"rating": "Extreme", "total_fire_ban": True},
        }
    }
    feeds["rfs_fdr_toban"] = replace(
        snapshot("rfs_fdr_toban", b"cached", changed_at=previous), not_modified=True
    )
    danger = loaded._compose_danger(districts, None, feeds)
    assert (
        danger["today"]["total_fire_ban"] is True
    )  # Yesterday's tomorrow, not yesterday's today.
    assert danger["tomorrow"]["rating"] == "Unknown"


@pytest.mark.parametrize(
    "entry", [{"notify_services": ["notify.fixture_receiver"]}], indirect=True
)
async def test_lifecycle_and_outbox_are_saved_before_delivery(
    hass, entry, loaded, feeds
):
    saved = []

    async def save(value):
        saved.append(value)

    async def notify(call):
        assert saved
        assert "new" in saved[0]["records"]
        assert saved[0]["notification_outbox"]["pending"]

    hass.services.async_register("notify", "fixture_receiver", notify)
    for name in ("rfs_cap", "rfs_incident_alerts"):
        feeds[name] = snapshot(name, cap("new", "Emergency Warning"))
    feeds["rfs_geojson"] = snapshot("rfs_geojson", geo("new", "Emergency Warning"))
    with patch.object(loaded._store, "async_save", side_effect=save):
        await loaded.async_refresh()
    assert saved[0]["notification_outbox"]["pending"]
    assert not loaded._outbox.pending
    hass.services.async_remove("notify", "fixture_receiver")


async def test_failed_atomic_save_rolls_back_lifecycle(loaded, feeds):
    feeds["rfs_cap"] = snapshot("rfs_cap", cap("new", "Emergency Warning"))
    with patch.object(
        loaded._store, "async_save", side_effect=OSError("fixture disk failure")
    ):
        with pytest.raises(OSError):
            await loaded._async_update_data()
    assert "new" not in loaded._records
    await loaded.async_refresh()
    assert any(event.incident_id == "new" for event in loaded.last_events)


async def test_polygon_membership_qualifies_even_with_distant_marker(loaded):
    ring = ((-34.0, 150.0), (-34.0, 152.0), (-32.0, 152.0), (-32.0, 150.0))
    incident = Incident(
        "area",
        "Fixture bushfire",
        warning_level="Emergency Warning",
        latitude=-36.0,
        longitude=148.0,
        polygons=(ring,),
    ).with_home(-33.0, 151.0)
    assert loaded._qualifies(incident)
    _all, monitored = loaded._locate_incidents((incident,))
    assert monitored


async def test_nsw_structure_fire_does_not_enter_alert_lifecycle(loaded, feeds):
    feeds["rfs_cap"] = snapshot("rfs_cap", cap("structure", "Advice", "Structure Fire"))
    await loaded.async_refresh()
    assert loaded.data["incident_count"] == 0
    assert not any(item.incident_id == "structure" for item in loaded.last_events)


async def test_local_notification_publication_preserves_feed_poll_and_health():
    """An outbox refresh must not postpone the next poll or mask its failure."""
    from unittest.mock import patch
    from custom_components.australian_fire_watch.coordinator import FireWatchCoordinator

    coordinator = object.__new__(FireWatchCoordinator)
    coordinator.last_update_success = False
    coordinator.data = {}
    with (
        patch.object(coordinator, "_compose_data", return_value={"local": True}),
        patch.object(coordinator, "async_update_listeners") as listeners,
        patch.object(coordinator, "async_set_updated_data") as reset_poll,
    ):
        coordinator._publish_local_data()
    reset_poll.assert_not_called()
    listeners.assert_called_once()
    assert coordinator.last_update_success is False
    assert coordinator.data == {"local": True}
