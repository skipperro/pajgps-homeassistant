"""Platform for sensor integration."""
from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant import config_entries
from homeassistant.helpers.entity import DeviceInfo

from custom_components.pajgps.const import DOMAIN
import asyncio
import aiohttp
import logging

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)
API_URL = "https://connect.paj-gps.de/api/v1/"
VERSION = "0.5.0"

TOKEN = None
TOKEN_REFRESH_LOCK = asyncio.Lock()
LAST_TOKEN_REFRESH = None


class LoginResponse:
    token = None
    userID = None
    routeIcon = None

    def __init__(self, json):
        self.token = json["success"]["token"]
        self.userID = json["success"]["userID"]
        self.routeIcon = json["success"]["routeIcon"]

    def __str__(self):
        return f"token: {self.token}, userID: {self.userID}, routeIcon: {self.routeIcon}"


class ApiError:
    error = None
    def __init__(self, json):
        self.error = json["error"]


class PajGpsTrackerData:
    # From JSON:
    # {
    #       "lat": 49.02193166666667,
    #       "lng": 12.656183333333333,
    #       "direction": 0,
    #       "battery": 70,
    #       "speed": 0,
    #       "iddevice": 1237050,
    #       "accuracy": 0
    #     }
    lat = None
    lng = None
    direction = None
    battery = None
    speed = None
    iddevice = None
    accuracy = None

    def __init__(self, json):
        self.lat = json["lat"]
        self.lng = json["lng"]
        self.direction = json["direction"]
        self.battery = json["battery"]
        self.speed = json["speed"]
        self.iddevice = json["iddevice"]
        self.accuracy = json["accuracy"]

    def __str__(self):
        return f"lat: {self.lat}, lng: {self.lng}, direction: {self.direction}, battery: {self.battery}, speed: {self.speed}, iddevice: {self.iddevice}"

# Battery sensor reading data from GPS sensor battery_level attribute
class PajGpsBatterySensor(SensorEntity):

    gpssensor: PajGpsSensor = None
    def __init__(self, gpssensor: PajGpsSensor):
        self.gpssensor = gpssensor
        self._attr_icon = "mdi:battery"
        self._attr_name = f"PAJ GPS {self.gpssensor._gps_id} Battery Level"
        self._attr_unique_id = f'pajgps_{self.gpssensor._gps_id}_battery'
        self._attr_extra_state_attributes = {}

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return the device info."""
        return {
            "identifiers": {(DOMAIN, self.gpssensor._gps_id)},
        }

    @property
    def device_class(self) -> SensorDeviceClass | str | None:
        return SensorDeviceClass.BATTERY

    @property
    def state_class(self) -> SensorStateClass | str | None:
        return SensorStateClass.MEASUREMENT

    @property
    def native_value (self) -> int | None:
        if self.gpssensor.battery_level is not None:
            new_value = int(self.gpssensor.battery_level)
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
    def should_poll(self) -> bool:
        return True

    @property
    def icon(self) -> str | None:
        battery_level = self.native_value
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


# Speed sensor reading data from GPS sensor speed attribute
class PajGpsSpeedSensor(SensorEntity):

    gpssensor: PajGpsSensor = None
    def __init__(self, gpssensor: PajGpsSensor):
        self.gpssensor = gpssensor
        self._attr_icon = "mdi:speedometer"
        self._attr_name = f"PAJ GPS {self.gpssensor._gps_id} Speed"
        self._attr_unique_id = f'pajgps_{self.gpssensor._gps_id}_speed'
        self._attr_extra_state_attributes = {}

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return the device info."""
        return {
            "identifiers": {(DOMAIN, self.gpssensor._gps_id)},
        }

    @property
    def native_value (self) -> int | None:
        if self.gpssensor.speed is not None:
            new_value = int(self.gpssensor.speed)
            # Make sure value is between 0 and 1000
            if new_value < 0:
                new_value = 0
            elif new_value > 1000:
                new_value = 1000
            return new_value
        else:
            return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        return "km/h"

    @property
    def should_poll(self) -> bool:
        return True


# Define a GPS tracker sensor/device class for Home Assistant
class PajGpsSensor(TrackerEntity):

    _last_data = None

    def __init__(self, gps_id: str, imei: str, model: str, has_battery: bool, token: str):
        self._gps_id = gps_id
        self._token = token
        self._attr_icon = "mdi:map-marker"
        self._attr_name = f"PAJ GPS {self._gps_id}"
        self._attr_unique_id = f'pajgps_{gps_id}'
        self._attr_extra_state_attributes = {}

        self._imei = imei
        self._model = model
        self._has_battery = has_battery


    @property
    def device_info(self) -> DeviceInfo | None:
        """Return the device info."""
        return {
            "identifiers": {(DOMAIN, self._gps_id)},
            "name": self._attr_name,
            "manufacturer": "PAJ GPS",
            "model": self._model,
            "sw_version": VERSION,
        }

    @property
    def should_poll(self) -> bool:
        return True

    @property
    def latitude(self) -> float | None:
        """Return latitude value of the device."""
        # If _last_data is not None, return latitude from _last_data. Else return None.
        if self._last_data is not None:
            return self._last_data.lat
        else:
            return None

    @property
    def longitude(self) -> float | None:
        """Return longitude value of the device."""
        # If _last_data is not None, return longitude from _last_data. Else return None.
        if self._last_data is not None:
            return self._last_data.lng
        else:
            return None

    @property
    def battery_level(self) -> int | None:
        """Return the battery level of the device."""
        # If _last_data is not None, return battery level from _last_data. Else return None.
        if self._last_data is not None:
            return self._last_data.battery
        else:
            return None

    @property
    def source_type(self) -> str:
        """Return the source type, eg gps or router, of the device."""
        return "gps"

    @property
    def speed(self) -> int | None:
        """Return the speed of the device."""
        # If _last_data is not None, return speed from _last_data. Else return None.
        if self._last_data is not None:
            return self._last_data.speed
        else:
            return None

    async def refresh_token(self):
        global TOKEN, LAST_TOKEN_REFRESH, TOKEN_REFRESH_LOCK

        async with TOKEN_REFRESH_LOCK:
            # Refresh token once every 10 minutes
            if (LAST_TOKEN_REFRESH is None or time.time() - LAST_TOKEN_REFRESH > 600) or TOKEN is None:
                _LOGGER.debug("Refreshing token...")
                try:
                    email = self.hass.config_entries.async_entries(DOMAIN)[0].data["email"]
                    password = self.hass.config_entries.async_entries(DOMAIN)[0].data["password"]

                    # Fetch new token
                    new_token = await get_login_token(email, password)
                    if new_token:
                        TOKEN = new_token
                        LAST_TOKEN_REFRESH = time.time()
                        _LOGGER.debug("Token refreshed successfully.")
                    else:
                        _LOGGER.error("Failed to refresh token.")
                except Exception as e:
                    _LOGGER.error(f"Error during token refresh: {e}")
            else:
                _LOGGER.debug("Token refresh skipped (still valid).")

    async def async_update(self) -> None:
        global TOKEN
        """Fetch new state data for the sensor."""
        # Get the GPS data from the API
        try:
            await self.refresh_token()
            tracker_data = await get_device_data(TOKEN, self._gps_id)
            if tracker_data is not None:
                self._last_data = tracker_data
                # Add extra attribute with raw data as string
                self._attr_extra_state_attributes["raw_data"] = str(tracker_data)

        except Exception as e:
            _LOGGER.error(f'{e}')
            self._attr_native_value = None


async def get_login_token(email, password):
    # Get login token from HTTP Post request to API_URL/login.
    # Use aiohttp instead of requests to avoid blocking
    # Corresponding CURL command:
    # curl -X 'POST' \
    #   'https://connect.paj-gps.de/api/login?email=EMAIL&password=PASSWORD' \
    #   -H 'accept: application/json' \
    #   -H 'X-CSRF-TOKEN: ' \
    #   -d ''
    # Returns LoginResponse.token or None
    url = API_URL + "login"
    payload = {}
    headers = {
        'accept': 'application/json',
        'X-CSRF-TOKEN': ''
    }
    params = {
        'email': email,
        'password': password
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, data=payload, params=params) as response:
            try:
                if response.status == 200:
                    json = await response.json()
                    login_response = LoginResponse(json)
                    return login_response.token
                else:
                    # Handle error using ApiError class
                    json = await response.json()
                    api_error = ApiError(json)
                    _LOGGER.error(f"Error {response.status} while getting login token: {api_error.error}")
                    return None
            except Exception as e:
                _LOGGER.error(f"{e}")
                return None

async def get_devices(token):
    # Get GPS devices from HTTP Get request to API_URL/device.
    # Use aiohttp instead of requests to avoid blocking.
    # Corresponding CURL command:
    # curl -X 'GET' \
    #   'https://connect.paj-gps.de/api/device' \
    #   -H 'accept: application/json' \
    #   -H 'Authorization: Bearer TOKEN' \
    #   -H 'X-CSRF-TOKEN: '
    # Returns dictionary of device id, name, imei, model and has_battery from response.success.

    _LOGGER.debug("Getting devices")

    url = API_URL + "device"
    payload = {}
    headers = {
        'accept': 'application/json',
        'Authorization': f'Bearer {token}',
        'X-CSRF-TOKEN': ''
    }
    params = {}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, data=payload, params=params) as response:
            try:
                if response.status == 200:
                    json = await response.json()
                    devices = json["success"]
                    results = {}
                    for device in devices:
                        results[device["id"]] = {
                            "id": device["id"],
                            "name": device["name"],
                            "imei": device["imei"],
                            "model": device["device_models"][0]["model"],
                            "has_battery": device["device_models"][0]["standalone_battery"] == 1
                        }
                    return results
                else:
                    # Handle error using ApiError class
                    json = await response.json()
                    api_error = ApiError(json)
                    _LOGGER.error(f"Error {response.status} while getting devices: {api_error.error}")
                    return None
            except Exception as e:
                _LOGGER.error(f"{e}")
                return None


async def get_device_data(token, device_id):
    # Get GPS data from HTTP Get request to API_URL/trackerdata/{DeviceID}/last_points.
    # Use aiohttp instead of requests to avoid blocking.
    # Corresponding CURL command:
    # curl -X 'GET' \
    #   'https://connect.paj-gps.de/api/trackerdata/{DeviceID}/last_points?lastPoints=1' \
    #   -H 'accept: application/json' \
    #   -H 'Authorization: Bearer TOKEN' \
    #   -H 'X-CSRF-TOKEN: '
    # Returns instance of PAJGPSTrackerData object.

    _LOGGER.debug(f"Getting data for device: {device_id}")

    url = API_URL + f"trackerdata/{device_id}/last_points"
    payload = {}
    headers = {
        'accept': 'application/json',
        'Authorization': f'Bearer {token}',
        'X-CSRF-TOKEN': ''
    }
    params = {
        'lastPoints': 1
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, data=payload, params=params) as response:
            try:
                if response.status == 200:
                    json = await response.json()
                    tracker_data = PajGpsTrackerData(json["success"][0])
                    return tracker_data
                else:
                    # Handle error using ApiError class
                    json = await response.json()
                    api_error = ApiError(json)
                    _LOGGER.error(f"Error {response.status} while getting device data: {api_error.error}")
                    return None
            except Exception as e:
                _LOGGER.error(f"{e}")
                return None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
):
    """Add sensors for passed config_entry in HA."""
    _LOGGER.debug("Starting setup for PAJ GPS integration")

    # Validate email and password
    email = config_entry.data.get("email")
    password = config_entry.data.get("password")
    if not email or not password:
        _LOGGER.error("Email or password not set in config entry")
        return

    # Get Authorization token
    token = await get_login_token(email, password)
    if not token:
        _LOGGER.error("Failed to retrieve login token")
        return

    # Get devices
    devices = await get_devices(token)
    if not devices:
        _LOGGER.error("No devices found or failed to fetch devices")
        return

    # Prepare entities for addition
    to_add = []
    for device_id, device in devices.items():
        try:
            gpssensor = PajGpsSensor(
                gps_id=device["id"],
                imei=device["imei"],
                model=device["model"],
                has_battery=device["has_battery"],
                token=token,
            )
            to_add.append(gpssensor)

            # Add battery sensor if applicable
            if device["has_battery"]:
                to_add.append(PajGpsBatterySensor(gpssensor))

            # Add speed sensor
            to_add.append(PajGpsSpeedSensor(gpssensor))
        except Exception as e:
            _LOGGER.error(f"Error creating entities for device {device_id}: {e}")
            continue

    # Add entities to Home Assistant
    if to_add and async_add_entities:
        _LOGGER.debug(f"Adding {len(to_add)} entities to Home Assistant")
        async_add_entities(to_add, update_before_add=False)
    else:
        _LOGGER.warning("No entities to add for PAJ GPS integration")
