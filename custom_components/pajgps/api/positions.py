"""
Low-level position and elevation data fetching from the PajGPS and Open-Meteo APIs.

Responsible for:
- Fetching last known positions for all devices
- Fetching elevation data from the Open-Meteo API for a given coordinate
- Detecting which devices have moved since the last update
"""
import logging

from custom_components.pajgps.requests import make_request, ApiResponseError
from custom_components.pajgps.models import PajGPSPositionData

_LOGGER = logging.getLogger(__name__)

API_URL = "https://connect.paj-gps.de/api/v1/"
ELEVATION_API_URL = "https://api.open-meteo.com/v1/elevation"


async def fetch_positions(device_ids: list[int], headers: dict) -> tuple[list[PajGPSPositionData], dict | None]:
    """
    Fetch the last known position for every device in device_ids.

    Returns a tuple of (positions, raw_json).
    On error returns ([], None).

    Corresponding CURL command:
    curl -X 'POST' \
      'https://connect.paj-gps.de/api/v1/trackerdata/getalllastpositions' \
      -d '{"deviceIDs": [<ids>], "fromLastPoint": false}'
    """
    url = API_URL + "trackerdata/getalllastpositions"
    payload = {"deviceIDs": device_ids, "fromLastPoint": False}
    raw_json = None
    try:
        raw_json = await make_request("POST", url, headers, payload=payload)
    except ApiResponseError as e:
        _LOGGER.error("Error while getting tracking data: %s", e)
        return [], None
    except TimeoutError:
        _LOGGER.warning("Timeout while getting tracking data")
        return [], None
    except KeyError as e:
        _LOGGER.error("Missing key in tracking data response: %s", e)
        return [], None

    if not raw_json or "success" not in raw_json:
        _LOGGER.error("Unexpected response format in tracking data: %s", raw_json)
        return [], raw_json

    positions = [
        PajGPSPositionData(
            device["iddevice"],
            device["lat"],
            device["lng"],
            device["direction"],
            device["speed"],
            device["battery"],
        )
        for device in raw_json["success"]
    ]
    return positions, raw_json


async def fetch_elevation(device_id: int, position: PajGPSPositionData) -> float | None:
    """
    Fetch the elevation (in metres) for the given position from the Open-Meteo API.

    Rounds lat/lng to ~100 m precision before the request to improve cache hit rate.
    Returns None on any error.

    Example request:
    https://api.open-meteo.com/v1/elevation?latitude=52.52&longitude=13.41
    """
    # Round to about 100 metres precision to improve cache hit rate on the remote API
    lat = round(position.lat, 5)
    lng = round(position.lng, 5)
    params = {"latitude": lat, "longitude": lng}
    headers = {"accept": "application/json"}

    raw_json = None
    try:
        raw_json = await make_request("GET", ELEVATION_API_URL, headers, params=params)
    except TimeoutError:
        _LOGGER.warning(
            "Timeout while getting elevation data for device %s at (%s, %s)",
            device_id, lat, lng,
        )
        return None
    except ValueError as e:
        _LOGGER.warning(
            "Failed to get elevation for device %s at (%s, %s): %s",
            device_id, lat, lng, e,
        )
        return None
    except Exception as e:
        _LOGGER.error(
            "Unexpected error while getting elevation for device %s at (%s, %s): %s: %s",
            device_id, lat, lng, type(e).__name__, e,
        )
        return None

    if raw_json and "elevation" in raw_json:
        return raw_json["elevation"][0]

    _LOGGER.warning(
        "Unexpected elevation response format for device %s at (%s, %s): %s",
        device_id, lat, lng, raw_json,
    )
    return None


def find_moved_device_ids(
    new_positions: list[PajGPSPositionData],
    old_positions: list[PajGPSPositionData],
) -> list[int]:
    """
    Return device IDs whose lat/lng changed compared to the previous update,
    or whose elevation has never been fetched.
    """
    old_by_id = {p.device_id: p for p in old_positions}
    moved = []
    for new in new_positions:
        old = old_by_id.get(new.device_id)
        if old is None:
            continue
        if old.lat != new.lat or old.lng != new.lng or new.elevation is None:
            moved.append(new.device_id)
    return moved

