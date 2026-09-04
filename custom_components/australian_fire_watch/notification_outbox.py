"""Persistent per-recipient notification work, stored with lifecycle records.

Delivery is at-least-once across a crash. Stable tags replace retried messages
rather than stacking them. A newer transition supersedes older queued messages.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

TTL_SECONDS = 15 * 60
SEND_TIMEOUT_SECONDS = 20


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("Outbox timestamp must include a timezone")
    return result


class NotificationOutbox:
    """One failing recipient never causes successful recipients to be retried."""

    def __init__(self, saved: Mapping[str, Any] | None = None) -> None:
        saved = saved if isinstance(saved, Mapping) else {}
        self.pending: dict[str, dict[str, Any]] = {}
        pending = saved.get("pending") or {}
        for key, value in (pending.items() if isinstance(pending, Mapping) else ()):
            try:
                item = deepcopy(dict(value))
                for field in ("created_at", "expires_at", "next_attempt_at"):
                    _time(item[field])
                if not item["service"].startswith("notify.") or not item["data"].get("tag"):
                    continue
                item["attempts"] = max(0, int(item.get("attempts", 0)))
                self.pending[str(key)] = item
            except (ValueError, TypeError, KeyError, AttributeError):
                continue
        self.expired_count = max(0, int(saved.get("expired_count", 0)))
        self.last_error: str | None = saved.get("last_error")
        self.last_success: str | None = saved.get("last_success")

    def dump(self) -> dict[str, Any]:
        return deepcopy({"pending": self.pending, "expired_count": self.expired_count,
                         "last_error": self.last_error, "last_success": self.last_success})

    def discard_tag(self, tag: str) -> None:
        for key, item in tuple(self.pending.items()):
            if item["data"]["tag"] == tag:
                self.pending.pop(key, None)

    def enqueue(self, services: tuple[str, ...], title: str, message: str,
                data: Mapping[str, Any], now: datetime, *, guard: Mapping[str, Any] | None = None) -> None:
        tag = str(data["tag"])
        self.discard_tag(tag)
        for service in dict.fromkeys(services):
            key = f"{service}|{tag}"
            self.pending[key] = {
                "service": service, "title": title, "message": message,
                "data": deepcopy(dict(data)), "guard": deepcopy(dict(guard or {})),
                "created_at": now.isoformat(),
                "expires_at": (now+timedelta(seconds=TTL_SECONDS)).isoformat(),
                "next_attempt_at": now.isoformat(), "attempts": 0, "last_error": None,
            }

    @property
    def health(self) -> dict[str, Any]:
        failures = sum(bool(item.get("last_error")) for item in self.pending.values())
        return {"pending_count": len(self.pending), "failed_count": failures,
                "expired_count": self.expired_count, "last_error": self.last_error,
                "last_successful_delivery": self.last_success,
                "status": "failed" if failures or self.expired_count else "pending" if self.pending else "ok"}

    async def drain(
        self, *, now: datetime, configured_services: tuple[str, ...],
        sender: Callable[[dict[str, Any]], Awaitable[None]],
        persist: Callable[[], Awaitable[None]], allow_send: bool,
        eligible: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        """Retry due work; discard expired events and removed recipients.

        The coordinator serializes drains with polling and acknowledgement.
        Cancellation is not caught, so pending work survives shutdown.
        """
        for key, item in tuple(self.pending.items()):
            if item["service"] not in configured_services or _time(item["expires_at"]) <= now:
                if item["service"] in configured_services:
                    self.expired_count += 1
                    self.last_error = "A pending notification expired before delivery"
                self.pending.pop(key, None)
                await persist()
                continue
            if not allow_send or (eligible is not None and not eligible(item)) or _time(item["next_attempt_at"]) > now:
                continue
            item["attempts"] += 1
            delay = min(30 * 2**min(item["attempts"]-1, 4), 300)
            item["next_attempt_at"] = (now+timedelta(seconds=delay)).isoformat()
            await persist()
            try:
                async with asyncio.timeout(SEND_TIMEOUT_SECONDS):
                    await sender(item)
            except Exception as err:
                item["last_error"] = f"{type(err).__name__}: {err}"[:300]
                self.last_error = item["last_error"]
            else:
                self.pending.pop(key, None)
                self.last_success = now.isoformat()
            await persist()
