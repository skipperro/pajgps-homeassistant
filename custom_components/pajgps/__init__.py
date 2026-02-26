import logging

from homeassistant import config_entries, core
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .coordinator import PajGpsCoordinator
from .const import DOMAIN

PLATFORMS: list[Platform] = [Platform.DEVICE_TRACKER, Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH]
_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: core.HomeAssistant, config: dict) -> bool:
    """Set up the integration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Set up platform from a ConfigEntry."""
    hass.data.setdefault(DOMAIN, {})

    pajgps_coordinator = PajGpsCoordinator(hass, dict(entry.data))
    try:
        await pajgps_coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        raise
    except Exception as exc:
        raise ConfigEntryNotReady(f"Failed to connect to PAJ GPS: {exc}") from exc

    hass.data[DOMAIN][entry.entry_id] = pajgps_coordinator

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_remove_config_entry_device(
    hass: core.HomeAssistant, config_entry: config_entries.ConfigEntry, device_entry
) -> bool:
    """Remove a device from the integration."""
    return True


async def _async_update_listener(hass: HomeAssistant, config_entry: config_entries.ConfigEntry) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Unload a config entry."""
    pajgps_coordinator: PajGpsCoordinator | None = hass.data[DOMAIN].pop(entry.entry_id, None)
    if pajgps_coordinator is not None:
        await pajgps_coordinator.async_shutdown()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)