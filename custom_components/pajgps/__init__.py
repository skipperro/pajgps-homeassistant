import asyncio
import logging

from homeassistant import config_entries, core
from homeassistant.const import Platform
from homeassistant.helpers.device_registry import async_get as async_get_device_registry

from .const import DOMAIN

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.DEVICE_TRACKER, Platform.BINARY_SENSOR]
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
    hass_data = dict(entry.data)

    # Register update listener to update config entry when options are updated.
    unsub_options_update_listener = entry.add_update_listener(options_update_listener)
    hass_data["unsub_options_update_listener"] = unsub_options_update_listener
    hass.data[DOMAIN][entry.entry_id] = hass_data

    # Forward the setup to the device_tracker platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_remove_config_entry_device(
    hass: core.HomeAssistant, config_entry: config_entries.ConfigEntry, device_entry
) -> bool:
    """Remove a device from the integration."""
    _LOGGER.debug("Removing device: %s", device_entry.id)

    device_registry = async_get_device_registry(hass)
    device = device_registry.async_get(device_entry.id)

    if device:
        # Iterate over entities linked to the device and remove them
        for identifier in device.identifiers:
            if identifier[0] == DOMAIN:
                _LOGGER.debug("Removing entity for identifier: %s", identifier)
                # Perform any necessary cleanup here if required
                # For example, delete entity state, remove external data references, etc.

        # Remove the device itself from the registry
        device_registry.async_remove_device(device_entry.id)
        _LOGGER.debug("Device removed successfully")
        return True

    _LOGGER.warning("Device not found: %s", device_entry.id)
    return False

async def options_update_listener(
    hass: core.HomeAssistant, config_entry: config_entries.ConfigEntry
):
    """Handle options update."""
    await hass.config_entries.async_reload(config_entry.entry_id)

async def async_unload_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[hass.config_entries.async_forward_entry_unload(entry, "device_tracker")]
        )
    )
    # Remove options_update_listener.
    hass.data[DOMAIN][entry.entry_id]["unsub_options_update_listener"]()

    # Remove config entry from domain.
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
