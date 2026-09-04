"""Pure validity, freshness and calendar-date rules for official feeds."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

NSW_TZ = ZoneInfo("Australia/Sydney")


def _recent(snapshot: Any, parsed: Any, stale_seconds: int, now: datetime) -> bool:
    fetched = snapshot.fetched_at
    if fetched is None or not -60 <= (now - fetched).total_seconds() <= stale_seconds:
        return False
    metadata = getattr(parsed, "metadata", {})
    # Per-incident update times are NOT the age of a successfully revalidated feed.
    if metadata.get("generated_at_is_feed_time"):
        generated = getattr(parsed, "generated_at", None)
        if generated is not None and not -60 <= (now - generated).total_seconds() <= stale_seconds:
            return False
    return True


def current_snapshot(snapshot: Any, parsed: Any, stale_seconds: int, now: datetime) -> bool:
    """Require a complete current response, not merely a retained body."""
    return bool(
        parsed is not None
        and snapshot.response_received
        and _recent(snapshot, parsed, stale_seconds, now)
        and getattr(parsed, "metadata", {}).get("complete", True)
    )


def incident_feed_health(
    snapshots: Mapping[str, Any], parsed: Mapping[str, Any],
    required: tuple[str, ...], stale_seconds: int, now: datetime,
) -> tuple[str, tuple[str, ...]]:
    """One current source can add warnings; all sources are needed for absence."""
    current = tuple(name for name in required if current_snapshot(snapshots[name], parsed.get(name), stale_seconds, now))
    available = [name for name in required if parsed.get(name) is not None]
    if not available:
        return "unavailable", current
    if len(current) == len(required):
        return "fresh", current
    recent = any(_recent(snapshots[name], parsed[name], stale_seconds, now) for name in available)
    return ("degraded" if recent else "stale"), current


def dated_danger(
    district: str, rfs: Mapping[str, Any], snapshot: Any, *,
    stale_seconds: int, now: datetime,
) -> dict[str, Any]:
    """Bind relative days to publication/acceptance time, never to each poll.

    Unchanged responses and 304s do not advance changed_at. A freshly
    revalidated declaration can use yesterday's explicitly published tomorrow.
    Failed fetches never expose a current-day boolean, even with retained data.
    """
    anchor = snapshot.changed_at
    current = current_snapshot(snapshot, rfs or None, stale_seconds, now)
    today = now.astimezone(NSW_TZ).date()
    by_date: dict[str, dict[str, Any]] = {}
    if anchor is not None:
        base = anchor.astimezone(NSW_TZ).date()
        for offset, period in enumerate(("today", "tomorrow")):
            by_date[(base + timedelta(days=offset)).isoformat()] = dict(rfs.get(period) or {})
    result: dict[str, Any] = {"district": district}
    for offset, period in enumerate(("today", "tomorrow")):
        day = (today + timedelta(days=offset)).isoformat()
        raw = by_date.get(day, {})
        usable = bool(current and raw)
        result[period] = {
            "date": day,
            "rating": raw.get("rating", "Unknown") if usable else "Unknown",
            "total_fire_ban": raw.get("total_fire_ban") if usable else None,
            "available": usable,
            "issued_at": anchor.isoformat() if anchor else None,
            "rating_source": "NSW RFS fdrToban.xml" if usable else None,
            "last_known": dict(raw) if raw and not usable else None,
        }
    return result
