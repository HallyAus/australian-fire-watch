"""One-use reviewed-source patch builder; removed before the resulting commit."""
import ast
import hashlib
from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parent
COMPONENT = ROOT / "custom_components/australian_fire_watch"
EXPECTED = {
    "api.py": "6a5a9db0ccf4756469fbccca052a97e12e965ee3",
    "binary_sensor.py": "5d33cef6851bc62cf8a9f226e54350cbb06e2028",
    "coordinator.py": "4de2cb855e236eef97e1fa6d0081e26d358eefbe",
    "model.py": "03fd0e3db617329f13ea2ebb55567e80a1060b93",
    "parsers.py": "7b3e4a3af4497125267f8b4b4d1fa88bfcee40d5",
    "regional_parsers.py": "13a5f0dbd177c3ffd4872042d4105e1405221f77",
    "__init__.py": "e273a9075bde1fbe8973bb396a3e2ff37cde505d",
}
files = {}
for name, sha in EXPECTED.items():
    raw = (COMPONENT / name).read_bytes()
    actual = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw, usedforsecurity=False).hexdigest()
    assert actual == sha, f"Reviewed source changed: {name}"
    files[name] = raw.decode()


def replace(name, old, new, count=1):
    assert files[name].count(old) == count, (name, old[:100], files[name].count(old), count)
    files[name] = files[name].replace(old, new)


def function(name, symbol, body):
    node = ast.parse(files[name])
    for part in symbol.split("."):
        nodes = [n for n in node.body if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == part]
        assert len(nodes) == 1, symbol
        node = nodes[0]
    start = min([node.lineno] + [n.lineno for n in getattr(node, "decorator_list", [])])
    lines = files[name].splitlines(keepends=True)
    source = textwrap.indent(textwrap.dedent(body).strip() + "\n", " " * node.col_offset)
    files[name] = "".join(lines[:start-1]) + source + "".join(lines[node.end_lineno:])


# A candidate HTTP response is promoted only after its parser validates it.
replace("api.py", "from typing import Final", "from typing import Any, Callable, Final")
replace("api.py", "async def async_fetch(self, name: str, url: str) -> FeedSnapshot:", "async def async_fetch(self, name: str, url: str, *, validator: Callable[[bytes], Any] | None = None) -> FeedSnapshot:")
replace("api.py", '                    new_etag = response.headers.get("ETag")', '''                    if validator is not None:
                        parsed = validator(body)
                        if not getattr(parsed, "metadata", {}).get("complete", True):
                            raise ValueError("Feed contains incomplete records")
                    new_etag = response.headers.get("ETag")''')
replace("api.py", "                    changed = body != state.body", "                    publication_changed = modified is not None and modified != state.last_modified\n                    changed = body != state.body")
replace("api.py", "                    if changed or state.last_change is None:", "                    if changed or publication_changed or state.last_change is None:")
replace("api.py", "except (TimeoutError, ClientError, ValueError, OSError) as err:", "except (TimeoutError, ClientError, ValueError, TypeError, KeyError, IndexError, OSError) as err:")

# Validate envelope structure, raw record completeness and warning geometry.
replace("parsers.py", '    generated_at = _parse_datetime(_text(root, "dateTimeSent"))', '''    if _local(root) not in {"distribution", "EDXLDistribution", "alert"}:
        raise FeedParseError("Not a CAP/EDXL document")
    if not _descendants(root, "alert") and not (_text(root, "dateTimeSent") or _text(root, "distributionID")):
        raise FeedParseError("Empty CAP distribution lacks publisher metadata")
    complete = all(_text(item, "status") for item in _descendants(root, "alert"))
    generated_at = _parse_datetime(_text(root, "dateTimeSent"))''')
replace("parsers.py", "        if not info_nodes:\n            continue", '        if not info_nodes:\n            raise FeedParseError("Actual CAP alert is missing info")')
replace("parsers.py", "        if not incident_id:\n            continue", '        if not incident_id:\n            raise FeedParseError("Actual CAP alert is missing its identity")')
replace("parsers.py", '        {"distribution_id": _text(root, "distributionID")},', '        {"distribution_id": _text(root, "distributionID"), "complete": bool(complete), "generated_at_is_feed_time": True},')
replace("parsers.py", "    incidents: list[Incident] = []\n    generated_candidates: list[datetime] = []", "    _require_feature_collection(data)\n    incidents: list[Incident] = []\n    generated_candidates: list[datetime] = []")
replace("parsers.py", "    districts: dict[str, dict[str, Any]] = {}", '''    if _local(root) != "FireDangerMap" or not _descendants(root, "District"):
        raise FeedParseError("Not a populated RFS fire-danger document")
    districts: dict[str, dict[str, Any]] = {}''')
replace("parsers.py", "        if not name:\n            continue\n        districts[name]", '        if not name:\n            raise FeedParseError("Fire-danger district is missing its name")\n        districts[name]')
replace("parsers.py", '    channels = _descendants(root, "channel")\n    channel = channels[0] if channels else root', '    _require_rss(root)\n    channels = _descendants(root, "channel")\n    channel = channels[0] if channels else root')
files["parsers.py"] += '''

def _require_feature_collection(data: Any) -> None:
    """Missing or partial collections are not evidence of zero incidents."""
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise FeedParseError("Not a FeatureCollection")
    features = data.get("features")
    if not isinstance(features, list) or data.get("exceededTransferLimit"):
        raise FeedParseError("Missing, invalid or truncated feature collection")
    for feature in features:
        if not isinstance(feature, dict) or not isinstance(feature.get("properties"), dict) or not feature["properties"]:
            raise FeedParseError("Incomplete feature record")


def _require_rss(root: ET.Element) -> None:
    if _local(root) == "rss" and len(_children(root, "channel")) == 1:
        return
    if root.tag == "{http://www.w3.org/2005/Atom}feed":
        return
    raise FeedParseError("Not an RSS channel or Atom feed")


def _geojson_warning_areas(geometry: Any) -> tuple:
    """Preserve exterior/hole membership, not a flattened collection of rings."""
    areas = []
    for item in _flatten_geojson_geometries(geometry):
        kind = item.get("type")
        if kind not in {"Polygon", "MultiPolygon"}:
            continue
        coordinates = item.get("coordinates")
        if not isinstance(coordinates, list):
            raise FeedParseError("Invalid warning geometry")
        raw_polygons = [coordinates] if kind == "Polygon" else coordinates
        for raw_polygon in raw_polygons:
            if not isinstance(raw_polygon, list) or not raw_polygon:
                raise FeedParseError("Empty warning polygon")
            polygon = []
            for raw_ring in raw_polygon:
                try:
                    ring = tuple((float(point[1]), float(point[0])) for point in raw_ring)
                except (ValueError, TypeError, IndexError) as err:
                    raise FeedParseError("Invalid warning ring") from err
                if len(set(ring)) < 3 or not all(_valid_coordinate(*point) for point in ring):
                    raise FeedParseError("Incomplete warning ring")
                polygon.append(ring)
            areas.append(tuple(polygon))
    return tuple(areas)
'''
function("parsers.py", "_parse_cap_polygon", '''
def _parse_cap_polygon(value: str) -> tuple[tuple[float, float], ...]:
    points = []
    for token in value.split():
        try:
            latitude, longitude = token.split(",", 1)
            point = (float(latitude), float(longitude))
        except (ValueError, TypeError) as err:
            raise FeedParseError("Malformed CAP polygon coordinate") from err
        if not _valid_coordinate(*point):
            raise FeedParseError("CAP polygon coordinate outside valid range")
        points.append(point)
    if len(set(points)) < 3:
        raise FeedParseError("CAP polygon has fewer than three distinct vertices")
    return tuple(points)
''')
replace("regional_parsers.py", "    _geojson_polygons,", "    _geojson_polygons,\n    _geojson_warning_areas,\n    _require_feature_collection,\n    _require_rss,")
replace("regional_parsers.py", '    incidents: list[Incident] = []\n    generated: list[datetime] = []\n    for index, feature in enumerate(data.get("features", [])):', '    _require_feature_collection(data)\n    incidents: list[Incident] = []\n    generated: list[datetime] = []\n    for index, feature in enumerate(data.get("features", [])):', 3)
replace("regional_parsers.py", '    incidents: list[Incident] = []\n    for index, feature in enumerate(collection.get("features", [])):', '    _require_feature_collection(collection)\n    incidents: list[Incident] = []\n    for index, feature in enumerate(collection.get("features", [])):')
replace("regional_parsers.py", '    for index, placemark in enumerate(_descendants(root, "Placemark")):\n        title = _text(placemark, "name") or "Fire incident"', '''    if _local(root) != "kml" or not (_descendants(root, "Document") or _descendants(root, "Folder")):
        raise FeedParseError("Not a KML document")
    for index, placemark in enumerate(_descendants(root, "Placemark")):
        if not _text(placemark, "name"):
            raise FeedParseError("KML placemark lacks a name")
        title = _text(placemark, "name") or "Fire incident"''')
replace("regional_parsers.py", '                coordinates = "".join(node.itertext()).strip().split()[0]', '''                values = "".join(node.itertext()).strip().split()
                if not values:
                    raise FeedParseError("KML coordinates are empty")
                coordinates = values[0]''')
replace("regional_parsers.py", '''    records = [
        node for node in root.iter() if _local(node).casefold() in {"item", "entry"}
    ]''', '''    _require_rss(root)
    records = [
        node for node in root.iter() if _local(node).casefold() in {"item", "entry"}
    ]
    if any(not _text(item, "title") for item in records):
        raise FeedParseError("RSS item lacks a title")''')
function("regional_parsers.py", "fire_incidents_only", '''
def fire_incidents_only(feed: ParsedFeed) -> ParsedFeed:
    """Structured incident type takes precedence over incidental warning prose."""
    incidents = []
    excluded = _NON_BUSH_FIRE_MARKERS + ("fire structure", "fire vehicle")
    for incident in feed.incidents:
        if incident.control_status.casefold() in {"closed", "complete", "completed", "finalised"}:
            continue
        kind = incident.incident_type.casefold()
        if any(marker in kind for marker in excluded):
            continue
        if incident.is_planned or any(marker in kind for marker in _FIRE_MARKERS):
            incidents.append(incident)
            continue
        text = f"{incident.title} {kind} {incident.description or ''}".casefold()
        if any(marker in text for marker in excluded):
            continue
        if incident.is_fire is True or any(marker in text for marker in _FIRE_MARKERS) or (" fire " in f" {text} " and "region: cfs" in text):
            incidents.append(incident)
    return ParsedFeed(tuple(incidents), feed.generated_at, feed.metadata)
''')

# Warning polygons affect qualification, while marker distance remains unchanged.
replace("model.py", "from typing import Any, Iterable, Mapping", "from typing import Any, Iterable, Mapping\n\nfrom .warning_geometry import area_relevance")
replace("model.py", "    sources: tuple[str, ...] = ()", "    sources: tuple[str, ...] = ()\n    warning_areas: tuple[tuple[tuple[tuple[float, float], ...], ...], ...] = ()\n    inside_warning_area: bool | None = None\n    warning_area_distance_km: float | None = None")
replace("model.py", '            (self.instruction or "").casefold(),', '            (self.instruction or "").casefold(),\n            self.inside_warning_area,')
function("model.py", "Incident.with_home", '''
def with_home(self, latitude: float, longitude: float) -> "Incident":
    areas = self.warning_areas if self.warning_rank > 0 else ()
    inside, distance = area_relevance((latitude, longitude), areas)
    changes: dict[str, Any] = {"inside_warning_area": inside, "warning_area_distance_km": distance}
    if self.latitude is not None and self.longitude is not None:
        changes["distance_km"] = haversine_km(latitude, longitude, self.latitude, self.longitude)
        changes["direction"] = compass_direction(latitude, longitude, self.latitude, self.longitude)
    return replace(self, **changes)

@property
def qualification_distance_km(self) -> float | None:
    if self.warning_rank > 0 and self.warning_areas:
        return self.warning_area_distance_km
    return self.distance_km
''')
replace("model.py", '            "has_warning_polygon": bool(self.polygons),', '            "has_warning_polygon": bool(self.warning_areas),\n            "inside_warning_area": self.inside_warning_area,\n            "warning_area_distance_km": self.warning_area_distance_km,')
replace("model.py", '    previous_signature = tuple(previous.get("material_signature", ()))', '    previous_signature = tuple(previous.get("material_signature", ()))\n    if len(previous_signature) == 6:\n        previous_signature += (None,)')
replace("model.py", "radius_band(incident.distance_km)", "radius_band(incident.qualification_distance_km)")
replace("model.py", "radius_band(current.distance_km) < previous_band", "radius_band(current.qualification_distance_km) < previous_band")
replace("model.py", "        else:\n            transition = classify_transition(previous, incident)", '''        else:
            if not allow_missing_updates and incident.warning_rank < int(previous.get("warning_rank", 0)):
                next_records[incident_id] = dict(previous)
                continue
            transition = classify_transition(previous, incident)''')
replace("model.py", '                        dict(previous),\n                        is_qualified,', '                        dict(previous),\n                        is_qualified or bool(previous.get("qualified", False)),')
replace("model.py", '        if incident_id in authoritative:\n            events.append(', '''        if incident_id in authoritative:
            if not allow_missing_updates:
                next_records[incident_id] = record
                continue
            events.append(''')
replace("parsers.py", "                polygons=polygons,\n                sources=(source,),", '''                polygons=polygons,
                warning_areas=tuple((polygon,) for polygon in polygons)
                if normalize_warning(warning) in {"Advice", "Watch and Act", "Emergency Warning"} else (),
                sources=(source,),''')
replace("parsers.py", '                sources=("NSW RFS GeoJSON",),', '''                warning_areas=_geojson_warning_areas(feature.get("geometry"))
                if normalize_warning(properties.get("category") or fields.get("ALERT LEVEL"))
                in {"Advice", "Watch and Act", "Emergency Warning"} else (),
                sources=("NSW RFS GeoJSON",),''')
replace("parsers.py", '            polygons=polygons,\n            sources=tuple', '            polygons=polygons,\n            warning_areas=tuple(dict.fromkeys((*current.warning_areas, *candidate.warning_areas))),\n            sources=tuple')
replace("regional_parsers.py", "                polygons=polygons,\n                responsible_agency=source,", '                polygons=polygons,\n                warning_areas=_geojson_warning_areas(feature.get("geometry")) if feed_type == "warning" else (),\n                responsible_agency=source,')

# Coordinator: positive evidence and negative evidence use different quorums.
replace("coordinator.py", "from .api import FeedSnapshot, OfficialFeedClient", "from .api import FeedSnapshot, OfficialFeedClient\nfrom .feed_safety import current_snapshot, dated_danger, incident_feed_health, NSW_TZ\nfrom .notification_outbox import NotificationOutbox\nfrom homeassistant.helpers.event import async_track_time_interval")
replace("coordinator.py", "        self._store_lock = asyncio.Lock()", '''        self._store_lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()
        self._closing = False
        self._cancel_delivery_retry = None
        self._outbox = NotificationOutbox()
        self._last_incidents: dict[str, Incident] = {}
        self._current_incidents: dict[str, Incident] = {}
        self._retained_ids: set[str] = set()''')
replace("coordinator.py", '        saved = await self._store.async_load() or {}', '        saved = await self._store.async_load() or {}\n        self._outbox = NotificationOutbox(saved.get("outbox"))')
function("coordinator.py", "FireWatchCoordinator._async_update_data", '''
async def _async_update_data(self) -> dict[str, Any]:
    # Nothing else can checkpoint lifecycle state between staging a transition
    # and its pending delivery in the same persistent store.
    async with self._operation_lock:
        if self._closing:
            raise asyncio.CancelledError
        return await self._async_poll()

async def _async_poll(self) -> dict[str, Any]:
    if self.jurisdiction.code != "NSW":
        return await self._async_update_regional_data()
    feeds = dict(CORE_FEEDS)
    validators = {
        "rfs_cap": parse_cap, "rfs_geojson": parse_geojson,
        "rfs_incident_alerts": partial(parse_cap, source="NSW RFS IncidentAlerts polygons"),
        "rfs_fdr_toban": parse_rfs_fire_danger,
        "bom_idn10016": parse_bom_fire_danger,
        "bom_nsw_warnings": parse_bom_fire_weather_warnings,
    }
    if bool(self.config.get(CONF_ENABLE_BOM, DEFAULT_ENABLE_BOM)):
        feeds.update(BOM_FEEDS)
    results = await asyncio.gather(*(self.api.async_fetch(name, url, validator=validators[name]) for name, url in feeds.items()))
    snapshots = {item.name: item for item in results}
    self._parse_errors = {}
    parsed = {name: self._parse(name, item, validators[name]) for name, item in snapshots.items()}
    cap, geojson = parsed["rfs_cap"], parsed["rfs_geojson"]
    self._feed = self._compose_feed(snapshots, cap, geojson)
    self._danger = self._compose_danger(parsed.get("rfs_fdr_toban"), parsed.get("bom_idn10016"), snapshots)
    warnings = parsed.get("bom_nsw_warnings")
    self._warnings = list(warnings.metadata.get("warnings", [])) if warnings else []
    events = await self._async_process_incidents(snapshots, parsed, ("rfs_cap", "rfs_geojson", "rfs_incident_alerts"))
    danger_events = await self._async_track_danger_lifecycle(any(self._danger.get(period, {}).get("available") for period in ("today", "tomorrow")))
    self.last_events = tuple(events)
    self.last_danger_events = tuple(danger_events)
    await self._async_emit_events(events, danger_events)
    return self._compose_data()

async def _async_process_incidents(self, snapshots, parsed, names) -> list[LifecycleEvent]:
    now = datetime.now(timezone.utc)
    stale = int(self.config.get(CONF_STALE_AFTER, DEFAULT_STALE_AFTER_MINUTES)) * 60
    status, current = incident_feed_health(snapshots, parsed, names, stale, now)
    self._feed.update({"incident_status": status, "current_incident_sources": list(current), "assessed_at": now.isoformat()})
    if status != "fresh":
        self._feed["status"] = status
    resolution_current = len(current) == len(names)
    if self.jurisdiction.code == "NSW":
        cap, geojson = parsed.get("rfs_cap"), parsed.get("rfs_geojson")
        corroborated = bool("rfs_cap" in current and "rfs_geojson" in current and not cap.incidents and not geojson.incidents)
        resolution_current = resolution_current and bool(geojson is not None and authoritative_incident_snapshot_valid(
            response_received="rfs_geojson" in current, parsed_count=len(geojson.incidents),
            advertised_count=int(geojson.metadata.get("feature_count", -1)),
            existing_record_count=len(self._records), empty_corroborated=corroborated,
        ))
    # Validate raw completeness above; deliberately excluded non-bushfire
    # records must not be mistaken for a partial parse.
    filtered = {name: fire_incidents_only(parsed[name]).incidents if parsed.get(name) is not None else () for name in names}
    merged: tuple[Incident, ...] = ()
    authoritative: tuple[Incident, ...] = ()
    for name in names:
        merged = merge_incidents(merged, filtered[name])
        if name in current:
            authoritative = merge_incidents(authoritative, filtered[name])
    latitude, longitude = self._home_coordinates()
    radius = float(self.config.get(CONF_MONITOR_RADIUS, DEFAULT_MONITOR_RADIUS_KM))
    located = tuple(item.with_home(latitude, longitude) for item in merged)
    authoritative_located = tuple(item.with_home(latitude, longitude) for item in authoritative)
    self._current_incidents = {item.id: item for item in authoritative_located}
    monitored = tuple(item for item in located if item.qualification_distance_km is None or item.qualification_distance_km <= radius)
    current_monitored = tuple(item for item in authoritative_located if item.qualification_distance_km is None or item.qualification_distance_km <= radius)
    self._incidents = tuple(item for item in sort_incidents(monitored) if not item.is_planned)
    self._planned = tuple(item for item in sort_incidents(monitored) if item.is_planned)
    events = await self._async_track_lifecycle(current_monitored, authoritative_located, bool(current), resolution_current)
    self._retain_unconfirmed_incidents()
    return events
''')
function("coordinator.py", "FireWatchCoordinator._async_update_regional_data", '''
async def _async_update_regional_data(self) -> dict[str, Any]:
    profile = self.jurisdiction
    validators = {feed.name: partial(_parse_regional_cap if feed.parser == "cap" else PARSER_NAMES[feed.parser], source=profile.agency, official_url=profile.official_url) for feed in profile.feeds}
    results = await asyncio.gather(*(self.api.async_fetch(feed.name, feed.url, validator=validators[feed.name]) for feed in profile.feeds))
    snapshots = {item.name: item for item in results}
    self._parse_errors = {}
    parsed = {name: self._parse(name, item, validators[name]) for name, item in snapshots.items()}
    self._feed = self._compose_regional_feed(snapshots, {name: item for name, item in parsed.items() if item is not None})
    self._danger = _unknown_danger()
    self._danger["district"] = "Not available for this jurisdiction"
    self._danger["source_note"] = "Use the official jurisdiction source for fire-danger information."
    self._warnings = []
    events = await self._async_process_incidents(snapshots, parsed, tuple(feed.name for feed in profile.feeds))
    self.last_events = tuple(events)
    self.last_danger_events = ()
    await self._async_emit_events(events, [])
    return self._compose_data()
''')
function("coordinator.py", "FireWatchCoordinator._compose_regional_feed", '''
def _compose_regional_feed(self, snapshots: dict[str, FeedSnapshot], parsed_feeds: dict[str, Any]) -> dict[str, Any]:
    profile = self.jurisdiction
    now = datetime.now(timezone.utc)
    stale = int(self.config.get(CONF_STALE_AFTER, DEFAULT_STALE_AFTER_MINUTES)) * 60
    names = tuple(feed.name for feed in profile.feeds)
    status, current = incident_feed_health(snapshots, parsed_feeds, names, stale, now)
    fetched = min((snapshots[name].fetched_at for name in names if snapshots[name].fetched_at), default=None)
    generated = max((item.generated_at for item in parsed_feeds.values() if item.generated_at), default=None)
    return {
        "status": status, "incident_status": status, "current_incident_sources": list(current),
        "last_successful_update": _iso(fetched), "data_generated_at": _iso(generated),
        "age_seconds": _age_seconds(fetched, now), "stale_after_seconds": stale,
        "source_name": profile.agency, "official_url": profile.official_url,
        "attribution": profile.attribution,
        "cross_check": {"feed_count": len(names), "available_count": len(parsed_feeds)},
        "sources": self._source_details(snapshots),
    }
''')
function("coordinator.py", "FireWatchCoordinator._compose_feed", '''
def _compose_feed(self, snapshots: dict[str, FeedSnapshot], cap: Any | None, geojson: Any | None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    stale = int(self.config.get(CONF_STALE_AFTER, DEFAULT_STALE_AFTER_MINUTES)) * 60
    status, current = incident_feed_health(snapshots, {"rfs_cap": cap, "rfs_geojson": geojson}, ("rfs_cap", "rfs_geojson"), stale, now)
    if status == "fresh" and (self._parse_errors or any(not item.response_received for item in snapshots.values())):
        status = "degraded"
    primary_name = next(iter(current), "rfs_cap" if cap is not None else "rfs_geojson")
    primary = snapshots[primary_name]
    cap_ids = {item.id for item in cap.incidents} if cap else set()
    geo_ids = {item.id for item in geojson.incidents} if geojson else set()
    generated = cap.generated_at if primary_name == "rfs_cap" and cap else (geojson.generated_at if geojson else None)
    return {
        "status": status, "last_successful_update": _iso(primary.fetched_at), "data_generated_at": _iso(generated),
        "age_seconds": _age_seconds(primary.fetched_at, now), "stale_after_seconds": stale,
        "source_name": "NSW RFS CAP" if primary_name == "rfs_cap" else "NSW RFS GeoJSON fallback",
        "official_url": OFFICIAL_INCIDENTS_URL, "attribution": self.jurisdiction.attribution,
        "cross_check": {"cap_count": len(cap_ids), "geojson_count": len(geo_ids), "cap_only_count": len(cap_ids-geo_ids), "geojson_only_count": len(geo_ids-cap_ids)},
        "sources": self._source_details(snapshots),
    }
''')
function("coordinator.py", "FireWatchCoordinator._compose_danger", '''
def _compose_danger(self, rfs_districts: dict[str, Any] | None, bom: dict[str, Any] | None, snapshots: dict[str, FeedSnapshot]) -> dict[str, Any]:
    district = str(self.config.get(CONF_DISTRICT, DEFAULT_DISTRICT))
    now = datetime.now(timezone.utc)
    stale = int(self.config.get(CONF_STALE_AFTER, DEFAULT_STALE_AFTER_MINUTES)) * 60
    result = dated_danger(district, (rfs_districts or {}).get(district, {}), snapshots["rfs_fdr_toban"], stale_seconds=stale, now=now)
    bom_snapshot = snapshots.get("bom_idn10016")
    bom_current = bom_snapshot is not None and current_snapshot(bom_snapshot, bom, stale, now)
    forecasts = list((bom or {}).get("districts", {}).get(district, [])) if bom_current else []
    by_date = {item.get("date"): item for item in forecasts}
    for period in ("today", "tomorrow"):
        day = result[period]
        forecast = by_date.get(day["date"], {})
        day["fbi"] = forecast.get("fbi")
        day["fbi_source"] = "BOM IDN10016" if forecast else None
    result.update({
        "forecast": forecasts, "bom_issued_at": _iso((bom or {}).get("issued_at")) if bom_current else None,
        "rfs_issued_at": _iso(snapshots["rfs_fdr_toban"].changed_at),
        "source_note": "NSW RFS declarations retain their publication date. Unverified current-day declarations are unavailable.",
    })
    return result
''')
function("coordinator.py", "FireWatchCoordinator._summary_status", '''
def _summary_status(self, qualifying: list[Incident]) -> str:
    health = self._feed.get("incident_status", self._feed.get("status"))
    if health in {"unavailable", "stale"}:
        return health
    if qualifying:
        return {WarningLevel.EMERGENCY_WARNING: "emergency_warning", WarningLevel.WATCH_AND_ACT: "watch_and_act", WarningLevel.ADVICE: "advice"}.get(qualifying[0].warning_level, "incident_nearby")
    if health != "fresh" or any(item.warning_rank > 0 and item.qualification_distance_km is None for item in self._incidents):
        return "unavailable"
    if any(item.distance_km is not None and item.distance_km <= float(self.config.get(CONF_ADVICE_RADIUS, DEFAULT_ADVICE_RADIUS_KM)) for item in self._planned):
        return "planned_activity"
    return "no_current_warning"
''')
function("coordinator.py", "FireWatchCoordinator._qualifies", '''
def _qualifies(self, incident: Incident) -> bool:
    if incident.is_planned:
        return False
    distance = incident.qualification_distance_km
    if distance is None:
        return False
    radius = {
        WarningLevel.EMERGENCY_WARNING: float(self.config.get(CONF_EMERGENCY_RADIUS, DEFAULT_EMERGENCY_RADIUS_KM)),
        WarningLevel.WATCH_AND_ACT: float(self.config.get(CONF_WATCH_RADIUS, DEFAULT_WATCH_RADIUS_KM)),
        WarningLevel.ADVICE: float(self.config.get(CONF_ADVICE_RADIUS, DEFAULT_ADVICE_RADIUS_KM)),
    }.get(incident.warning_level)
    if radius is not None:
        return distance <= radius
    return bool(incident.is_fire and distance <= float(self.config.get(CONF_UNCLASSIFIED_RADIUS, DEFAULT_UNCLASSIFIED_RADIUS_KM)))


def _retain_unconfirmed_incidents(self) -> None:
    observed = {item.id: item for item in (*self._incidents, *self._planned)}
    pending = set(self._records) - set(observed)
    retained = [self._last_incidents[identity] for identity in pending if identity in self._last_incidents]
    self._retained_ids = {item.id for item in retained}
    self._incidents = tuple(sort_incidents((*self._incidents, *(item for item in retained if not item.is_planned))))
    self._planned = tuple(sort_incidents((*self._planned, *(item for item in retained if item.is_planned))))
    self._last_incidents = {item.id: item for item in (*self._incidents, *self._planned)}
    if pending and self._feed.get("incident_status") == "fresh":
        self._feed["incident_status"] = "degraded"
        self._feed["status"] = "degraded"
    self._feed["unconfirmed_missing_count"] = len(pending)
''')
replace("coordinator.py", "        if state_changed:\n            await self._async_save_state()", "        # Persisted atomically with pending notifications in _async_emit_events.")
replace("coordinator.py", "        if records != previous_records or baseline_complete != previous_baseline:\n            await self._async_save_state()", "        # Persisted atomically with pending notifications in _async_emit_events.")
replace("coordinator.py", '                    "snoozed": self._snoozed,', '                    "snoozed": self._snoozed,\n                    "outbox": self._outbox.dump(),')
replace("coordinator.py", '            "alerts_assigned": bool(alert_targets),', '            "alerts_assigned": bool(alert_targets),\n            "delivery": self._outbox.health,')
replace("coordinator.py", '            snoozed_until=self._snoozed.get(incident.id),\n        )', '            snoozed_until=self._snoozed.get(incident.id),\n        ) | {"retained_pending_confirmation": incident.id in self._retained_ids}')

# Stage all recipients BEFORE saving lifecycle records; never send before save.
function("coordinator.py", "FireWatchCoordinator._async_emit_events", '''
async def _async_emit_events(self, events: list[LifecycleEvent], danger_events: list[DangerLifecycleEvent]) -> None:
    direct = bool(_notify_services(self.config.get(CONF_NOTIFY_SERVICES, [])))
    payloads = []
    for event in events:
        tag = f"australian-fire-watch-{self.entry.entry_id}-{event.incident_id}"
        self._outbox.discard_tag(tag)
        allowed = self._notification_allowed(event)
        payloads.append({
            "alert_kind": "incident", "entry_id": self.entry.entry_id,
            "location_name": str(self.config.get(CONF_NAME, DEFAULT_NAME)),
            "lifecycle": event.lifecycle, "incident_id": event.incident_id,
            "incident": self._incident_dict(event.incident), "previous": dict(event.previous or {}),
            "qualifies_for_alert": event.qualifies_for_alert, "notification_allowed": allowed,
            "delivery_priority": incident_notification_priority(event), "direct_delivery_configured": direct,
            "summary": incident_event_summary(event),
            "recommended_action": _recommended_action(self._summary_status([event.incident])) if event.incident and event.qualifies_for_alert else "Check the official incident feed for current information.",
            "notification_tag": tag, "test": False, "official_url": self.jurisdiction.official_url,
        })
        if event.qualifies_for_alert and allowed:
            await self._async_notify(event, test=False)
    for event in danger_events:
        tag = f"australian-fire-watch-{self.entry.entry_id}-danger-{event.danger_id}"
        self._outbox.discard_tag(tag)
        payloads.append({
            "alert_kind": "danger", "entry_id": self.entry.entry_id,
            "location_name": str(self.config.get(CONF_NAME, DEFAULT_NAME)),
            "lifecycle": event.lifecycle, "danger_id": event.danger_id,
            "danger": dict(event.danger), "previous": dict(event.previous or {}),
            "qualifies_for_alert": event.qualifies_for_alert, "notification_allowed": True,
            "delivery_priority": danger_notification_priority(event.danger, event.lifecycle),
            "direct_delivery_configured": direct, "summary": _danger_summary(event),
            "recommended_action": _danger_recommended_action(event), "notification_tag": tag,
            "test": False, "official_url": OFFICIAL_DANGER_URL,
        })
        if event.qualifies_for_alert:
            await self._async_notify_danger(event)
    await self._async_save_state()
    for payload in payloads:
        self.hass.bus.async_fire(EVENT_ALERT, payload)
    await self._async_flush_outbox()
''')
replace("coordinator.py", '''        priority = incident_notification_priority(event, test=test)
        _apply_notification_priority(data, priority, "incident")
        await self._async_send_notification(services, title, message, data)''', '''        priority = incident_notification_priority(event, test=test)
        _apply_notification_priority(data, priority, "incident")
        await self._async_send_notification(services, title, message, data, guard={
            "kind": "test" if test else "incident", "id": event.incident_id,
            "lifecycle": event.lifecycle, "warning_level": incident.warning_level if incident else None,
        })''')
replace("coordinator.py", '''        priority = danger_notification_priority(detail, event.lifecycle)
        _apply_notification_priority(data, priority, "danger")
        await self._async_send_notification(services, title, message, data)''', '''        priority = danger_notification_priority(detail, event.lifecycle)
        _apply_notification_priority(data, priority, "danger")
        await self._async_send_notification(services, title, message, data, guard={
            "kind": "danger", "id": event.danger_id, "lifecycle": event.lifecycle,
        })''')
# Rename original public methods before installing locking wrappers.
replace("coordinator.py", "    async def async_acknowledge(self, incident_id: str) -> None:", "    async def _async_acknowledge_unlocked(self, incident_id: str) -> None:")
replace("coordinator.py", "    async def async_snooze(self, incident_id: str, duration_minutes: int) -> None:", "    async def _async_snooze_unlocked(self, incident_id: str, duration_minutes: int) -> None:")
replace("coordinator.py", "    async def async_test_alert(self, level: str) -> None:", "    async def _async_test_alert_unlocked(self, level: str) -> None:")
function("coordinator.py", "FireWatchCoordinator._async_send_notification", '''
async def _async_send_notification(self, services: tuple[str, ...], title: str, message: str, data: dict[str, Any], *, guard: dict[str, Any]) -> None:
    self._outbox.enqueue(services, title, message, data, datetime.now(timezone.utc), guard=guard)

async def _async_flush_outbox(self) -> None:
    now = datetime.now(timezone.utc)
    removed = False
    for key, item in tuple(self._outbox.pending.items()):
        guard = item.get("guard", {})
        kind, identity, lifecycle = guard.get("kind"), guard.get("id"), guard.get("lifecycle")
        obsolete = False
        if kind == "incident":
            record = self._records.get(identity)
            if lifecycle in {"resolved", "left_radius"}:
                obsolete = record is not None
            elif lifecycle == "deescalated":
                obsolete = record is None
            else:
                obsolete = record is None or not record.get("qualified", False)
                if lifecycle != "escalated" and record is not None and record.get("warning_level") != WarningLevel.EMERGENCY_WARNING:
                    until = _as_datetime(self._snoozed.get(identity))
                    obsolete = obsolete or identity in self._acknowledged or (until is not None and until > now)
        elif kind == "danger":
            obsolete = identity not in self._danger_records or str(identity) < now.astimezone(NSW_TZ).date().isoformat()
        if obsolete:
            self._outbox.pending.pop(key, None)
            removed = True
    if removed:
        await self._async_save_state()

    def eligible(item: dict[str, Any]) -> bool:
        if self._closing:
            return False
        guard = item.get("guard", {})
        if guard.get("kind") == "test":
            return True
        assessed = _as_datetime(self._feed.get("assessed_at"))
        if assessed is None or now - assessed > MIN_UPDATE_INTERVAL:
            return False
        if guard.get("kind") == "danger":
            return any(day.get("date") == guard.get("id") and day.get("available") for day in (self._danger.get("today", {}), self._danger.get("tomorrow", {})))
        if not self._feed.get("current_incident_sources"):
            return False
        if guard.get("lifecycle") in {"resolved", "left_radius", "deescalated"}:
            return self._feed.get("incident_status") == "fresh"
        current = self._current_incidents.get(guard.get("id"))
        return bool(current is not None and self._qualifies(current) and current.warning_level == guard.get("warning_level"))

    async def send(item: dict[str, Any]) -> None:
        _, service = item["service"].split(".", 1)
        if not self.hass.services.has_service("notify", service):
            raise HomeAssistantError(f"Configured notification service {item['service']} is unavailable")
        await self.hass.services.async_call("notify", service, {"title": item["title"], "message": item["message"], "data": item["data"]}, blocking=True)

    await self._outbox.drain(now=now, configured_services=_notify_services(self.config.get(CONF_NOTIFY_SERVICES, [])), sender=send, persist=self._async_save_state, allow_send=True, eligible=eligible)

def async_start_delivery_retry(self):
    """Start the independent retry timer; it must not reset the feed timer."""
    self._cancel_delivery_retry = async_track_time_interval(self.hass, self._async_retry_notifications, timedelta(seconds=30))
    return self._stop_delivery_retry

def _stop_delivery_retry(self) -> None:
    self._closing = True
    if self._cancel_delivery_retry is not None:
        self._cancel_delivery_retry()
        self._cancel_delivery_retry = None

async def async_shutdown_delivery(self) -> None:
    self._stop_delivery_retry()
    async with self._operation_lock:
        pass

async def _async_retry_notifications(self, _now: datetime) -> None:
    if self._closing or not self._outbox.pending:
        return
    async with self._operation_lock:
        if self._closing:
            return
        before = self._outbox.health
        await self._async_flush_outbox()
        if self.data is not None and self._outbox.health != before:
            self.data["delivery"] = self._outbox.health
            self.async_update_listeners()

async def async_acknowledge(self, incident_id: str) -> None:
    async with self._operation_lock:
        if self._closing:
            raise HomeAssistantError("Integration is unloading")
        await self._async_acknowledge_unlocked(incident_id)

async def async_snooze(self, incident_id: str, duration_minutes: int) -> None:
    async with self._operation_lock:
        if self._closing:
            raise HomeAssistantError("Integration is unloading")
        await self._async_snooze_unlocked(incident_id, duration_minutes)

async def async_test_alert(self, level: str) -> None:
    async with self._operation_lock:
        if self._closing:
            raise HomeAssistantError("Integration is unloading")
        await self._async_test_alert_unlocked(level)

def _source_details(self, snapshots: dict[str, FeedSnapshot]) -> dict[str, Any]:
    return {name: {"status": item.status, "url": item.url,
        "last_successful_fetch": _iso(item.fetched_at), "last_changed": _iso(item.changed_at),
        "last_modified": _iso(item.last_modified), "from_cache": item.from_cache,
        "error": item.error or self._parse_errors.get(name)} for name, item in snapshots.items()}
''')
replace("coordinator.py", "        await self._async_notify(event, test=True)", "        await self._async_notify(event, test=True)\n        await self._async_save_state()\n        await self._async_flush_outbox()")

# Entity state must distinguish unavailable assessment from a negative warning.
function("binary_sensor.py", "FireWatchActiveWarningBinarySensor.is_on", '''
@property
def is_on(self) -> bool | None:
    feed = self.coordinator.data.get("feed", {})
    if feed.get("incident_status", feed.get("status")) != "fresh":
        return None
    if self.coordinator.data.get("status") in {"unavailable", "stale"}:
        return None
    return self.coordinator.data.get("status") in {"advice", "watch_and_act", "emergency_warning"}

@property
def available(self) -> bool:
    return super().available and self.is_on is not None
''')
function("binary_sensor.py", "FireWatchActiveWarningBinarySensor.extra_state_attributes", '''
@property
def extra_state_attributes(self) -> dict[str, Any]:
    feed = self.coordinator.data.get("feed", {})
    return {"warning_level": self.coordinator.data.get("official_warning_level"),
        "incident": self.coordinator.data.get("highest_priority_incident"),
        "retained_information": not self.available,
        "feed_status": feed.get("incident_status", feed.get("status")),
        "last_confirmed_update": feed.get("last_successful_update")}
''')
function("binary_sensor.py", "FireWatchTotalFireBanBinarySensor.available", '''
@property
def available(self) -> bool:
    today = self.coordinator.data.get("danger", {}).get("today", {})
    return super().available and bool(today.get("available")) and self.is_on is not None
''')
replace("binary_sensor.py", "            FireWatchFeedProblemBinarySensor(coordinator),", "            FireWatchFeedProblemBinarySensor(coordinator),\n            FireWatchDeliveryProblemBinarySensor(coordinator),")
files["binary_sensor.py"] += '''

class FireWatchDeliveryProblemBinarySensor(FireWatchBinarySensorBase):
    """Expose pending failures and expired deliveries, not just log messages."""
    _attr_name = "Notification delivery problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: FireWatchCoordinator) -> None:
        super().__init__(coordinator, "delivery_problem")

    @property
    def is_on(self) -> bool:
        health = self.coordinator.data.get("delivery", {})
        return bool(health.get("failed_count") or health.get("expired_count"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self.coordinator.data.get("delivery", {}))
'''
replace("__init__.py", "    _register_mobile_actions(hass)\n    return True", "    _register_mobile_actions(hass)\n    entry.async_on_unload(coordinator.async_start_delivery_retry())\n    return True")
replace("__init__.py", "    domain_data = hass.data[DOMAIN]\n    domain_data[DATA_ENTRIES].pop(entry.entry_id, None)", "    domain_data = hass.data[DOMAIN]\n    coordinator = domain_data[DATA_ENTRIES].get(entry.entry_id)\n    if coordinator is not None:\n        await coordinator.async_shutdown_delivery()\n    domain_data[DATA_ENTRIES].pop(entry.entry_id, None)")

for name, source in files.items():
    compile(source, name, "exec")
for name, source in files.items():
    (COMPONENT / name).write_text(source)

# Persistent validation job, unlike the one-use builder running this script.
workflow = ROOT / ".github/workflows/validate.yml"
source = workflow.read_text().replace("python -m pip install --upgrade pip pyyaml", "python -m pip install --upgrade pip pyyaml aiohttp")
source += '''
  integration:
    name: Home Assistant runtime regression tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v6
        with:
          python-version: "3.14"
      - name: Install pinned Home Assistant test harness
        run: python -m pip install -r integration_tests/requirements.txt
      - name: Run Home Assistant integration tests
        run: python -m pytest -c integration_tests/pytest.ini integration_tests -v
      - name: Check bundled JavaScript syntax
        run: node --check custom_components/australian_fire_watch/frontend/australian-fire-watch-panel.js
'''
workflow.write_text(source)
print("Applied reviewed-source reliability fixes. Validation is required before publishing.")
