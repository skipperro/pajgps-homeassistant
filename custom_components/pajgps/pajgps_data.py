"""
Main class for PajGPS data handling.
Singleton class to handle data fetching and storing for all the sensors to read from.
This class is responsible for fetching data from the PajGPS API and storing it.
It also acts as a gateway for the sensors to make only few API calls which results all sensors can read
instead of each sensor making its own API calls.
"""
import asyncio
import logging
import time
from datetime import timedelta
import aiohttp
from homeassistant.helpers.device_registry import DeviceInfo
from custom_components.pajgps.const import DOMAIN, VERSION, ALERT_NAMES

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)
REQUEST_TIMEOUT = 5  # 5 seconds x 3 requests per update = 24 seconds (must stay below SCAN_INTERVAL)
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
            _LOGGER.error(f"Unknown alert type: {_alert_type}")
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

    guid: str

    # Credentials properties
    email: str
    password: str
    token: str
    last_token_update: float = 0.0
    token_ttl: int = 60 * 10  # 10 minutes

    # Update properties
    last_update: float = time.time() - 60
    data_ttl: int = int(SCAN_INTERVAL.total_seconds() / 2)  # update requests done more often than this many seconds will be ignored
    mark_alerts_as_read: bool = True
    update_lock = asyncio.Lock()
    force_battery = True
    fetch_elevation = True

    # Pure json responses from API
    devices_json: str
    alerts_json: str
    positions_json: str

    # Deserialized data
    devices: list[PajGPSDevice] = []
    alerts: list[PajGPSAlert] = []
    positions: list[PajGPSPositionData] = []

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

    @classmethod
    def get_instance(cls, guid: str, entry_name: str, email: str, password: str, mark_alerts_as_read: bool, fetch_elevation: bool, force_battery: bool) -> "PajGPSData":
        """
        Get or create a singleton instance of PajGPSData for the given entry_name.
        """
        if guid not in PajGPSDataInstances:
            PajGPSDataInstances[guid] = cls(guid, entry_name, email, password, mark_alerts_as_read, fetch_elevation, force_battery)
        return PajGPSDataInstances[guid]

    @classmethod
    def clean_instances(cls) -> None:
        """
        Clean all instances of PajGPSData.
        This is used for testing purposes to reset the singleton instances.
        """
        PajGPSDataInstances.clear()

    @staticmethod
    async def make_get_request(url: str, headers: dict, params: dict = None, timeout: int = REQUEST_TIMEOUT):
        """Reusable function for making GET requests."""
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params, timeout=timeout) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    json = await response.json()
                    if json.get("error"):
                        raise ApiError(json)


        # Close the session
        await session.close()

    @staticmethod
    async def make_post_request(url: str, headers: dict, payload: dict = None, params: dict = None,
                                timeout: int = REQUEST_TIMEOUT):
        """Reusable function for making POST requests."""
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, params=params, timeout=timeout) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    json = await response.json()
                    raise ApiError(json)
        # Close the session
        await session.close()

    @staticmethod
    async def make_put_request(url: str, headers: dict, params: dict = None, timeout: int = REQUEST_TIMEOUT):
        """Reusable function for making PUT requests."""
        async with aiohttp.ClientSession() as session:
            async with session.put(url, headers=headers, params=params, timeout=timeout) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    json = await response.json()
                    raise ApiError(json)
        # Close the session
        await session.close()

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
            json = await self.make_post_request(url, headers, params=params)
            login_response = LoginResponse(json)
            return login_response.token
        except ApiError as e:
            _LOGGER.error(f"Error while getting login token: {e.error}")
            return None
        except TimeoutError as e:
            _LOGGER.error("Timeout while getting login token.")
        except Exception as e:
            _LOGGER.error(f"Error while getting login token: {e}")
            return None

    async def refresh_token(self, forced: bool = False) -> None:
        # Refresh token once every 10 minutes
        if (time.time() - self.last_token_update > self.token_ttl) or self.token is None or forced:
            _LOGGER.debug("Refreshing token...")
            try:
                email = self.email # self.hass.config_entries.async_entries(DOMAIN)[0].data["email"]
                password = self.password # self.hass.config_entries.async_entries(DOMAIN)[0].data["password"]

                # Fetch new token
                new_token = await self.get_login_token()
                if new_token:
                    self.token = new_token
                    self.last_token_update = time.time()
                    _LOGGER.debug("Token refreshed successfully.")
                else:
                    _LOGGER.error("Failed to refresh token.")
            except TimeoutError as e:
                _LOGGER.error("Timeout while getting login token.")
            except Exception as e:
                _LOGGER.error(f"Error during token refresh: {e}")
                self.clean_data()
        else:
            _LOGGER.debug("Token refresh skipped (still valid).")

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


    async def async_update(self, forced: bool = False) -> None:
        """
        Update the data from the PajGPS API.
        This method is called by the update coordinator.
        It fetches the data from the API and updates the internal state.
        """
        # Check if we need to update data
        if (time.time() - self.last_update) < self.data_ttl and not forced:
            return

        async with self.update_lock:
            # Check again if we need to update data
            if (time.time() - self.last_update) < self.data_ttl and not forced:
                return

            # Update last update time
            self.last_update = time.time()

            # Check if we need to refresh token
            await self.refresh_token()

            # Fetch the new data from the API
            await self.update_devices_data()
            await self.update_position_data()
            await self.update_alerts_data()


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
            json = await self.make_post_request(url, headers, payload=payload)
            self.positions_json = json
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
                        asyncio.create_task(self.update_elevation(device_id))
                        self.get_position(device_id).last_elevation_update = time.time()

            self.positions = new_positions
        except ApiError as e:
            _LOGGER.error(f"Error while getting tracking data: {e.error}")
            self.positions = []
        except TimeoutError as e:
            _LOGGER.warning("Timeout while getting tracking data.")
        except Exception as e:
            _LOGGER.error(f"Error updating position data: {e}")
            self.positions = []

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
        try:
            json = await self.make_get_request(url, headers, params=params)
            if "elevation" in json:
                position.elevation = json["elevation"][0]
            else:
                _LOGGER.error(f"Error while getting elevation data: {json}")
        except TimeoutError as e:
            _LOGGER.warning("Timeout while getting elevation data.")
        except Exception as e:
            _LOGGER.error(f"Error while getting elevation data: {e}")
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
        try:
            json = await self.make_get_request(url, headers, params=params)
            self.alerts_json = json
            new_alerts = [
                PajGPSAlert(alert["iddevice"], alert["meldungtyp"])
                for alert in json["success"]
            ]
            self.alerts = new_alerts

            if self.mark_alerts_as_read:
                alert_ids = [alert.alert_type for alert in new_alerts]
                asyncio.create_task(self.consume_alerts(alert_ids)) # Fire and forget to avoid blocking
        except ApiError as e:
            _LOGGER.error(f"Error while getting alerts data: {e.error}")
            self.alerts = []
        except TimeoutError as e:
            _LOGGER.warning("Timeout while getting alerts data.")
        except Exception as e:
            _LOGGER.error(f"Error updating alerts: {e}")
            self.alerts = []

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
        try:
            json = await self.make_get_request(url, headers)
            self.devices_json = json
            new_devices = []
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
        except ApiError as e:
            _LOGGER.error(f"Error while getting devices data: {e.error}")
            self.devices = []
        except TimeoutError as e:
            _LOGGER.warning("Timeout while getting devices data.")
        except Exception as e:
            _LOGGER.error(f"Error while updating Paj GPS devices: {e}")
            self.devices = []


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
                await self.make_put_request(url, headers, params=params)
                _LOGGER.debug(f"Alert {alert_id} marked as read.")
            except ApiError as e:
                _LOGGER.error(f"Error while marking alert {alert_id} as read: {e.error}")
            except TimeoutError as e:
                _LOGGER.warning("Timeout while marking alerts as read.")
            except Exception as e:
                _LOGGER.error(f"Error while marking alerts as read: {e}")

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
            _LOGGER.error(f"Unknown alert type: {alert_type}")
            return

        # Change the alert state in PajGPSData
        device = self.get_device(device_id)
        if device is None:
            _LOGGER.error(f"Device not found: {device_id}")
            return

        url = API_URL + "device/" + str(device_id)
        headers = self.get_standard_headers()
        params = {
            alert_name: state_int
        }
        try:
            await self.make_put_request(url, headers, params=params)
            _LOGGER.debug(f"Alert {alert_name} for device {device_id} set to {state_int}.")
        except ApiError as e:
            _LOGGER.error(f"Error while changing alert state: {e.error}")
        except TimeoutError as e:
            _LOGGER.warning("Timeout while changing alert state.")
        except Exception as e:
            _LOGGER.error(f"Error while changing alert state: {e}")