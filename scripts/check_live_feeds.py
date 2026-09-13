"""Read-only contract check for every configured official feed.

This intentionally checks transport and parser compatibility without asserting
that a feed contains an incident. A valid empty response is normal and safe.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Callable
from urllib.request import Request, urlopen

_ROOT = Path(__file__).parents[1]
_PACKAGE = "custom_components.australian_fire_watch"
if _PACKAGE not in sys.modules:
    package = ModuleType(_PACKAGE)
    package.__path__ = [str(_ROOT / "custom_components" / "australian_fire_watch")]
    sys.modules[_PACKAGE] = package

from custom_components.australian_fire_watch.const import (  # noqa: E402
    BOM_FIRE_DANGER_URL,
    BOM_WARNINGS_URL,
    CAP_URL,
    FDR_TOBAN_URL,
    GEOJSON_URL,
    INCIDENT_ALERTS_URL,
    VERSION,
)
from custom_components.australian_fire_watch.jurisdictions import (  # noqa: E402
    JURISDICTIONS,
)
from custom_components.australian_fire_watch.model import ParsedFeed  # noqa: E402
from custom_components.australian_fire_watch.parsers import (  # noqa: E402
    parse_bom_fire_danger,
    parse_bom_fire_weather_warnings,
    parse_cap,
    parse_geojson,
    parse_rfs_fire_danger,
)
from custom_components.australian_fire_watch.regional_parsers import (  # noqa: E402
    PARSER_NAMES,
    fire_incidents_only,
)

MAX_RESPONSE_BYTES = 20 * 1024 * 1024
Parser = Callable[[bytes], Any]


def _regional_parser(code: str, parser_name: str) -> Parser:
    profile = JURISDICTIONS[code]
    parser = parse_cap if parser_name == "cap" else PARSER_NAMES[parser_name]
    return partial(
        parser,
        source=profile.agency,
        official_url=profile.official_url,
    )


def _contracts() -> list[tuple[str, str, Parser]]:
    contracts: list[tuple[str, str, Parser]] = [
        ("NSW/rfs_cap", CAP_URL, parse_cap),
        ("NSW/rfs_geojson", GEOJSON_URL, parse_geojson),
        (
            "NSW/rfs_incident_alerts",
            INCIDENT_ALERTS_URL,
            partial(parse_cap, source="NSW RFS IncidentAlerts polygons"),
        ),
        ("NSW/rfs_fdr_toban", FDR_TOBAN_URL, parse_rfs_fire_danger),
        ("NSW/bom_fire_danger", BOM_FIRE_DANGER_URL, parse_bom_fire_danger),
        ("NSW/bom_warnings", BOM_WARNINGS_URL, parse_bom_fire_weather_warnings),
    ]
    for code, profile in JURISDICTIONS.items():
        if code == "NSW":
            continue
        contracts.extend(
            (
                f"{code}/{feed.name}",
                feed.url,
                _regional_parser(code, feed.parser),
            )
            for feed in profile.feeds
        )
    return contracts


def _fetch(url: str) -> tuple[bytes, str]:
    request = Request(
        url,
        headers={
            "Accept": "application/json, application/geo+json, application/xml, text/xml, */*",
            "User-Agent": f"Australian-Fire-Watch-Feed-Check/{VERSION}",
        },
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - trusted registry
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds 20 MiB safety limit")
        return body, response.headers.get_content_type()


def main() -> int:
    failures: list[str] = []
    for name, url, parser in _contracts():
        try:
            body, content_type = _fetch(url)
            result = parser(body)
            if isinstance(result, ParsedFeed):
                count = len(fire_incidents_only(result).incidents)
                summary = f"{count} filtered incident(s)"
            elif isinstance(result, dict):
                summary = f"{len(result)} top-level record(s)"
            else:
                raise TypeError(f"unexpected parser result {type(result).__name__}")
            print(f"PASS {name}: {content_type}, {len(body)} bytes, {summary}")
        except Exception as err:  # Keep checking so one run reports every drift.
            failures.append(f"{name}: {type(err).__name__}: {err}")
            print(f"FAIL {failures[-1]}", file=sys.stderr)
    if failures:
        print(f"\n{len(failures)} live feed contract(s) failed", file=sys.stderr)
        return 1
    print("\nAll live feed contracts passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
