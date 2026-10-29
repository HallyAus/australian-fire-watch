"""Pure Queensland ArcGIS response normalization; no Home Assistant dependencies."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

# Queensland uses AEST all year. A fixed offset avoids first-use ZoneInfo disk I/O
# on Home Assistant's event loop.
AEST = timezone(timedelta(hours=10), name="AEST")
UTC = timezone.utc
VALID_RATINGS = frozenset(
    {"No Rating", "Moderate", "High", "Extreme", "Catastrophic"}
)


class QldDataError(ValueError):
    """The upstream response is not trustworthy for a boolean/rating state."""


def _timestamp(value: Any) -> datetime | None:
    """Convert an ArcGIS epoch-millisecond field to aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QldDataError("Invalid ArcGIS timestamp type")
    try:
        return datetime.fromtimestamp(value / 1000, UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise QldDataError("Invalid ArcGIS timestamp value") from exc


def _features(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("error") is not None:
        raise QldDataError("ArcGIS returned an error")
    features = payload.get("features")
    if not isinstance(features, list):
        raise QldDataError("ArcGIS features array missing")
    result = []
    for item in features:
        if not isinstance(item, dict) or not isinstance(item.get("attributes"), dict):
            raise QldDataError("Invalid ArcGIS feature attributes")
        result.append(item["attributes"])
    return result


def _one_feature(payload: Any) -> dict[str, Any] | None:
    features = _features(payload)
    if len(features) > 1 or payload.get("exceededTransferLimit"):
        raise QldDataError("Ambiguous geographic match")
    return features[0] if features else None


def parse_forecast(
    payload: Any, *, now: datetime, max_age: timedelta = timedelta(hours=36)
) -> dict[str, Any]:
    """Parse the fire danger polygon covering the monitored point.

    ``covered`` is False only for a valid zero-feature spatial query. It is
    unknown on a failed request (handled by the provider).
    """
    row = _one_feature(payload)
    if row is None:
        return {"covered": False, "health": "unavailable", "error": "out_of_coverage"}

    district = row.get("Area_Name")
    if not isinstance(district, str) or not district.strip():
        raise QldDataError("Fire weather district missing")

    published = _timestamp(row.get("FMETimeStamp"))
    if published is None:
        raise QldDataError("Forecast source timestamp missing")
    now_utc = now.astimezone(UTC)
    age = now_utc - published
    if age < -timedelta(hours=2):
        raise QldDataError("Forecast source timestamp is in the future")

    by_date: dict[date, str] = {}
    for n in range(1, 5):
        raw_date, rating = row.get(f"Date{n}"), row.get(f"Day{n}")
        if raw_date is None and (rating is None or rating == ""):
            continue
        stamp = _timestamp(raw_date)
        if stamp is None:
            raise QldDataError("Forecast rating has no date")
        local_day = stamp.astimezone(AEST).date()
        if rating not in VALID_RATINGS:
            raise QldDataError("Unexpected AFDRS rating")
        if local_day in by_date:
            raise QldDataError("Duplicate fire danger forecast date")
        by_date[local_day] = rating

    if not by_date:
        raise QldDataError("No dated fire danger ratings")
    today = now.astimezone(AEST).date()
    forecast = [
        {"date": (today + timedelta(days=n)).isoformat(),
         "rating": by_date.get(today + timedelta(days=n), "Unknown"),
         "available": (today + timedelta(days=n)) in by_date and age <= max_age}
        for n in range(4)
    ]
    return {
        "covered": True,
        "health": "fresh" if age <= max_age else "stale",
        "district": district.strip(),
        "source_updated_at": published.isoformat(),
        "forecast": forecast,
        "error": None if age <= max_age else "source_timestamp_stale",
    }


def parse_local_fire_ban(payload: Any) -> dict[str, Any]:
    """Parse explicit QFD fire-ban states; never derive No Ban from zero rows."""
    row = _one_feature(payload)
    if row is None:
        raise QldDataError("No council fire-ban polygon matched location")
    council, raw = row.get("SHIRE_NAME"), row.get("HASFIREBAN")
    if not isinstance(council, str) or not council.strip():
        raise QldDataError("Council name missing")
    if raw not in ("Fire Ban", "No Fire Ban"):
        raise QldDataError("Unexpected fire-ban state")
    link = row.get("Link")
    return {
        "state": raw == "Fire Ban",
        "raw_status": raw,
        "lga": council.strip(),
        "effective_from": _iso(_timestamp(row.get("DATE_FROM"))),
        "effective_to": _iso(_timestamp(row.get("DATE_TO"))),
        "record_updated_at": _iso(_timestamp(row.get("FMETimestamp"))),
        "declaration_url": link if isinstance(link, str) and link.startswith("https://") else None,
    }


def danger_from_forecast(forecast: dict[str, Any]) -> dict[str, Any]:
    """Build the existing coordinator danger contract without NSW ban semantics."""
    days = list(forecast.get("forecast") or [])

    def day(index: int) -> dict[str, Any]:
        info = days[index] if index < len(days) else {}
        return {
            "date": info.get("date"),
            "rating": info.get("rating", "Unknown"),
            "available": bool(info.get("available")),
            "fbi": None,
            "total_fire_ban": None,
            "issued_at": forecast.get("source_updated_at"),
            "rating_source": "QFD/BOM ArcGIS FDR",
            "fbi_source": None,
            "retained": not bool(info.get("available")),
        }

    return {
        "district": forecast.get("district"),
        "today": day(0),
        "tomorrow": day(1),
        "forecast": days,
        "rfs_issued_at": None,
        "bom_issued_at": forecast.get("source_updated_at"),
        "source_note": (
            "Queensland QFD/BOM forecast; fire bans are separate legal declarations. "
            "Unmatched or stale ratings are unavailable."
        ),
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def danger_with_local_fire_ban(
    danger: dict[str, Any], ban: dict[str, Any]
) -> dict[str, Any]:
    """Reuse today's legacy Total Fire Ban field with QLD's legal declaration.

    Restriction availability is deliberately independent of FDR availability.
    This must only be called when the configured position is in Queensland.
    """
    today = dict(danger.get("today") or {})
    valid = ban.get("health") == "fresh" and isinstance(ban.get("state"), bool)
    today.update({
        "total_fire_ban": ban["state"] if valid else None,
        "total_fire_ban_available": valid,
        "fire_ban_health": ban.get("health", "unavailable"),
        "fire_ban_lga": ban.get("lga"),
        "fire_ban_source_status": ban.get("raw_status"),
        "fire_ban_effective_from": ban.get("effective_from"),
        "fire_ban_effective_to": ban.get("effective_to"),
        "fire_ban_record_updated_at": ban.get("record_updated_at"),
    })
    return {**danger, "today": today}


def merge_qld_feed_health(
    feed: dict[str, Any], qld: dict[str, Any]
) -> dict[str, Any]:
    """Incorporate QLD enrichment into existing Feed health / Feed problem.

    Keep incident completeness independent, so an FDR outage cannot clear an
    existing incident warning or manufacture an all-clear.
    """
    result = dict(feed)
    sources = dict(feed.get("sources") or {})
    details: dict[str, dict[str, Any]] = {}
    for name, key, url in (
        (
            "QLD fire danger",
            "forecast",
            "https://www.fire.qld.gov.au/prepare/bushfire/fire-danger-ratings",
        ),
        (
            "QLD local fire ban",
            "local_fire_ban",
            "https://www.fire.qld.gov.au/safety-education/using-fire-outdoors/"
            "fire-bans-and-restrictions",
        ),
    ):
        record = dict(qld.get(key) or {})
        status = str(record.get("health", "unavailable"))
        detail = {
            "status": status,
            "jurisdiction": "QLD",
            "url": url,
            "last_successful_fetch": (
                record.get("checked_at") if status == "fresh" else None
            ),
            "last_checked": record.get("checked_at"),
            "last_changed": record.get("source_updated_at")
            or record.get("record_updated_at"),
            "error": record.get("error"),
        }
        sources[f"qld_{key}"] = detail
        details[key] = detail
    result["sources"] = sources
    cross_check = dict(feed.get("cross_check") or {})
    cross_check["qld_enrichment_count"] = len(details)
    cross_check["qld_enrichment_available_count"] = sum(
        detail["status"] == "fresh" for detail in details.values()
    )
    result["cross_check"] = cross_check
    result["qld_enrichment"] = {
        "status": qld.get("health", "unavailable"),
        "sources": details,
    }
    qld_failed = [name for name, detail in details.items() if detail["status"] != "fresh"]
    if qld_failed:
        if result.get("status") == "fresh":
            result["status"] = "degraded"
        message = "QLD enrichment delayed or unavailable: " + ", ".join(qld_failed)
        result["message"] = "; ".join(
            part for part in (result.get("message"), message) if part
        )
    return result
