"""
Main class for PajGPS data handling.
Singleton class to handle data fetching and storing for all the sensors to read from.
This class is responsible for fetching data from the PajGPS API and storing it.
It also acts as a gateway for the sensors to make only few API calls which results all sensors can read
instead of each sensor making its own API calls.
"""
import asyncio
import logging
import random
import time
from datetime import timedelta
import aiohttp
from custom_components.pajgps.const import DOMAIN, VERSION
from custom_components.pajgps.requests import (
    make_request,
    ApiResponseError,
    check_pajgps_availability,
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)
API_URL = "https://connect.paj-gps.de/api/v1/"


class PajGPSDevice:
    """Representation of single Paj GPS device."""

    # Basic attributes
    id: int
    name: str
    imei: str
    model: str
    has_battery: bool

    # Alarms
    has_alarm_sos: bool
    alarm_sos_enabled: bool
    has_alarm_shock: bool
    alarm_shock_enabled: bool
    has_alarm_voltage: bool
    alarm_voltage_enabled: bool
    has_alarm_battery: bool
    alarm_battery_enabled: bool
    has_alarm_speed: bool
    alarm_speed_enabled: bool
    has_alarm_power_cutoff: bool
    alarm_power_cutoff_enabled: bool
    has_alarm_ignition: bool
    alarm_ignition_enabled: bool
    has_alarm_drop: bool
    alarm_drop_enabled: bool

    def __init__(self, id: int) -> None:
        """Initialize the PajGPSDevice class."""
        self.id = id

    def is_alert_enabled(self, _alert_type) -> bool:
        """
        Check if the alert is available and enabled for the device.
        """
        if _alert_type == 1:                 # Shock Alert
            return self.has_alarm_shock and self.alarm_shock_enabled
        elif _alert_type == 2:               # Battery Alert
            return self.has_alarm_battery and self.alarm_battery_enabled
        elif _alert_type == 4:               # SOS Alert
            return self.has_alarm_sos and self.alarm_sos_enabled
        elif _alert_type == 5:               # Speed Alert
            return self.has_alarm_speed and self.alarm_speed_enabled
        elif _alert_type == 6:               # Power Cutoff Alert
            return self.has_alarm_power_cutoff and self.alarm_power_cutoff_enabled
        elif _alert_type == 7:               # Ignition Alert
            return self.has_alarm_ignition and self.alarm_ignition_enabled
        elif _alert_type == 9:               # Drop Alert
            return self.has_alarm_drop and self.alarm_drop_enabled
        elif _alert_type == 13:              # Voltage Alert
            return self.has_alarm_voltage and self.alarm_voltage_enabled
        else:
            _LOGGER.error("Unknown alert type: %s", _alert_type)
            return False


class PajGPSAlert:
    """Representation of single Paj GPS notification/alert."""

    device_id: int
    alert_type: int

    def __init__(self, device_id: int, alert_type:int) -> None:
        """Initialize the PajGPSAlert class."""
        self.device_id = device_id
        self.alert_type = alert_type

class PajGPSPositionData:
    """Representation of single Paj GPS device tracking data."""

    device_id: int
    lat: float
    lng: float
    elevation: float | None = None
    direction: int
    speed: int
    battery: int
    last_elevation_update: float = 0.0

    def __init__(self, device_id: int, lat: float, lng: float, direction:int, speed: int, battery: int) -> None:
        """Initialize the PajGPSTracking class."""
        self.device_id = device_id
        self.lat = lat
        self.lng = lng
        self.direction = direction
        self.speed = speed
        self.battery = battery


class PajGPSSensorData:
    """Representation of single Paj GPS device sensor data."""

    device_id: int
    voltage: float = 0.0
    total_update_time_ms: float = 0.0   # Total time for full PajGPS data update in milliseconds

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

class ApiError(Exception):
    error = None
    def __init__(self, json):
        self.error = json["error"]


PajGPSDataInstances: dict[str, "PajGPSData"] = {}

class PajGPSData:
    """Main class for PajGPS data handling."""

    # Basic properties
    guid: str
    entry_name: str

    # Session properties
    _session: aiohttp.ClientSession | None
    _background_tasks: set[asyncio.Task]

    # Credentials properties
    email: str
    password: str
    token: str | None
    last_token_update: float
    token_ttl: int = 60 * 5  # 5 minutes

    # Update properties
    last_update: float
    data_ttl: int = int(SCAN_INTERVAL.total_seconds() / 2)  # update requests done more often than this many seconds will be ignored
    mark_alerts_as_read: bool
    update_lock: asyncio.Lock
    force_battery: bool
    fetch_elevation: bool
    total_update_time_ms: float  # Total time of last full update in milliseconds

    # Pure json responses from API
    devices_json: str
    alerts_json: str
    positions_json: str

    # Deserialized data
    devices: list[PajGPSDevice]
    alerts: list[PajGPSAlert]
    positions: list[PajGPSPositionData]
    sensors: list[PajGPSSensorData]


    def __init__(self, guid: str, entry_name: str, email: str, password: str, mark_alerts_as_read: bool, fetch_elevation: bool, force_battery: bool) -> None:
        """
        Initialize the PajGPSData class.
        """

        self.guid = guid
        self.entry_name = entry_name
        self.email = email
        self.password = password
        self.mark_alerts_as_read = mark_alerts_as_read
        self.fetch_elevation = fetch_elevation
        self.force_battery = force_battery
        self._session = None
        self._background_tasks = set()
        self.update_lock = asyncio.Lock()
        self.devices = []
        self.alerts = []
        self.positions = []
        self.sensors = []
        self.token = None
        self.last_token_update = 0.0
        self.last_update = time.time() - 60
        self.total_update_time_ms = 0.0


    async def async_close(self) -> None:
        """Close the session and cleanup resources."""
        # Wait for any pending background tasks
        if self._background_tasks:
            _LOGGER.debug("Waiting for %s background tasks to complete", len(self._background_tasks))
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

        # Close the session
        if self._session and not self._session.closed:
            await self._session.close()
            # Give the underlying connections time to close
            await asyncio.sleep(0.25)
            self._session = None
            _LOGGER.debug("Session closed successfully")

    @classmethod
    def get_instance(cls, guid: str, entry_name: str, email: str, password: str, mark_alerts_as_read: bool, fetch_elevation: bool, force_battery: bool) -> "PajGPSData":
        """
        Get or create a singleton instance of PajGPSData for the given entry_name.
        """
        if guid not in PajGPSDataInstances:
            PajGPSDataInstances[guid] = cls(guid, entry_name, email, password, mark_alerts_as_read, fetch_elevation, force_battery)
        return PajGPSDataInstances[guid]

    @classmethod
    async def clean_instances(cls) -> None:
        """
        Clean all instances of PajGPSData.
        This is used for testing purposes to reset the singleton instances.
        """
        for instance in PajGPSDataInstances.values():
            await instance.async_close()
        PajGPSDataInstances.clear()

    async def get_login_token(self) -> str | None:
        """
        Get login token from HTTP Post request to API_URL/login.
        Use aiohttp instead of requests to avoid blocking
        Corresponding CURL command:
        curl -X 'POST' \
          'https://connect.paj-gps.de/api/v1/login?email=EMAIL&password=PASSWORD' \
          -H 'accept: application/json' \
          -H 'X-CSRF-TOKEN: ' \
          -d ''
        Returns LoginResponse.token or None
        """

        url = API_URL + "login"
        payload = {}
        headers = {
            'accept': 'application/json',
            'X-CSRF-TOKEN': ''
        }
        params = {
            'email': self.email,
            'password': self.password
        }
        try:
            json = await make_request("POST", url, headers, params=params)
            login_response = LoginResponse(json)
            return login_response.token
        except ApiResponseError as e:
            raise ApiError(e.error_json)
        except ApiError as e:
            _LOGGER.error("Error while getting login token: %s", e.error)
            return None
        except TimeoutError as e:
            _LOGGER.error("Timeout while getting login token")

    async def refresh_token(self, forced: bool = False) -> None:
        # Refresh token once every 5 minutes
        if (time.time() - self.last_token_update > self.token_ttl) or self.token is None or forced:
            _LOGGER.debug("Refreshing token")
            new_token = None
            try:
                # Fetch new token
                new_token = await self.get_login_token()
            except TimeoutError as e:
                _LOGGER.error("Timeout while getting login token")

            if new_token:
                self.token = new_token
                self.last_token_update = time.time()
                _LOGGER.debug("Token refreshed successfully")
            else:
                _LOGGER.error("Failed to refresh token")

        else:
            _LOGGER.debug("Token refresh skipped (still valid)")

    def clean_data(self):
        self.devices = []
        self.alerts = []
        self.positions = []

    def get_standard_headers(self) -> dict:
        """
        Get standard headers for API requests.
        :return: dict with headers
        """
        return {
            'accept': 'application/json',
            'Authorization': f'Bearer {self.token}',
            'X-CSRF-TOKEN': ''
        }


    async def update_pajgps_data(self, forced: bool = False) -> None:
        """
        Orchestrate a full data refresh.
        Skips if data is still fresh or an update is already in progress.
        """
        if not await self._should_run_update(forced):
            return

        async with self.update_lock:
            if not await self._should_run_update(forced):
                return

            self.last_update = time.time()

            if not await self._is_infrastructure_ready():
                # Delay next retry by 1 minute to avoid flooding warnings
                self.last_update = time.time() + 60
                return

            await self._fetch_all_data()

    async def _should_run_update(self, forced: bool) -> bool:
        """Return True if enough time has passed since last update, or if the update is forced."""
        if forced:
            return True
        if self.update_lock.locked():
            _LOGGER.debug("Update already in progress, skipping this update")
            return False
        # Wait a small random delay to avoid thundering-herd when multiple sensors trigger at once
        await asyncio.sleep(random.random())
        return (time.time() - self.last_update) >= self.data_ttl

    async def _is_infrastructure_ready(self) -> bool:
        """Ensure the API is reachable and the auth token is valid."""
        if not await check_pajgps_availability():
            _LOGGER.warning("API is not reachable, skipping update")
            return False
        await self.refresh_token()
        return True

    async def _fetch_all_data(self) -> None:
        """Fetch all device data from the API and record the total duration."""
        start = time.perf_counter()

        # Devices must be fetched first — other calls depend on the device list
        await self.update_devices_data()

        await asyncio.gather(
            self.update_position_data(),
            self.update_alerts_data(),
            self.update_sensors_data(),
        )

        self._record_update_duration(start)

    def _record_update_duration(self, start: float) -> None:
        """Persist the measured update duration on self and all sensor entries."""
        duration_ms = (time.perf_counter() - start) * 1000
        self.total_update_time_ms = duration_ms

        # Sanity check: ignore values outside the 0–30 s range
        if 0 < duration_ms < 30_000:
            for sensor in self.sensors:
                sensor.total_update_time_ms = duration_ms


    def get_device(self, device_id: int) -> PajGPSDevice | None:
        """Get device by id."""
        for device in self.devices:
            if device.id == device_id:
                return device
        return None

    def get_device_ids(self) -> list[int]:
        """Get device ids."""
        return [device.id for device in self.devices]

    def get_device_info(self, device_id: int) -> dict | None:
        """Get device info by id."""
        for device in self.devices:
            if device.id == device_id:
                return {
                    "identifiers": {
                        (DOMAIN, f"{self.guid}_{device.id}")
                    },
                    "name": f"{device.name}",
                    "manufacturer": "PAJ GPS",
                    "model": device.model,
                    "sw_version": VERSION,
                }
        return None

    def get_position(self, device_id: int) -> PajGPSPositionData | None:
        """Get position data by device id."""
        for position in self.positions:
            if position.device_id == device_id:
                return position
        return None

    def get_sensors(self, device_id: int) -> PajGPSSensorData | None:
        """Get sensor data by device id."""
        for sensor in self.sensors:
            if sensor.device_id == device_id:
                return sensor
        return None

    def get_alerts(self, device_id: int) -> list[PajGPSAlert]:
        """Get alerts by device id."""
        return [alert for alert in self.alerts if alert.device_id == device_id]

    async def update_position_data(self) -> None:
        """
        Gets the position data for all the devices from API and saves them in self.positions_json and self.positions.
        Using aiohttp to avoid blocking.
        Corresponding CURL command:
        curl -X 'POST' \
          'https://connect.paj-gps.de/api/v1/trackerdata/getalllastpositions' \
          -d '{
          "deviceIDs": [<deviceIDs>],
          "fromLastPoint": false
        }'
        """
        url = API_URL + "trackerdata/getalllastpositions"
        payload = {
            "deviceIDs": self.get_device_ids(),
            "fromLastPoint": False
        }
        headers = self.get_standard_headers()
        try:
            json = await make_request("POST", url, headers, payload=payload)
        except ApiResponseError as e:
            raise ApiError(e.error_json)
        except ApiError as e:
            _LOGGER.error("Error while getting tracking data: %s", e.error)
            self.positions = []
            return
        except TimeoutError as e:
            _LOGGER.warning("Timeout while getting tracking data")
            self.positions = []
            return
        except KeyError as e:
            _LOGGER.error("Missing key in tracking data response: %s", e)
            self.positions = []
            return

        self.positions_json = json

        if "success" not in json:
            _LOGGER.error("Unexpected response format in tracking data: %s", json)
            self.positions = []
            return

        new_positions = [
            PajGPSPositionData(
                device["iddevice"],
                device["lat"],
                device["lng"],
                device["direction"],
                device["speed"],
                device["battery"]
            ) for device in json["success"]
        ]


        if self.fetch_elevation:
            # Get new positions that have lat and lng different from old positions for same device
            moved_device_ids = []
            for new_position in new_positions:
                old_position = self.get_position(new_position.device_id)
                if old_position is not None:
                    if (old_position.lat != new_position.lat) or (old_position.lng != new_position.lng) or new_position.elevation is None:
                        moved_device_ids.append(new_position.device_id)

            # Update elevation for moved devices in background
            for device_id in moved_device_ids:
                # Check if there was an update in the last 5 minutes
                if time.time() - self.get_position(device_id).last_elevation_update > 60 * 5:
                    task = asyncio.create_task(self.update_elevation(device_id))
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)
                    self.get_position(device_id).last_elevation_update = time.time()

        self.positions = new_positions


    async def update_elevation(self, device_id: int) -> None:
        """
        Determine the elevation of the device using the Open Meteo API.
        Example request:
        https://api.open-meteo.com/v1/elevation?latitude=52.52&longitude=13.41
        Example JSON response:
        {"elevation":[38.0]}
        """
        url = "https://api.open-meteo.com/v1/elevation"
        headers = {
            'accept': 'application/json'
        }
        position = self.get_position(device_id)
        if position is None:
            return
        # Round the latitude and longitude to about 100 meters precision
        position.lat = round(position.lat, 5)
        position.lng = round(position.lng, 5)
        params = {
            'latitude': position.lat,
            'longitude': position.lng
        }
        json = None
        try:
            json = await make_request("GET", url, headers, params=params)
        except TimeoutError:
            _LOGGER.warning(
                "Timeout while getting elevation data for device %s at (%s, %s) from Open-Meteo API",
                device_id, position.lat, position.lng
            )
            position.elevation = None
        except ValueError as e:
            # Content-type mismatch or HTTP error
            _LOGGER.warning(
                "Failed to get elevation for device %s at (%s, %s): %s",
                device_id, position.lat, position.lng, e
            )
            position.elevation = None
        except Exception as e:
            _LOGGER.error(
                "Unexpected error while getting elevation for device %s at (%s, %s): %s: %s",
                device_id, position.lat, position.lng, type(e).__name__, e
            )
            position.elevation = None

        if json and "elevation" in json:
            position.elevation = json["elevation"][0]
        else:
            _LOGGER.warning(
                "Unexpected elevation response format for device %s at (%s, %s): %s",
                device_id, position.lat, position.lng, json
            )
            position.elevation = None



    async def update_alerts_data(self) -> None:
        """
        Gets the alerts data for all the devices from API and saves them in self.alerts_json and self.alerts.
        Using aiohttp to avoid blocking.
        Corresponding CURL command:
        curl -X 'GET' \
          'https://connect.paj-gps.de/api/v1/notifications?isRead=0'
        """
        url = API_URL + "notifications"
        params = {
            'isRead': 0
        }
        headers = self.get_standard_headers()
        json = None
        try:
            json = await make_request("GET", url, headers, params=params)
            self.alerts_json = json
        except ApiError as e:
            _LOGGER.error("Error while getting alerts data: %s", e.error)
            self.alerts = []
        except TimeoutError as e:
            _LOGGER.warning("Timeout while getting alerts data")

        if json:
            new_alerts = [
                PajGPSAlert(alert["iddevice"], alert["meldungtyp"])
                for alert in json["success"]
            ]
            self.alerts = new_alerts

            if self.mark_alerts_as_read:
                alert_ids = [alert.alert_type for alert in new_alerts]
                task = asyncio.create_task(self.consume_alerts(alert_ids))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)


    async def update_devices_data(self) -> None:
        """
        Gets info about all devices in the account from the API and saves them in self.devices_json and self.devices.
        Using aiohttp to avoid blocking.
        Corresponding CURL command:
        curl -X 'GET' \
          'https://connect.paj-gps.de/api/v1/device'
        """
        url = API_URL + "device"
        headers = self.get_standard_headers()
        json = None
        try:
            json = await make_request("GET", url, headers)
            self.devices_json = json
        except ApiResponseError as e:
            _LOGGER.error("Error while getting devices data: %s", e)
            self.devices = []
            return
        except ApiError as e:
            _LOGGER.error("Error while getting devices data: %s", e.error)
            self.devices = []
            return
        except TimeoutError:
            _LOGGER.warning("Timeout while getting devices data")
            return

        new_devices = []
        if json:
            for device in json["success"]:
                device_data = PajGPSDevice(device["id"])
                device_data.name = device["name"]
                device_data.imei = device["imei"]
                device_data.model = device["device_models"][0]["model"]
                device_data.has_battery = device["device_models"][0]["standalone_battery"] == 1
                device_data.has_alarm_sos = device["device_models"][0]["alarm_sos"] == 1
                device_data.has_alarm_shock = device["device_models"][0]["alarm_erschuetterung"] == 1
                device_data.has_alarm_voltage = device["device_models"][0]["alarm_volt"] == 1
                device_data.has_alarm_battery = device["device_models"][0]["alarm_batteriestand"] == 1
                device_data.has_alarm_speed = device["device_models"][0]["alarm_geschwindigkeit"] == 1
                device_data.has_alarm_power_cutoff = device["device_models"][0]["alarm_stromunterbrechung"] == 1
                device_data.has_alarm_ignition = device["device_models"][0]["alarm_zuendalarm"] == 1
                device_data.has_alarm_drop = device["device_models"][0]["alarm_fall"] == 1
                device_data.alarm_sos_enabled = device["alarmsos"] == 1
                device_data.alarm_shock_enabled = device["alarmbewegung"] == 1
                device_data.alarm_voltage_enabled = device["alarm_volt"] == 1
                device_data.alarm_battery_enabled = device["alarmakkuwarnung"] == 1
                device_data.alarm_speed_enabled = device["alarmgeschwindigkeit"] == 1
                device_data.alarm_power_cutoff_enabled = device["alarmstromunterbrechung"] == 1
                device_data.alarm_ignition_enabled = device["alarmzuendalarm"] == 1
                device_data.alarm_drop_enabled = device["alarm_fall_enabled"] == 1
                new_devices.append(device_data)
        self.devices = new_devices


    async def update_sensors_data(self) -> None:
        """
        Update the sensors data for all the devices from API and saves them in self.sensors.
        Also measures the time taken for each device's sensor update.
        Using aiohttp to avoid blocking.
        Corresponding CURL command:
        curl -X 'GET' \
          'https://connect.paj-gps.de/api/v1/sensordata/last/{DeviceID}'

        Response example:
        {
          "success": {
            "ts": {
              "$date": {
                "$numberLong": "1758522050000"
              }
            },
            "volt": 100000,
            "did": 1242185,
            "date_unix": {
              "$date": {
                "$numberLong": "1758499200000"
              }
            },
            "date_iso": "2025-09-22T06:20:50+00:00"
          }
        }
        """
        headers = self.get_standard_headers()
        new_sensors = []

        for device in self.devices:
            url = API_URL + f"sensordata/last/{device.id}"
            sensor_data = PajGPSSensorData()
            sensor_data.device_id = device.id
            json = None

            try:
                json = await make_request("GET", url, headers)
            except ApiResponseError as e:
                raise ApiError(e.error_json)
            except ApiError as e:
                _LOGGER.error("Error while getting sensor data for device %s: %s", device.id, e.error)
                sensor_data.voltage = 0.0
            except TimeoutError as e:
                _LOGGER.warning("Timeout while getting sensor data for device %s", device.id)
                sensor_data.voltage = 0.0

            if json and "success" in json and "volt" in json["success"]:
                # Convert from millivolts to volts and round to 1 decimal place
                sensor_data.voltage = round(json["success"]["volt"] / 1000, 1)
            else:
                _LOGGER.debug("No sensor data for device %s", device.id)
                sensor_data.voltage = 0.0



            new_sensors.append(sensor_data)

        self.sensors = new_sensors


    async def consume_alerts(self, alert_ids: list[int]) -> None:
        """
        Marks the alerts as read in the API.
        Corresponding CURL command for one type of alert:
        curl -X 'PUT' \
          'https://connect.paj-gps.de/api/v1/notifications/markReadByCustomer?alertType=<ALERT_ID>&isRead=1'
        """
        url = API_URL + "notifications/markReadByCustomer"
        headers = self.get_standard_headers()
        for alert_id in alert_ids:
            params = {
                'alertType': alert_id,
                'isRead': 1
            }
            try:
                await make_request("PUT", url, headers, params=params)
                _LOGGER.debug("Alert %s marked as read", alert_id)
            except ApiResponseError as e:
                raise ApiError(e.error_json)
            except ApiError as e:
                _LOGGER.error("Error while marking alert %s as read: %s", alert_id, e.error)
            except TimeoutError as e:
                _LOGGER.warning("Timeout while marking alerts as read")

    async def change_alert_state(self, device_id: int, alert_type: int, state: bool) -> None:
        """
        Change the state of the alert for the device by updating given property of the device.
        This will enable or disable the alert.
        Disabled alerts will not generate notifications, so the alert state will never be true.
        Corresponding CURL command:
        curl -X 'PUT' \
              'https://connect.paj-gps.de/api/v1/device/<DeviceID>' \
              -d '{
              "alarmsos": 1
            }'
        """
        state_int = 1 if state else 0
        alert_name: str = ""
        device = self.get_device(device_id)
        
        if alert_type == 1:                 # Shock Alert
            alert_name = "alarmbewegung"
            device.alarm_shock_enabled = state
        elif alert_type == 2:               # Battery Alert
            alert_name = "alarmakkuwarnung"
            device.alarm_battery_enabled = state
        elif alert_type == 4:               # SOS Alert
            alert_name = "alarmsos"
            device.alarm_sos_enabled = state
        elif alert_type == 5:               # Speed Alert
            alert_name = "alarmgeschwindigkeit"
            device.alarm_speed_enabled = state
        elif alert_type == 6:               # Power Cutoff Alert
            alert_name = "alarmstromunterbrechung"
            device.alarm_power_cutoff_enabled = state
        elif alert_type == 7:               # Ignition Alert
            alert_name = "alarmzuendalarm"
            device.alarm_ignition_enabled = state
        elif alert_type == 9:               # Drop Alert
            alert_name = "alarm_fall"
            device.alarm_drop_enabled = state
        elif alert_type == 13:              # Voltage Alert
            alert_name = "alarm_volt"
            device.alarm_voltage_enabled = state

        else:
            _LOGGER.error("Unknown alert type: %s", alert_type)
            return

        # Change the alert state in PajGPSData
        device = self.get_device(device_id)
        if device is None:
            _LOGGER.error("Device not found: %s", device_id)
            return

        url = API_URL + "device/" + str(device_id)
        headers = self.get_standard_headers()
        params = {
            alert_name: state_int
        }
        try:
            await make_request("PUT", url, headers, params=params)
            _LOGGER.debug("Alert %s for device %s set to %s", alert_name, device_id, state_int)
        except ApiResponseError as e:
            raise ApiError(e.error_json)
        except ApiError as e:
            _LOGGER.error("Error while changing alert state: %s", e.error)
        except TimeoutError as e:
            _LOGGER.warning("Timeout while changing alert state")
