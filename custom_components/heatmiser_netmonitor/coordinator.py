"""Data update coordinator for the Heatmiser NetMonitor integration."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging
import time
from typing import Any

import requests

from homeassistant.components.climate.const import HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .heatmiser_hub import HeatmiserHub, HeatmiserStat

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)
# Read the comms counters on every Nth poll (every 5 minutes at 30 s).
COMMS_STATS_EVERY = 10

# Delivery of temperature and mode changes. Testing on a real network showed
# that a single send rarely sticks: the NetMonitor shows the new value, then
# its own read of the stat 25-60 s later puts the old value back. Changes stuck
# reliably with 4 sends 15 s apart and with 10 sends 1 s apart, while 3 sends
# 1 s apart and two sends 30 s apart were hit and miss. 5 sends 2 s apart is
# the middle ground: about 10 s of sends, like the 10-send burst.
# So each round sends a change SENDS_PER_ROUND times, RESEND_EVERY seconds
# apart, on its own timer. A reading only counts as the stat's real value once
# SETTLE_AFTER seconds have passed since the last send, because until then the
# NetMonitor may just be echoing what was sent.
SENDS_PER_ROUND = 5
RESEND_EVERY = 2
SETTLE_AFTER = 90
MAX_ROUNDS = 3

KIND_TEMPERATURE = "temperature"
KIND_MODE = "mode"


def _now() -> float:
    return time.monotonic()


@dataclass
class Tracked:
    """What Home Assistant knows a stat is set to, and what it wants."""

    current: Any
    target: Any
    last_sent: float = 0.0
    sends_this_round: int = 0
    rounds: int = 0
    # Identifies the current round, so a timed resend from an older round or
    # an older target does nothing.
    round_id: int = 0

    @property
    def settled(self) -> bool:
        return self.current == self.target


type HeatmiserConfigEntry = ConfigEntry[HeatmiserCoordinator]


class HeatmiserCoordinator(DataUpdateCoordinator[dict[str, HeatmiserStat]]):
    """Poll the NetMonitor for all stats, and deliver changes until they stick.

    For each stat and setting (temperature or mode) that Home Assistant has
    changed, it keeps the value the stat is known to have (current) and the
    value wanted (target). On each poll:

    - settled (current == target) and the reading differs: someone changed
      the stat (at the thermostat, or its program did); adopt the reading.
    - in flight and the reading is neither current nor target: likewise,
      that change wins.
    - in flight, less than SETTLE_AFTER since the last send: resend once per
      round, on a timer; otherwise wait, since the
      NetMonitor may be echoing what was sent.
    - in flight and settled long enough: if the reading equals the target,
      it's confirmed; if it's still the old value, start another round, up to
      MAX_ROUNDS, then give up and adopt the reading.
    """

    config_entry: HeatmiserConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HeatmiserConfigEntry,
        hub: HeatmiserHub,
        stats: list[HeatmiserStat],
    ) -> None:
        """Initialise the coordinator with the stats found at setup."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.hub = hub
        self.stats = stats
        # Seed with the data from the initial device listing.
        self.data = {stat.name: stat for stat in stats}
        # Per-stat send/receive counters from statistics.htm.
        self.comms: dict[str, dict] = {}
        self._polls = 0
        self.tracked: dict[tuple[str, str], Tracked] = {}

    @staticmethod
    def _reading(stat: HeatmiserStat, kind: str):
        if kind == KIND_TEMPERATURE:
            return stat.target_temperature
        return stat.hvac_mode

    async def async_set(self, name: str, kind: str, value) -> None:
        """Set a stat's temperature or mode, and keep delivering it until it sticks.

        Sends once straight away (so an unreachable NetMonitor raises to the
        caller); later polls resend and confirm it. A newer value for the
        same stat and setting simply replaces the target.
        """
        if kind == KIND_TEMPERATURE:
            value = int(value)
        else:
            value = HVACMode(value)
        key = (name, kind)
        tracked = self.tracked.get(key)
        if tracked is None:
            stat = (self.data or {}).get(name)
            tracked = Tracked(current=self._reading(stat, kind) if stat else None, target=value)
            self.tracked[key] = tracked
        tracked.target = value
        tracked.rounds = 1
        tracked.sends_this_round = 1
        tracked.last_sent = _now()
        tracked.round_id += 1
        await self.hub.send_setting_async(name, kind, value)
        self._schedule_resend(name, kind, tracked)

    def _schedule_resend(self, name: str, kind: str, tracked: Tracked) -> None:
        """Resend this round's change every RESEND_EVERY seconds, up to SENDS_PER_ROUND sends."""
        round_id = tracked.round_id

        async def resend_later():
            while tracked.sends_this_round < SENDS_PER_ROUND:
                await asyncio.sleep(RESEND_EVERY)
                if tracked.round_id != round_id or tracked.settled:
                    return
                await self._send(name, kind, tracked)

        self.hass.async_create_background_task(
            resend_later(), f"heatmiser_netmonitor resend {name} {kind}"
        )

    async def _send(self, name: str, kind: str, tracked: Tracked) -> None:
        tracked.sends_this_round += 1
        tracked.last_sent = _now()
        try:
            await self.hub.send_setting_async(name, kind, tracked.target)
        except (requests.RequestException, ValueError, IndexError) as err:
            _LOGGER.warning("Sending %s %s to %s failed: %s", kind, tracked.target, name, err)

    async def _reconcile(self, data: dict[str, HeatmiserStat]) -> None:
        """Compare what each stat reads with what's wanted, and act on it."""
        now = _now()
        for (name, kind), tracked in self.tracked.items():
            stat = data.get(name)
            reading = self._reading(stat, kind) if stat else None
            if reading is None:
                continue  # not communicating; try again next poll

            if tracked.settled:
                if reading != tracked.current:
                    _LOGGER.info(
                        "%s %s changed to %s outside Home Assistant", name, kind, reading
                    )
                    tracked.current = tracked.target = reading
                continue

            if reading not in (tracked.current, tracked.target):
                _LOGGER.info(
                    "%s %s changed to %s outside Home Assistant while %s was being "
                    "sent; keeping %s",
                    name, kind, reading, tracked.target, reading,
                )
                tracked.current = tracked.target = reading
                continue

            since = now - tracked.last_sent
            if since < SETTLE_AFTER or tracked.sends_this_round < SENDS_PER_ROUND:
                continue  # wait for this round's sends, then for them to settle

            if reading == tracked.target:
                _LOGGER.info(
                    "%s %s %s confirmed after %d round(s)",
                    name, kind, tracked.target, tracked.rounds,
                )
                tracked.current = reading
                continue

            if tracked.rounds >= MAX_ROUNDS:
                _LOGGER.error(
                    "%s %s %s didn't stick after %d rounds; it reads %s",
                    name, kind, tracked.target, tracked.rounds, reading,
                )
                tracked.current = tracked.target = reading
                continue

            _LOGGER.warning(
                "%s %s %s didn't stick (round %d), sending again",
                name, kind, tracked.target, tracked.rounds,
            )
            tracked.rounds += 1
            tracked.sends_this_round = 0
            tracked.round_id += 1
            await self._send(name, kind, tracked)
            self._schedule_resend(name, kind, tracked)

    async def _async_update_data(self) -> dict[str, HeatmiserStat]:
        """Fetch the latest status for every stat in two requests."""
        try:
            latest = await self.hub.get_all_status_async()
        except (requests.RequestException, IndexError, ValueError) as err:
            raise UpdateFailed(f"Error communicating with NetMonitor: {err}") from err

        data: dict[str, HeatmiserStat] = {}
        for stat in self.stats:
            old = (self.data or {}).get(stat.name, stat)
            new = latest.get(stat.name)
            if new is None:
                data[stat.name] = old
                continue
            if new.current_temperature is None:
                # Stat not communicating ("NC"): keep the last known values.
                new.current_temperature = old.current_temperature
                new.target_temperature = old.target_temperature
            data[stat.name] = new

        await self._reconcile(data)

        if self._polls % COMMS_STATS_EVERY == 0:
            try:
                self.comms = await self.hub.get_comms_stats_async()
            except (requests.RequestException, IndexError, ValueError) as err:
                _LOGGER.debug("Couldn't read comms statistics: %s", err)
        self._polls += 1
        return data
