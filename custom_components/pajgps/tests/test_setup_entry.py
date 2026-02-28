"""
Unit tests for __init__.py async_setup_entry.

Coverage:
- cannot_connect → raises ConfigEntryNotReady before coordinator is created
- invalid_auth   → raises ConfigEntryNotReady before coordinator is created
- valid credentials + coordinator success → returns True, runtime_data set
- valid credentials + coordinator first-refresh fails → raises ConfigEntryNotReady
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.exceptions import ConfigEntryNotReady


def _make_mock_entry(email: str = "user@example.com", password: str = "secret") -> MagicMock:
    """Return a minimal mock ConfigEntry."""
    entry = MagicMock()
    entry.data = {
        "guid": "test-guid",
        "entry_name": "Test",
        "email": email,
        "password": password,
        "mark_alerts_as_read": False,
        "fetch_elevation": False,
        "force_battery": False,
    }
    entry.async_on_unload = MagicMock()
    entry.add_update_listener = MagicMock(return_value=MagicMock())
    return entry


class TestAsyncSetupEntry(unittest.IsolatedAsyncioTestCase):
    """Tests for async_setup_entry in __init__.py."""

    async def test_cannot_connect_raises_config_entry_not_ready(self):
        """When API is unreachable, setup must raise ConfigEntryNotReady immediately."""
        from custom_components.pajgps import async_setup_entry

        hass = MagicMock()
        entry = _make_mock_entry()

        with patch(
            "custom_components.pajgps._validate_credentials",
            new=AsyncMock(return_value="cannot_connect"),
        ):
            with self.assertRaises(ConfigEntryNotReady) as ctx:
                await async_setup_entry(hass, entry)

        self.assertIn("PAJ GPS API", str(ctx.exception))

    async def test_invalid_auth_raises_config_entry_not_ready(self):
        """When credentials are wrong, setup must raise ConfigEntryNotReady immediately."""
        from custom_components.pajgps import async_setup_entry

        hass = MagicMock()
        entry = _make_mock_entry()

        with patch(
            "custom_components.pajgps._validate_credentials",
            new=AsyncMock(return_value="invalid_auth"),
        ):
            with self.assertRaises(ConfigEntryNotReady) as ctx:
                await async_setup_entry(hass, entry)

        self.assertIn("credentials", str(ctx.exception))

    async def test_coordinator_not_created_on_cannot_connect(self):
        """PajGpsCoordinator must never be instantiated when credentials fail."""
        from custom_components.pajgps import async_setup_entry

        hass = MagicMock()
        entry = _make_mock_entry()

        with patch(
            "custom_components.pajgps._validate_credentials",
            new=AsyncMock(return_value="cannot_connect"),
        ), patch("custom_components.pajgps.PajGpsCoordinator") as MockCoord:
            with self.assertRaises(ConfigEntryNotReady):
                await async_setup_entry(hass, entry)

        MockCoord.assert_not_called()

    async def test_coordinator_not_created_on_invalid_auth(self):
        """PajGpsCoordinator must never be instantiated when credentials are invalid."""
        from custom_components.pajgps import async_setup_entry

        hass = MagicMock()
        entry = _make_mock_entry()

        with patch(
            "custom_components.pajgps._validate_credentials",
            new=AsyncMock(return_value="invalid_auth"),
        ), patch("custom_components.pajgps.PajGpsCoordinator") as MockCoord:
            with self.assertRaises(ConfigEntryNotReady):
                await async_setup_entry(hass, entry)

        MockCoord.assert_not_called()

    async def test_valid_credentials_completes_setup(self):
        """Valid credentials and a healthy coordinator must return True."""
        from custom_components.pajgps import async_setup_entry

        hass = MagicMock()
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        entry = _make_mock_entry()

        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()

        with patch(
            "custom_components.pajgps._validate_credentials",
            new=AsyncMock(return_value=None),
        ), patch(
            "custom_components.pajgps.PajGpsCoordinator",
            return_value=mock_coordinator,
        ):
            result = await async_setup_entry(hass, entry)

        self.assertTrue(result)

    async def test_valid_credentials_sets_runtime_data(self):
        """The coordinator must be stored in entry.runtime_data on success."""
        from custom_components.pajgps import async_setup_entry

        hass = MagicMock()
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        entry = _make_mock_entry()

        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()

        with patch(
            "custom_components.pajgps._validate_credentials",
            new=AsyncMock(return_value=None),
        ), patch(
            "custom_components.pajgps.PajGpsCoordinator",
            return_value=mock_coordinator,
        ):
            await async_setup_entry(hass, entry)

        self.assertEqual(entry.runtime_data, mock_coordinator)

    async def test_coordinator_first_refresh_failure_raises_config_entry_not_ready(self):
        """If coordinator's first refresh fails, ConfigEntryNotReady must propagate."""
        from custom_components.pajgps import async_setup_entry

        hass = MagicMock()
        entry = _make_mock_entry()

        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock(
            side_effect=ConfigEntryNotReady("refresh failed")
        )

        with patch(
            "custom_components.pajgps._validate_credentials",
            new=AsyncMock(return_value=None),
        ), patch(
            "custom_components.pajgps.PajGpsCoordinator",
            return_value=mock_coordinator,
        ):
            with self.assertRaises(ConfigEntryNotReady):
                await async_setup_entry(hass, entry)
