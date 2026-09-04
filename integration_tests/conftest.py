"""Use real HA fixtures; mock only external transport and frontend boundaries."""
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def entry(hass):
    result = MockConfigEntry(domain="australian_fire_watch", title="Fixture", data={
        "name": "Fixture", "jurisdiction": "NSW", "zone": "zone.fixture",
        "enable_bom_enrichment": False, "monitor_radius_km": 150,
        "emergency_radius_km": 100, "watch_radius_km": 50, "advice_radius_km": 20,
        "unclassified_fire_radius_km": 10, "stale_after_minutes": 45,
        "fire_danger_district": "Greater Sydney Region", "notify_services": [],
    })
    result.add_to_hass(hass)
    hass.states.async_set("zone.fixture", "0", {"latitude": 0.0, "longitude": 0.0})
    return result
