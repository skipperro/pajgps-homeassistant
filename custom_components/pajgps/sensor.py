"""
Platform for GPS sensor integration.
This module is responsible for setting up the battery level and speed sensor entities
and updating their state based on the data received from the Paj GPS API.
"""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant import config_entries
from homeassistant.helpers.entity import DeviceInfo

from custom_components.pajgps.const import DOMAIN, VERSION
from custom_components.pajgps.pajgps_data import PajGPSData
import logging

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)

class PajGPSBatterySensor(SensorEntity):
    """
    Representation of a Paj GPS battery level sensor.
    Takes the data from base PajGPSData object created in async_setup_entry.
    """
    _pajgps_data = None
    _device_id = None
    _battery_level: int | None = None

    def __init__(self, pajgps_data: PajGPSData, device_id: int) -> None:
        """Initialize the sensor."""
        self._pajgps_data = pajgps_data
        self._device_id = device_id
        self._device_name = f"{self._pajgps_data.get_device(device_id).name}"
        self._attr_unique_id = f"pajgps_{self._pajgps_data.guid}_{self._device_id}_battery"
        self._attr_name = f"{self._device_name} Battery Level"
        self._attr_icon = "mdi:battery"

    async def async_update(self) -> None:
        """Update the sensor state."""
        try:
            await self._pajgps_data.async_update()
            position_data = self._pajgps_data.get_position(self._device_id)
            if position_data is not None:
                if position_data.battery is not None:
                    self._battery_level = position_data.battery
                else:
                    self._battery_level = None
        except Exception as e:
            _LOGGER.error("Error updating battery sensor: %s", e)
            self._battery_level = None

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
    def device_class(self) -> SensorDeviceClass | str | None:
        return SensorDeviceClass.BATTERY

    @property
    def state_class(self) -> SensorStateClass | str | None:
        return SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | None:
        if self._battery_level is not None:
            new_value = int(self._battery_level)
            # Make sure value is between 0 and 100
            if new_value < 0:
                new_value = 0
            elif new_value > 100:
                new_value = 100
            return new_value
        else:
            return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        return "%"

    @property
    def icon(self) -> str | None:
        """Set the icon based on battery level in 10% increments."""
        battery_level = self._battery_level
        if battery_level is not None:
            if battery_level == 100:
                return "mdi:battery"
            elif battery_level >= 90:
                return "mdi:battery-90"
            elif battery_level >= 80:
                return "mdi:battery-80"
            elif battery_level >= 70:
                return "mdi:battery-70"
            elif battery_level >= 60:
                return "mdi:battery-60"
            elif battery_level >= 50:
                return "mdi:battery-50"
            elif battery_level >= 40:
                return "mdi:battery-40"
            elif battery_level >= 30:
                return "mdi:battery-30"
            elif battery_level >= 20:
                return "mdi:battery-20"
            elif battery_level >= 10:
                return "mdi:battery-10"
            else:
                return "mdi:battery-alert"
        else:
            return "mdi:battery-alert"

class PajGPSSpeedSensor(SensorEntity):
    """
    Representation of a Paj GPS speed sensor.
    Takes the data from base PajGPSData object created in async_setup_entry.
    """
    _pajgps_data = None
    _device_id = None
    _speed: float | None = None

    def __init__(self, pajgps_data: PajGPSData, device_id: int) -> None:
        """Initialize the sensor."""
        self._pajgps_data = pajgps_data
        self._device_id = device_id
        self._device_name = f"{self._pajgps_data.get_device(device_id).name}"
        self._attr_unique_id = f"pajgps_{self._pajgps_data.guid}_{self._device_id}_speed"
        self._attr_name = f"{self._device_name} Speed"
        self._attr_icon = "mdi:speedometer"

    async def async_update(self) -> None:
        """Update the sensor state."""
        try:
            await self._pajgps_data.async_update()
            position_data = self._pajgps_data.get_position(self._device_id)
            if position_data is not None:
                if position_data.speed is not None:
                    self._speed = position_data.speed
                else:
                    self._speed = None
        except Exception as e:
            _LOGGER.error("Error updating speed sensor: %s", e)
            self._speed = None

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
    def device_class(self) -> SensorDeviceClass | str | None:
        return SensorDeviceClass.SPEED

    @property
    def state_class(self) -> SensorStateClass | str | None:
        return SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float | None:
        if self._speed is not None:
            new_value = float(self._speed)
            # Make sure value is between 0 and 1000
            if new_value < 0.0:
                new_value = 0.0
            elif new_value > 1000.0:
                new_value = 1000.0
            return new_value
        else:
            return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        return "km/h"

class PajGPSElevationSensor(SensorEntity):
    """
    Representation of a Paj GPS elevation sensor.
    Takes the data from base PajGPSData object created in async_setup_entry.
    """
    _pajgps_data = None
    _device_id = None
    _elevation: float | None = None

    def __init__(self, pajgps_data: PajGPSData, device_id: int) -> None:
        """Initialize the sensor."""
        self._pajgps_data = pajgps_data
        self._device_id = device_id
        self._device_name = f"{self._pajgps_data.get_device(device_id).name}"
        self._attr_unique_id = f"pajgps_{self._pajgps_data.guid}_{self._device_id}_elevation"
        self._attr_name = f"{self._device_name} Elevation"
        self._attr_icon = "mdi:map-marker-up"

    async def async_update(self) -> None:
        """Update the sensor state."""
        try:
            await self._pajgps_data.async_update()
            position_data = self._pajgps_data.get_position(self._device_id)
            if position_data is not None:
                if position_data.elevation is not None:
                    self._elevation = position_data.elevation
                else:
                    self._elevation = None
        except Exception as e:
            _LOGGER.error("Error updating elevation sensor: %s", e)
            self._elevation = None

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
    def device_class(self) -> SensorDeviceClass | str | None:
        return SensorDeviceClass.DISTANCE

    @property
    def state_class(self) -> SensorStateClass | str | None:
        return SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float | None:
        if self._elevation is not None:
            new_value = float(self._elevation)
            # Make sure value is between 0 and 10000
            if new_value < 0.0:
                new_value = 0.0
            elif new_value > 10000.0:
                new_value = 10000.0
            return new_value
        else:
            return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        return "m"


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

    # Add the Paj GPS sensors to the entity registry
    devices = pajgps_data.get_device_ids()
    if devices is not None:
        _LOGGER.debug("Devices found: %s", devices)
        entities = []
        for device_id in devices:
            entities.append(PajGPSSpeedSensor(pajgps_data, device_id))
            # Check if this device model supports battery
            if pajgps_data.get_device(device_id).has_battery or pajgps_data.force_battery:
                entities.append(PajGPSBatterySensor(pajgps_data, device_id))
            # Check if user wants to get elevation
            if pajgps_data.fetch_elevation:
                entities.append(PajGPSElevationSensor(pajgps_data, device_id))

        if entities and async_add_entities:
            async_add_entities(entities, update_before_add=True)
    else:
        _LOGGER.error("No devices found for entry: %s", entry_name)

