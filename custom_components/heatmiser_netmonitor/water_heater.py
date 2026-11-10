"""Water Heater module for the Heatmiser NetMonitor integration."""
import logging

import voluptuous as vol

from homeassistant.components.water_heater import (
    STATE_GAS,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HeatmiserConfigEntry, HeatmiserCoordinator
from .heatmiser_hub import HeatmiserStat
from .schemas import HOURS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: HeatmiserConfigEntry, async_add_entities
):
    """Set up Heatmiser hot water based on config_entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        HeatmiserWaterHeater(coordinator, stat)
        for stat in coordinator.stats
        if stat.hw_timer_output != STATE_UNAVAILABLE
    )

    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service(
        "boost_hot_water",
        {
            vol.Optional("time_period", default="01:00:00"): HOURS,
        },
        "async_hot_water_boost",
    )


class HeatmiserWaterHeater(CoordinatorEntity[HeatmiserCoordinator], WaterHeaterEntity):
    """Heatmiser Water Heater Device."""

    def __init__(self, coordinator: HeatmiserCoordinator, stat: HeatmiserStat) -> None:
        """Set up Heatmiser water heater entity based on a stat."""
        super().__init__(coordinator)
        self._stat_name = stat.name
        self._stat_id = str(stat.id)
        self.hub = coordinator.hub
        self._attr_supported_features = (
            WaterHeaterEntityFeature.ON_OFF | WaterHeaterEntityFeature.OPERATION_MODE
        )
        self._attr_operation_list = [STATE_GAS, STATE_OFF]

    @property
    def water_heater(self) -> HeatmiserStat:
        """Return the latest data for this stat."""
        return self.coordinator.data[self._stat_name]

    @property
    def name(self):
        """Return the name of the water heater."""
        return self._stat_name + " Hot Water"

    @property
    def unique_id(self):
        """Return unique ID of entity."""
        return self._stat_id

    @property
    def native_temperature_unit(self):
        """Return the unit of measurement."""
        return UnitOfTemperature.CELSIUS

    @property
    def current_operation(self):
        """Return current operation."""
        if self.water_heater.hw_timer_output == STATE_ON:
            return STATE_GAS
        if self.water_heater.hw_timer_output == STATE_OFF:
            return STATE_OFF
        return None

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        if self.water_heater.hw_timer_output == STATE_ON:
            return "mdi:water-boiler"
        return "mdi:water-boiler-off"

    async def async_turn_on(self, **kwargs):
        """Turn on hotwater."""
        await self.hub.set_boost_async(self._stat_name, 24)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        """Turn off hotwater."""
        await self.hub.set_boost_async(self._stat_name, 0)
        await self.coordinator.async_request_refresh()

    async def async_set_operation_mode(self, operation_mode):
        """Set operation mode."""
        if operation_mode == STATE_GAS:
            await self.hub.set_boost_async(self._stat_name, 24)
        if operation_mode == STATE_OFF:
            await self.hub.set_boost_async(self._stat_name, 0)
        await self.coordinator.async_request_refresh()

    async def async_hot_water_boost(self, time_period):
        """Handle the service call."""
        await self.hub.set_boost_async(self._stat_name, time_period)
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, "heatmiser_nermonitor")
            },
            name="Netmonitor",
            manufacturer="Heatmiser",
        )
