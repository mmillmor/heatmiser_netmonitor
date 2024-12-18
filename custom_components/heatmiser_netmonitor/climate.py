"""Climate module for the Heatmiser NetMonitor integration."""
import voluptuous as vol
import logging

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVACAction,
    HVACMode,
    ClimateEntityFeature
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import config_validation as cv, entity_platform

from .heatmiser_hub import HeatmiserHub, HeatmiserStat
from .const import DOMAIN
from pprint import pprint
_LOGGER = logging.getLogger(__name__)



def setup_platform(hass: HomeAssistant, config: ConfigType) -> None:
    """Set up the Heatmiser platform."""
    # Assign configuration variables.
    # The configuration check takes care they are present.
    host = config["host"]
    username = config["username"]
    password = config["password"]

    hub = HeatmiserHub(host, username, password, hass)
    hub.get_devices_async()


async def async_setup_entry(hass: HomeAssistant, config_entry , async_add_entities):
    """Set up Heatmiser climate based on config_entry."""
    host = config_entry.data.get("host")
    username = config_entry.data.get("username")
    password = config_entry.data.get("password")

    hub = HeatmiserHub(host, username, password, hass)
    devices = await hub.get_devices_async()
    entities = []
    if devices:
        for stat in devices:
            entities.append(HeatmiserClimate(stat, hub))
    async_add_entities(entities, True)

    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service(
        "set_system_time",
        {},
        "async_set_time",
    )

    platform.async_register_entity_service(
        "set_holiday",
        vol.All(
            cv.make_entity_service_schema(
                {
                    vol.Required("start_date_time"): cv.datetime,
                    vol.Required("end_date_time"): cv.datetime,
                },
            )
    ),
        "async_set_holiday",
    )

    platform.async_register_entity_service(
        "set_home",
        {},
        "async_set_home",
    )

    platform.async_register_entity_service(
        "set_away",
        {},
        "async_set_away",
    )

class HeatmiserClimate(ClimateEntity):
    """Climate object for a Heatmiser stat."""

    def __init__(self, stat: HeatmiserStat, hub: HeatmiserHub) -> None:
        """Set up Heatmiser climate entity based on a stat."""
        self._attr_supported_features = (ClimateEntityFeature(0) | ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF)
        self._hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
        self.stat = stat
        self.hub = hub
        self._enable_turn_on_off_backwards_compatibility = False

    @property
    def name(self):
        """Return the name of the thermostat, if any."""
        return self.stat.name

    @property
    def unique_id(self):
        """Return a unique ID."""
        return self.stat.id

    @property
    def temperature_unit(self):
        """Return the unit of measurement which this thermostat uses."""
        return UnitOfTemperature.CELSIUS

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self.stat.current_temperature

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self.stat.target_temperature

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return 1

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature."""
        await self.hub.set_temperature_async(self.stat.name, kwargs["temperature"])
        await self.async_update()

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
        await self.hub.set_mode_async(self.stat.name, HVACMode.HEAT)
        await self.async_update()

    async def async_turn_off(self):
        await self.hub.set_mode_async(self.stat.name, HVACMode.OFF)
        await self.async_update()

    async def async_set_hvac_mode(self, hvac_mode) -> None:
        """Set HVAC mode."""
        await self.hub.set_mode_async(self.stat.name, hvac_mode)
        await self.async_update()

    async def async_set_time(self) -> None:
        """Set the time."""
        await self.hub.set_time_async()

    async def async_set_home(self) -> None:
        """Set home."""
        await self.hub.set_home_async()

    async def async_set_away(self) -> None:
        """Set away."""
        await self.hub.set_away_async()

    async def async_set_holiday(self,start_date_time,end_date_time) -> None:
        """Set a holiday."""
        await self.hub.set_holiday_async(start_date_time,end_date_time)

    async def async_update(self) -> None:
        """Retrieve latest state."""
        new_stat_state = await self.hub.get_device_status_async(self.stat.name)
        if new_stat_state.current_temperature != None:
            new_stat_state.id = self.stat.id
            self.stat = new_stat_state

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
