"""Coordinator that combines official NSW RFS and BOM products safely."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import FeedSnapshot, OfficialFeedClient
from .const import (
    BOM_FIRE_DANGER_URL,
    BOM_WARNINGS_URL,
    CAP_URL,
    CONF_ADVICE_RADIUS,
    CONF_DISTRICT,
    CONF_ENABLE_BOM,
    CONF_EMERGENCY_RADIUS,
    CONF_MONITOR_RADIUS,
    CONF_NAME,
    CONF_NOTIFY_SERVICES,
    CONF_READINESS_ENTITIES,
    CONF_STALE_AFTER,
    CONF_UNCLASSIFIED_RADIUS,
    CONF_WATCH_RADIUS,
    CONF_WEATHER_ENTITY,
    CONF_ZONE,
    DEFAULT_ADVICE_RADIUS_KM,
    DEFAULT_DISTRICT,
    DEFAULT_ENABLE_BOM,
    DEFAULT_EMERGENCY_RADIUS_KM,
    DEFAULT_MONITOR_RADIUS_KM,
    DEFAULT_NAME,
    DEFAULT_STALE_AFTER_MINUTES,
    DEFAULT_UNCLASSIFIED_RADIUS_KM,
    DEFAULT_WATCH_RADIUS_KM,
    DEFAULT_ZONE,
    DOMAIN,
    EVENT_ALERT,
    FDR_TOBAN_URL,
    GEOJSON_URL,
    INCIDENT_ALERTS_URL,
    MIN_UPDATE_INTERVAL,
    OFFICIAL_BOM_WARNINGS_URL,
    OFFICIAL_DANGER_URL,
    OFFICIAL_INCIDENTS_URL,
    SUMMARY_INCIDENT_LIMIT,
    SUMMARY_PLANNED_LIMIT,
)
from .model import (
    authoritative_incident_snapshot_valid,
    DangerLifecycleEvent,
    Incident,
    LifecycleEvent,
    WarningLevel,
    danger_notification_priority,
    incident_entity_id,
    incident_event_summary,
    incident_notification_priority,
    normalize_warning,
    sort_incidents,
    track_danger_lifecycle,
    track_incident_lifecycle,
)
from .parsers import (
    FeedParseError,
    merge_incidents,
    parse_bom_fire_danger,
    parse_bom_fire_weather_warnings,
    parse_cap,
    parse_geojson,
    parse_rfs_fire_danger,
)

_LOGGER = logging.getLogger(__name__)

CORE_FEEDS = {
    "rfs_cap": CAP_URL,
    "rfs_geojson": GEOJSON_URL,
    "rfs_incident_alerts": INCIDENT_ALERTS_URL,
    "rfs_fdr_toban": FDR_TOBAN_URL,
}

BOM_FEEDS = {
    "bom_idn10016": BOM_FIRE_DANGER_URL,
    "bom_nsw_warnings": BOM_WARNINGS_URL,
}


class FireWatchCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch, normalize, rank and track one monitored zone."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=MIN_UPDATE_INTERVAL,
            always_update=False,
        )
        self.entry = entry
        self.api = OfficialFeedClient(aiohttp_client.async_get_clientsession(hass))
        self._store = Store[dict[str, Any]](
            hass, 1, f"{DOMAIN}.{entry.entry_id}.lifecycle"
        )
        self._store_lock = asyncio.Lock()
        self._records: dict[str, dict[str, Any]] = {}
        self._danger_records: dict[str, dict[str, Any]] = {}
        self._acknowledged: dict[str, str] = {}
        self._snoozed: dict[str, str] = {}
        self._baseline_complete = False
        self._danger_baseline_complete = False
        self._incidents: tuple[Incident, ...] = ()
        self._planned: tuple[Incident, ...] = ()
        self._danger: dict[str, Any] = _unknown_danger()
        self._warnings: list[dict[str, Any]] = []
        self._feed: dict[str, Any] = _empty_feed()
        self._parse_errors: dict[str, str] = {}
        self.last_events: tuple[LifecycleEvent, ...] = ()
        self.last_danger_events: tuple[DangerLifecycleEvent, ...] = ()

    @property
    def config(self) -> dict[str, Any]:
        """Config entry data with options taking precedence."""
        return {**dict(self.entry.data), **dict(self.entry.options)}

    async def async_initialize(self) -> None:
        """Load persistent lifecycle/acknowledgement state before first poll."""
        saved = await self._store.async_load() or {}
        self._records = {
            str(key): dict(value)
            for key, value in (saved.get("records") or {}).items()
            if isinstance(value, Mapping)
        }
        self._danger_records = {
            str(key): dict(value)
            for key, value in (saved.get("danger_records") or {}).items()
            if isinstance(value, Mapping)
        }
        self._acknowledged = {
            str(key): str(value)
            for key, value in (saved.get("acknowledged") or {}).items()
        }
        self._snoozed = {
            str(key): str(value) for key, value in (saved.get("snoozed") or {}).items()
        }
        self._baseline_complete = bool(saved.get("baseline_complete", False))
        self._danger_baseline_complete = bool(
            saved.get("danger_baseline_complete", False)
        )

    async def _async_update_data(self) -> dict[str, Any]:
        feeds = dict(CORE_FEEDS)
        bom_enabled = bool(self.config.get(CONF_ENABLE_BOM, DEFAULT_ENABLE_BOM))
        if bom_enabled:
            feeds.update(BOM_FEEDS)
        snapshots_list = await asyncio.gather(
            *(self.api.async_fetch(name, url) for name, url in feeds.items())
        )
        snapshots = {snapshot.name: snapshot for snapshot in snapshots_list}
        self._parse_errors = {}

        cap = self._parse("rfs_cap", snapshots["rfs_cap"], parse_cap)
        geojson = self._parse("rfs_geojson", snapshots["rfs_geojson"], parse_geojson)
        supplemental = self._parse(
            "rfs_incident_alerts",
            snapshots["rfs_incident_alerts"],
            lambda body: parse_cap(body, source="NSW RFS IncidentAlerts polygons"),
        )
        rfs_districts = self._parse(
            "rfs_fdr_toban", snapshots["rfs_fdr_toban"], parse_rfs_fire_danger
        )
        bom_danger = (
            self._parse(
                "bom_idn10016", snapshots["bom_idn10016"], parse_bom_fire_danger
            )
            if bom_enabled
            else None
        )
        bom_warnings = (
            self._parse(
                "bom_nsw_warnings",
                snapshots["bom_nsw_warnings"],
                parse_bom_fire_weather_warnings,
            )
            if bom_enabled
            else None
        )

        primary_incidents = cap.incidents if cap else ()
        fallback_incidents = geojson.incidents if geojson else ()
        supplemental_incidents = supplemental.incidents if supplemental else ()
        merged = merge_incidents(
            primary_incidents, fallback_incidents, supplemental_incidents
        )
        home_latitude, home_longitude = self._home_coordinates()
        monitor_radius = float(
            self.config.get(CONF_MONITOR_RADIUS, DEFAULT_MONITOR_RADIUS_KM)
        )
        located = tuple(
            incident.with_home(home_latitude, home_longitude) for incident in merged
        )
        geojson_feature_count = (
            int(geojson.metadata.get("feature_count", -1))
            if geojson is not None
            else -1
        )
        cap_current = bool(cap is not None and snapshots["rfs_cap"].response_received)
        geojson_response_current = bool(
            geojson is not None and snapshots["rfs_geojson"].response_received
        )
        empty_corroborated = bool(
            cap_current
            and geojson_response_current
            and cap is not None
            and geojson is not None
            and not cap.incidents
            and not geojson.incidents
        )
        geojson_validated = bool(
            geojson is not None
            and authoritative_incident_snapshot_valid(
                response_received=geojson_response_current,
                parsed_count=len(geojson.incidents),
                advertised_count=geojson_feature_count,
                existing_record_count=len(self._records),
                empty_corroborated=empty_corroborated,
            )
        )
        authoritative_merged = merge_incidents(
            (cap.incidents if cap_current and cap is not None else ()),
            geojson.incidents if geojson_validated and geojson is not None else (),
            (
                supplemental.incidents
                if supplemental is not None
                and snapshots["rfs_incident_alerts"].response_received
                else ()
            ),
        )
        authoritative_located = tuple(
            incident.with_home(home_latitude, home_longitude)
            for incident in authoritative_merged
        )
        authoritative_monitored = tuple(
            incident
            for incident in authoritative_located
            if incident.distance_km is None or incident.distance_km <= monitor_radius
        )
        monitored = tuple(
            incident
            for incident in located
            if incident.distance_km is None or incident.distance_km <= monitor_radius
        )
        self._incidents = tuple(
            incident
            for incident in sort_incidents(monitored)
            if not incident.is_planned
        )
        self._planned = tuple(
            incident for incident in sort_incidents(monitored) if incident.is_planned
        )
        self._danger = self._compose_danger(rfs_districts, bom_danger, snapshots)
        self._warnings = (
            list(bom_warnings.metadata.get("warnings", [])) if bom_warnings else []
        )
        self._feed = self._compose_feed(snapshots, cap, geojson)

        snapshot_current = bool(
            self._feed["status"] not in {"stale", "unavailable"} and geojson_validated
        )
        resolution_current = bool(snapshot_current and cap_current)
        events = await self._async_track_lifecycle(
            authoritative_monitored,
            authoritative_located,
            snapshot_current,
            resolution_current,
        )
        danger_current = bool(
            rfs_districts
            and str(self.config.get(CONF_DISTRICT, DEFAULT_DISTRICT)) in rfs_districts
            and snapshots["rfs_fdr_toban"].response_received
        )
        danger_events = await self._async_track_danger_lifecycle(danger_current)
        self.last_events = tuple(events)
        self.last_danger_events = tuple(danger_events)
        data = self._compose_data()
        await self._async_emit_events(events, danger_events)
        return data

    def _parse(self, name: str, snapshot: FeedSnapshot, parser: Any) -> Any | None:
        if snapshot.body is None:
            return None
        try:
            return parser(snapshot.body)
        except (FeedParseError, ValueError, TypeError, KeyError) as err:
            self._parse_errors[name] = f"{type(err).__name__}: {err}"[:300]
            _LOGGER.error("Unable to parse official feed %s: %s", name, err)
            return None

    def _home_coordinates(self) -> tuple[float, float]:
        zone_entity = str(self.config.get(CONF_ZONE, DEFAULT_ZONE))
        zone = self.hass.states.get(zone_entity)
        if zone:
            try:
                return float(zone.attributes["latitude"]), float(
                    zone.attributes["longitude"]
                )
            except (KeyError, TypeError, ValueError):
                _LOGGER.warning(
                    "Zone %s has no usable coordinates; using HA home", zone_entity
                )
        return float(self.hass.config.latitude), float(self.hass.config.longitude)

    def _compose_danger(
        self,
        rfs_districts: dict[str, Any] | None,
        bom: dict[str, Any] | None,
        snapshots: dict[str, FeedSnapshot],
    ) -> dict[str, Any]:
        district = str(self.config.get(CONF_DISTRICT, DEFAULT_DISTRICT))
        rfs = (rfs_districts or {}).get(district, {})
        issued_rfs = _iso(snapshots["rfs_fdr_toban"].changed_at)
        bom_issued = _iso((bom or {}).get("issued_at"))
        bom_forecasts = list((bom or {}).get("districts", {}).get(district, []))
        local_today = dt_util.now().date()
        by_date = {item.get("date"): item for item in bom_forecasts}

        def day(name: str, offset: int) -> dict[str, Any]:
            rfs_day = dict(rfs.get(name) or {})
            date = (local_today + timedelta(days=offset)).isoformat()
            bom_day = by_date.get(date, {})
            return {
                "date": date,
                "rating": rfs_day.get("rating", "Unknown"),
                "fbi": bom_day.get("fbi"),
                "total_fire_ban": rfs_day.get("total_fire_ban"),
                "issued_at": issued_rfs,
                "rating_source": "NSW RFS fdrToban.xml" if rfs_day else None,
                "fbi_source": "BOM IDN10016" if bom_day else None,
            }

        return {
            "district": district,
            "today": day("today", 0),
            "tomorrow": day("tomorrow", 1),
            "forecast": bom_forecasts,
            "bom_issued_at": bom_issued,
            "rfs_issued_at": issued_rfs,
            "source_note": (
                "NSW RFS is the source of truth for ratings and Total Fire Bans; "
                "BOM IDN10016 supplements the four-day Fire Behaviour Index."
            ),
        }

    def _compose_feed(
        self,
        snapshots: dict[str, FeedSnapshot],
        cap: Any | None,
        geojson: Any | None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        primary = snapshots["rfs_cap"] if cap else snapshots["rfs_geojson"]
        generated = None
        if cap:
            generated = cap.generated_at
        elif geojson:
            generated = snapshots["rfs_geojson"].last_modified or geojson.generated_at
        generated = generated or primary.changed_at or primary.fetched_at
        age_seconds = _age_seconds(generated, now)
        stale_after = (
            int(self.config.get(CONF_STALE_AFTER, DEFAULT_STALE_AFTER_MINUTES)) * 60
        )
        if cap is None and geojson is None:
            status = "unavailable"
        elif age_seconds is None or age_seconds > stale_after:
            status = "stale"
        elif cap is None:
            status = "degraded"
        elif self._parse_errors or any(
            snapshots[name].status in {"retained", "backoff", "unavailable"}
            for name in ("rfs_fdr_toban", "bom_idn10016", "bom_nsw_warnings")
            if name in snapshots
        ):
            status = "degraded"
        else:
            status = "fresh"

        cap_ids = {incident.id for incident in cap.incidents} if cap else set()
        geo_ids = {incident.id for incident in geojson.incidents} if geojson else set()
        source_details = {
            name: {
                "status": snapshot.status,
                "url": snapshot.url,
                "last_successful_fetch": _iso(snapshot.fetched_at),
                "last_changed": _iso(snapshot.changed_at),
                "last_modified": _iso(snapshot.last_modified),
                "from_cache": snapshot.from_cache,
                "error": snapshot.error or self._parse_errors.get(name),
            }
            for name, snapshot in snapshots.items()
        }
        return {
            "status": status,
            "last_successful_update": _iso(primary.fetched_at),
            "data_generated_at": _iso(generated),
            "age_seconds": age_seconds,
            "stale_after_seconds": stale_after,
            "source_name": "NSW RFS CAP" if cap else "NSW RFS GeoJSON fallback",
            "official_url": OFFICIAL_INCIDENTS_URL,
            "attribution": (
                "© State of New South Wales (NSW Rural Fire Service). "
                "For current information go to www.rfs.nsw.gov.au."
            ),
            "cross_check": {
                "cap_count": len(cap_ids),
                "geojson_count": len(geo_ids),
                "cap_only_count": len(cap_ids - geo_ids),
                "geojson_only_count": len(geo_ids - cap_ids),
            },
            "sources": source_details,
        }

    def _compose_data(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        _discard_expired(self._snoozed, now)
        qualifying = [
            incident for incident in self._incidents if self._qualifies(incident)
        ]
        highest = (
            qualifying[0]
            if qualifying
            else (self._incidents[0] if self._incidents else None)
        )
        status = self._summary_status(qualifying)
        recommended = _recommended_action(status)
        incident_dicts = [
            self._incident_dict(incident)
            for incident in self._incidents[:SUMMARY_INCIDENT_LIMIT]
        ]
        planned_dicts = [
            self._incident_dict(incident)
            for incident in self._planned[:SUMMARY_PLANNED_LIMIT]
        ]
        warning_level = (
            qualifying[0].warning_level
            if qualifying and qualifying[0].warning_rank > 0
            else None
        )
        location_name = str(self.config.get(CONF_NAME, DEFAULT_NAME))
        alert_targets = _notify_services(self.config.get(CONF_NOTIFY_SERVICES, []))
        return {
            "status": status,
            "entry_id": self.entry.entry_id,
            "integration": DOMAIN,
            "location_name": location_name,
            "summary": _summary_text(status, highest, self._feed),
            "recommended_action": recommended,
            "official_warning_level": warning_level,
            "danger": self._danger,
            "incidents": incident_dicts,
            "planned_burns": planned_dicts,
            "incident_count": len(self._incidents),
            "planned_burn_count": len(self._planned),
            "highest_priority_incident": self._incident_dict(highest)
            if highest
            else None,
            "fire_weather_warnings": self._warnings,
            "fire_weather_warnings_url": OFFICIAL_BOM_WARNINGS_URL,
            "feed": self._feed,
            "weather": self._weather_context(),
            "readiness_entities": list(self.config.get(CONF_READINESS_ENTITIES, [])),
            "alerts_assigned": bool(alert_targets),
            "alert_targets": list(alert_targets),
            "disclaimer": (
                "Supplementary awareness only. Check Hazards Near Me NSW, NSW RFS, "
                "BOM, local radio and emergency instructions."
            ),
            "last_updated": now.isoformat(),
        }

    def _incident_dict(self, incident: Incident | None) -> dict[str, Any] | None:
        if incident is None:
            return None
        return incident.as_dict(
            entity_id=incident_entity_id(self.entry.entry_id, incident.id),
            acknowledged=incident.id in self._acknowledged,
            snoozed_until=self._snoozed.get(incident.id),
        )

    def _summary_status(self, qualifying: list[Incident]) -> str:
        if self._feed.get("status") == "unavailable":
            return "unavailable"
        if self._feed.get("status") == "stale":
            return "stale"
        if qualifying:
            warning = qualifying[0].warning_level
            if warning == WarningLevel.EMERGENCY_WARNING:
                return "emergency_warning"
            if warning == WarningLevel.WATCH_AND_ACT:
                return "watch_and_act"
            if warning == WarningLevel.ADVICE:
                return "advice"
            return "incident_nearby"
        if any(
            incident.distance_km is not None
            and incident.distance_km
            <= float(self.config.get(CONF_ADVICE_RADIUS, DEFAULT_ADVICE_RADIUS_KM))
            for incident in self._planned
        ):
            return "planned_activity"
        return "no_current_warning"

    def _qualifies(self, incident: Incident) -> bool:
        if incident.is_planned or incident.distance_km is None:
            return False
        radius = {
            WarningLevel.EMERGENCY_WARNING: float(
                self.config.get(CONF_EMERGENCY_RADIUS, DEFAULT_EMERGENCY_RADIUS_KM)
            ),
            WarningLevel.WATCH_AND_ACT: float(
                self.config.get(CONF_WATCH_RADIUS, DEFAULT_WATCH_RADIUS_KM)
            ),
            WarningLevel.ADVICE: float(
                self.config.get(CONF_ADVICE_RADIUS, DEFAULT_ADVICE_RADIUS_KM)
            ),
        }.get(incident.warning_level)
        if radius is not None:
            return incident.distance_km <= radius
        return bool(
            incident.is_fire
            and incident.distance_km
            <= float(
                self.config.get(
                    CONF_UNCLASSIFIED_RADIUS, DEFAULT_UNCLASSIFIED_RADIUS_KM
                )
            )
        )

    def _weather_context(self) -> dict[str, Any] | None:
        entity_id = str(self.config.get(CONF_WEATHER_ENTITY, "")).strip()
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return {"entity_id": entity_id, "available": False, "context_only": True}
        attrs = state.attributes
        return {
            "entity_id": entity_id,
            "available": state.state not in {"unknown", "unavailable"},
            "condition": state.state,
            "temperature": attrs.get("temperature"),
            "humidity": attrs.get("humidity"),
            "wind_speed": attrs.get("wind_speed"),
            "wind_gust_speed": attrs.get("wind_gust_speed"),
            "wind_bearing": attrs.get("wind_bearing"),
            "temperature_unit": attrs.get("temperature_unit"),
            "wind_speed_unit": attrs.get("wind_speed_unit"),
            "context_only": True,
            "note": "Weather context only; this integration does not infer fire spread.",
        }

    async def _async_track_lifecycle(
        self,
        incidents: tuple[Incident, ...],
        authoritative_incidents: tuple[Incident, ...],
        snapshot_current: bool,
        resolution_current: bool,
    ) -> list[LifecycleEvent]:
        if not snapshot_current:
            return []
        previous_records = self._records
        previous_baseline = self._baseline_complete
        qualified_ids = {
            incident.id for incident in incidents if self._qualifies(incident)
        }
        records, events, baseline_complete = track_incident_lifecycle(
            previous_records,
            incidents,
            qualified_ids,
            baseline_complete=previous_baseline,
            authoritative_incidents=authoritative_incidents,
            allow_missing_updates=resolution_current,
        )
        self._records = records
        self._baseline_complete = baseline_complete
        state_changed = (
            records != previous_records or baseline_complete != previous_baseline
        )
        for event in events:
            if event.lifecycle in {"escalated", "resolved", "left_radius"}:
                acknowledgement = self._acknowledged.pop(event.incident_id, None)
                snooze = self._snoozed.pop(event.incident_id, None)
                state_changed = bool(acknowledgement or snooze) or state_changed
        if state_changed:
            await self._async_save_state()
        if not previous_baseline and baseline_complete:
            _LOGGER.info(
                "Established incident baseline for %s; initial alerts suppressed",
                self.entry.title,
            )
        return list(events)

    async def _async_track_danger_lifecycle(
        self, snapshot_current: bool
    ) -> list[DangerLifecycleEvent]:
        """Track alert-worthy RFS ratings/bans only after a healthy response."""
        if not snapshot_current:
            return []
        previous_records = self._danger_records
        previous_baseline = self._danger_baseline_complete
        records, events, baseline_complete = track_danger_lifecycle(
            previous_records,
            self._danger,
            baseline_complete=previous_baseline,
        )
        self._danger_records = records
        self._danger_baseline_complete = baseline_complete
        if records != previous_records or baseline_complete != previous_baseline:
            await self._async_save_state()
        if not previous_baseline and baseline_complete:
            _LOGGER.info(
                "Established fire-danger baseline for %s; initial alerts suppressed",
                self.entry.title,
            )
        return list(events)

    async def _async_save_state(self) -> None:
        async with self._store_lock:
            await self._store.async_save(
                {
                    "baseline_complete": self._baseline_complete,
                    "danger_baseline_complete": self._danger_baseline_complete,
                    "records": self._records,
                    "danger_records": self._danger_records,
                    "acknowledged": self._acknowledged,
                    "snoozed": self._snoozed,
                }
            )

    async def _async_emit_events(
        self,
        events: list[LifecycleEvent],
        danger_events: list[DangerLifecycleEvent],
    ) -> None:
        direct_delivery_configured = bool(
            _notify_services(self.config.get(CONF_NOTIFY_SERVICES, []))
        )
        for event in events:
            notification_allowed = self._notification_allowed(event)
            payload = {
                "alert_kind": "incident",
                "entry_id": self.entry.entry_id,
                "location_name": str(self.config.get(CONF_NAME, DEFAULT_NAME)),
                "lifecycle": event.lifecycle,
                "incident_id": event.incident_id,
                "incident": self._incident_dict(event.incident),
                "previous": dict(event.previous or {}),
                "qualifies_for_alert": event.qualifies_for_alert,
                "notification_allowed": notification_allowed,
                "delivery_priority": incident_notification_priority(event),
                "direct_delivery_configured": direct_delivery_configured,
                "summary": incident_event_summary(event),
                "recommended_action": (
                    _recommended_action(self._summary_status([event.incident]))
                    if event.incident and event.qualifies_for_alert
                    else "Check the official incident feed for current information."
                ),
                "notification_tag": (
                    f"nsw-fire-watch-{self.entry.entry_id}-{event.incident_id}"
                ),
                "test": False,
                "official_url": OFFICIAL_INCIDENTS_URL,
            }
            self.hass.bus.async_fire(EVENT_ALERT, payload)
            if event.qualifies_for_alert and notification_allowed:
                await self._async_notify(event, test=False)

        for event in danger_events:
            delivery_priority = danger_notification_priority(
                event.danger, event.lifecycle
            )
            payload = {
                "alert_kind": "danger",
                "entry_id": self.entry.entry_id,
                "location_name": str(self.config.get(CONF_NAME, DEFAULT_NAME)),
                "lifecycle": event.lifecycle,
                "danger_id": event.danger_id,
                "danger": dict(event.danger),
                "previous": dict(event.previous or {}),
                "qualifies_for_alert": event.qualifies_for_alert,
                "notification_allowed": True,
                "delivery_priority": delivery_priority,
                "direct_delivery_configured": direct_delivery_configured,
                "summary": _danger_summary(event),
                "recommended_action": _danger_recommended_action(event),
                "notification_tag": (
                    f"nsw-fire-watch-{self.entry.entry_id}-danger-{event.danger_id}"
                ),
                "test": False,
                "official_url": OFFICIAL_DANGER_URL,
            }
            self.hass.bus.async_fire(EVENT_ALERT, payload)
            if event.qualifies_for_alert:
                await self._async_notify_danger(event)

    def _notification_allowed(self, event: LifecycleEvent) -> bool:
        if event.lifecycle in {
            "escalated",
            "deescalated",
            "resolved",
            "left_radius",
        }:
            return True
        if (
            event.incident is not None
            and event.incident.warning_level == WarningLevel.EMERGENCY_WARNING
        ):
            # Acknowledgement must never hide a material official Emergency
            # Warning update. It only quiets lower-level routine updates.
            return True
        incident_id = event.incident_id
        if incident_id in self._acknowledged:
            return False
        until = _as_datetime(self._snoozed.get(incident_id))
        return until is None or until <= datetime.now(timezone.utc)

    async def _async_notify(self, event: LifecycleEvent, *, test: bool) -> None:
        services = _notify_services(self.config.get(CONF_NOTIFY_SERVICES, []))
        if not services:
            return
        incident = event.incident
        if incident is None:
            previous_title = str(
                (event.previous or {}).get("title") or event.incident_id
            )
            title = f"Incident feed update — {previous_title}"
            message = (
                f"{previous_title} is no longer in current feed after two healthy "
                "snapshots. This does not confirm the area is safe; check the "
                "official incident feed."
            )
            actions = [
                {
                    "action": "URI",
                    "title": "Open official map",
                    "uri": OFFICIAL_INCIDENTS_URL,
                }
            ]
        elif event.lifecycle == "left_radius":
            title = f"Incident range update — {incident.title}"
            message = (
                f"{incident.title} moved outside the configured monitor radius. "
                "It remains in the official feed; check the official map for its "
                "current status."
            )
            actions = [
                {
                    "action": "URI",
                    "title": "Open official map",
                    "uri": OFFICIAL_INCIDENTS_URL,
                }
            ]
        else:
            title_prefix = {
                WarningLevel.EMERGENCY_WARNING: "Emergency Warning",
                WarningLevel.WATCH_AND_ACT: "Watch and Act",
                WarningLevel.ADVICE: "Advice",
            }.get(incident.warning_level, "Fire incident nearby")
            title = f"{'TEST — ' if test else ''}{title_prefix} — {incident.title}"
            distance = (
                f"{incident.distance_km:.1f} km {incident.direction or ''} of "
                f"{self.config.get(CONF_NAME, DEFAULT_NAME)}"
                if incident.distance_km is not None
                else "Distance unavailable"
            )
            message = (
                f"{event.lifecycle.replace('_', ' ').title()}: "
                f"{incident.warning_level}; {incident.control_status}; {distance}. "
                f"{incident.instruction or 'Check official updates now.'}"
            )
            action_base = f"{self.entry.entry_id}|{incident.id}"
            actions = [
                {
                    "action": f"NSW_FIRE_WATCH_ACK|{action_base}",
                    "title": "Acknowledge",
                },
                {
                    "action": "URI",
                    "title": "Open official map",
                    "uri": OFFICIAL_INCIDENTS_URL,
                },
            ]
            if incident.warning_level != WarningLevel.EMERGENCY_WARNING:
                minutes = (
                    30 if incident.warning_level == WarningLevel.WATCH_AND_ACT else 120
                )
                actions.insert(
                    1,
                    {
                        "action": (f"NSW_FIRE_WATCH_SNOOZE|{action_base}|{minutes}"),
                        "title": f"Snooze {minutes} min",
                    },
                )
        data: dict[str, Any] = {
            "tag": f"nsw-fire-watch-{self.entry.entry_id}-{event.incident_id}",
            "group": f"nsw-fire-watch-{self.entry.entry_id}",
            "url": f"/{self.entry.entry_id and 'nsw-fire-watch'}",
            "clickAction": OFFICIAL_INCIDENTS_URL,
            "actions": actions,
        }
        priority = incident_notification_priority(event, test=test)
        _apply_notification_priority(data, priority, "incident")
        await self._async_send_notification(services, title, message, data)

    async def _async_notify_danger(self, event: DangerLifecycleEvent) -> None:
        services = _notify_services(self.config.get(CONF_NOTIFY_SERVICES, []))
        if not services:
            return
        detail = dict(event.danger)
        title = _danger_summary(event)
        message = _danger_notification_message(event)
        data: dict[str, Any] = {
            "tag": (f"nsw-fire-watch-{self.entry.entry_id}-danger-{event.danger_id}"),
            "group": f"nsw-fire-watch-{self.entry.entry_id}",
            "url": "/nsw-fire-watch",
            "clickAction": OFFICIAL_DANGER_URL,
            "actions": [
                {
                    "action": "URI",
                    "title": "Open official ratings",
                    "uri": OFFICIAL_DANGER_URL,
                }
            ],
        }
        priority = danger_notification_priority(detail, event.lifecycle)
        _apply_notification_priority(data, priority, "danger")
        await self._async_send_notification(services, title, message, data)

    async def _async_send_notification(
        self,
        services: tuple[str, ...],
        title: str,
        message: str,
        data: dict[str, Any],
    ) -> None:
        for full_service in services:
            _, service = full_service.split(".", 1)
            if not self.hass.services.has_service("notify", service):
                _LOGGER.warning(
                    "Configured notification service %s is unavailable", full_service
                )
                continue
            try:
                await self.hass.services.async_call(
                    "notify",
                    service,
                    {"title": title, "message": message, "data": data},
                    blocking=True,
                )
            except HomeAssistantError as err:
                _LOGGER.error("Notification through %s failed: %s", full_service, err)

    async def async_acknowledge(self, incident_id: str) -> None:
        """Acknowledge current incident updates until a later escalation."""
        if not any(
            item.id == incident_id for item in (*self._incidents, *self._planned)
        ):
            raise HomeAssistantError(f"Unknown active incident: {incident_id}")
        self._acknowledged[incident_id] = datetime.now(timezone.utc).isoformat()
        self._snoozed.pop(incident_id, None)
        await self._async_save_state()
        self.async_set_updated_data(self._compose_data())

    async def async_snooze(self, incident_id: str, duration_minutes: int) -> None:
        """Temporarily suppress non-emergency notifications."""
        incident = next(
            (
                item
                for item in (*self._incidents, *self._planned)
                if item.id == incident_id
            ),
            None,
        )
        if incident is None:
            raise HomeAssistantError(f"Unknown active incident: {incident_id}")
        if incident.warning_level == WarningLevel.EMERGENCY_WARNING:
            raise HomeAssistantError(
                "Emergency Warnings can be acknowledged but not snoozed"
            )
        maximum = 30 if incident.warning_level == WarningLevel.WATCH_AND_ACT else 120
        if duration_minutes < 1 or duration_minutes > maximum:
            raise HomeAssistantError(
                f"Snooze must be between 1 and {maximum} minutes for this warning level"
            )
        self._snoozed[incident_id] = (
            datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
        ).isoformat()
        self._acknowledged.pop(incident_id, None)
        await self._async_save_state()
        self.async_set_updated_data(self._compose_data())

    async def async_test_alert(self, level: str) -> None:
        """Emit and optionally notify a clearly labelled, non-critical test."""
        normalized = normalize_warning(level)
        if normalized not in {
            WarningLevel.ADVICE,
            WarningLevel.WATCH_AND_ACT,
            WarningLevel.EMERGENCY_WARNING,
        }:
            raise HomeAssistantError(
                "level must be Advice, Watch and Act, or Emergency Warning"
            )
        latitude, longitude = self._home_coordinates()
        incident = Incident(
            id=f"test-{self.entry.entry_id}",
            title="NSW Fire Watch test",
            incident_type="Test",
            warning_level=normalized,
            control_status="Test only",
            is_fire=False,
            latitude=latitude,
            longitude=longitude,
            distance_km=0.0,
            official_url=OFFICIAL_INCIDENTS_URL,
            instruction="This is only a notification-path test. No incident exists.",
            sources=("NSW Fire Watch test",),
        )
        event = LifecycleEvent(incident.id, "test", incident, None)
        payload = {
            "alert_kind": "incident",
            "entry_id": self.entry.entry_id,
            "location_name": str(self.config.get(CONF_NAME, DEFAULT_NAME)),
            "lifecycle": "test",
            "incident_id": incident.id,
            "incident": incident.as_dict(),
            "previous": {},
            "qualifies_for_alert": False,
            "notification_allowed": True,
            "delivery_priority": "normal",
            "direct_delivery_configured": bool(
                _notify_services(self.config.get(CONF_NOTIFY_SERVICES, []))
            ),
            "summary": f"TEST — {normalized}",
            "recommended_action": "Verify delivery only; no incident exists.",
            "notification_tag": f"nsw-fire-watch-test-{self.entry.entry_id}",
            "test": True,
            "official_url": OFFICIAL_INCIDENTS_URL,
        }
        self.hass.bus.async_fire(EVENT_ALERT, payload)
        await self._async_notify(event, test=True)


def _danger_period_label(detail: Mapping[str, Any]) -> str:
    period = str(detail.get("period") or "").casefold()
    if period == "today":
        return "Today"
    if period == "tomorrow":
        return "Tomorrow"
    return str(detail.get("date") or "Fire danger")


def _danger_summary(event: DangerLifecycleEvent) -> str:
    detail = event.danger
    period = _danger_period_label(detail)
    district = str(detail.get("district") or "configured district")
    rating = str(detail.get("rating") or "Unknown")
    if event.lifecycle == "resolved":
        return f"Fire danger declaration changed — {district}"
    if detail.get("total_fire_ban") is True:
        return f"Total Fire Ban {period.casefold()} — {district} ({rating})"
    return f"{rating} fire danger {period.casefold()} — {district}"


def _danger_recommended_action(event: DangerLifecycleEvent) -> str:
    if event.lifecycle in {"deescalated", "resolved"}:
        return (
            "The previous declaration changed. Check the current NSW RFS "
            "rating and Total Fire Ban product; do not treat this as safe."
        )
    detail = event.danger
    if detail.get("total_fire_ban") is True:
        return "A Total Fire Ban is declared. Check and follow current NSW RFS restrictions."
    return {
        "High": "Be ready to act and review your bush-fire survival plan.",
        "Extreme": "Take action now to protect life and property; check official advice.",
        "Catastrophic": "Leave bush-fire risk areas; follow current official instructions.",
    }.get(str(detail.get("rating")), "Check the current official declaration.")


def _danger_notification_message(event: DangerLifecycleEvent) -> str:
    detail = event.danger
    if event.lifecycle in {"deescalated", "resolved"}:
        previous = event.previous or {}
        return (
            f"The previously published {previous.get('rating', 'fire danger')} "
            f"rating / Total Fire Ban for {previous.get('date', event.danger_id)} "
            "has changed. Check the current NSW RFS declaration; this does not "
            "confirm conditions are safe."
        )
    ban_text = (
        " A Total Fire Ban is declared." if detail.get("total_fire_ban") is True else ""
    )
    return (
        f"{event.lifecycle.replace('_', ' ').title()}: "
        f"{detail.get('rating', 'Unknown')} fire danger for "
        f"{detail.get('district', 'the configured district')} on "
        f"{detail.get('date', event.danger_id)}.{ban_text} "
        f"{_danger_recommended_action(event)}"
    )


def _apply_notification_priority(
    data: dict[str, Any], priority: str, kind: str
) -> None:
    if priority == "critical":
        data["push"] = {
            "sound": {"name": "default", "critical": 1, "volume": 1.0},
            "interruption-level": "critical",
        }
        data["channel"] = f"nsw_fire_watch_{kind}_critical"
        data["ttl"] = 0
        data["priority"] = "high"
    elif priority == "time_sensitive":
        data["push"] = {"interruption-level": "time-sensitive"}
        data["channel"] = f"nsw_fire_watch_{kind}_time_sensitive"
    else:
        data["channel"] = "nsw_fire_watch_information"


def _unknown_danger() -> dict[str, Any]:
    day = {
        "date": None,
        "rating": "Unknown",
        "fbi": None,
        "total_fire_ban": None,
        "issued_at": None,
        "rating_source": None,
        "fbi_source": None,
    }
    return {
        "district": None,
        "today": dict(day),
        "tomorrow": dict(day),
        "forecast": [],
        "bom_issued_at": None,
        "rfs_issued_at": None,
    }


def _empty_feed() -> dict[str, Any]:
    return {
        "status": "unavailable",
        "last_successful_update": None,
        "data_generated_at": None,
        "age_seconds": None,
        "source_name": None,
        "official_url": OFFICIAL_INCIDENTS_URL,
        "sources": {},
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return (
        result.replace(tzinfo=timezone.utc)
        if result.tzinfo is None
        else result.astimezone(timezone.utc)
    )


def _age_seconds(value: Any, now: datetime) -> int | None:
    parsed = _as_datetime(value)
    if parsed is None:
        return None
    return max(0, int((now - parsed).total_seconds()))


def _discard_expired(values: dict[str, str], now: datetime) -> None:
    for key, value in tuple(values.items()):
        expiry = _as_datetime(value)
        if expiry is None or expiry <= now:
            values.pop(key, None)


def _notify_services(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        raw = value.replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw = value
    else:
        raw = []
    return tuple(
        dict.fromkeys(
            text
            for item in raw
            if (text := str(item).strip())
            and text.startswith("notify.")
            and "." in text
        )
    )


def _recommended_action(status: str) -> str:
    return {
        "emergency_warning": "Take action immediately. Follow the official warning and emergency instructions.",
        "watch_and_act": "Start taking action now. Check the official incident update and your bush-fire plan.",
        "advice": "Stay up to date. Monitor official sources and be ready if conditions change.",
        "incident_nearby": "Check the incident in official sources and monitor for a warning-level change.",
        "planned_activity": "Planned activity is nearby. Monitor conditions and official updates if smoke affects you.",
        "no_current_warning": "No current warning in the configured alert radii. Stay prepared and keep official alerts enabled.",
        "stale": "Live updates are stale. Check Hazards Near Me NSW, NSW RFS, BOM or local radio now.",
        "unavailable": "Live updates are unavailable. Use Hazards Near Me NSW, NSW RFS, BOM and local radio.",
    }.get(status, "Check official sources.")


def _summary_text(status: str, highest: Incident | None, feed: dict[str, Any]) -> str:
    if status == "unavailable":
        return "Live incident updates unavailable — check official sources"
    if status == "stale":
        return "Live incident updates stale — check official sources"
    if highest and status not in {"no_current_warning", "planned_activity"}:
        distance = (
            f" ({highest.distance_km:.1f} km)"
            if highest.distance_km is not None
            else ""
        )
        warning_label = (
            "No official warning level"
            if highest.warning_level == WarningLevel.NOT_APPLICABLE
            else str(highest.warning_level)
        )
        return f"{warning_label}: {highest.title}{distance}"
    if status == "planned_activity":
        return "No current warning; planned fire activity is nearby"
    return "No current warning in the configured alert radii"
