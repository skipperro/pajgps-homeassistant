"""
Tests for entity setup of alert switches and binary sensors, and for
device model resolution in get_device_info.

Covers:
- get_device_info reads model from device.device_models[0]["model"]
- get_device_info falls back to "Unknown" when device_models is empty or None
- async_setup_entry (switch + binary_sensor) creates an entity when a supported
  alert field is 0 (disabled) — not just when it is truthy
- async_setup_entry does NOT create an entity when an alert field is None
  (meaning the device does not support that alert type at all)
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.pajgps.coordinator_data import CoordinatorData
from custom_components.pajgps.const import ALERT_TYPE_TO_DEVICE_FIELD

from .test_common import make_coordinator, make_device, make_entry_data


# ---------------------------------------------------------------------------
# get_device_info — device model resolution
# ---------------------------------------------------------------------------

class TestGetDeviceInfoModel(unittest.TestCase):
    """Verify that get_device_info reads the model from device.device_models."""

    def _make_coord_with_device(self, device):
        coord = make_coordinator()
        coord.data = CoordinatorData(devices=[device])
        return coord

    def test_model_read_from_device_models_first_entry(self):
        """Model should come from device_models[0]['model']."""
        device = make_device(1, device_models=[{"model": "PAJ ALLROUND Finder 4G"}])
        coord = self._make_coord_with_device(device)

        info = coord.get_device_info(1)

        self.assertEqual(info["model"], "PAJ ALLROUND Finder 4G")

    def test_model_falls_back_to_unknown_when_device_models_is_empty_list(self):
        """When device_models is an empty list there is no model entry — fall back to 'Unknown'."""
        device = make_device(1, device_models=[])
        coord = self._make_coord_with_device(device)

        info = coord.get_device_info(1)

        self.assertEqual(info["model"], "Unknown")

    def test_model_falls_back_to_unknown_when_device_models_is_none(self):
        """When device_models is None fall back to 'Unknown'."""
        device = make_device(1, device_models=None)
        coord = self._make_coord_with_device(device)

        info = coord.get_device_info(1)

        self.assertEqual(info["model"], "Unknown")

    def test_model_falls_back_to_unknown_when_model_key_is_none(self):
        """When device_models[0]['model'] is None fall back to 'Unknown'."""
        device = make_device(1, device_models=[{"model": None}])
        coord = self._make_coord_with_device(device)

        info = coord.get_device_info(1)

        self.assertEqual(info["model"], "Unknown")

    def test_model_uses_first_entry_when_multiple_models_present(self):
        """Only the first entry in device_models should be used."""
        device = make_device(
            1,
            device_models=[
                {"model": "First Model"},
                {"model": "Second Model"},
            ],
        )
        coord = self._make_coord_with_device(device)

        info = coord.get_device_info(1)

        self.assertEqual(info["model"], "First Model")


# ---------------------------------------------------------------------------
# Helpers shared by switch + binary_sensor setup tests
# ---------------------------------------------------------------------------

def _make_hass_and_config_entry(coordinator):
    """Return a fake hass and config_entry wired to the given coordinator."""
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry_id"

    hass = MagicMock()
    hass.data = {"pajgps": {"test_entry_id": coordinator}}

    return hass, config_entry


# ---------------------------------------------------------------------------
# switch.async_setup_entry — entity creation rules
# ---------------------------------------------------------------------------

class TestSwitchSetupEntry(unittest.IsolatedAsyncioTestCase):
    """
    Verify that alert switch entities are created according to the
    'check presence, not truthiness' rule.
    """

    async def _run_setup(self, device):
        """Run async_setup_entry for the switch platform and return added entities."""
        from custom_components.pajgps import switch as switch_module

        coord = make_coordinator()
        coord.data = CoordinatorData(devices=[device])
        hass, config_entry = _make_hass_and_config_entry(coord)

        added_entities = []

        def fake_add(entities, **kwargs):
            added_entities.extend(entities)

        await switch_module.async_setup_entry(hass, config_entry, fake_add)
        return added_entities

    async def test_entity_created_when_alert_field_is_zero(self):
        """
        A value of 0 means the alert is supported but currently disabled.
        An entity MUST still be created.
        """
        # All alert fields set to 0 (supported but disabled)
        kwargs = {field: 0 for field in ALERT_TYPE_TO_DEVICE_FIELD.values()}
        device = make_device(1, **kwargs)

        entities = await self._run_setup(device)

        self.assertEqual(len(entities), len(ALERT_TYPE_TO_DEVICE_FIELD))

    async def test_entity_created_when_alert_field_is_one(self):
        """A value of 1 means the alert is supported and enabled — entity must be created."""
        kwargs = {field: 1 for field in ALERT_TYPE_TO_DEVICE_FIELD.values()}
        device = make_device(1, **kwargs)

        entities = await self._run_setup(device)

        self.assertEqual(len(entities), len(ALERT_TYPE_TO_DEVICE_FIELD))

    async def test_no_entity_created_when_alert_field_is_none(self):
        """
        A value of None means the device does not support that alert type at all.
        No entity should be created for that type.
        """
        # All alert fields set to None (unsupported)
        kwargs = {field: None for field in ALERT_TYPE_TO_DEVICE_FIELD.values()}
        device = make_device(1, **kwargs)

        entities = await self._run_setup(device)

        self.assertEqual(len(entities), 0)

    async def test_entity_created_only_for_supported_alert_fields(self):
        """
        When only some alert fields are non-None, only those get entities.
        The zero-vs-None distinction must be respected for each field individually.
        """
        # Deliberately set first two supported fields to 0, rest to None
        fields = list(ALERT_TYPE_TO_DEVICE_FIELD.values())
        supported = set(fields[:2])
        kwargs = {f: (0 if f in supported else None) for f in fields}
        device = make_device(1, **kwargs)

        entities = await self._run_setup(device)

        self.assertEqual(len(entities), 2)

    async def test_no_entities_logged_warning_when_no_devices(self):
        """When there are no devices at all, no entities are added."""
        from custom_components.pajgps import switch as switch_module

        coord = make_coordinator()
        coord.data = CoordinatorData(devices=[])
        hass, config_entry = _make_hass_and_config_entry(coord)

        added_entities = []

        def fake_add(entities, **kwargs):
            added_entities.extend(entities)  # pragma: no cover

        with patch("custom_components.pajgps.switch._LOGGER") as mock_logger:
            await switch_module.async_setup_entry(hass, config_entry, fake_add)
            mock_logger.warning.assert_called_once()

        self.assertEqual(len(added_entities), 0)


# ---------------------------------------------------------------------------
# binary_sensor.async_setup_entry — entity creation rules
# ---------------------------------------------------------------------------

class TestBinarySensorSetupEntry(unittest.IsolatedAsyncioTestCase):
    """
    Verify that alert binary sensor entities are created according to the
    'check presence, not truthiness' rule.
    """

    async def _run_setup(self, device):
        """Run async_setup_entry for the binary_sensor platform and return added entities."""
        from custom_components.pajgps import binary_sensor as bs_module

        coord = make_coordinator()
        coord.data = CoordinatorData(devices=[device])
        hass, config_entry = _make_hass_and_config_entry(coord)

        added_entities = []

        def fake_add(entities, **kwargs):
            added_entities.extend(entities)

        await bs_module.async_setup_entry(hass, config_entry, fake_add)
        return added_entities

    async def test_entity_created_when_alert_field_is_zero(self):
        """
        A value of 0 means the alert is supported but currently disabled.
        A binary sensor entity MUST still be created.
        """
        kwargs = {field: 0 for field in ALERT_TYPE_TO_DEVICE_FIELD.values()}
        device = make_device(1, **kwargs)

        entities = await self._run_setup(device)

        self.assertEqual(len(entities), len(ALERT_TYPE_TO_DEVICE_FIELD))

    async def test_entity_created_when_alert_field_is_one(self):
        """A value of 1 means the alert is supported and enabled — entity must be created."""
        kwargs = {field: 1 for field in ALERT_TYPE_TO_DEVICE_FIELD.values()}
        device = make_device(1, **kwargs)

        entities = await self._run_setup(device)

        self.assertEqual(len(entities), len(ALERT_TYPE_TO_DEVICE_FIELD))

    async def test_no_entity_created_when_alert_field_is_none(self):
        """
        A value of None means the device does not support that alert type at all.
        No binary sensor entity should be created for that type.
        """
        kwargs = {field: None for field in ALERT_TYPE_TO_DEVICE_FIELD.values()}
        device = make_device(1, **kwargs)

        entities = await self._run_setup(device)

        self.assertEqual(len(entities), 0)

    async def test_entity_created_only_for_supported_alert_fields(self):
        """
        When only some alert fields are non-None, only those get entities.
        The zero-vs-None distinction must be respected for each field individually.
        """
        fields = list(ALERT_TYPE_TO_DEVICE_FIELD.values())
        supported = set(fields[:3])
        kwargs = {f: (0 if f in supported else None) for f in fields}
        device = make_device(1, **kwargs)

        entities = await self._run_setup(device)

        self.assertEqual(len(entities), 3)

    async def test_no_entities_logged_warning_when_no_devices(self):
        """When there are no devices at all, no entities are added and a warning is logged."""
        from custom_components.pajgps import binary_sensor as bs_module

        coord = make_coordinator()
        coord.data = CoordinatorData(devices=[])
        hass, config_entry = _make_hass_and_config_entry(coord)

        added_entities = []

        def fake_add(entities, **kwargs):
            added_entities.extend(entities)  # pragma: no cover

        with patch("custom_components.pajgps.binary_sensor._LOGGER") as mock_logger:
            await bs_module.async_setup_entry(hass, config_entry, fake_add)
            mock_logger.warning.assert_called_once()

        self.assertEqual(len(added_entities), 0)
