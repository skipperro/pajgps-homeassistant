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
from custom_components.pajgps.api import auth, devices, alerts, sensors, positions
from custom_components.pajgps import models, requests

MIN_ELEVATION_UPDATE_DELAY = 60 * 5 # Minimum delay between elevation updates for the same device in seconds (5 minutes)
_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)
API_URL = "https://connect.paj-gps.de/api/v1/"

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
    devices_json: dict
    alerts_json: dict
    positions_json: dict

    # Deserialized data
    devices: list[models.PajGPSDevice]
    alerts: list[models.PajGPSAlert]
    positions: list[models.PajGPSPositionData]
    sensors: list[models.PajGPSSensorData]


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

    async def refresh_token(self, forced: bool = False) -> None:
        """Refresh the bearer token via api/auth, updating local state."""
        self.token, self.last_token_update = await auth.refresh_token(
            current_token=self.token,
            last_token_update=self.last_token_update,
            token_ttl=self.token_ttl,
            email=self.email,
            password=self.password,
            forced=forced,
        )

    def clean_data(self):
        self.devices = []
        self.alerts = []
        self.positions = []

    def get_standard_headers(self) -> dict:
        """Get standard headers for API requests."""
        return auth.get_standard_headers(self.token)


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
        if not await requests.check_pajgps_availability():
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


    def get_device(self, device_id: int) -> models.PajGPSDevice | None:
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

    def get_position(self, device_id: int) -> models.PajGPSPositionData | None:
        """Get position data by device id."""
        for position in self.positions:
            if position.device_id == device_id:
                return position
        return None

    def get_sensors(self, device_id: int) -> models.PajGPSSensorData | None:
        """Get sensor data by device id."""
        for sensor in self.sensors:
            if sensor.device_id == device_id:
                return sensor
        return None

    def get_alerts(self, device_id: int) -> list[models.PajGPSAlert]:
        """Get alerts by device id."""
        return [alert for alert in self.alerts if alert.device_id == device_id]

    async def update_position_data(self) -> None:
        """Fetch last positions for all devices and schedule elevation updates for moved devices."""
        new_positions, raw_json = await positions.fetch_positions(
            self.get_device_ids(), self.get_standard_headers()
        )

        if raw_json is not None:
            self.positions_json = raw_json

        if self.fetch_elevation:
            moved_ids = positions.find_moved_device_ids(new_positions, self.positions)
            for device_id in moved_ids:
                old = self.get_position(device_id)
                if old is not None and (time.time() - old.last_elevation_update) <= MIN_ELEVATION_UPDATE_DELAY:
                    continue
                new_pos = next((p for p in new_positions if p.device_id == device_id), None)
                if new_pos is None:
                    continue
                if old is not None:
                    old.last_elevation_update = time.time()
                task = asyncio.create_task(self._update_elevation_for(device_id, new_pos))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)

        self.positions = new_positions

    async def _update_elevation_for(self, device_id: int, position: models.PajGPSPositionData) -> None:
        """Fetch elevation for a single position and store the result."""
        elevation = await positions.fetch_elevation(device_id, position)
        live = self.get_position(device_id)
        target = live if live is not None else position
        target.elevation = elevation
        target.lat = round(position.lat, 5)
        target.lng = round(position.lng, 5)



    async def update_devices_data(self) -> None:
        """Fetch device list from the API and update self.devices."""
        new_devices, raw_json = await devices.fetch_devices(self.get_standard_headers())
        if raw_json is not None:
            self.devices_json = raw_json
        self.devices = new_devices

    async def update_sensors_data(self) -> None:
        """Fetch sensor data for all known devices and update self.sensors."""
        self.sensors = await sensors.fetch_sensors(self.devices, self.get_standard_headers())

    async def update_alerts_data(self) -> None:
        """Fetch unread alerts and optionally schedule marking them as read."""
        new_alerts, raw_json = await alerts.fetch_alerts(self.get_standard_headers())

        if raw_json is not None:
            self.alerts_json = raw_json

        self.alerts = new_alerts

        if new_alerts and self.mark_alerts_as_read:
            alert_ids = [alert.alert_type for alert in new_alerts]
            task = asyncio.create_task(self.consume_alerts(alert_ids))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def consume_alerts(self, alert_ids: list[int]) -> None:
        """Mark the given alert types as read in the API."""
        await alerts.consume_alerts(alert_ids, self.get_standard_headers())

    async def change_alert_state(self, device_id: int, alert_type: int, state: bool) -> None:
        """Enable or disable an alert type for a device."""
        device = self.get_device(device_id)
        if device is None:
            _LOGGER.error("Device not found: %s", device_id)
            return
        await alerts.change_alert_state(device, alert_type, state, self.get_standard_headers())
