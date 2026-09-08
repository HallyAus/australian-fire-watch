"""Provider-supplied Central Watch locations; proximity is not visibility.

Public catalogue supplied by Watchtowers Networks in September 2026. There is
no incident, availability or streaming API. Keep these links supplementary to
official warnings and preserve the provider's double-encoded camera names.
"""

from __future__ import annotations

from math import isfinite
from typing import Any
from urllib.parse import quote

from .model import haversine_km

CENTRAL_WATCH_URL = "https://centralwatch.watchtowers.io/au"
CONF_ENABLE_CAMERAS = "enable_central_watch"
CONF_CAMERA_RADIUS = "camera_radius_km"
DEFAULT_CAMERA_RADIUS_KM = 30.0

# Site ID, name, region, latitude, longitude, available viewer names.
# Co-located Guard/Sentry cameras share one distance calculation and UI row.
CAMERA_SITES = (
    ("kowen", "Kowen Forest", "ACT", -35.275066, 149.275159, ("Guard", "Sentry")),
    ("ginini", "Mt Ginini", "ACT", -35.5294, 148.7718, ("Guard", "Sentry")),
    ("coree", "Mt Coree", "ACT", -35.307321, 148.810202, ("Guard", "Sentry")),
    ("stromlo", "Stromlo", "ACT", -35.3162, 149.0106, ("Sentry",)),
    ("tennent", "Mt Tennent", "ACT", -35.550024, 149.044696, ("Guard", "Sentry")),
    ("one-tree", "One Tree Hill", "ACT", -35.142196, 149.091321, ("Guard", "Sentry")),
    ("bugtown", "Big BugTown", "NSW", -35.873987, 148.7366806, ("Guard",)),
    ("talbingo", "Big Talbingo", "NSW", -35.616309, 148.331454, ("Guard",)),
    ("bowning", "Bowning Hill", "NSW", -34.777981, 148.830716, ("Guard", "Sentry")),
    ("galore", "Galore Hill", "NSW", -35.108797, 146.790427, ("Guard",)),
    (
        "kurrajong",
        "Kurrajong Heights",
        "NSW",
        -33.53617,
        150.62538,
        ("Guard", "Sentry"),
    ),
    ("black-jack", "Black Jack", "NSW", -35.974701, 148.313447, ("Guard",)),
    ("flakney", "Mt Flakney", "NSW", -35.289092, 147.430019, ("Guard", "Sentry")),
    ("ikes", "Mt Ikes", "NSW", -35.897984, 147.949072, ("Guard", "Sentry")),
    ("ingebyra", "Mt Ingebyra", "NSW", -36.643886, 148.456218, ("Guard",)),
    ("youngal", "Mt Youngal", "NSW", -36.394868, 148.118588, ("Guard",)),
)


def camera_catalogue() -> dict[str, dict[str, Any]]:
    """Send one compact catalogue, not repeated URLs in every incident."""
    return {
        site_id: {"name": name, "region": region, "views": list(views)}
        for site_id, name, region, _lat, _lon, views in CAMERA_SITES
    }


def camera_url(site_id: str, view: str | None = None) -> str:
    site = next(item for item in CAMERA_SITES if item[0] == site_id)
    selected = view or site[5][0]
    if selected not in site[5]:
        raise ValueError("Unknown camera view")
    name = quote(quote(f"{site[1]} - {selected}", safe=""), safe="")
    return f"{CENTRAL_WATCH_URL}?camera={name}"


def nearby_camera_sites(
    latitude: float | None,
    longitude: float | None,
    radius_km: float = DEFAULT_CAMERA_RADIUS_KM,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Nearest sites to the reported point, across all jurisdiction borders.

    Do not substitute a home coordinate or warning polygon for a missing fire
    location. Thresholds use unrounded distances; display distances are rounded.
    """
    if latitude is None or longitude is None:
        return []
    if not all(isfinite(value) for value in (latitude, longitude, radius_km)):
        return []
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180) or radius_km <= 0:
        return []
    matches = sorted(
        (haversine_km(latitude, longitude, lat, lon), site_id)
        for site_id, _name, _region, lat, lon, _views in CAMERA_SITES
    )
    return [
        {"site_id": site_id, "distance_km": round(distance, 1)}
        for distance, site_id in matches
        if distance <= radius_km
    ][: max(0, limit)]
