"""Data update coordinator for the Heatmiser NetMonitor integration."""
from __future__ import annotations

from datetime import timedelta
import logging

import requests

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .heatmiser_hub import HeatmiserHub, HeatmiserStat

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)

type HeatmiserConfigEntry = ConfigEntry[HeatmiserCoordinator]


class HeatmiserCoordinator(DataUpdateCoordinator[dict[str, HeatmiserStat]]):
    """Poll the NetMonitor once per cycle for all stats."""

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

    async def _async_update_data(self) -> dict[str, HeatmiserStat]:
        """Fetch the latest status for every stat."""
        data: dict[str, HeatmiserStat] = {}
        try:
            for stat in self.stats:
                old = (self.data or {}).get(stat.name, stat)
                new = await self.hub.get_device_status_async(stat.name)
                if new is None:
                    data[stat.name] = old
                    continue
                new.id = stat.id
                if new.current_temperature is None:
                    # Stat not communicating ("NC"): keep the last known values.
                    new.current_temperature = old.current_temperature
                    new.target_temperature = old.target_temperature
                data[stat.name] = new
        except (requests.RequestException, IndexError, ValueError) as err:
            raise UpdateFailed(f"Error communicating with NetMonitor: {err}") from err
        return data
