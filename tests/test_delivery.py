"""Delivery of temperature and mode changes: send, resend, check."""
from unittest.mock import patch

import pytest

from custom_components.heatmiser_netmonitor.const import DOMAIN

from .test_integration import setup

HUB = "custom_components.heatmiser_netmonitor.heatmiser_hub"


@pytest.fixture(autouse=True)
def fast_delivery():
    with patch(f"{HUB}.RESEND_AFTER", 0.05), patch(f"{HUB}.VERIFY_AFTER", 0.1):
        yield


async def settle(hass):
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_temperature_needs_resend_and_sticks(hass, netmonitor):
    await setup(hass)
    await hass.services.async_call(
        "climate", "set_temperature",
        {"entity_id": "climate.living_room", "temperature": 18}, blocking=True,
    )
    assert netmonitor.targets[4] == 14  # first send alone didn't stick
    await settle(hass)
    assert netmonitor.targets[4] == 18
    # Sent by map, not via right.htm's selected stat.
    assert all(p != "/right.htm" for p, _ in netmonitor.posts)
    assert hass.states.get("climate.living_room").attributes["temperature"] == 18


async def test_two_rooms_change_mode_together(hass, netmonitor):
    await setup(hass)
    # Study and Kitchen to frost, Hall out of frost, all at once.
    for entity, mode in (("climate.study", "off"), ("climate.kitchen", "off"),
                         ("climate.hall", "heat")):
        await hass.services.async_call(
            "climate", "set_hvac_mode", {"entity_id": entity, "hvac_mode": mode},
            blocking=True,
        )
    await settle(hass)
    # Study (0) and Kitchen (3) in frost, Hall (1) out, Playroom (2) and
    # Bedroom (5) untouched.
    assert netmonitor.frost_state[:6] == "101101"
    assert hass.states.get("climate.study").state == "off"
    assert hass.states.get("climate.hall").state == "heat"


async def test_newer_change_cancels_older_resends(hass, netmonitor):
    await setup(hass)
    for t in (18, 19):
        await hass.services.async_call(
            "climate", "set_temperature",
            {"entity_id": "climate.living_room", "temperature": t}, blocking=True,
        )
    await settle(hass)
    assert netmonitor.targets[4] == 19
    sent_18 = [b for p, b in netmonitor.posts if p == "tempset.htm" and "quickSet=18" in b]
    assert len(sent_18) == 1  # only the first send; its resends were cancelled
