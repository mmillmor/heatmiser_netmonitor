"""Delivery of temperature and mode changes: current/target reconciliation on each poll."""
from .test_integration import setup


async def poll(hass, entry, clock, seconds):
    """Let time pass, then run one poll."""
    clock.advance(seconds)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


def sends(netmonitor, text):
    return [b for p, b in netmonitor.posts if p == "/right.htm" and text in b]


async def set_temp(hass, entity, t):
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": entity, "temperature": t}, blocking=True
    )


async def test_resend_then_confirm(hass, netmonitor, clock):
    entry = await setup(hass)
    await set_temp(hass, "climate.living_room", 18)
    assert len(sends(netmonitor, "selSetTemp=18")) == 1
    assert netmonitor.targets[4] == 14              # one send doesn't stick
    # The UI shows the requested value straight away.
    assert hass.states.get("climate.living_room").attributes["temperature"] == 18

    await poll(hass, entry, clock, 15)              # too soon to resend
    assert len(sends(netmonitor, "selSetTemp=18")) == 1
    await poll(hass, entry, clock, 16)              # 31 s: resend
    assert len(sends(netmonitor, "selSetTemp=18")) == 2
    assert netmonitor.targets[4] == 18

    tracked = entry.runtime_data.tracked[("Living Room", "temperature")]
    await poll(hass, entry, clock, 60)              # matches, but too soon to trust
    assert not tracked.settled
    await poll(hass, entry, clock, 31)              # 91 s after the resend
    assert tracked.settled and tracked.current == 18
    assert len(sends(netmonitor, "selSetTemp=18")) == 2   # two sends, not ten
    assert hass.states.get("climate.living_room").attributes["temperature"] == 18


async def test_reverted_change_gets_another_round(hass, netmonitor, clock):
    entry = await setup(hass)
    stuck = {"n": 0}
    real = netmonitor._apply_if_repeated

    def first_round_fails(kind, index, value):
        stuck["n"] += 1
        return False if stuck["n"] <= 2 else real(kind, index, value)

    netmonitor._apply_if_repeated = first_round_fails
    await set_temp(hass, "climate.living_room", 18)
    await poll(hass, entry, clock, 31)              # resend (round 1)
    await poll(hass, entry, clock, 91)              # reverted: round 2 starts
    assert len(sends(netmonitor, "selSetTemp=18")) == 3
    await poll(hass, entry, clock, 31)              # round 2 resend
    await poll(hass, entry, clock, 91)
    tracked = entry.runtime_data.tracked[("Living Room", "temperature")]
    assert netmonitor.targets[4] == 18 and tracked.settled and tracked.rounds == 2


async def test_gives_up_after_three_rounds(hass, netmonitor, clock):
    entry = await setup(hass)
    netmonitor._apply_if_repeated = lambda *a: False
    await set_temp(hass, "climate.living_room", 22)
    for _ in range(3):
        await poll(hass, entry, clock, 31)
        await poll(hass, entry, clock, 91)
    tracked = entry.runtime_data.tracked[("Living Room", "temperature")]
    assert len(sends(netmonitor, "selSetTemp=22")) == 6
    assert tracked.settled and tracked.current == 14     # adopts what it reads
    # and the UI shows what the thermostat really is again.
    assert hass.states.get("climate.living_room").attributes["temperature"] == 14
    await poll(hass, entry, clock, 200)
    assert len(sends(netmonitor, "selSetTemp=22")) == 6  # and stops sending


async def test_change_at_thermostat_is_adopted(hass, netmonitor, clock):
    entry = await setup(hass)
    await set_temp(hass, "climate.living_room", 18)
    await poll(hass, entry, clock, 31)
    await poll(hass, entry, clock, 91)
    tracked = entry.runtime_data.tracked[("Living Room", "temperature")]
    assert tracked.settled and tracked.current == 18
    netmonitor.targets[4] = 16                      # changed at the thermostat
    await poll(hass, entry, clock, 30)
    assert tracked.current == tracked.target == 16
    assert not sends(netmonitor, "selSetTemp=18")[2:]   # nothing re-sent


async def test_third_value_during_delivery_wins(hass, netmonitor, clock):
    entry = await setup(hass)
    await set_temp(hass, "climate.living_room", 18)
    netmonitor.targets[4] = 16                      # program changed it meanwhile
    await poll(hass, entry, clock, 31)
    tracked = entry.runtime_data.tracked[("Living Room", "temperature")]
    assert tracked.current == tracked.target == 16
    assert len(sends(netmonitor, "selSetTemp=18")) == 1  # no resend


async def test_newer_target_replaces_older(hass, netmonitor, clock):
    entry = await setup(hass)
    await set_temp(hass, "climate.living_room", 18)
    await set_temp(hass, "climate.living_room", 19)
    await poll(hass, entry, clock, 31)
    await poll(hass, entry, clock, 91)
    assert netmonitor.targets[4] == 19
    assert len(sends(netmonitor, "selSetTemp=18")) == 1


async def test_several_rooms_at_once(hass, netmonitor, clock):
    entry = await setup(hass)
    for entity, mode in (("climate.study", "off"), ("climate.kitchen", "off"),
                         ("climate.hall", "heat")):
        await hass.services.async_call(
            "climate", "set_hvac_mode", {"entity_id": entity, "hvac_mode": mode},
            blocking=True,
        )
        assert hass.states.get(entity).state == mode   # shown straight away
    await set_temp(hass, "climate.living_room", 20)
    await poll(hass, entry, clock, 31)
    await poll(hass, entry, clock, 91)
    assert netmonitor.frost_state[:6] == "101101"   # Study, Kitchen on; Hall off
    assert netmonitor.targets[4] == 20 and netmonitor.targets[0] == 21
    coordinator = entry.runtime_data
    assert all(t.settled for t in coordinator.tracked.values())
    assert hass.states.get("climate.study").state == "off"
    assert hass.states.get("climate.hall").state == "heat"
