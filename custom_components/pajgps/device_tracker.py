"""
Platform for GPS sensor integration.
This module is responsible for setting up the GPS sensor entities
and updating their state based on the data received from the Paj GPS API.
"""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant import config_entries
from homeassistant.helpers.entity import DeviceInfo

from custom_components.pajgps.const import DOMAIN, VERSION
from custom_components.pajgps.pajgps_data import PajGPSData
import logging

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)

class PajGPSPositionSensor(TrackerEntity):
    """
    Representation of a Paj GPS position sensor.
    Takes the data from base PajGPSData object created in async_setup_entry.
    """
    _pajgps_data = None
    _device_id = None
    _longitude: float | None = None
    _latitude: float | None = None

    def __init__(self, pajgps_data: PajGPSData, device_id: int) -> None:
        """Initialize the sensor."""
        self._pajgps_data = pajgps_data
        self._device_id = device_id
        self._device_name = f"{self._pajgps_data.get_device(device_id).name}"
        self._attr_unique_id = f"pajgps_{self._pajgps_data.guid}_{self._device_id}_gps"
        self._attr_name = f"{self._device_name} Location"
        self._attr_icon = "mdi:map-marker"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return the device info."""
        if self._pajgps_data is None:
            return None
        return self._pajgps_data.get_device_info(self._device_id)

    @property
    def should_poll(self) -> bool:
        return True

    @property
    def latitude(self) -> float | None:
        """Return latitude value of the device."""
        if self._latitude is not None:
            return self._latitude
        else:
            return None

    @property
    def longitude(self) -> float | None:
        """Return longitude value of the device."""
        if self._longitude is not None:
            return self._longitude
        else:
            return None


    @property
    def source_type(self) -> str:
        """Return the source type, eg gps or router, of the device."""
        return "gps"

    async def async_update(self) -> None:
        """Update the GPS sensor data."""
        await self._pajgps_data.async_update()
        position_data = self._pajgps_data.get_position(self._device_id)
        if position_data is not None:
            if position_data.lat is not None and position_data.lng is not None:
                self._latitude = position_data.lat
                self._longitude = position_data.lng
            else:
                self._latitude = None
                self._longitude = None
        else:
            self._latitude = None
            self._longitude = None

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
):
    """Add sensors for passed config_entry in HA."""
    _LOGGER.debug("Starting setup for PAJ GPS integration")

    # Get the entry name
    entry_name = config_entry.data.get("entry_name", "My Paj GPS account")

    # Validate email and password
    guid = config_entry.data.get("guid")
    email = config_entry.data.get("email")
    password = config_entry.data.get("password")
    mark_alerts_as_read = config_entry.data.get("mark_alerts_as_read", True)
    if not email or not password:
        _LOGGER.error("Email or password not set in config entry")
        return

    fetch_elevation = config_entry.data.get("fetch_elevation", False)
    force_battery = config_entry.data.get("force_battery", False)

    # Create main Paj GPS data object from pajgps_data.py
    pajgps_data = PajGPSData.get_instance(guid, entry_name, email, password, mark_alerts_as_read, fetch_elevation, force_battery)

    # Update the data
    await pajgps_data.async_update()

    # Add the Paj GPS position sensors to the entity registry
    devices = pajgps_data.get_device_ids()
    if devices is not None:
        _LOGGER.debug("Adding Paj GPS position sensors")
        entities = []
        for device_id in devices:
            entities.append(PajGPSPositionSensor(pajgps_data, device_id))
        if entities and async_add_entities:
            async_add_entities(entities, update_before_add=True)
        else:
            _LOGGER.warning("No new Paj GPS devices to add")


