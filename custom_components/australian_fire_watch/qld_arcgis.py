"""Read-only Queensland Fire Department ArcGIS enrichment provider.

Independent health for FDR and local fire bans.
A failed query never becomes an affirmative "No Fire Ban" observation.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Callable

from aiohttp import ClientError, ClientSession

from .qld_parsers import (
    QldDataError,
    parse_forecast,
    parse_local_fire_ban,
)

ROOT = "https://services1.arcgis.com/vkTwD8kHw2woKBqV/arcgis/rest/services"
FDR_URL = f"{ROOT}/BOM_Fire_Danger_Ratings_Public_View_/FeatureServer/0/query"
BAN_URL = f"{ROOT}/LGAs_Firebans_Public_View/FeatureServer/0/query"
QFD_DANGER_URL = "https://www.fire.qld.gov.au/prepare/bushfire/fire-danger-ratings"
QFD_BAN_URL = "https://www.fire.qld.gov.au/safety-education/using-fire-outdoors/fire-bans-and-restrictions"
MAX_BODY = 1_000_000
TIMEOUT = 20
FIELDS = {
    "forecast": "Area_Name,Day1,Day2,Day3,Day4,Date1,Date2,Date3,Date4,FMETimeStamp",
    "local_fire_ban": "SHIRE_NAME,HASFIREBAN,DATE_FROM,DATE_TO,FMETimestamp,Link",
}
ENDPOINTS = {
    "forecast": FDR_URL,
    "local_fire_ban": BAN_URL,
}


def empty_qld() -> dict[str, Any]:
    """Stable unavailable representation for HA startup and failed updates."""
    return {
        "forecast": {"covered": None, "health": "unavailable", "forecast": []},
        "local_fire_ban": {"state": None, "health": "unavailable"},
        "health": "unavailable",
    }


class QldArcGISProvider:
    """Small, bounded async client using Home Assistant's shared aiohttp session."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def _fetch(self, key: str, latitude: float, longitude: float) -> Any:
        params = {
            "geometry": f"{longitude:.7f},{latitude:.7f}",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "where": "1=1",
            "outFields": FIELDS[key],
            "returnGeometry": "false",
            "f": "json",
        }
        async with asyncio.timeout(TIMEOUT):
            async with self._session.get(
                ENDPOINTS[key],
                params=params,
                headers={"Accept": "application/json"},
            ) as response:
                if response.status != 200:
                    raise QldDataError(f"ArcGIS HTTP {response.status}")
                chunks: list[bytes] = []
                length = 0
                async for chunk in response.content.iter_chunked(64 * 1024):
                    length += len(chunk)
                    if length > MAX_BODY:
                        raise QldDataError("ArcGIS response exceeded size limit")
                    chunks.append(chunk)
        try:
            return json.loads(b"".join(chunks))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise QldDataError("Invalid ArcGIS JSON") from exc

    async def _one(
        self,
        key: str,
        latitude: float,
        longitude: float,
        parser: Callable[[Any], dict[str, Any]],
        *,
        now: datetime,
    ) -> dict[str, Any]:
        try:
            response = await self._fetch(key, latitude, longitude)
            parsed = parser(response)
            # A legitimate no-match is not an HTTP failure, but it isn't a
            # current fire danger assessment either.
            parsed.setdefault("health", "fresh")
            parsed["checked_at"] = now.isoformat()
            return parsed
        except (QldDataError, ClientError, TimeoutError, OSError, ValueError, TypeError) as exc:
            # Never log or put query URLs with private coordinates in attributes.
            return {
                "state": None,
                "covered": None,
                "health": "unavailable",
                "error": f"{type(exc).__name__}: {str(exc)[:120] if isinstance(exc, QldDataError) else 'request failed'}",
                "checked_at": now.isoformat(),
            }

    async def async_fetch(
        self, latitude: float, longitude: float, *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Fetch only the two QLD enrichment layers required by HA entities."""
        now = now or datetime.now(timezone.utc)
        forecast, ban = await asyncio.gather(
            self._one(
                "forecast", latitude, longitude,
                lambda response: parse_forecast(response, now=now), now=now,
            ),
            self._one(
                "local_fire_ban", latitude, longitude,
                parse_local_fire_ban, now=now,
            ),
        )
        statuses = {forecast["health"], ban["health"]}
        health = (
            "fresh" if statuses == {"fresh"}
            else "stale" if statuses == {"stale"}
            else "unavailable" if statuses == {"unavailable"}
            else "degraded"
        )
        return {
            "forecast": forecast,
            "local_fire_ban": ban,
            "health": health,
        }
