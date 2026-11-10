"""Climate module for the Heatmiser NetMonitor integration."""
import logging

import voluptuous as vol

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import ClimateEntityFeature, HVACMode
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HeatmiserConfigEntry, HeatmiserCoordinator
from .heatmiser_hub import HeatmiserStat
from .schemas import HOURS, TEMPERATURE

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, config_entry: HeatmiserConfigEntry, async_add_entities
):
    """Set up Heatmiser climate based on config_entry."""
    coordinator = config_entry.runtime_data
    async_add_entities(HeatmiserClimate(coordinator, stat) for stat in coordinator.stats)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "set_system_time",
        {},
        "async_set_time",
    )

    platform.async_register_entity_service(
        "set_holiday",
        cv.make_entity_service_schema(
            {
                vol.Required("start_date_time"): cv.datetime,
                vol.Required("end_date_time"): cv.datetime,
            },
        ),
        "async_set_holiday",
    )

    platform.async_register_entity_service(
        "boost_heating",
        cv.make_entity_service_schema(
            {
                vol.Required("temperature"): TEMPERATURE,
            },
        ),
        "async_boost_heating",
    )

    platform.async_register_entity_service(
        "hold_temperature",
        cv.make_entity_service_schema(
            {
                vol.Required("temperature"): TEMPERATURE,
                vol.Optional("time_period", default="01:00:00"): vol.All(
                    HOURS, vol.Range(min=1, max=99)
                ),
            },
        ),
        "async_hold_temperature",
    )

    platform.async_register_entity_service(
        "setback_heating", {}, "async_setback_heating"
    )

    platform.async_register_entity_service("set_home", {}, "async_set_home")

    platform.async_register_entity_service("set_away", {}, "async_set_away")


class HeatmiserClimate(CoordinatorEntity[HeatmiserCoordinator], ClimateEntity):
    """Climate object for a Heatmiser stat."""

    def __init__(self, coordinator: HeatmiserCoordinator, stat: HeatmiserStat) -> None:
        """Set up Heatmiser climate entity based on a stat."""
        super().__init__(coordinator)
        self._stat_name = stat.name
        self._stat_id = str(stat.id)
        self._stat_index = stat.id
        self.hub = coordinator.hub
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        self._hvac_modes = [HVACMode.HEAT, HVACMode.OFF]

    @property
    def stat(self) -> HeatmiserStat:
        """Return the latest data for this stat."""
        return self.coordinator.data[self._stat_name]

    @property
    def name(self):
        """Return the name of the thermostat, if any."""
        return self._stat_name

    @property
    def unique_id(self):
        """Return a unique ID."""
        return self._stat_id

    @property
    def native_temperature_unit(self):
        """Return the unit of measurement which this thermostat uses."""
        return UnitOfTemperature.CELSIUS

    @property
    def native_current_temperature(self):
        """Return the current temperature."""
        return self.stat.current_temperature

    @property
    def native_target_temperature(self):
        """Return the temperature we try to reach."""
        return self.stat.target_temperature

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return 1

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature."""
        await self.hub.set_temperature_async(self._stat_name, kwargs["temperature"])
        await self.coordinator.async_request_refresh()

    @property
    def hvac_action(self):
        """Return the current state."""
        return self.stat.current_state

    @property
    def hvac_mode(self):
        """Return current operation ie. heat, cool, idle."""
        return self.stat.hvac_mode

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available operation modes."""
        return self._hvac_modes

    async def async_turn_on(self):
        """Turn the heating on."""
        await self.hub.set_mode_async(self._stat_name, HVACMode.HEAT)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self):
        """Turn the heating off."""
        await self.hub.set_mode_async(self._stat_name, HVACMode.OFF)
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode) -> None:
        """Set HVAC mode."""
        await self.hub.set_mode_async(self._stat_name, hvac_mode)
        await self.coordinator.async_request_refresh()

    async def async_set_time(self) -> None:
        """Set the time."""
        await self.hub.set_time_async()

    async def async_boost_heating(self, temperature) -> None:
        """Boost the heating to a temperature."""
        await self.hub.boost_heating_async(self._stat_index, temperature)
        await self.coordinator.async_request_refresh()

    async def async_hold_temperature(self, temperature, time_period) -> None:
        """Hold a temperature for a period of time."""
        await self.hub.hold_temperature_async(self._stat_index, temperature, time_period)
        await self.coordinator.async_request_refresh()

    async def async_setback_heating(self) -> None:
        """Set the heating back."""
        await self.hub.setback_heating_async(self._stat_index)
        await self.coordinator.async_request_refresh()

    async def async_set_home(self) -> None:
        """Set home."""
        await self.hub.set_home_async()

    async def async_set_away(self) -> None:
        """Set away."""
        await self.hub.set_away_async()

    async def async_set_holiday(self, start_date_time, end_date_time) -> None:
        """Set a holiday."""
        await self.hub.set_holiday_async(start_date_time, end_date_time)

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
