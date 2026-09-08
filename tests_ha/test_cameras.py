"""Camera context must not change official notification urgency or routing."""

from dataclasses import replace
import json
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.australian_fire_watch.model import Incident, LifecycleEvent


@pytest.mark.parametrize("level", ["Advice", "Watch and Act", "Emergency Warning"])
async def test_camera_notification_preserves_official_action_and_priority(
    hass, entry, loaded, level
):
    hass.config_entries.async_update_entry(
        entry, options={"notify_services": ["notify.fixture"]}
    )
    incident = Incident(
        "camera-test",
        "Public camera fixture",
        warning_level=level,
        latitude=-35.275066,
        longitude=149.275159,
        official_url="https://example.invalid/official",
    )
    with patch.object(
        loaded, "_async_send_notification", new_callable=AsyncMock
    ) as send:
        await loaded._async_notify(
            LifecycleEvent(incident.id, "new", incident), test=False
        )
    payload = send.call_args.args[3]
    assert len(payload["actions"]) == 3
    assert payload["actions"][0]["uri"] == incident.official_url
    assert payload["actions"][1]["title"] == "View camera"
    assert "Kowen%2520Forest" in payload["actions"][1]["uri"]
    assert "ACK|" in payload["actions"][2]["action"]
    assert payload["clickAction"] == incident.official_url
    assert (payload.get("push", {}).get("interruption-level") == "critical") == (
        level == "Emergency Warning"
    )
    assert "from reported fire location" in send.call_args.args[2]


@pytest.mark.parametrize(
    "enabled,latitude,lifecycle",
    [
        (False, -35.275066, "new"),
        (True, None, "new"),
        (True, -35.275066, "left_radius"),
        (True, -35.275066, "resolved"),
    ],
)
async def test_no_camera_button_without_current_match(
    hass, entry, loaded, enabled, latitude, lifecycle
):
    hass.config_entries.async_update_entry(
        entry,
        options={
            "notify_services": ["notify.fixture"],
            "enable_central_watch": enabled,
        },
    )
    incident = Incident("fixture", "Fixture", latitude=latitude, longitude=149.275159)
    if lifecycle == "resolved":
        incident = None
    with patch.object(
        loaded, "_async_send_notification", new_callable=AsyncMock
    ) as send:
        await loaded._async_notify(
            LifecycleEvent("fixture", lifecycle, incident), test=False
        )
    assert all(
        item["title"] != "View camera" for item in send.call_args.args[3]["actions"]
    )


async def test_camera_dashboard_without_fires_and_option_disable(hass, entry, loaded):
    hass.config.latitude, hass.config.longitude = -35.275066, 149.275159
    with patch.object(
        loaded, "_home_coordinates", return_value=(-35.275066, 149.275159)
    ):
        data = loaded._compose_data()
    assert not data["incidents"]
    assert data["camera_network"]["nearby_sites"][0]["site_id"] == "kowen"
    hass.config_entries.async_update_entry(
        entry, options={"enable_central_watch": False}
    )
    assert loaded._compose_data()["camera_network"] == {"enabled": False}
    assert "nearby_cameras" not in loaded._incident_dict(Incident("fixture", "Fixture"))


async def test_camera_context_keeps_typical_full_summary_below_recorder_limit(
    hass, loaded
):
    hass.config.latitude, hass.config.longitude = -35.275066, 149.275159
    base = Incident(
        "one",
        "Public camera fixture",
        latitude=-35.275066,
        longitude=149.275159,
        warning_level="Advice",
        official_url="https://example.invalid/official",
    )
    loaded._incidents = tuple(
        replace(base, id=f"incident-{index}") for index in range(10)
    )
    loaded._planned = tuple(
        replace(base, id=f"planned-{index}", is_planned=True) for index in range(4)
    )
    with patch.object(
        loaded, "_home_coordinates", return_value=(-35.275066, 149.275159)
    ):
        data = loaded._compose_data()
    assert data["incidents"][0]["nearby_cameras"]
    assert len(json.dumps(data).encode()) < 16384


def test_camera_config_defaults_and_validated_radius():
    import voluptuous as vol
    from custom_components.australian_fire_watch import YAML_ENTRY_SCHEMA
    from custom_components.australian_fire_watch.config_flow import _prepare, _schema

    defaults = YAML_ENTRY_SCHEMA({})
    assert defaults["enable_central_watch"] is True
    assert defaults["camera_radius_km"] == 30
    assert _prepare(defaults)["camera_radius_km"] == 30
    values = _schema({})(
        {
            "name": "Fixture",
            "zone": "zone.home",
            "jurisdictions": ["NSW"],
            "enable_central_watch": False,
            "camera_radius_km": 20,
        }
    )
    assert _prepare(values)["enable_central_watch"] is False
    assert _prepare(values)["camera_radius_km"] == 20
    for radius in (0, 31):
        with pytest.raises(vol.Invalid):
            YAML_ENTRY_SCHEMA({"camera_radius_km": radius})
