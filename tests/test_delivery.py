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


async def test_network_error_does_not_lose_request(hass, netmonitor, clock):
    """A network error during the first burst keeps the request in flight for retry."""
    import requests
    from unittest.mock import patch

    entry = await setup(hass)
    with patch(
        "custom_components.heatmiser_netmonitor.heatmiser_hub.HeatmiserHub._post",
        side_effect=requests.ConnectionError("offline"),
    ):
        await set_temp(hass, "climate.living_room", 18)
        assert hass.states.get("climate.living_room").attributes["temperature"] == 18
        await resend_done(hass)

    assert not tracked(entry).settled
    assert tracked(entry).sends_this_round == N

    # Network recovers on the next poll after SETTLE_AFTER: round 2 delivers it.
    await poll(hass, entry, clock, 91)
    assert netmonitor.targets[4] == 18
    await poll(hass, entry, clock, 91)
    assert tracked(entry).settled and tracked(entry).current == 18


async def test_overlapping_sets_do_not_spawn_duplicate_resends(hass, netmonitor, clock):
    """Rapid concurrent changes while the lock is held only send the latest burst."""
    import asyncio

    entry = await setup(hass)
    coordinator = entry.runtime_data
    gate = asyncio.Event()
    real_send = coordinator.hub.send_setting_async

    async def gated_send(name, kind, value, should_send=None):
        await gate.wait()
        return await real_send(name, kind, value, should_send=should_send)

    coordinator.hub.send_setting_async = gated_send
    t1 = hass.async_create_task(coordinator.async_set("Living Room", "temperature", 18))
    await asyncio.sleep(0)
    t2 = hass.async_create_task(coordinator.async_set("Living Room", "temperature", 19))
    await asyncio.sleep(0)
    assert hass.states.get("climate.living_room").attributes["temperature"] == 19
    gate.set()
    await asyncio.gather(t1, t2)
    await resend_done(hass)

    assert len(sends(netmonitor, "selSetTemp=18")) <= 1
    assert len(sends(netmonitor, "selSetTemp=19")) == N
    assert netmonitor.targets[4] == 19


async def test_nc_stat_does_not_confirm_from_cached_echo(hass, netmonitor, clock):
    """A stat going NC after an unconfirmed echo must not be treated as confirmed."""
    from .conftest import QUICK

    entry = await setup(hass)
    await set_temp(hass, "climate.living_room", 18)
    await resend_done(hass)
    assert netmonitor.targets[4] == 18
    await poll(hass, entry, clock, 30)  # caches 18 in coordinator.data

    # Stat goes NC before settling; 91 s pass while still NC.
    saved = QUICK[4]
    try:
        QUICK[4] = "NCNC03"
        await poll(hass, entry, clock, 61)
        assert not tracked(entry).settled
    finally:
        QUICK[4] = saved

    await poll(hass, entry, clock, 1)
    assert tracked(entry).settled and tracked(entry).current == 18


async def test_settle_timer_starts_after_send_completes(hass, netmonitor, clock):
    """SETTLE_AFTER is measured from when the last send finishes, not before lock wait."""
    entry = await setup(hass)
    coordinator = entry.runtime_data
    real_send = coordinator.hub.send_setting_async

    async def slow_send(name, kind, value, should_send=None):
        clock.advance(10)  # simulate waiting on lock / slow HTTP
        return await real_send(name, kind, value, should_send=should_send)

    coordinator.hub.send_setting_async = slow_send
    await set_temp(hass, "climate.living_room", 18)
    await resend_done(hass)

    # 85 s after the final send finished (even though 135 s passed since start): not settled yet.
    await poll(hass, entry, clock, 85)
    assert not tracked(entry).settled

    # 6 s later (91 s after the final send finished): now settled.
    await poll(hass, entry, clock, 6)
    assert tracked(entry).settled and tracked(entry).current == 18


async def test_outside_change_before_first_ha_set_updates_current(hass, netmonitor, clock):
    """A schedule change on an untouched stat updates current so a later failed round retries."""
    entry = await setup(hass)
    # Living Room changes from 14 to 16 on its schedule before HA ever sets it.
    netmonitor.targets[4] = 16
    await poll(hass, entry, clock, 30)
    assert tracked(entry).current == 16

    # Now user sets 20, and round 1 fails to reach the stat (still reads 16).
    count = {"n": 0}
    real = netmonitor._apply_if_repeated

    def first_round_fails(kind, index, value):
        count["n"] += 1
        return False if count["n"] <= N else real(kind, index, value)

    netmonitor._apply_if_repeated = first_round_fails
    await set_temp(hass, "climate.living_room", 20)
    await resend_done(hass)

    # Poll at 30 s reads 16 (the old value, not a new outside override): stays in flight.
    await poll(hass, entry, clock, 30)
    assert not tracked(entry).settled
    assert hass.states.get("climate.living_room").attributes["temperature"] == 20

    # Poll at 91 s triggers round 2, which lands 20.
    await poll(hass, entry, clock, 61)
    assert netmonitor.targets[4] == 20


async def test_poll_in_flight_during_set_does_not_cancel_request(hass, netmonitor, clock):
    """A poll that started before async_set sent its first packet must not cancel async_set."""
    import asyncio

    entry = await setup(hass)
    coordinator = entry.runtime_data
    netmonitor.targets[4] = 16  # stat changed to 16 just as poll started

    poll_entered = asyncio.Event()
    allow_poll_finish = asyncio.Event()
    real_get_all = coordinator.hub.get_all_status_async

    async def gated_get_all():
        async with coordinator.hub._lock:
            poll_entered.set()
            await allow_poll_finish.wait()
            return await hass.async_add_executor_job(coordinator.hub.get_all_status)

    coordinator.hub.get_all_status_async = gated_get_all
    poll_task = hass.async_create_task(coordinator.async_refresh())
    await poll_entered.wait()

    # User sets 20 while poll holds the hub lock (before send #1 of 20 can run).
    set_task = hass.async_create_task(coordinator.async_set("Living Room", "temperature", 20))
    await asyncio.sleep(0)
    assert hass.states.get("climate.living_room").attributes["temperature"] == 20

    allow_poll_finish.set()
    await asyncio.gather(poll_task, set_task)
    await resend_done(hass)

    assert not tracked(entry).settled
    assert tracked(entry).target == 20
    assert tracked(entry).current == 16
    assert netmonitor.targets[4] == 20
