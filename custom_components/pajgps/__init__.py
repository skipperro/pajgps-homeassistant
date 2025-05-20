import logging

from homeassistant import config_entries, core
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .pajgps_data import PajGPSData
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
    entry.async_on_unload(
        entry.add_update_listener(_async_update_listener)
    )

    await async_initialize_data(entry)

    # Forward the setup to the device_tracker platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_initialize_data(entry: config_entries.ConfigEntry):
    """Initialize the PajGPS data object."""
    try:
        # Create a new PajGPSData object
        data = PajGPSData.get_instance(entry.data["guid"], entry.data["entry_name"], entry.data["email"], entry.data["password"], entry.data["mark_alerts_as_read"], entry.data["fetch_elevation"], entry.data["force_battery"])
        # Initialize the data object
        await data.async_update(True)
    except Exception as e:
        _LOGGER.error(f"Failed to initialize PajGPS data: {e}")

async def async_remove_config_entry_device(
    hass: core.HomeAssistant, config_entry: config_entries.ConfigEntry, device_entry
) -> bool:
    """Remove a device from the integration."""
    return True

    _LOGGER.warning("Device not found: %s", device_entry.id)
    return False

async def _async_update_listener(hass: HomeAssistant, config_entry):
    """Handle config options update."""
    # Reload the integration when the options change.
    await hass.config_entries.async_reload(config_entry.entry_id)

async def options_update_listener(
    hass: core.HomeAssistant, config_entry: config_entries.ConfigEntry
):
    """Handle options update."""
    await hass.config_entries.async_reload(config_entry.entry_id)

async def async_unload_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
