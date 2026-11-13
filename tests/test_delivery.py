"""Delivery of temperature and mode changes through right.htm: send, resend, check."""
from custom_components.heatmiser_netmonitor.const import DOMAIN  # noqa: F401

from .test_integration import setup


async def settle(hass):
    await hass.async_block_till_done(wait_background_tasks=True)


def right_posts(netmonitor):
    return [b for p, b in netmonitor.posts if p == "/right.htm"]


async def test_temperature_needs_resend_and_sticks(hass, netmonitor):
    await setup(hass)
    await hass.services.async_call(
        "climate", "set_temperature",
        {"entity_id": "climate.living_room", "temperature": 18}, blocking=True,
    )
    assert netmonitor.targets[4] == 14  # first send alone didn't stick
    assert len([b for b in right_posts(netmonitor) if "selSetTemp" in b]) == 1
    await settle(hass)
    assert netmonitor.targets[4] == 18
    # Two sends (now and the resend), not ten.
    assert len([b for b in right_posts(netmonitor) if "selSetTemp" in b]) == 2
    assert hass.states.get("climate.living_room").attributes["temperature"] == 18


async def test_several_rooms_change_at_once(hass, netmonitor):
    await setup(hass)
    for entity, mode in (("climate.study", "off"), ("climate.kitchen", "off"),
                         ("climate.hall", "heat")):
        await hass.services.async_call(
            "climate", "set_hvac_mode", {"entity_id": entity, "hvac_mode": mode},
            blocking=True,
        )
    await hass.services.async_call(
        "climate", "set_temperature",
        {"entity_id": "climate.living_room", "temperature": 20}, blocking=True,
    )
    await settle(hass)
    # Study (0) and Kitchen (3) in frost, Hall (1) out; Playroom (2) and
    # Bedroom (5) untouched; Living Room at 20; no other targets changed.
    assert netmonitor.frost_state[:6] == "101101"
    assert netmonitor.targets[4] == 20
    assert netmonitor.targets[0] == 21 and netmonitor.targets[3] == 19
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
    assert len([b for b in right_posts(netmonitor) if "selSetTemp=18" in b]) == 1


async def test_change_that_never_sticks_gives_up(hass, netmonitor):
    await setup(hass)
    netmonitor._apply_if_repeated = lambda *a: False  # nothing ever sticks
    await hass.services.async_call(
        "climate", "set_temperature",
        {"entity_id": "climate.living_room", "temperature": 22}, blocking=True,
    )
    await settle(hass)
    sends = [b for b in right_posts(netmonitor) if "selSetTemp=22" in b]
    # First send, then per round a resend and (for rounds 1-2) a retry: 1 + 3 + 2.
    assert len(sends) == 6
    assert netmonitor.targets[4] == 14
