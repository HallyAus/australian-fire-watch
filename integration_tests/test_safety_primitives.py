"""Deterministic date, geometry, freshness and durable-delivery regressions."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from custom_components.australian_fire_watch.feed_safety import current_snapshot, dated_danger, incident_feed_health
from custom_components.australian_fire_watch.notification_outbox import NotificationOutbox
from custom_components.australian_fire_watch.warning_geometry import area_relevance

NOW = datetime(2026, 9, 5, 2, tzinfo=timezone.utc)
SERVICES = ("notify.fixture_a", "notify.fixture_b")
RING = ((-2., -2.), (-2., 2.), (2., 2.), (2., -2.))


def snap(*, fresh=True, age=0, anchor=None):
    return SimpleNamespace(response_received=fresh, fetched_at=NOW-timedelta(seconds=age), changed_at=anchor or NOW)


def parsed(**metadata):
    return SimpleNamespace(metadata={"complete": True, **metadata}, generated_at=NOW-timedelta(hours=2))


@pytest.mark.parametrize("snapshot,body", [
    (snap(fresh=False), parsed()), (snap(), None),
    (snap(age=2701), parsed()), (snap(), parsed(complete=False)),
    (snap(), parsed(generated_at_is_feed_time=True)),
])
def test_invalid_or_stale_source_is_not_current(snapshot, body):
    assert not current_snapshot(snapshot, body, 2700, NOW)


def test_old_incident_time_does_not_stale_revalidated_feed():
    assert current_snapshot(snap(), parsed(), 2700, NOW)


def test_one_source_can_raise_but_not_clear():
    status, current = incident_feed_health({"a": snap(), "b": snap(fresh=False, age=5000)}, {"a": parsed(), "b": parsed()}, ("a", "b"), 2700, NOW)
    assert status == "degraded" and current == ("a",)


def test_complete_sources_are_fresh():
    assert incident_feed_health({"a": snap(), "b": snap()}, {"a": parsed(), "b": parsed()}, ("a", "b"), 2700, NOW) == ("fresh", ("a", "b"))


def test_old_sources_stale_and_missing_sources_unavailable():
    assert incident_feed_health({"a": snap(fresh=False, age=5000)}, {"a": parsed()}, ("a",), 2700, NOW)[0] == "stale"
    assert incident_feed_health({"a": snap(fresh=False)}, {}, ("a",), 2700, NOW)[0] == "unavailable"


def test_outage_never_keeps_false_ban_available():
    result = dated_danger("Fixture", {"today": {"rating": "High", "total_fire_ban": False}}, snap(fresh=False), stale_seconds=2700, now=NOW)
    assert result["today"]["total_fire_ban"] is None
    assert not result["today"]["available"]
    assert result["today"]["last_known"]["total_fire_ban"] is False


def test_yesterdays_today_is_not_redated():
    result = dated_danger("Fixture", {"today": {"rating": "High", "total_fire_ban": False}}, snap(anchor=NOW-timedelta(days=1)), stale_seconds=2700, now=NOW)
    assert result["today"]["total_fire_ban"] is None
    assert result["today"]["rating"] == "Unknown"


def test_revalidated_yesterdays_tomorrow_maps_to_today():
    result = dated_danger("Fixture", {"today": {"rating": "High", "total_fire_ban": False}, "tomorrow": {"rating": "Extreme", "total_fire_ban": True}}, snap(anchor=NOW-timedelta(days=1)), stale_seconds=2700, now=NOW)
    assert result["today"]["total_fire_ban"] is True
    assert result["today"]["rating"] == "Extreme"
    assert not result["tomorrow"]["available"]


def test_nsw_calendar_not_utc_calendar():
    now = datetime(2026, 9, 5, 15, tzinfo=timezone.utc)
    snapshot = snap(anchor=NOW)
    snapshot.fetched_at = now
    result = dated_danger("Fixture", {"today": {"rating": "High"}, "tomorrow": {"rating": "Extreme"}}, snapshot, stale_seconds=2700, now=now)
    assert result["today"]["date"] == "2026-09-06"
    assert result["today"]["rating"] == "Extreme"


@pytest.mark.parametrize("point,expected", [((0., 0.), True), ((0., 3.), False), ((-2., -2.), True)])
def test_polygon_containment_and_boundary(point, expected):
    inside, distance = area_relevance(point, ((RING,),))
    assert inside is expected
    assert (distance == 0) is expected


def test_polygon_holes_and_disjoint_areas():
    hole = ((-1., -1.), (-1., 1.), (1., 1.), (1., -1.))
    assert area_relevance((0., 0.), ((RING, hole),))[0] is False
    assert area_relevance((1.5, 0.), ((RING, hole),)) == (True, 0.0)
    other = ((4., 4.), (4., 6.), (6., 6.), (6., 4.))
    assert area_relevance((5., 5.), ((RING,), (other,))) == (True, 0.0)


def test_invalid_or_absent_geometry_is_unknown():
    assert area_relevance((0., 0.), ()) == (None, None)
    assert area_relevance((0., 0.), ((((0., 0.), (float("nan"), 1.), (2., 2.)),),)) == (None, None)


def test_dateline_polygon_does_not_cover_greenwich():
    ring = ((-1., 179.), (-1., -179.), (1., -179.), (1., 179.))
    assert area_relevance((0., 180.), ((ring,),)) == (True, 0.0)
    assert area_relevance((0., 0.), ((ring,),))[0] is False


def queue(services=SERVICES):
    result = NotificationOutbox()
    result.enqueue(services, "Fixture warning", "Fixture message", {"tag": "fixture"}, NOW)
    return result


async def test_successful_recipient_not_retried_after_restore():
    box = queue()
    seen = []
    async def send(item):
        seen.append(item["service"])
        if item["service"] == SERVICES[1]:
            raise RuntimeError("Temporary failure")
    await box.drain(now=NOW, configured_services=SERVICES, sender=send, persist=AsyncMock(), allow_send=True)
    assert len(box.pending) == 1 and box.health["failed_count"] == 1
    restored = NotificationOutbox(box.dump())
    async def recovered(item):
        seen.append(item["service"])
    await restored.drain(now=NOW+timedelta(seconds=31), configured_services=SERVICES, sender=recovered, persist=AsyncMock(), allow_send=True)
    assert seen == [SERVICES[0], SERVICES[1], SERVICES[1]]
    assert not restored.pending


async def test_persist_precedes_send():
    order = []
    async def persist():
        order.append("persist")
    async def send(item):
        order.append("send")
    await queue(SERVICES[:1]).drain(now=NOW, configured_services=SERVICES, sender=send, persist=persist, allow_send=True)
    assert order == ["persist", "send", "persist"]


@pytest.mark.parametrize("allowed", [True, False])
async def test_expired_alert_is_never_sent(allowed):
    box, send = queue(), AsyncMock()
    await box.drain(now=NOW+timedelta(minutes=16), configured_services=SERVICES, sender=send, persist=AsyncMock(), allow_send=allowed)
    send.assert_not_awaited()
    assert not box.pending and box.expired_count == 2


async def test_removed_recipients_pruned():
    box, send = queue(), AsyncMock()
    await box.drain(now=NOW, configured_services=(), sender=send, persist=AsyncMock(), allow_send=True)
    assert not box.pending
    send.assert_not_awaited()


async def test_backoff_prevents_repeated_attempts():
    box = queue(SERVICES[:1])
    send = AsyncMock(side_effect=RuntimeError("Temporary failure"))
    for seconds in (0, 1, 29):
        await box.drain(now=NOW+timedelta(seconds=seconds), configured_services=SERVICES, sender=send, persist=AsyncMock(), allow_send=True)
    assert send.await_count == 1


async def test_cancellation_preserves_pending():
    box = queue(SERVICES[:1])
    with pytest.raises(asyncio.CancelledError):
        await box.drain(now=NOW, configured_services=SERVICES, sender=AsyncMock(side_effect=asyncio.CancelledError()), persist=AsyncMock(), allow_send=True)
    assert len(box.pending) == 1


async def test_newer_transition_supersedes_old_queue():
    box = queue()
    box.enqueue(SERVICES, "Changed", "Newer message", {"tag": "fixture"}, NOW+timedelta(seconds=1))
    assert len(box.pending) == 2
    assert all(item["title"] == "Changed" for item in box.pending.values())


async def test_ineligible_work_is_retained():
    box, send = queue(), AsyncMock()
    await box.drain(now=NOW, configured_services=SERVICES, sender=send, persist=AsyncMock(), allow_send=True, eligible=lambda item: False)
    assert len(box.pending) == 2
    send.assert_not_awaited()


async def test_failed_checkpoint_prevents_send():
    send = AsyncMock()
    with pytest.raises(OSError):
        await queue().drain(now=NOW, configured_services=SERVICES, sender=send, persist=AsyncMock(side_effect=OSError("Disk unavailable")), allow_send=True)
    send.assert_not_awaited()
