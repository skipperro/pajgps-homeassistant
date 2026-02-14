import os
import time
import asyncio
import unittest
from unittest.mock import AsyncMock, patch
import custom_components.pajgps.pajgps_data as pajgps_data
from dotenv import load_dotenv

class PajGpsDataTest(unittest.IsolatedAsyncioTestCase):

    data: pajgps_data.PajGPSData

    async def asyncSetUp(self) -> None:
        """
        This function is called before each test case.
        """
        load_dotenv()
        email = os.getenv('PAJGPS_EMAIL')
        password = os.getenv('PAJGPS_PASSWORD')
        entry_name = "test_entry"
        await pajgps_data.PajGPSData.clean_instances()
        self.data = pajgps_data.PajGPSData.get_instance("test-guid", entry_name, email, password, False, False, False)

    async def asyncTearDown(self) -> None:
        """
        This function is called after each test case.
        """
        await self.data.async_close()
        await pajgps_data.PajGPSData.clean_instances()


    async def test_login(self):
        """
        Test if credentials are set and if login token is valid.
        """
        assert self.data.email is not None
        assert self.data.password is not None
        if self.data.email is None or self.data.password is None:
            return
        # Test login with valid credentials
        token = await self.data.get_login_token()
        assert token is not None
        # Test if login token is valid bearer header
        if token is not None:
            assert len(token) > 20

    async def test_refresh_token(self):
        """
        Test the refresh_token method.
        """
        with patch.object(self.data, 'get_login_token', new=AsyncMock(return_value="new_token")):
            self.data.token = None
            await self.data.refresh_token()
            assert self.data.token == "new_token"

    async def test_async_update(self):
        """
        Test the async_update method.
        """
        with (patch.object(self.data, 'refresh_token', new=AsyncMock()), \
             patch.object(self.data, 'update_position_data', new=AsyncMock()), \
             patch.object(self.data, 'update_alerts_data', new=AsyncMock()), \
             patch.object(self.data, 'update_devices_data', new=AsyncMock())):
            self.data.token = "test_token"
            await self.data.refresh_token()
            await self.data.async_update()
            assert self.data.last_update > 0


    def test_get_standard_headers(self):
        """
        Test the get_standard_headers method.
        """
        self.data.token = "test_token"
        headers = self.data.get_standard_headers()
        assert headers["Authorization"] == "Bearer test_token"
        assert headers["accept"] == "application/json"

    async def test_refresh_token_skipped(self):
        """
        Test that refresh_token skips refreshing if the token is still valid.
        """
        self.data.token = "valid_token"
        self.data.last_token_update = time.time()
        with patch.object(self.data, 'get_login_token', new=AsyncMock()) as mock_get_login_token:
            await self.data.refresh_token()
            mock_get_login_token.assert_not_called()

    async def test_two_instances(self):
        """
        Test that two instances of PajGPSData are created with different entry names.
        """
        entry_name_1 = "test_entry_1"
        entry_name_2 = "test_entry_2"
        email_1 = "email_1@email.com"
        email_2 = "email_2@email.com"
        password_1 = "password_1"
        password_2 = "password_2"

        await pajgps_data.PajGPSData.clean_instances()
        data_1 = pajgps_data.PajGPSData.get_instance("guid1", entry_name_1, email_1, password_1, False, False, False)
        data_2 = pajgps_data.PajGPSData.get_instance("guid2", entry_name_2, email_2, password_2, False, False, False)
        assert data_1 is not data_2
        assert data_1.guid != data_2.guid
        assert data_1.entry_name != data_2.entry_name
        assert data_1.email != data_2.email
        assert data_1.password != data_2.password

    async def test_singleton(self):
        """
        Test that only one instance of PajGPSData is created with the same entry name.
        """
        entry_name = "test_entry"
        email = "email@email.com"
        password = "password"
        await pajgps_data.PajGPSData.clean_instances()
        data_1 = pajgps_data.PajGPSData.get_instance("guid1", entry_name, email, password, False, False, False)
        data_2 = pajgps_data.PajGPSData.get_instance("guid1", entry_name, email, password, False, False, False)
        assert data_1 is data_2
        assert data_1.guid == data_2.guid
        assert data_1.entry_name == data_2.entry_name
        assert data_1.email == data_2.email
        assert data_1.password == data_2.password
        # Test if changes in one instance are reflected in the other
        data_1.token = "should_be_same_token"
        assert data_2.token == "should_be_same_token"

    async def test_update_data(self):
        """
        Test the update_position_data method.
        """
        await self.data.refresh_token()
        await self.data.update_devices_data()
        assert self.data.devices is not None
        assert len(self.data.devices) > 0
        for dev in self.data.devices:
            assert dev.id is not None
            assert dev.name is not None
            assert dev.imei is not None
            assert dev.has_battery is not None

        assert self.data.get_device_ids() is not None
        assert len(self.data.get_device_ids()) > 0

        await self.data.update_position_data()
        assert self.data.positions is not None
        assert len(self.data.positions) > 0
        for pos in self.data.positions:
            assert pos.lat is not None
            assert pos.lng is not None
            assert pos.speed is not None
            assert pos.battery is not None

        # Mock the make_get_request to test the update_alerts_data method without data from api
        with patch.object(self.data, 'make_get_request', new=AsyncMock(return_value={"success": [
                {
                  "id": 1,
                  "iddevice": 1,
                  "meldungtyp": 2,
                },
                {
                  "id": 2,
                  "iddevice": 2,
                  "meldungtyp": 3,
                }
              ]})):
            await self.data.update_alerts_data()
            assert self.data.alerts is not None
            assert len(self.data.alerts) == 2
            assert self.data.alerts[0].device_id == 1
            assert self.data.alerts[0].alert_type == 2
            assert self.data.alerts[1].device_id == 2
            assert self.data.alerts[1].alert_type == 3

    async def test_elevation(self):
        """
        Test the elevation data.
        """
        await self.data.refresh_token()
        await self.data.async_update()
        # Update the elevation data for the first device
        device_id = self.data.get_device_ids()[0]
        device = self.data.get_device(device_id)
        assert device is not None
        await self.data.update_elevation(device_id)
        position = self.data.get_position(device_id)
        assert position is not None
        assert position.elevation is not None

    async def test_voltage_sensor(self):
        """
        Test the voltage sensor data.
        """
        await self.data.refresh_token()
        await self.data.async_update()
        # Check if any device has voltage data
        found_voltage = False
        for device_id in self.data.get_device_ids():
            sensors = self.data.get_sensors(device_id)
            if sensors is not None and sensors.voltage is not None:
                found_voltage = True
                print(f"Device ID: {device_id}, Voltage: {sensors.voltage}V")
                assert sensors.voltage >= 0.0
            else:
                print(f"Device ID: {device_id} has no voltage data")
        assert found_voltage, "No device with voltage data found"

    async def test_get_alerts_from_api(self):
        """
        Test getting alerts from real API (read-only, no modifications).
        """
        await self.data.refresh_token()
        await self.data.update_devices_data()
        await self.data.update_alerts_data()

        # Alerts should be a list (can be empty)
        assert self.data.alerts is not None
        assert isinstance(self.data.alerts, list)

        # If there are alerts, check their structure
        for alert in self.data.alerts:
            assert isinstance(alert, pajgps_data.PajGPSAlert)
            assert alert.device_id is not None
            assert alert.alert_type is not None
            assert alert.alert_type in [1, 2, 4, 5, 6, 7, 9, 13]  # Valid alert types

    async def test_get_alerts_by_device(self):
        """
        Test filtering alerts by device_id.
        """
        await self.data.refresh_token()
        await self.data.update_devices_data()

        if len(self.data.devices) > 0:
            device_id = self.data.get_device_ids()[0]

            # Mock alerts for testing
            self.data.alerts = [
                pajgps_data.PajGPSAlert(device_id, 2),
                pajgps_data.PajGPSAlert(device_id, 4),
                pajgps_data.PajGPSAlert(999999, 5),  # Different device
            ]

            device_alerts = self.data.get_alerts(device_id)
            assert len(device_alerts) == 2
            for alert in device_alerts:
                assert alert.device_id == device_id

    async def test_device_is_alert_enabled(self):
        """
        Test the is_alert_enabled method for devices (read-only).
        """
        await self.data.refresh_token()
        await self.data.update_devices_data()

        assert len(self.data.devices) > 0
        device = self.data.devices[0]

        # Test all alert types
        alert_types = [1, 2, 4, 5, 6, 7, 9, 13]
        for alert_type in alert_types:
            # Should return boolean without throwing error
            result = device.is_alert_enabled(alert_type)
            assert isinstance(result, bool)

        # Test invalid alert type
        result = device.is_alert_enabled(999)
        assert result == False

    async def test_get_device_info(self):
        """
        Test the get_device_info method for device registry.
        """
        await self.data.refresh_token()
        await self.data.update_devices_data()

        assert len(self.data.devices) > 0
        device_id = self.data.get_device_ids()[0]

        device_info = self.data.get_device_info(device_id)
        assert device_info is not None
        assert "identifiers" in device_info
        assert "name" in device_info
        assert "manufacturer" in device_info
        assert device_info["manufacturer"] == "PAJ GPS"
        assert "model" in device_info
        assert "sw_version" in device_info

        # Test with non-existent device
        device_info = self.data.get_device_info(999999)
        assert device_info is None

    async def test_get_device_by_id(self):
        """
        Test the get_device method.
        """
        await self.data.refresh_token()
        await self.data.update_devices_data()

        assert len(self.data.devices) > 0
        device_id = self.data.get_device_ids()[0]

        device = self.data.get_device(device_id)
        assert device is not None
        assert device.id == device_id
        assert device.name is not None
        assert device.imei is not None

        # Test with non-existent device
        device = self.data.get_device(999999)
        assert device is None

    async def test_get_position_by_device_id(self):
        """
        Test the get_position method.
        """
        await self.data.refresh_token()
        await self.data.update_devices_data()
        await self.data.update_position_data()

        assert len(self.data.positions) > 0
        device_id = self.data.get_device_ids()[0]

        position = self.data.get_position(device_id)
        assert position is not None
        assert position.device_id == device_id
        assert position.lat is not None
        assert position.lng is not None
        assert position.speed is not None
        assert position.battery is not None

        # Test with non-existent device
        position = self.data.get_position(999999)
        assert position is None

    async def test_data_ttl(self):
        """
        Test that async_update respects data_ttl.
        """
        await self.data.refresh_token()

        # First update
        await self.data.async_update(forced=True)
        first_update_time = self.data.last_update

        # Immediate second update (should be skipped due to TTL)
        with patch.object(self.data, 'update_devices_data', new=AsyncMock()) as mock_update:
            await self.data.async_update(forced=False)
            mock_update.assert_not_called()

        # Update time should not change
        assert self.data.last_update == first_update_time

        # Forced update should work
        await self.data.async_update(forced=True)
        assert self.data.last_update > first_update_time

    async def test_clean_data(self):
        """
        Test the clean_data method.
        """
        await self.data.refresh_token()
        await self.data.update_devices_data()
        await self.data.update_position_data()

        assert len(self.data.devices) > 0
        assert len(self.data.positions) > 0

        self.data.clean_data()

        assert len(self.data.devices) == 0
        assert len(self.data.positions) == 0
        assert len(self.data.alerts) == 0

    async def test_api_error_handling(self):
        """
        Test handling of API errors.
        """
        # Mock an API error response
        with patch.object(self.data, 'make_get_request',
                         new=AsyncMock(side_effect=pajgps_data.ApiError({"error": "Test error"}))):
            await self.data.update_devices_data()
            # Should handle error gracefully and set devices to empty list
            assert self.data.devices == []

    async def test_timeout_handling(self):
        """
        Test handling of timeout errors.
        """
        # Mock a timeout
        with patch.object(self.data, 'make_get_request',
                         new=AsyncMock(side_effect=TimeoutError())):
            await self.data.update_position_data()
            # Should handle timeout gracefully and set positions to empty list
            assert self.data.positions == []

    async def test_session_reuse(self):
        """
        Test that the same session is reused across multiple requests.
        """
        await self.data.refresh_token()

        session1 = await self.data._get_session()
        session2 = await self.data._get_session()

        # Should be the same session object
        assert session1 is session2
        assert not session1.closed

    async def test_session_recreation_after_close(self):
        """
        Test that session is recreated after being closed.
        """
        await self.data.refresh_token()

        session1 = await self.data._get_session()
        await self.data.async_close()

        # Session should be closed
        assert session1.closed

        # New session should be created
        session2 = await self.data._get_session()
        assert session2 is not session1
        assert not session2.closed

    async def test_background_tasks_tracking(self):
        """
        Test that background tasks are properly tracked.
        """
        await self.data.refresh_token()
        await self.data.update_devices_data()

        # Mock make_get_request for alerts with mark_as_read enabled
        self.data.mark_alerts_as_read = True

        with patch.object(self.data, 'make_get_request',
                         new=AsyncMock(return_value={"success": [{"iddevice": 1, "meldungtyp": 2}]})):
            with patch.object(self.data, 'make_put_request', new=AsyncMock(return_value={"success": True})):
                await self.data.update_alerts_data()

                # Give background tasks a moment to start
                await asyncio.sleep(0.1)

                # Background tasks should complete quickly
                if self.data._background_tasks:
                    await asyncio.gather(*self.data._background_tasks, return_exceptions=True)

                # After completion, background tasks should be cleaned up
                assert len(self.data._background_tasks) == 0

    async def test_position_data_structure(self):
        """
        Test the structure of position data.
        """
        await self.data.refresh_token()
        await self.data.update_devices_data()
        await self.data.update_position_data()

        assert len(self.data.positions) > 0

        for position in self.data.positions:
            assert isinstance(position, pajgps_data.PajGPSPositionData)
            assert isinstance(position.lat, (int, float))
            assert isinstance(position.lng, (int, float))
            assert isinstance(position.direction, int)
            assert isinstance(position.speed, int)
            assert isinstance(position.battery, int)
            assert -90 <= position.lat <= 90
            assert -180 <= position.lng <= 180
            assert 0 <= position.direction <= 360
            assert position.speed >= 0
            assert 0 <= position.battery <= 100

    async def test_device_data_structure(self):
        """
        Test the structure of device data.
        """
        await self.data.refresh_token()
        await self.data.update_devices_data()

        assert len(self.data.devices) > 0

        for device in self.data.devices:
            assert isinstance(device, pajgps_data.PajGPSDevice)
            assert isinstance(device.id, int)
            assert isinstance(device.name, str)
            assert isinstance(device.imei, str)
            assert isinstance(device.model, str)
            assert isinstance(device.has_battery, bool)
            # Check alarm capabilities are booleans
            assert isinstance(device.has_alarm_sos, bool)
            assert isinstance(device.has_alarm_shock, bool)
            assert isinstance(device.has_alarm_voltage, bool)
            assert isinstance(device.has_alarm_battery, bool)
            assert isinstance(device.has_alarm_speed, bool)
            assert isinstance(device.has_alarm_power_cutoff, bool)
            assert isinstance(device.has_alarm_ignition, bool)
            assert isinstance(device.has_alarm_drop, bool)

    async def test_multiple_updates_in_sequence(self):
        """
        Test multiple sequential updates work correctly.
        """
        await self.data.refresh_token()

        # First update
        await self.data.async_update(forced=True)
        devices_count_1 = len(self.data.devices)
        positions_count_1 = len(self.data.positions)

        # Second update (forced)
        await self.data.async_update(forced=True)
        devices_count_2 = len(self.data.devices)
        positions_count_2 = len(self.data.positions)

        # Should have data after both updates
        assert devices_count_1 > 0
        assert devices_count_2 > 0
        assert positions_count_1 > 0
        assert positions_count_2 > 0

    async def test_update_time_sensors(self):
        """
        Test the update time measurements in sensor data.
        """
        await self.data.refresh_token()
        await self.data.async_update(forced=True)

        # Check that total update time was measured
        assert self.data.total_update_time_ms > 0
        print(f"Total update time: {self.data.total_update_time_ms:.2f}ms")

        # Check that each device has update time measurements
        for device_id in self.data.get_device_ids():
            sensors = self.data.get_sensors(device_id)
            assert sensors is not None

            # Check device update time
            assert sensors.device_update_time_ms >= 0
            print(f"Device {device_id} update time: {sensors.device_update_time_ms:.2f}ms")

            # Check total update time (should be same for all devices)
            assert sensors.total_update_time_ms == self.data.total_update_time_ms
            print(f"Device {device_id} total update time: {sensors.total_update_time_ms:.2f}ms")

        # Verify that total update time is greater than individual device times
        # (since it includes all API calls)
        if len(self.data.sensors) > 0:
            max_device_time = max(s.device_update_time_ms for s in self.data.sensors)
            assert self.data.total_update_time_ms >= max_device_time

