"""End-to-end tests against the simulated NetMonitor."""
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.heatmiser_netmonitor.const import DOMAIN

from .conftest import HOST


async def setup(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN, data={"host": HOST, "username": "u", "password": "p"}
    )
    entry.add_to_hass(hass)
    with patch("custom_components.heatmiser_netmonitor.heatmiser_hub.time.sleep"):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_bulk_poll_sets_modes(hass, netmonitor):
    await setup(hass)
    assert hass.states.get("climate.hall").state == "off"
    assert hass.states.get("climate.bedroom").state == "off"
    study = hass.states.get("climate.study")
    assert study.state == "heat"
    assert study.attributes["current_temperature"] == 19
    assert study.attributes["temperature"] == 21
    assert study.attributes["hvac_action"] == "heating"
    assert hass.states.get("climate.bedroom_5").attributes["temperature"] == 16
    # Polling used the bulk pages, not right.htm.
    assert not any(p == "/right.htm" for p, _ in netmonitor.posts)


async def test_comms_sensors(hass, netmonitor):
    await setup(hass)
    study = hass.states.get("sensor.study_comms_success")
    assert float(study.state) == 95.0
    assert study.attributes["sent"] == 1000 and study.attributes["received"] == 950
    b5 = hass.states.get("sensor.bedroom_5_comms_success")
    assert b5.attributes["address"] == 13
    assert float(b5.state) == round(100 * 2050 / 2100, 1)


async def test_setback_touches_only_that_room(hass, netmonitor):
    await setup(hass)
    before = netmonitor.frost_state
    with patch("custom_components.heatmiser_netmonitor.heatmiser_hub.time.sleep"):
        await hass.services.async_call(
            DOMAIN, "setback_heating", {"entity_id": "climate.kitchen"}, blocking=True
        )
    # Never writes frost.htm, whose map sets every room's frost state.
    assert not any(p == "frost.htm" for p, _ in netmonitor.posts)
    bodies = [b for p, b in netmonitor.posts if p == "/right.htm"]
    assert "curSelStat=Kitchen" in bodies[0] and "selFrost=1" in bodies[1]
    await hass.async_block_till_done(wait_background_tasks=True)
    # Kitchen (3) added; Hall, Playroom and Bedroom stay in frost.
    assert netmonitor.frost_state[:6] == "011101"


async def test_test_send_and_poll(hass, netmonitor):
    await setup(hass)
    res = await hass.services.async_call(
        DOMAIN, "test_send",
        {"entity_id": "climate.living_room", "temperature": 18, "attempts": 2,
         "method": "map"},
        blocking=True, return_response=True,
    )
    r = res["climate.living_room"]
    assert r["method"] == "map" and len(r["attempts"]) == 2
    assert r["sent"]["quickSet"] == "18"
    assert r["sent"]["quickSetMap"][4] == "1" and r["sent"]["quickSetMap"].count("1") == 1

    res = await hass.services.async_call(
        DOMAIN, "test_send",
        {"entity_id": "climate.living_room", "hvac_mode": "off", "method": "select"},
        blocking=True, return_response=True,
    )
    assert res["climate.living_room"]["sent"] == {"selFrost": "1"}

    from homeassistant.exceptions import ServiceValidationError
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "test_send",
            {"entity_id": "climate.study", "hvac_mode": "off", "method": "map"},
            blocking=True, return_response=True,
        )
    assert not any(p == "frost.htm" for p, _ in netmonitor.posts)

    for method in ("select", "bulk"):
        res = await hass.services.async_call(
            DOMAIN, "test_poll", {"entity_id": "climate.study", "method": method},
            blocking=True, return_response=True,
        )
        assert "error" not in res["climate.study"], res
    assert res["climate.study"]["target_temperature"] == 21


async def test_failures_raise_homeassistanterror(hass, netmonitor):
    await setup(hass)
    import requests
    with patch(
        "custom_components.heatmiser_netmonitor.heatmiser_hub.HeatmiserHub._post",
        side_effect=requests.ConnectionError("noise"),
    ), patch("custom_components.heatmiser_netmonitor.heatmiser_hub.time.sleep"):
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                "climate", "set_temperature",
                {"entity_id": "climate.study", "temperature": 20}, blocking=True,
            )
