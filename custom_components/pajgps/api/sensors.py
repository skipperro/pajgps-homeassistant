"""
Low-level sensor data fetching from the PajGPS API.

Responsible for:
- Fetching voltage sensor data per device
- Converting raw millivolt values to volts
"""
import logging

from custom_components.pajgps.requests import make_request, ApiResponseError
from custom_components.pajgps.models import PajGPSDevice, PajGPSSensorData

_LOGGER = logging.getLogger(__name__)

API_URL = "https://connect.paj-gps.de/api/v1/"


async def fetch_sensors(devices: list[PajGPSDevice], headers: dict) -> list[PajGPSSensorData]:
    """
    Fetch sensor data for every device in the supplied list.

    Returns a list of PajGPSSensorData, one entry per device.
    Voltage defaults to 0.0 on error or missing data.

    Corresponding CURL command:
    curl -X 'GET' 'https://connect.paj-gps.de/api/v1/sensordata/last/{DeviceID}'
    """
    new_sensors = []

    for device in devices:
        sensor_data = PajGPSSensorData()
        sensor_data.device_id = device.id
        sensor_data.voltage = await _fetch_device_voltage(device.id, headers)
        new_sensors.append(sensor_data)

    return new_sensors


async def _fetch_device_voltage(device_id: int, headers: dict) -> float:
    """
    Fetch the voltage for a single device and convert millivolts → volts.

    Returns 0.0 on any error or absent data.
    """
    url = API_URL + f"sensordata/last/{device_id}"
    try:
        raw_json = await make_request("GET", url, headers)
    except ApiResponseError as e:
        _LOGGER.error("Error while getting sensor data for device %s: %s", device_id, e)
        return 0.0
    except TimeoutError:
        _LOGGER.warning("Timeout while getting sensor data for device %s", device_id)
        return 0.0

    if raw_json and "success" in raw_json and "volt" in raw_json["success"]:
        # Convert from millivolts to volts and round to 1 decimal place
        return round(raw_json["success"]["volt"] / 1000, 1)

    _LOGGER.debug("No sensor data for device %s", device_id)
    return 0.0

