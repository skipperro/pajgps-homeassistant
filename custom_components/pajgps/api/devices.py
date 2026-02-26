"""
Low-level device data fetching from the PajGPS API.

Responsible for:
- Fetching the raw device list from the API
- Mapping the JSON response fields onto PajGPSDevice model instances
"""
import logging

from custom_components.pajgps.requests import make_request, ApiResponseError
from custom_components.pajgps.models import PajGPSDevice

_LOGGER = logging.getLogger(__name__)

API_URL = "https://connect.paj-gps.de/api/v1/"


def _parse_device(device: dict) -> PajGPSDevice | None:
    """Map a single raw API device dict onto a PajGPSDevice instance."""
    if not device.get("device_models"):
        _LOGGER.warning("Device %s has no device_models, skipping", device.get("id"))
        return None
    model = device["device_models"][0]
    device_data = PajGPSDevice(device["id"])
    device_data.name = device["name"]
    device_data.imei = device["imei"]
    device_data.model = model["model"]
    device_data.has_battery = model["standalone_battery"] == 1
    device_data.has_alarm_sos = model["alarm_sos"] == 1
    device_data.has_alarm_shock = model["alarm_erschuetterung"] == 1
    device_data.has_alarm_voltage = model["alarm_volt"] == 1
    device_data.has_alarm_battery = model["alarm_batteriestand"] == 1
    device_data.has_alarm_speed = model["alarm_geschwindigkeit"] == 1
    device_data.has_alarm_power_cutoff = model["alarm_stromunterbrechung"] == 1
    device_data.has_alarm_ignition = model["alarm_zuendalarm"] == 1
    device_data.has_alarm_drop = model["alarm_drop"] == 1
    device_data.alarm_sos_enabled = device["alarmsos"] == 1
    device_data.alarm_shock_enabled = device["alarmbewegung"] == 1
    device_data.alarm_voltage_enabled = device["alarm_volt"] == 1
    device_data.alarm_battery_enabled = device["alarmakkuwarnung"] == 1
    device_data.alarm_speed_enabled = device["alarmgeschwindigkeit"] == 1
    device_data.alarm_power_cutoff_enabled = device["alarmstromunterbrechung"] == 1
    device_data.alarm_ignition_enabled = device["alarmzuendalarm"] == 1
    device_data.alarm_drop_enabled = device["alarm_fall_enabled"] == 1
    return device_data


async def fetch_devices(headers: dict) -> tuple[list[PajGPSDevice], dict | None]:
    """
    Fetch all devices from the PajGPS API.

    Returns a tuple of (devices, raw_json).
    On error returns ([], None).

    Corresponding CURL command:
    curl -X 'GET' 'https://connect.paj-gps.de/api/v1/device'
    """
    url = API_URL + "device"
    raw_json = None
    try:
        raw_json = await make_request("GET", url, headers)
    except ApiResponseError as e:
        _LOGGER.error("Error while getting devices data: %s", e)
        return [], None
    except TimeoutError:
        _LOGGER.warning("Timeout while getting devices data")
        return [], None

    if not raw_json or "success" not in raw_json:
        return [], raw_json

    parsed = [_parse_device(device) for device in raw_json["success"]]
    return [d for d in parsed if d is not None], raw_json

