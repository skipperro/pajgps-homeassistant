import os
import time
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import custom_components.pajgps.pajgps_data as pajgps_data
from dotenv import load_dotenv

class PajGpsDataTest(unittest.IsolatedAsyncioTestCase):

    data: pajgps_data.PajGPSData

    def setUp(self) -> None:
        """
        This function is called before each test case.
        """
        load_dotenv()
        email = os.getenv('PAJGPS_EMAIL')
        password = os.getenv('PAJGPS_PASSWORD')
        entry_name = "test_entry"
        pajgps_data.PajGPSData.clean_instances()
        self.data = pajgps_data.PajGPSData.get_instance("test-guid", entry_name, email, password, False, False, False)


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

        pajgps_data.PajGPSData.clean_instances()
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
        pajgps_data.PajGPSData.clean_instances()
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