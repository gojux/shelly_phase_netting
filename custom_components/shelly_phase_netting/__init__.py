from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, PLATFORMS, STORE_VERSION, store_key
from .coordinator import ShellyPhaseNettingCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = ShellyPhaseNettingCoordinator(hass, entry)
    try:
        await coordinator.async_initialize()
    except BaseException:
        await hass.async_add_executor_job(coordinator.api.close)
        raise
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(coordinator.async_add_listener(coordinator.async_schedule_history_import))
    coordinator.async_schedule_history_import()
    return True


async def _async_reload_on_update(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply changed options (e.g. the polling interval)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await hass.async_add_executor_job(coordinator.api.close)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the persisted cursor and totals together with the config entry."""
    await Store(hass, STORE_VERSION, store_key(entry.entry_id)).async_remove()
