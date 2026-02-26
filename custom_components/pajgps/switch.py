"""
Platform for GPS alert switch integration.
Enables/disables alert types on PAJ GPS devices directly through the coordinator.
"""
from __future__ import annotations
import logging
from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant import config_entries
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, ALERT_NAMES, ALERT_TYPE_TO_DEVICE_FIELD
from .coordinator import PajGpsCoordinator
_LOGGER = logging.getLogger(__name__)
class PajGPSAlertSwitch(CoordinatorEntity[PajGpsCoordinator], SwitchEntity):
    """
    Switch entity that enables or disables an alert type on a PAJ GPS device.
    Write path: fires an immediate PUT via the coordinator (no queue, no delay),
    then updates the snapshot optimistically.  Server confirmation arrives with
    the next device-tier refresh (~300 s).
    """
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:bell-cog"
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
            f"pajgps_{pajgps_coordinator.entry_data['guid']}_{device_id}_switch_{alert_type}"
        )
        self._attr_name = f"{device_name} {alert_name} Switch"
    @property
    def device_info(self) -> DeviceInfo | None:
        return self.coordinator.get_device_info(self._device_id)
    @property
    def is_on(self) -> bool | None:
        device = next(
            (d for d in self.coordinator.data.devices if d.id == self._device_id), None
        )
        if device is None:
            return None
        field = ALERT_TYPE_TO_DEVICE_FIELD.get(self._alert_type)
        if field is None:
            return None
        return bool(getattr(device, field, False))
    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_update_alert_state(self._device_id, self._alert_type, True)
    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_update_alert_state(self._device_id, self._alert_type, False)
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
) -> None:
    """Set up PAJ GPS alert switch entities from a config entry."""
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
                entities.append(PajGPSAlertSwitch(coordinator, device.id, alert_type))
    if entities:
        async_add_entities(entities)
    else:
        _LOGGER.warning("No PAJ GPS alert switch entities to add")
