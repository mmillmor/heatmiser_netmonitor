"""Delivery of temperature and mode changes: timed resend plus current/target checks on polls."""
from .test_integration import setup
from custom_components.heatmiser_netmonitor.coordinator import SENDS_PER_ROUND as N


async def resend_done(hass):
    await hass.async_block_till_done(wait_background_tasks=True)


async def poll(hass, entry, clock, seconds):
    """Let time pass, then run one poll."""
    clock.advance(seconds)
    await entry.runtime_data.async_refresh()
    await resend_done(hass)


def sends(netmonitor, text):
    return [b for p, b in netmonitor.posts if p == "/right.htm" and text in b]


async def set_temp(hass, entity, t):
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": entity, "temperature": t}, blocking=True
    )


def tracked(entry, name="Living Room", kind="temperature"):
    return entry.runtime_data.tracked[(name, kind)]


async def test_timed_resend_then_confirm(hass, netmonitor, clock):
    entry = await setup(hass)
    await set_temp(hass, "climate.living_room", 18)
    assert len(sends(netmonitor, "selSetTemp=18")) == 1
    assert netmonitor.targets[4] == 14              # one send doesn't stick
    # The UI shows the requested value straight away.
    assert hass.states.get("climate.living_room").attributes["temperature"] == 18

    await resend_done(hass)                         # the timed resends
    assert len(sends(netmonitor, "selSetTemp=18")) == N
    assert netmonitor.targets[4] == 18

    await poll(hass, entry, clock, 60)              # matches, but too soon to trust
    assert not tracked(entry).settled
    await poll(hass, entry, clock, 31)              # 91 s after the resend
    assert tracked(entry).settled and tracked(entry).current == 18
    assert len(sends(netmonitor, "selSetTemp=18")) == N   # one round


async def test_polls_dont_resend_early(hass, netmonitor, clock):
    entry = await setup(hass)
    netmonitor._apply_if_repeated = lambda *a: False
    await set_temp(hass, "climate.living_room", 18)
    await resend_done(hass)
    for _ in range(2):
        await poll(hass, entry, clock, 30)          # within the settle window
    assert len(sends(netmonitor, "selSetTemp=18")) == N


async def test_reverted_change_gets_another_round(hass, netmonitor, clock):
    entry = await setup(hass)
    count = {"n": 0}
    real = netmonitor._apply_if_repeated

    def first_round_fails(kind, index, value):
        count["n"] += 1
        return False if count["n"] <= N else real(kind, index, value)

    netmonitor._apply_if_repeated = first_round_fails
    await set_temp(hass, "climate.living_room", 18)
    await resend_done(hass)
    await poll(hass, entry, clock, 91)              # reverted: round 2 
    assert len(sends(netmonitor, "selSetTemp=18")) == 2 * N
    assert netmonitor.targets[4] == 18
    await poll(hass, entry, clock, 91)
    assert tracked(entry).settled and tracked(entry).rounds == 2


async def test_gives_up_after_three_rounds(hass, netmonitor, clock):
    entry = await setup(hass)
    netmonitor._apply_if_repeated = lambda *a: False
    await set_temp(hass, "climate.living_room", 22)
    await resend_done(hass)
    for _ in range(3):
        await poll(hass, entry, clock, 91)
    assert len(sends(netmonitor, "selSetTemp=22")) == 3 * N
    assert tracked(entry).settled and tracked(entry).current == 14   # adopts reading
    assert hass.states.get("climate.living_room").attributes["temperature"] == 14
    await poll(hass, entry, clock, 200)
    assert len(sends(netmonitor, "selSetTemp=22")) == 3 * N             # and stops


async def test_change_at_thermostat_is_adopted(hass, netmonitor, clock):
    entry = await setup(hass)
    await set_temp(hass, "climate.living_room", 18)
    await resend_done(hass)
    await poll(hass, entry, clock, 91)
    assert tracked(entry).settled and tracked(entry).current == 18
    netmonitor.targets[4] = 16                      # changed at the thermostat
    await poll(hass, entry, clock, 30)
    assert tracked(entry).current == tracked(entry).target == 16
    assert len(sends(netmonitor, "selSetTemp=18")) == N               # nothing re-sent


async def test_third_value_during_delivery_wins(hass, netmonitor, clock):
    entry = await setup(hass)
    await set_temp(hass, "climate.living_room", 18)
    await resend_done(hass)
    netmonitor.targets[4] = 16                      # program changed it meanwhile
    await poll(hass, entry, clock, 31)
    assert tracked(entry).current == tracked(entry).target == 16
    await poll(hass, entry, clock, 91)
    assert len(sends(netmonitor, "selSetTemp=18")) == N               # no new round


async def test_newer_target_cancels_older_resend(hass, netmonitor, clock):
    entry = await setup(hass)
    await set_temp(hass, "climate.living_room", 18)
    await set_temp(hass, "climate.living_room", 19)  # before 18's timed resend
    await resend_done(hass)
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
    await resend_done(hass)
    await poll(hass, entry, clock, 91)
    assert netmonitor.frost_state[:6] == "101101"   # Study, Kitchen on; Hall off
    assert netmonitor.targets[4] == 20 and netmonitor.targets[0] == 21
    assert all(t.settled for t in entry.runtime_data.tracked.values())
    assert hass.states.get("climate.study").state == "off"
    assert hass.states.get("climate.hall").state == "heat"


async def test_changing_back_before_confirmed_is_still_delivered(hass, netmonitor, clock):
    """Going back to the old value while a change is in flight still gets sent."""
    entry = await setup(hass)
    await set_temp(hass, "climate.living_room", 18)
    await resend_done(hass)
    assert netmonitor.targets[4] == 18              # landed, not yet confirmed
    await set_temp(hass, "climate.living_room", 14)  # back to the old value
    assert hass.states.get("climate.living_room").attributes["temperature"] == 14
    await resend_done(hass)
    assert len(sends(netmonitor, "selSetTemp=14")) == N
    assert netmonitor.targets[4] == 14
    await poll(hass, entry, clock, 91)
    assert tracked(entry).settled and tracked(entry).current == 14
    assert hass.states.get("climate.living_room").attributes["temperature"] == 14



async def test_reversing_a_landed_change_doesnt_bounce(hass, netmonitor, clock):
    """Changing back while the first change still reads on the stat doesn't bounce.

    The stat reads 18 (the first change), current and target are both 14; 18
    was sent by us, so it mustn't be taken for a change at the thermostat.
    """
    entry = await setup(hass)
    netmonitor._apply_if_repeated = lambda *a: False   # nothing lands from now on
    netmonitor.targets[4] = 18                          # first change has landed
    await set_temp(hass, "climate.living_room", 18)
    await set_temp(hass, "climate.living_room", 14)     # change back straight away
    await poll(hass, entry, clock, 1)                   # reads 18
    assert hass.states.get("climate.living_room").attributes["temperature"] == 14
    assert not tracked(entry).settled
