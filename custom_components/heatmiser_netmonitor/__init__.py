"""The Heatmiser NetMonitor integration."""
from __future__ import annotations

import requests

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from .coordinator import HeatmiserConfigEntry, HeatmiserCoordinator
from .heatmiser_hub import HeatmiserHub

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.WATER_HEATER]


async def async_setup_entry(hass: HomeAssistant, entry: HeatmiserConfigEntry) -> bool:
    """Set up Heatmiser NetMonitor from a config entry."""
    conf = {**entry.data, **entry.options}
    hub = HeatmiserHub(conf["host"], conf["username"], conf["password"], hass)

    try:
        stats = await hub.get_devices_async()
    except (requests.RequestException, IndexError, ValueError) as err:
        raise ConfigEntryNotReady(f"Cannot reach NetMonitor: {err}") from err

    coordinator = HeatmiserCoordinator(hass, entry, hub, stats)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Older versions used the integer stat index as the unique_id.
    await er.async_migrate_entries(hass, entry.entry_id, _async_migrate_unique_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Reload when the options flow saves new connection details.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


@callback
def _async_migrate_unique_id(entity_entry: er.RegistryEntry) -> dict[str, str] | None:
    """Convert integer unique IDs to strings, keeping the same entities."""
    if isinstance(entity_entry.unique_id, str):
        return None
    return {"new_unique_id": str(entity_entry.unique_id)}


async def _async_update_listener(
    hass: HomeAssistant, entry: HeatmiserConfigEntry
) -> None:
    """Reload the entry after options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HeatmiserConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
