"""
Platform for GPS binary sensor (alert) integration.
Reads notification data from PajGpsCoordinator to expose triggered alerts.
"""
from __future__ import annotations
import logging
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant import config_entries
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, ALERT_NAMES
from .coordinator import PajGpsCoordinator
_LOGGER = logging.getLogger(__name__)
class PajGPSAlertSensor(CoordinatorEntity[PajGpsCoordinator], BinarySensorEntity):
    """Binary sensor that is ON when an unread notification of a given type exists."""
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    def __init__(
        self, pajgps_coordinator: PajGpsCoordinator, device_id: int, alert_type: int
    ) -> None:
        super().__init__(pajgps_coordinator)
        self._device_id = device_id
        self._alert_type = alert_type
        alert_name = ALERT_NAMES.get(alert_type, "Unknown Alert")
        device = next((d for d in pajgps_coordinator.data.devices if d.id == device_id), None)
        device_name = device.name if device and device.name else f"PAJ GPS {device_id}"
        self._attr_unique_id = (
            f"pajgps_{pajgps_coordinator.entry_data['guid']}_{device_id}_alert_{alert_type}"
        )
        self._attr_name = f"{device_name} {alert_name}"
    @property
    def device_info(self) -> DeviceInfo | None:
        return self.coordinator.get_device_info(self._device_id)
    @property
    def is_on(self) -> bool:
        notifications = self.coordinator.data.notifications.get(self._device_id, [])
        return any(n.meldungtyp == self._alert_type for n in notifications)
    @property
    def icon(self) -> str:
        return "mdi:bell-alert" if self.is_on else "mdi:bell"
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
) -> None:
    """Set up PAJ GPS binary sensor (alert) entities from a config entry."""
    coordinator: PajGpsCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    # Maps alarm capability field → alert_type int
    alarm_fields = [
        ("alarmbewegung", 1),           # Shock
        ("alarmakkuwarnung", 2),         # Battery
        ("alarmsos", 4),                 # SOS
        ("alarmgeschwindigkeit", 5),     # Speed
        ("alarmstromunterbrechung", 6),  # Power cut-off
        ("alarmzuendalarm", 7),          # Ignition
        ("alarm_fall_enabled", 9),       # Drop
        ("alarm_volt", 13),              # Voltage
    ]
    entities = []
    for device in coordinator.data.devices:
        if device.id is None:
            continue
        for field, alert_type in alarm_fields:
            if getattr(device, field, None):
                entities.append(PajGPSAlertSensor(coordinator, device.id, alert_type))
    if entities:
        async_add_entities(entities)
    else:
        _LOGGER.warning("No PAJ GPS alert entities to add")
