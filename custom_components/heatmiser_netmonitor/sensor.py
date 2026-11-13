"""Comms statistics sensors for the Heatmiser NetMonitor integration."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HeatmiserConfigEntry, HeatmiserCoordinator
from .heatmiser_hub import HeatmiserStat


async def async_setup_entry(
    hass: HomeAssistant, entry: HeatmiserConfigEntry, async_add_entities
):
    """Set up a comms success-rate sensor for each stat."""
    coordinator = entry.runtime_data
    async_add_entities(HeatmiserCommsSensor(coordinator, stat) for stat in coordinator.stats)


class HeatmiserCommsSensor(CoordinatorEntity[HeatmiserCoordinator], SensorEntity):
    """Share of NetMonitor messages to a stat that got a reply."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:lan-check"

    def __init__(self, coordinator: HeatmiserCoordinator, stat: HeatmiserStat) -> None:
        """Set up the sensor for one stat."""
        super().__init__(coordinator)
        self._stat_name = stat.name
        self._attr_name = f"{stat.name} comms success"
        self._attr_unique_id = f"{stat.id}_comms_success"

    @property
    def _comms(self) -> dict | None:
        return self.coordinator.comms.get(self._stat_name)

    @property
    def available(self) -> bool:
        """Available once the counters have been read."""
        return super().available and self._comms is not None

    @property
    def native_value(self):
        """Return the NetMonitor's received/sent ratio as a percentage."""
        return self._comms["rate"] if self._comms else None

    @property
    def extra_state_attributes(self):
        """Return the raw counters."""
        if not self._comms:
            return None
        return {
            "address": self._comms["address"],
            "sent": self._comms["sent"],
            "received": self._comms["received"],
            "online": self._comms["online"],
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, "heatmiser_nermonitor")},
            name="Netmonitor",
            manufacturer="Heatmiser",
        )
