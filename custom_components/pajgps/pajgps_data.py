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
from custom_components.pajgps.const import DOMAIN, VERSION

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)
REQUEST_TIMEOUT = int(SCAN_INTERVAL.total_seconds() / 2)
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

    def __init__(self, id: int) -> None:
        """Initialize the PajGPSDevice class."""
        self.id = id

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
    speed: int
    battery: int

    def __init__(self, device_id: int, lat: float, lng: float, speed: int, battery: int) -> None:
        """Initialize the PajGPSTracking class."""
        self.device_id = device_id
        self.lat = lat
        self.lng = lng
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

    # Pure json responses from API
    devices_json: str
    alerts_json: str
    positions_json: str

    # Deserialized data
    devices: list[PajGPSDevice] = []
    alerts: list[PajGPSAlert] = []
    positions: list[PajGPSPositionData] = []

    def __init__(self, entry_name: str, email: str, password: str, mark_alerts_as_read: bool) -> None:
        """
        Initialize the PajGPSData class.
        """
        self.entry_name = entry_name
        self.email = email
        self.password = password
        self.mark_alerts_as_read = mark_alerts_as_read

    @classmethod
    def get_instance(cls, entry_name: str, email: str, password: str, mark_alerts_as_read: bool) -> "PajGPSData":
        """
        Get or create a singleton instance of PajGPSData for the given entry_name.
        """
        if entry_name not in PajGPSDataInstances:
            PajGPSDataInstances[entry_name] = cls(entry_name, email, password, mark_alerts_as_read)
        return PajGPSDataInstances[entry_name]

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
        except Exception as e:
            _LOGGER.error(f"{e}")
            return None

    async def refresh_token(self):
        # Refresh token once every 10 minutes
        if (time.time() - self.last_token_update > self.token_ttl) or self.token is None:
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
            except Exception as e:
                _LOGGER.error(f"Error during token refresh: {e}")
        else:
            _LOGGER.debug("Token refresh skipped (still valid).")


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

    def get_device_info(self, device_id: int) -> DeviceInfo | None:
        """Get device info by id."""
        for device in self.devices:
            if device.id == device_id:
                dev_info = DeviceInfo(
                    identifiers={
                        (DOMAIN,
                         f"{self.entry_name_identifier()}-{device.id}",)
                    },
                    name=f"{device.name} ({device.id})",
                    manufacturer="PAJ GPS",
                    model=device.model,
                    sw_version=VERSION,
                )
                return dev_info
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
                    device["speed"],
                    device["battery"]
                ) for device in json["success"]
            ]
            self.positions = new_positions
        except ApiError as e:
            _LOGGER.error(f"Error while getting tracking data: {e.error}")
        except Exception as e:
            _LOGGER.error(f"{e}")


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
        except Exception as e:
            _LOGGER.error(f"{e}")

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
                device_data.alarm_sos_enabled = device["alarmsos"] == 1
                device_data.alarm_shock_enabled = device["alarmbewegung"] == 1
                device_data.alarm_voltage_enabled = device["alarm_volt"] == 1
                new_devices.append(device_data)
            self.devices = new_devices
        except ApiError as e:
            _LOGGER.error(f"Error while getting devices data: {e.error}")
        except Exception as e:
            _LOGGER.error(f"{e}")


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
            except Exception as e:
                _LOGGER.error(f"{e}")

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
        alert_name: str = ""
        if alert_type == 1:                 # Shock Alert
            alert_name = "alarmbewegung"
        elif alert_type == 4:               # SOS Alert
            alert_name = "alarmsos"
        elif alert_type == 13:              # Voltage Alert
            alert_name = "alarm_volt"
        else:
            _LOGGER.error(f"Unknown alert type: {alert_type}")
            return

        state_int = 1 if state else 0

        url = API_URL + "device/" + str(device_id)
        headers = self.get_standard_headers()
        payload = {
            alert_name: state_int
        }
        try:
            await self.make_put_request(url, headers, payload=payload)
            _LOGGER.debug(f"Alert {alert_name} for device {device_id} set to {state_int}.")
        except ApiError as e:
            _LOGGER.error(f"Error while changing alert state: {e.error}")
        except Exception as e:
            _LOGGER.error(f"{e}")

    def email_as_identifier(self) -> str:
        """
        Convert email to identifier for the device registry.
        This is used to create a unique identifier for the device in the device registry.
        The "@" character is replaced with "_at_" to avoid issues with the device registry.
        The "." character is replaced with "_" to avoid issues with the device registry.
        """
        return self.email.replace("@", "_at_").replace(".", "_")

    def entry_name_identifier(self) -> str:
        """
        Convert entry name to identifier for the device registry.
        This is used to create a unique identifier for the device in the device registry.
        The " " character is replaced with "_" to avoid issues with the device registry.
        The whole string will be converted to lowercase to avoid issues with the device registry.
        """
        return self.entry_name.replace(" ", "_").lower()