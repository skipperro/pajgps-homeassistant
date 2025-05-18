import os
import unittest
import custom_components.pajgps.device_tracker_old as tracker
from dotenv import load_dotenv

class PajGpsTrackerTest(unittest.IsolatedAsyncioTestCase):

    email = None
    password = None

    def setUp(self) -> None:
        # Get credentials from .env file in root directory
        load_dotenv()
        self.email = os.getenv('PAJGPS_EMAIL')
        self.password = os.getenv('PAJGPS_PASSWORD')


    async def test_login(self):
        # Test if credentials are set
        assert self.email != None
        assert self.password != None
        if self.email == None or self.password == None:
            return
        # Test login with valid credentials
        token = await tracker.get_login_token(self.email, self.password)
        assert token != None
        # Test if login token is valid bearer header
        if token != None:
            assert len(token) > 20

    async def test_get_devices(self):
        # Get Authoization token
        token = await tracker.get_login_token(self.email, self.password)
        assert token != None
        if token == None:
            return
        # Test if get_devices returns a list of devices
        devices = await tracker.get_devices(token)
        assert devices is not None


    async def test_get_device_data(self):
        # Get Authoization token
        token = await tracker.get_login_token(self.email, self.password)
        assert token != None
        if token == None:
            return
        # Get devices
        devices = await tracker.get_devices(token)
        assert devices != None
        if devices == None:
            return
        # Test if get_device_data returns a list of device data
        for device in devices:
            device_data = await tracker.get_device_data(token, device)
            assert device_data != None
