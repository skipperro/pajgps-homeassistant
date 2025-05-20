"""
Platform for GPS sensor integration.
This module is responsible for setting up the battery level and speed sensor entities
and updating their state based on the data received from the Paj GPS API.
"""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant import config_entries
from homeassistant.helpers.entity import DeviceInfo

from custom_components.pajgps.const import DOMAIN, VERSION, ALERT_NAMES
from custom_components.pajgps.pajgps_data import PajGPSData
import logging

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)

class PajGPSAlertSensor(BinarySensorEntity):
    """
    Representation of a Paj GPS alert sensor.
    Takes the data from base PajGPSData object created in async_setup_entry.
    """
    _pajgps_data = None
    _device_id = None
    _alert_type: int = 0
    _state: bool = False

    def __init__(self, pajgps_data: PajGPSData, device_id: int, alert_type) -> None:
        """Initialize the sensor."""
        self._pajgps_data = pajgps_data
        self._device_id = device_id
        self._alert_type = alert_type
        alert_name = ALERT_NAMES.get(alert_type, "Unknown Alert")
        self._device_name = f"{self._pajgps_data.get_device(device_id).name}"
        self._attr_unique_id = f"pajgps_{self._pajgps_data.guid}_{self._device_id}_alert_{self._alert_type}"
        self._attr_name = f"{self._device_name} {alert_name}"
        self._attr_icon = "mdi:bell"

    async def async_update(self) -> None:
        """Update the sensor state."""
        await self._pajgps_data.async_update()
        alerts = self._pajgps_data.get_alerts(self._device_id)
        self._state = False
        if alerts is not None:
            for alert in alerts:
                if alert.device_id == self._device_id and alert.alert_type == self._alert_type:
                    self._state = True
                    break

    @property
    def icon(self) -> str | None:
        """Return the icon of the sensor."""
        if self._state:
            return "mdi:bell-alert"
        return "mdi:bell"

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
    def device_class(self) -> BinarySensorDeviceClass | str | None:
        return BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool | None:
        """Return if the binary sensor is on."""
        # This needs to enumerate to true or false
        return self._state

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

    # Add the Paj GPS alert sensors to the entity registry
    devices = pajgps_data.get_device_ids()
    if devices is not None:
        _LOGGER.debug("Devices found: %s", devices)
        entities = []
        for device_id in devices:
            device = pajgps_data.get_device(device_id)
            if device is not None:
                if device.has_alarm_shock:
                    entities.append(PajGPSAlertSensor(pajgps_data, device_id, 1))
                if device.has_alarm_battery:
                    entities.append(PajGPSAlertSensor(pajgps_data, device_id, 2))
                if device.has_alarm_sos:
                    entities.append(PajGPSAlertSensor(pajgps_data, device_id, 4))
                if device.has_alarm_speed:
                    entities.append(PajGPSAlertSensor(pajgps_data, device_id, 5))
                if device.has_alarm_power_cutoff:
                    entities.append(PajGPSAlertSensor(pajgps_data, device_id, 6))
                if device.has_alarm_ignition:
                    entities.append(PajGPSAlertSensor(pajgps_data, device_id, 7))
                if device.has_alarm_drop:
                    entities.append(PajGPSAlertSensor(pajgps_data, device_id, 9))
                if device.has_alarm_voltage:
                    entities.append(PajGPSAlertSensor(pajgps_data, device_id, 13))

        if entities and async_add_entities:
            async_add_entities(entities, update_before_add=True)
    else:
        _LOGGER.error("No devices found for entry: %s", entry_name)

