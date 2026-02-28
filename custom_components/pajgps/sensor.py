"""
Platform for GPS sensor integration.
Reads sensor, position, and elevation data from PajGpsCoordinator.
"""
from __future__ import annotations
import logging
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant import config_entries
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .coordinator import PajGpsCoordinator
_LOGGER = logging.getLogger(__name__)
class PajGPSVoltageSensor(CoordinatorEntity[PajGpsCoordinator], SensorEntity):
    """Voltage sensor reading from coordinator sensor_data."""
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "V"
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:flash"

    def __init__(self, pajgps_coordinator: PajGpsCoordinator, device_id: int) -> None:
        super().__init__(pajgps_coordinator)
        self._device_id = device_id
        device = next((d for d in pajgps_coordinator.data.devices if d.id == device_id), None)
        device_name = device.name if device and device.name else f"PAJ GPS {device_id}"
        self._attr_unique_id = f"pajgps_{pajgps_coordinator.entry_data['guid']}_{device_id}_voltage"
        self._attr_name = f"{device_name} Voltage"

    @property
    def device_info(self) -> DeviceInfo | None:
        return self.coordinator.get_device_info(self._device_id)

    @property
    def native_value(self) -> float | None:
        sd = self.coordinator.data.sensor_data.get(self._device_id)
        if sd is None or sd.volt is None:
            return None
        value = float(sd.volt / 1000.0)  # API gives millivolts, convert to volts
        return max(0.0, min(300.0, value))

class PajGPSBatterySensor(CoordinatorEntity[PajGpsCoordinator], SensorEntity):
    """Battery level sensor reading from coordinator positions."""
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    def __init__(self, pajgps_coordinator: PajGpsCoordinator, device_id: int) -> None:
        super().__init__(pajgps_coordinator)
        self._device_id = device_id
        device = next((d for d in pajgps_coordinator.data.devices if d.id == device_id), None)
        device_name = device.name if device and device.name else f"PAJ GPS {device_id}"
        self._attr_unique_id = f"pajgps_{pajgps_coordinator.entry_data['guid']}_{device_id}_battery"
        self._attr_name = f"{device_name} Battery Level"

    @property
    def device_info(self) -> DeviceInfo | None:
        return self.coordinator.get_device_info(self._device_id)

    @property
    def native_value(self) -> int | None:
        tp = self.coordinator.data.positions.get(self._device_id)
        if tp is None or tp.battery is None:
            return None
        return max(0, min(100, int(tp.battery)))

    @property
    def icon(self) -> str:
        level = self.native_value
        if level is None:
            return "mdi:battery-alert"
        if level == 100:
            return "mdi:battery"
        if level >= 90:
            return "mdi:battery-90"
        if level >= 80:
            return "mdi:battery-80"
        if level >= 70:
            return "mdi:battery-70"
        if level >= 60:
            return "mdi:battery-60"
        if level >= 50:
            return "mdi:battery-50"
        if level >= 40:
            return "mdi:battery-40"
        if level >= 30:
            return "mdi:battery-30"
        if level >= 20:
            return "mdi:battery-20"
        if level >= 10:
            return "mdi:battery-10"
        return "mdi:battery-alert"

class PajGPSSpeedSensor(CoordinatorEntity[PajGpsCoordinator], SensorEntity):
    """Speed sensor reading from coordinator positions."""
    _attr_device_class = SensorDeviceClass.SPEED
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "km/h"
    _attr_icon = "mdi:speedometer"
    def __init__(self, pajgps_coordinator: PajGpsCoordinator, device_id: int) -> None:
        super().__init__(pajgps_coordinator)
        self._device_id = device_id
        device = next((d for d in pajgps_coordinator.data.devices if d.id == device_id), None)
        device_name = device.name if device and device.name else f"PAJ GPS {device_id}"
        self._attr_unique_id = f"pajgps_{pajgps_coordinator.entry_data['guid']}_{device_id}_speed"
        self._attr_name = f"{device_name} Speed"

    @property
    def device_info(self) -> DeviceInfo | None:
        return self.coordinator.get_device_info(self._device_id)

    @property
    def native_value(self) -> float | None:
        tp = self.coordinator.data.positions.get(self._device_id)
        if tp is None or tp.speed is None:
            return None
        return max(0.0, min(1000.0, float(tp.speed)))

class PajGPSElevationSensor(CoordinatorEntity[PajGpsCoordinator], SensorEntity):
    """Elevation sensor reading from coordinator elevations."""
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "m"
    _attr_icon = "mdi:map-marker-up"
    _attr_suggested_display_precision = 1
    def __init__(self, pajgps_coordinator: PajGpsCoordinator, device_id: int) -> None:
        super().__init__(pajgps_coordinator)
        self._device_id = device_id
        device = next((d for d in pajgps_coordinator.data.devices if d.id == device_id), None)
        device_name = device.name if device and device.name else f"PAJ GPS {device_id}"
        self._attr_unique_id = f"pajgps_{pajgps_coordinator.entry_data['guid']}_{device_id}_elevation"
        self._attr_name = f"{device_name} Elevation"

    @property
    def device_info(self) -> DeviceInfo | None:
        return self.coordinator.get_device_info(self._device_id)

    @property
    def native_value(self) -> float | None:
        elevation = self.coordinator.data.elevations.get(self._device_id)
        if elevation is None:
            return None
        return max(0.0, min(10000.0, float(elevation)))

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
) -> None:
    """Set up PAJ GPS sensor entities from a config entry."""
    coordinator: PajGpsCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    fetch_elevation = config_entry.data.get("fetch_elevation", False)
    force_battery = config_entry.data.get("force_battery", False)
    entities = []
    for device in coordinator.data.devices:
        if device.id is None:
            continue
        entities.append(PajGPSSpeedSensor(coordinator, device.id))
        entities.append(PajGPSVoltageSensor(coordinator, device.id))
        # Battery: only if device model supports it or user forced it
        has_battery = getattr(device, "last_battery", None) is not None
        if has_battery or force_battery:
            entities.append(PajGPSBatterySensor(coordinator, device.id))
        if fetch_elevation:
            entities.append(PajGPSElevationSensor(coordinator, device.id))
    if entities:
        async_add_entities(entities)
    else:
        _LOGGER.warning("No PAJ GPS sensor entities to add")
