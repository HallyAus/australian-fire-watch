"""Real coordinators and entities under feed, notification and storage failures."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import AsyncMock, Mock
import pytest
from homeassistant.exceptions import HomeAssistantError
from custom_components.australian_fire_watch.api import FeedSnapshot
from custom_components.australian_fire_watch.binary_sensor import FireWatchActiveWarningBinarySensor, FireWatchTotalFireBanBinarySensor
from custom_components.australian_fire_watch.coordinator import FireWatchCoordinator
from custom_components.australian_fire_watch.model import Incident, track_incident_lifecycle


def snap(name, url, body, *, current=True, age=0):
    now = datetime.now(timezone.utc) - timedelta(seconds=age)
    return FeedSnapshot(name, url, body, "ok" if current else "retained", now, now, None, None, None, not current, current)


def cap(level="Emergency Warning"):
    return f'''<distribution><dateTimeSent>{datetime.now(timezone.utc).isoformat()}</dateTimeSent>
    <alert><identifier>fixture</identifier><status>Actual</status><info><event>Bush Fire</event>
    <headline>Fixture fire</headline><parameter><valueName>AlertLevel</valueName><value>{level}</value></parameter>
    <parameter><valueName>IsFire</valueName><value>Yes</value></parameter>
    <area><circle>0,0 1</circle></area></info></alert></distribution>'''.encode()


def geo():
    return json.dumps({"type": "FeatureCollection", "features": [{"properties": {
        "guid": "https://example.invalid/fixture", "title": "Fixture fire", "category": "Emergency Warning",
        "description": "TYPE: Bush Fire\nFIRE: Yes\nSTATUS: Out of control"},
        "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}}]}).encode()


def coordinator(hass, entry):
    result = FireWatchCoordinator(hass, entry)
    result._store = AsyncMock()
    result._baseline_complete = True
    return result


def current_context(c, incident):
    c._feed = {"status": "fresh", "incident_status": "fresh", "current_incident_sources": ["fixture"], "assessed_at": datetime.now(timezone.utc).isoformat()}
    c._incidents = (incident,)
    c._current_incidents = {incident.id: incident}


@pytest.mark.parametrize("health", ["stale", "unavailable", "degraded"])
async def test_warning_sensor_unavailable_not_off(hass, entry, health):
    c = coordinator(hass, entry)
    c.data = {"status": health, "feed": {"status": health}}
    entity = FireWatchActiveWarningBinarySensor(c)
    assert entity.is_on is None and not entity.available


async def test_complete_absence_can_be_off(hass, entry):
    c = coordinator(hass, entry)
    c.data = {"status": "no_current_warning", "feed": {"status": "fresh"}}
    assert FireWatchActiveWarningBinarySensor(c).is_on is False


async def test_unverified_fire_ban_is_unavailable(hass, entry):
    c = coordinator(hass, entry)
    c.data = {"danger": {"today": {"total_fire_ban": False, "available": False}}}
    assert not FireWatchTotalFireBanBinarySensor(c).available


@pytest.mark.parametrize("healthy", ["rfs_cap", "rfs_geojson"])
async def test_one_healthy_nsw_source_can_raise_emergency(hass, entry, healthy):
    c = coordinator(hass, entry)
    async def fetch(name, url, **kwargs):
        if name == healthy:
            return snap(name, url, cap() if name == "rfs_cap" else geo())
        if name == "rfs_cap":
            return snap(name, url, cap("Advice"), current=False, age=7200)
        return snap(name, url, None, current=False)
    c.api.async_fetch = fetch
    data = await c._async_update_data()
    assert any(event.incident_id == "fixture" and event.lifecycle == "new" for event in c.last_events)
    assert data["status"] == "emergency_warning"
    assert data["feed"]["incident_status"] == "degraded"


async def test_nsw_structure_fire_is_not_nearby_bushfire(hass, entry):
    c = coordinator(hass, entry)
    body = cap().replace(b"Bush Fire", b"Structure Fire")
    async def fetch(name, url, **kwargs):
        return snap(name, url, body if name == "rfs_cap" else None, current=name == "rfs_cap")
    c.api.async_fetch = fetch
    data = await c._async_update_data()
    assert data["incident_count"] == 0
    assert not any(event.qualifies_for_alert for event in c.last_events)


async def test_polygon_contains_home_even_with_distant_marker(hass, entry):
    c = coordinator(hass, entry)
    ring = ((-1., -1.), (-1., 1.), (1., 1.), (1., -1.))
    item = Incident(id="fixture", title="Fixture", warning_level="Emergency Warning", latitude=20., longitude=20., warning_areas=((ring,),)).with_home(0., 0.)
    assert item.distance_km > 100
    assert item.inside_warning_area and c._qualifies(item)


async def test_lifecycle_and_pending_delivery_checkpoint_together(hass, entry):
    hass.config_entries.async_update_entry(entry, data={**entry.data, "notify_services": ["notify.fixture_a"]})
    c = coordinator(hass, entry)
    captures = []
    async def save(value):
        captures.append(deepcopy(value))
    c._store.async_save = AsyncMock(side_effect=save)
    async def fail(call):
        raise HomeAssistantError("Temporary notification failure")
    hass.services.async_register("notify", "fixture_a", fail)
    item = Incident(id="fixture", title="Fixture", warning_level="Emergency Warning", distance_km=0.)
    current_context(c, item)
    events = await c._async_track_lifecycle((item,), (item,), True, True)
    c._store.async_save.assert_not_awaited()
    await c._async_emit_events(events, [])
    assert "fixture" in captures[0]["records"]
    assert len(captures[0]["outbox"]["pending"]) == 1
    assert c._outbox.health["failed_count"] == 1
    restored = FireWatchCoordinator(hass, entry)
    restored._store = AsyncMock()
    restored._store.async_load.return_value = captures[-1]
    await restored.async_initialize()
    assert len(restored._outbox.pending) == 1 and "fixture" in restored._records


async def test_failed_checkpoint_prevents_actual_service_call(hass, entry):
    hass.config_entries.async_update_entry(entry, data={**entry.data, "notify_services": ["notify.fixture_a"]})
    c = coordinator(hass, entry)
    c._store.async_save.side_effect = OSError("Fixture disk failure")
    delivered = []
    async def send(call):
        delivered.append(call)
    hass.services.async_register("notify", "fixture_a", send)
    item = Incident(id="fixture", title="Fixture", warning_level="Emergency Warning", distance_km=0.)
    current_context(c, item)
    events = await c._async_track_lifecycle((item,), (item,), True, True)
    with pytest.raises(OSError):
        await c._async_emit_events(events, [])
    assert not delivered
    assert c._outbox.pending


async def test_regional_warning_survives_failed_incident_feed(hass, entry):
    hass.config_entries.async_update_entry(entry, data={**entry.data, "jurisdiction": "QLD"})
    c = coordinator(hass, entry)
    body = json.dumps({"type": "FeatureCollection", "features": [{"properties": {
        "UniqueID": "fixture-warning", "EventType": "Fire", "WarningTitle": "Fixture bushfire", "WarningLevel": "Emergency Warning"},
        "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}}]}).encode()
    async def fetch(name, url, **kwargs):
        return snap(name, url, body if name == "qld_warnings" else None, current=name == "qld_warnings")
    c.api.async_fetch = fetch
    data = await c._async_update_data()
    assert data["status"] == "emergency_warning"
    assert any(event.incident_id == "QLD-fixture-warning" and event.qualifies_for_alert for event in c.last_events)


async def test_first_empty_snapshot_does_not_clear_display(hass, entry):
    c = coordinator(hass, entry)
    item = Incident(id="fixture", title="Fixture", warning_level="Emergency Warning", distance_km=0.)
    c._incidents = (item,)
    await c._async_track_lifecycle((item,), (item,), True, True)
    c._retain_unconfirmed_incidents()
    c._incidents = ()
    c._feed = {"status": "fresh", "incident_status": "fresh"}
    await c._async_track_lifecycle((), (), True, True)
    c._retain_unconfirmed_incidents()
    assert c._incidents and "fixture" in c._retained_ids
    assert c._feed["incident_status"] == "degraded"
    c._incidents = ()
    c._feed = {"status": "fresh", "incident_status": "fresh"}
    await c._async_track_lifecycle((), (), True, True)
    c._retain_unconfirmed_incidents()
    assert not c._incidents and not c._records
    assert c._summary_status([]) == "no_current_warning"


async def test_retry_does_not_reset_poll_timer(hass, entry):
    hass.config_entries.async_update_entry(entry, data={**entry.data, "notify_services": ["notify.fixture_a"]})
    c = coordinator(hass, entry)
    item = Incident(id="fixture", title="Fixture", warning_level="Emergency Warning", distance_km=0.)
    current_context(c, item)
    await c._async_track_lifecycle((item,), (item,), True, True)
    c.data = {"delivery": {}}
    c.async_update_listeners = Mock()
    c.async_set_updated_data = Mock()
    c._outbox.enqueue(("notify.fixture_a",), "Fixture", "Fixture", {"tag": "fixture"}, datetime.now(timezone.utc), guard={"kind": "test"})
    async def send(call):
        pass
    hass.services.async_register("notify", "fixture_a", send)
    await c._async_retry_notifications(datetime.now(timezone.utc))
    assert not c._outbox.pending
    c.async_update_listeners.assert_called_once()
    c.async_set_updated_data.assert_not_called()


async def test_stale_assessment_holds_pending_notification(hass, entry):
    hass.config_entries.async_update_entry(entry, data={**entry.data, "notify_services": ["notify.fixture_a"]})
    c = coordinator(hass, entry)
    item = Incident(id="fixture", title="Fixture", warning_level="Emergency Warning", distance_km=0.)
    current_context(c, item)
    events = await c._async_track_lifecycle((item,), (item,), True, True)
    c._feed["assessed_at"] = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    calls = []
    async def send(call):
        calls.append(call)
    hass.services.async_register("notify", "fixture_a", send)
    await c._async_emit_events(events, [])
    assert not calls and c._outbox.pending


def test_partial_snapshot_cannot_downgrade_or_resolve():
    old = Incident(id="fixture", title="Fixture", warning_level="Emergency Warning", distance_km=0.)
    records, _, _ = track_incident_lifecycle({}, (old,), {old.id}, baseline_complete=True)
    lower = Incident(id="fixture", title="Fixture", warning_level="Advice", distance_km=0.)
    retained, events, _ = track_incident_lifecycle(records, (lower,), {lower.id}, baseline_complete=True, allow_missing_updates=False)
    assert not events and retained[old.id]["warning_level"] == "Emergency Warning"
    retained, events, _ = track_incident_lifecycle(retained, (), (), baseline_complete=True, allow_missing_updates=False)
    assert not events and retained[old.id]["missing_count"] == 0
