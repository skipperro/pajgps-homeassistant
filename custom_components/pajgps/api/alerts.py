"""
Low-level alerts data fetching and management for the PajGPS API.

Responsible for:
- Fetching unread alerts from the API
- Marking alerts as read (consuming)
- Enabling / disabling alert types per device
"""
import logging

from custom_components.pajgps.requests import make_request, ApiResponseError
from custom_components.pajgps.models import PajGPSAlert, PajGPSDevice

_LOGGER = logging.getLogger(__name__)

API_URL = "https://connect.paj-gps.de/api/v1/"

# Maps alert_type int → (field_name_on_device, attribute_name_on_PajGPSDevice)
_ALERT_TYPE_MAP: dict[int, tuple[str, str]] = {
    1:  ("alarmbewegung",          "alarm_shock_enabled"),
    2:  ("alarmakkuwarnung",       "alarm_battery_enabled"),
    4:  ("alarmsos",               "alarm_sos_enabled"),
    5:  ("alarmgeschwindigkeit",   "alarm_speed_enabled"),
    6:  ("alarmstromunterbrechung","alarm_power_cutoff_enabled"),
    7:  ("alarmzuendalarm",        "alarm_ignition_enabled"),
    9:  ("alarm_fall",             "alarm_drop_enabled"),
    13: ("alarm_volt",             "alarm_voltage_enabled"),
}


async def fetch_alerts(headers: dict) -> tuple[list[PajGPSAlert], dict | None]:
    """
    Fetch all unread alerts from the PajGPS API.

    Returns a tuple of (alerts, raw_json).
    On error returns ([], None).

    Corresponding CURL command:
    curl -X 'GET' 'https://connect.paj-gps.de/api/v1/notifications?isRead=0'
    """
    url = API_URL + "notifications"
    params = {"isRead": 0}
    raw_json = None
    try:
        raw_json = await make_request("GET", url, headers, params=params)
    except ApiResponseError as e:
        _LOGGER.error("Error while getting alerts data: %s", e)
        return [], None
    except TimeoutError:
        _LOGGER.warning("Timeout while getting alerts data")
        return [], None

    if not raw_json or "success" not in raw_json:
        return [], raw_json

    alerts = [
        PajGPSAlert(alert["iddevice"], alert["meldungtyp"])
        for alert in raw_json["success"]
    ]
    return alerts, raw_json


async def consume_alerts(alert_ids: list[int], headers: dict) -> None:
    """
    Mark the given alert types as read in the PajGPS API.

    Corresponding CURL command:
    curl -X 'PUT' \
      'https://connect.paj-gps.de/api/v1/notifications/markReadByCustomer?alertType=<ID>&isRead=1'
    """
    url = API_URL + "notifications/markReadByCustomer"
    for alert_id in alert_ids:
        params = {"alertType": alert_id, "isRead": 1}
        try:
            await make_request("PUT", url, headers, params=params)
            _LOGGER.debug("Alert %s marked as read", alert_id)
        except ApiResponseError as e:
            _LOGGER.error("Error while marking alert %s as read: %s", alert_id, e)
        except TimeoutError:
            _LOGGER.warning("Timeout while marking alerts as read")


async def change_alert_state(
    device: PajGPSDevice,
    alert_type: int,
    state: bool,
    headers: dict,
) -> None:
    """
    Enable or disable a specific alert type for a device via the PajGPS API.

    Also updates the in-memory device state so callers see the change immediately
    without waiting for the next full refresh.

    Corresponding CURL command:
    curl -X 'PUT' 'https://connect.paj-gps.de/api/v1/device/<DeviceID>' \
         -d '{"alarmsos": 1}'
    """
    if alert_type not in _ALERT_TYPE_MAP:
        _LOGGER.error("Unknown alert type: %s", alert_type)
        return

    alert_name, device_attr = _ALERT_TYPE_MAP[alert_type]
    setattr(device, device_attr, state)

    state_int = 1 if state else 0
    url = API_URL + "device/" + str(device.id)
    params = {alert_name: state_int}
    try:
        await make_request("PUT", url, headers, params=params)
        _LOGGER.debug("Alert %s for device %s set to %s", alert_name, device.id, state_int)
    except ApiResponseError as e:
        _LOGGER.error("Error while changing alert state: %s", e)
    except TimeoutError:
        _LOGGER.warning("Timeout while changing alert state")

