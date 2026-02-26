"""
Unit tests for PajGpsCoordinator.

Tests are grouped by the concept they exercise:
  - CoordinatorData snapshot helpers
  - DeviceRequestQueue behaviour (serialisation, duplicate protection, shutdown)
  - PajGpsCoordinator initialisation and tier scheduling
  - Each update tier (devices, positions+sensors, notifications)
  - Elevation side-effect logic
  - Alert-toggle write path (async_update_alert_state)
  - get_device_info helper
  - Full initial-refresh flow
  - Real API integration tests (require PAJGPS_EMAIL / PAJGPS_PASSWORD env vars)
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from dotenv import load_dotenv

from pajgps_api.models.device import Device
from pajgps_api.models.trackpoint import TrackPoint
from pajgps_api.models.sensordata import SensorData
from pajgps_api.models.notification import Notification
from pajgps_api.pajgps_api_error import AuthenticationError, PajGpsApiError

from custom_components.pajgps.coordinator import (
    DeviceRequestQueue,
    PajGpsCoordinator,
)
from custom_components.pajgps.coordinator_data import CoordinatorData
from custom_components.pajgps.coordinator_utils import apply_alert_flag
from custom_components.pajgps.const import (
    ALERT_TYPE_TO_DEVICE_FIELD,
    MIN_ELEVATION_DISTANCE,
    MIN_ELEVATION_UPDATE_DELAY,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_device(device_id: int = 1, **kwargs) -> Device:
    defaults = dict(
        id=device_id,
        name=f"Device {device_id}",
        imei=f"IMEI{device_id}",
        modellid=100,
        alarmbewegung=1,
        alarmakkuwarnung=1,
        alarmsos=1,
        alarmgeschwindigkeit=1,
        alarmstromunterbrechung=1,
        alarmzuendalarm=1,
        alarm_fall_enabled=1,
        alarm_volt=1,
    )
    defaults.update(kwargs)
    return Device(**defaults)


def make_trackpoint(device_id: int = 1, lat: float = 52.0, lng: float = 13.0, **kwargs) -> TrackPoint:
    defaults = dict(iddevice=device_id, lat=lat, lng=lng, speed=50, battery=80, direction=90)
    defaults.update(kwargs)
    return TrackPoint(**defaults)


def make_sensor(device_id: int = 1, volt: int = 12) -> SensorData:
    return SensorData(volt=volt, did=device_id)


def make_notification(device_id: int = 1, alert_type: int = 2, is_read: int = 0) -> Notification:
    return Notification(
        id=1, iddevice=device_id, icon="", bezeichnung="", meldungtyp=alert_type,
        dateunix=0, lat=52.0, lng=13.0, isread=is_read,
        radiusin=0, radiusout=0, zuendon=0, zuendoff=0, push=0, suppressed=0,
    )


def make_entry_data(**kwargs) -> dict:
    defaults = dict(
        guid="test-guid",
        entry_name="Test Entry",
        email="test@example.com",
        password="secret",
        mark_alerts_as_read=False,
        fetch_elevation=False,
        force_battery=False,
    )
    defaults.update(kwargs)
    return defaults


def make_coordinator(hass=None, **entry_kwargs) -> PajGpsCoordinator:
    """Build a coordinator with a mocked hass and mocked api.login."""
    if hass is None:
        hass = MagicMock()
        hass.async_create_task = lambda coro: asyncio.ensure_future(coro)
    coord = PajGpsCoordinator(hass, make_entry_data(**entry_kwargs))
    coord.api.login = AsyncMock()
    return coord


# ---------------------------------------------------------------------------
# CoordinatorData
# ---------------------------------------------------------------------------

class TestCoordinatorData(unittest.TestCase):

    def test_default_snapshot_is_empty(self):
        data = CoordinatorData()
        self.assertEqual(data.devices, [])
        self.assertEqual(data.positions, {})
        self.assertEqual(data.sensor_data, {})
        self.assertEqual(data.elevations, {})
        self.assertEqual(data.notifications, {})

    def test_replace_preserves_other_fields(self):
        device = make_device(1)
        data = CoordinatorData(devices=[device])
        tp = make_trackpoint(1)
        new_data = dataclasses.replace(data, positions={1: tp})

        self.assertEqual(new_data.devices, [device])
        self.assertEqual(new_data.positions, {1: tp})
        # Original is untouched (frozen)
        self.assertEqual(data.positions, {})

    def test_snapshot_is_immutable_via_replace(self):
        """Mutating via dataclasses.replace() creates a new object; original is unchanged."""
        device = make_device(1)
        original = CoordinatorData(devices=[device])
        updated = dataclasses.replace(original, positions={1: make_trackpoint(1)})
        # replace() returns a distinct object
        self.assertIsNot(original, updated)
        # original is untouched
        self.assertEqual(original.positions, {})
        # updated carries the new value
        self.assertIn(1, updated.positions)


# ---------------------------------------------------------------------------
# _apply_alert_flag
# ---------------------------------------------------------------------------

class TestApplyAlertFlag(unittest.TestCase):

    def test_enables_known_alert(self):
        device = make_device(1, alarmbewegung=0)
        updated = apply_alert_flag(device, alert_type=1, enabled=True)
        self.assertEqual(updated.alarmbewegung, 1)
        # Original unchanged
        self.assertEqual(device.alarmbewegung, 0)

    def test_disables_known_alert(self):
        device = make_device(1, alarmsos=1)
        updated = apply_alert_flag(device, alert_type=4, enabled=False)
        self.assertEqual(updated.alarmsos, 0)

    def test_unknown_alert_type_returns_original(self):
        device = make_device(1)
        result = apply_alert_flag(device, alert_type=999, enabled=True)
        self.assertIs(result, device)

    def test_all_alert_types_round_trip(self):
        for alert_type, field in ALERT_TYPE_TO_DEVICE_FIELD.items():
            device = make_device(1, **{field: 0})
            enabled = apply_alert_flag(device, alert_type, True)
            self.assertEqual(getattr(enabled, field), 1, f"alert_type={alert_type}")
            disabled = apply_alert_flag(enabled, alert_type, False)
            self.assertEqual(getattr(disabled, field), 0, f"alert_type={alert_type}")


# ---------------------------------------------------------------------------
# DeviceRequestQueue
# ---------------------------------------------------------------------------

class TestDeviceRequestQueue(unittest.IsolatedAsyncioTestCase):

    async def test_single_job_executed(self):
        queue = DeviceRequestQueue()
        called = []
        fut = await queue.enqueue(1, "sensor", AsyncMock(return_value="ok", side_effect=lambda: called.append(1) or "ok"))
        # Give the worker time to run
        await asyncio.sleep(0.05)
        self.assertIn(1, called)
        await queue.shutdown()

    async def test_result_returned_via_future(self):
        queue = DeviceRequestQueue()
        fut = await queue.enqueue(1, "sensor", AsyncMock(return_value="result"))
        result = await asyncio.wait_for(fut, timeout=2)
        self.assertEqual(result, "result")
        await queue.shutdown()

    async def test_duplicate_job_skipped(self):
        """Enqueueing the same job_type twice should execute it only once."""
        queue = DeviceRequestQueue()
        call_count = 0

        async def slow_job():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)
            return "done"

        fut1 = await queue.enqueue(1, "sensor", slow_job)
        fut2 = await queue.enqueue(1, "sensor", slow_job)  # duplicate — should be skipped

        r1 = await asyncio.wait_for(fut1, timeout=2)
        r2 = await asyncio.wait_for(fut2, timeout=2)

        self.assertEqual(r1, "done")
        self.assertIsNone(r2)  # pre-resolved with None
        self.assertEqual(call_count, 1)
        await queue.shutdown()

    async def test_different_job_types_both_execute(self):
        queue = DeviceRequestQueue()
        results = []

        fut1 = await queue.enqueue(1, "sensor", AsyncMock(return_value="sensor_result"))
        fut2 = await queue.enqueue(1, "notifications", AsyncMock(return_value="notif_result"))

        r1 = await asyncio.wait_for(fut1, timeout=2)
        r2 = await asyncio.wait_for(fut2, timeout=2)

        self.assertEqual(r1, "sensor_result")
        self.assertEqual(r2, "notif_result")
        await queue.shutdown()

    async def test_different_devices_run_in_parallel(self):
        """Jobs for device 1 and device 2 should not block each other."""
        queue = DeviceRequestQueue()
        start_times = {}
        end_times = {}

        async def timed_job(device_id):
            start_times[device_id] = time.monotonic()
            await asyncio.sleep(0.1)
            end_times[device_id] = time.monotonic()
            return device_id

        fut1 = await queue.enqueue(1, "sensor", lambda: timed_job(1))
        fut2 = await queue.enqueue(2, "sensor", lambda: timed_job(2))

        await asyncio.gather(
            asyncio.wait_for(fut1, timeout=2),
            asyncio.wait_for(fut2, timeout=2),
        )

        # Both should have started before either finished (parallel)
        overlap = start_times[2] < end_times[1] and start_times[1] < end_times[2]
        self.assertTrue(overlap, "Jobs for different devices should run in parallel")
        await queue.shutdown()

    async def test_exception_propagates_via_future(self):
        queue = DeviceRequestQueue()

        async def failing_job():
            raise ValueError("boom")

        fut = await queue.enqueue(1, "sensor", failing_job)
        with self.assertRaises(ValueError):
            await asyncio.wait_for(fut, timeout=2)
        await queue.shutdown()

    async def test_shutdown_cancels_workers(self):
        queue = DeviceRequestQueue()
        # Ensure a worker is created
        await queue.enqueue(1, "sensor", AsyncMock(return_value=None))
        await asyncio.sleep(0.05)
        await queue.shutdown()
        self.assertEqual(len(queue._workers), 0)


# ---------------------------------------------------------------------------
# PajGpsCoordinator — initialisation
# ---------------------------------------------------------------------------

class TestCoordinatorInit(unittest.TestCase):

    def test_initial_snapshot_is_empty(self):
        coord = make_coordinator()
        self.assertIsInstance(coord.data, CoordinatorData)
        self.assertEqual(coord.data.devices, [])

    def test_tier_timestamps_start_at_zero(self):
        coord = make_coordinator()
        self.assertEqual(coord._last_devices_fetch, 0.0)
        self.assertEqual(coord._last_positions_fetch, 0.0)
        self.assertEqual(coord._last_notifications_fetch, 0.0)

    def test_initial_refresh_done_is_false(self):
        coord = make_coordinator()
        self.assertFalse(coord._initial_refresh_done)


# ---------------------------------------------------------------------------
# PajGpsCoordinator — tier scheduling
# ---------------------------------------------------------------------------

class TestTierScheduling(unittest.IsolatedAsyncioTestCase):

    async def _make_ready_coordinator(self, **entry_kwargs) -> PajGpsCoordinator:
        """Return a coordinator whose initial refresh is already done."""
        coord = make_coordinator(**entry_kwargs)
        coord._initial_refresh_done = True
        coord.data = CoordinatorData(devices=[make_device(1)])
        return coord

    async def test_devices_tier_triggered_when_overdue(self):
        coord = await self._make_ready_coordinator()
        coord._last_devices_fetch = 0.0  # very overdue

        with patch.object(coord, '_run_devices_tier', new_callable=AsyncMock) as mock_tier:
            coord.hass.async_create_task = lambda coro: asyncio.ensure_future(coro)
            await coord._async_update_data()
            await asyncio.sleep(0.05)
            mock_tier.assert_awaited_once()

    async def test_devices_tier_not_triggered_when_fresh(self):
        coord = await self._make_ready_coordinator()
        coord._last_devices_fetch = time.monotonic()  # just fetched

        with patch.object(coord, '_run_devices_tier', new_callable=AsyncMock) as mock_tier:
            coord.hass.async_create_task = lambda coro: asyncio.ensure_future(coro)
            await coord._async_update_data()
            await asyncio.sleep(0.05)
            mock_tier.assert_not_awaited()

    async def test_notifications_tier_triggered_when_overdue(self):
        coord = await self._make_ready_coordinator()
        coord._last_notifications_fetch = 0.0

        with patch.object(coord, '_run_notifications_tier', new_callable=AsyncMock) as mock_tier:
            coord.hass.async_create_task = lambda coro: asyncio.ensure_future(coro)
            await coord._async_update_data()
            await asyncio.sleep(0.05)
            mock_tier.assert_awaited_once()

    async def test_returns_current_snapshot_on_subsequent_calls(self):
        coord = await self._make_ready_coordinator()
        coord._last_devices_fetch = time.monotonic()
        coord._last_positions_fetch = time.monotonic()
        coord._last_notifications_fetch = time.monotonic()

        result = await coord._async_update_data()
        self.assertIs(result, coord.data)

    async def test_login_failure_raises_update_failed(self):
        from homeassistant.helpers.update_coordinator import UpdateFailed
        coord = make_coordinator()
        coord.api.login = AsyncMock(side_effect=AuthenticationError("bad creds"))

        with self.assertRaises(UpdateFailed):
            await coord._async_update_data()


# ---------------------------------------------------------------------------
# PajGpsCoordinator — initial refresh
# ---------------------------------------------------------------------------

class TestInitialRefresh(unittest.IsolatedAsyncioTestCase):

    async def test_initial_refresh_runs_all_three_tiers(self):
        coord = make_coordinator()

        with (
            patch.object(coord, '_run_devices_tier', new_callable=AsyncMock) as d,
            patch.object(coord, '_run_positions_tier', new_callable=AsyncMock) as p,
            patch.object(coord, '_run_notifications_tier', new_callable=AsyncMock) as n,
        ):
            await coord._async_update_data()
            d.assert_awaited_once()
            p.assert_awaited_once()
            n.assert_awaited_once()

    async def test_initial_refresh_sets_flag(self):
        coord = make_coordinator()

        with (
            patch.object(coord, '_run_devices_tier', new_callable=AsyncMock),
            patch.object(coord, '_run_positions_tier', new_callable=AsyncMock),
            patch.object(coord, '_run_notifications_tier', new_callable=AsyncMock),
        ):
            await coord._async_update_data()
            self.assertTrue(coord._initial_refresh_done)

    async def test_initial_refresh_returns_data(self):
        coord = make_coordinator()
        coord.data = CoordinatorData(devices=[make_device(1)])

        with (
            patch.object(coord, '_run_devices_tier', new_callable=AsyncMock),
            patch.object(coord, '_run_positions_tier', new_callable=AsyncMock),
            patch.object(coord, '_run_notifications_tier', new_callable=AsyncMock),
        ):
            result = await coord._async_update_data()
            self.assertIsInstance(result, CoordinatorData)


# ---------------------------------------------------------------------------
# Tier 1 — devices
# ---------------------------------------------------------------------------

class TestDevicesTier(unittest.IsolatedAsyncioTestCase):

    async def test_devices_stored_in_snapshot(self):
        coord = make_coordinator()
        devices = [make_device(1), make_device(2)]
        coord.api.get_devices = AsyncMock(return_value=devices)

        received = []
        coord.async_set_updated_data = lambda d: received.append(d)

        await coord._run_devices_tier()

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].devices, devices)

    async def test_api_error_preserves_stale_data(self):
        coord = make_coordinator()
        coord.data = CoordinatorData(devices=[make_device(1)])
        coord.api.get_devices = AsyncMock(side_effect=PajGpsApiError("fail"))

        received = []
        coord.async_set_updated_data = lambda d: received.append(d)

        await coord._run_devices_tier()

        # async_set_updated_data should NOT have been called
        self.assertEqual(len(received), 0)
        # Existing data unchanged
        self.assertEqual(len(coord.data.devices), 1)  # type: ignore[union-attr]

    async def test_timestamp_updated_even_on_error(self):
        coord = make_coordinator()
        coord.api.get_devices = AsyncMock(side_effect=PajGpsApiError("fail"))
        coord.async_set_updated_data = MagicMock()

        before = time.monotonic()
        await coord._run_devices_tier()
        self.assertGreaterEqual(coord._last_devices_fetch, before)


# ---------------------------------------------------------------------------
# Tier 2 — positions + sensors
# ---------------------------------------------------------------------------

class TestPositionsTier(unittest.IsolatedAsyncioTestCase):

    async def _coord_with_device(self, device_id=1, **entry_kwargs) -> PajGpsCoordinator:
        coord = make_coordinator(**entry_kwargs)
        coord.data = CoordinatorData(devices=[make_device(device_id)])
        coord.api.get_all_last_positions = AsyncMock(return_value=[make_trackpoint(device_id)])
        coord.api.get_last_sensor_data = AsyncMock(return_value=make_sensor(device_id))
        return coord

    async def test_positions_pushed_immediately(self):
        coord = await self._coord_with_device(1)

        snapshots = []
        coord.async_set_updated_data = lambda d: snapshots.append(d)

        await coord._run_positions_tier()

        # First snapshot should have positions
        self.assertTrue(any(1 in s.positions for s in snapshots))

    async def test_sensor_data_pushed_per_device(self):
        coord = await self._coord_with_device(1)

        snapshots = []
        coord.async_set_updated_data = lambda d: snapshots.append(d)

        await coord._run_positions_tier()
        await asyncio.sleep(0.3)  # let queue worker flush

        self.assertTrue(any(1 in s.sensor_data for s in snapshots))

    async def test_position_api_error_does_not_push(self):
        coord = make_coordinator()
        coord.data = CoordinatorData(devices=[make_device(1)])
        coord.api.get_all_last_positions = AsyncMock(side_effect=PajGpsApiError("fail"))

        received = []
        coord.async_set_updated_data = lambda d: received.append(d)

        await coord._run_positions_tier()

        self.assertEqual(len(received), 0)

    async def test_no_devices_exits_early(self):
        coord = make_coordinator()
        coord.data = CoordinatorData(devices=[])
        coord.api.get_all_last_positions = AsyncMock()

        await coord._run_positions_tier()

        coord.api.get_all_last_positions.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tier 2 — elevation side-effects
# ---------------------------------------------------------------------------

class TestElevationScheduling(unittest.IsolatedAsyncioTestCase):

    def _coord_with_fetch_elevation(self, fetch_elevation=True) -> PajGpsCoordinator:
        coord = make_coordinator(fetch_elevation=fetch_elevation)
        coord.data = CoordinatorData(devices=[make_device(1)])
        coord._fetch_elevation_for = AsyncMock()
        return coord

    async def test_elevation_fetched_when_missing(self):
        coord = self._coord_with_fetch_elevation()
        # No elevation for device 1
        coord.data = dataclasses.replace(coord.data, elevations={})
        positions = {1: make_trackpoint(1, lat=52.0, lng=13.0)}

        tasks_launched = []
        coord.hass.async_create_task = lambda coro: tasks_launched.append(coro) or asyncio.ensure_future(coro)

        coord._schedule_elevation_tasks(positions)
        await asyncio.sleep(0.05)

        self.assertTrue(len(tasks_launched) > 0)

    async def test_elevation_not_fetched_when_disabled(self):
        coord = self._coord_with_fetch_elevation(fetch_elevation=False)
        positions = {1: make_trackpoint(1)}

        tasks_launched = []
        coord.hass.async_create_task = lambda coro: tasks_launched.append(coro) or asyncio.ensure_future(coro)

        coord._schedule_elevation_tasks(positions)
        self.assertEqual(len(tasks_launched), 0)

    async def test_elevation_not_fetched_when_device_has_not_moved(self):
        coord = self._coord_with_fetch_elevation()
        # Elevation already known and position unchanged
        coord.data = dataclasses.replace(coord.data, elevations={1: 100.0})
        coord._last_elevation_pos[1] = (52.0, 13.0)
        coord._last_elevation_fetch[1] = time.monotonic()  # just fetched

        positions = {1: make_trackpoint(1, lat=52.0, lng=13.0)}  # same position

        tasks_launched = []
        coord.hass.async_create_task = lambda coro: tasks_launched.append(coro) or asyncio.ensure_future(coro)

        coord._schedule_elevation_tasks(positions)
        self.assertEqual(len(tasks_launched), 0)

    async def test_elevation_fetched_when_moved_enough(self):
        coord = self._coord_with_fetch_elevation()
        coord.data = dataclasses.replace(coord.data, elevations={1: 100.0})
        # Last pos and fetch were long ago
        coord._last_elevation_pos[1] = (52.0, 13.0)
        coord._last_elevation_fetch[1] = time.monotonic() - MIN_ELEVATION_UPDATE_DELAY - 10

        # Move more than MIN_ELEVATION_DISTANCE
        new_lat = 52.0 + MIN_ELEVATION_DISTANCE * 2
        positions = {1: make_trackpoint(1, lat=new_lat, lng=13.0)}

        tasks_launched = []
        coord.hass.async_create_task = lambda coro: tasks_launched.append(coro) or asyncio.ensure_future(coro)

        coord._schedule_elevation_tasks(positions)
        self.assertTrue(len(tasks_launched) > 0)

    async def test_elevation_not_fetched_when_moved_but_too_soon(self):
        coord = self._coord_with_fetch_elevation()
        coord.data = dataclasses.replace(coord.data, elevations={1: 100.0})
        # Last fetch was very recent
        coord._last_elevation_pos[1] = (52.0, 13.0)
        coord._last_elevation_fetch[1] = time.monotonic()  # just fetched

        # Move a lot — but time guard blocks it
        new_lat = 52.0 + MIN_ELEVATION_DISTANCE * 5
        positions = {1: make_trackpoint(1, lat=new_lat, lng=13.0)}

        tasks_launched = []
        coord.hass.async_create_task = lambda coro: tasks_launched.append(coro) or asyncio.ensure_future(coro)

        coord._schedule_elevation_tasks(positions)
        self.assertEqual(len(tasks_launched), 0)

    async def test_fetch_elevation_pushes_snapshot_on_success(self):
        coord = make_coordinator()
        coord.data = CoordinatorData(devices=[make_device(1)])

        with patch.object(coord, '_fetch_elevation', new=AsyncMock(return_value=250.7)):
            snapshots = []
            coord.async_set_updated_data = lambda d: snapshots.append(d)
            await coord._fetch_elevation_for(1, 52.0, 13.0)

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].elevations[1], 251)  # rounded

    async def test_fetch_elevation_does_nothing_on_none(self):
        coord = make_coordinator()
        coord.data = CoordinatorData()

        with patch.object(coord, '_fetch_elevation', new=AsyncMock(return_value=None)):
            snapshots = []
            coord.async_set_updated_data = lambda d: snapshots.append(d)
            await coord._fetch_elevation_for(1, 52.0, 13.0)

        self.assertEqual(len(snapshots), 0)


# ---------------------------------------------------------------------------
# Tier 2 — _fetch_elevation HTTP call
# ---------------------------------------------------------------------------

class TestFetchElevationHttp(unittest.IsolatedAsyncioTestCase):

    async def test_returns_elevation_on_success(self):
        coord = make_coordinator()

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"elevation": [123.4]})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("custom_components.pajgps.coordinator_utils.aiohttp.ClientSession", return_value=mock_session):
            result = await coord._fetch_elevation(52.0, 13.0)

        self.assertAlmostEqual(result, 123.4)

    async def test_returns_none_on_http_error(self):
        coord = make_coordinator()

        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("custom_components.pajgps.coordinator_utils.aiohttp.ClientSession", return_value=mock_session):
            result = await coord._fetch_elevation(52.0, 13.0)

        self.assertIsNone(result)

    async def test_returns_none_on_timeout(self):
        coord = make_coordinator()

        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=asyncio.TimeoutError())
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("custom_components.pajgps.coordinator_utils.aiohttp.ClientSession", return_value=mock_session):
            result = await coord._fetch_elevation(52.0, 13.0)

        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Tier 3 — notifications
# ---------------------------------------------------------------------------

class TestNotificationsTier(unittest.IsolatedAsyncioTestCase):

    async def test_unread_notifications_pushed_per_device(self):
        coord = make_coordinator()
        coord.data = CoordinatorData(devices=[make_device(1)])

        unread = [make_notification(1, alert_type=2, is_read=0)]
        read = [make_notification(1, alert_type=4, is_read=1)]
        coord.api.get_device_notifications = AsyncMock(return_value=unread + read)

        snapshots = []
        coord.async_set_updated_data = lambda d: snapshots.append(d)

        await coord._run_notifications_tier()
        await asyncio.sleep(0.3)

        notif_snapshots = [s for s in snapshots if 1 in s.notifications]
        self.assertTrue(len(notif_snapshots) > 0)
        # Only the unread one should appear
        self.assertEqual(len(notif_snapshots[-1].notifications[1]), 1)
        self.assertEqual(notif_snapshots[-1].notifications[1][0].meldungtyp, 2)

    async def test_mark_as_read_fired_when_configured(self):
        coord = make_coordinator(mark_alerts_as_read=True)
        coord.data = CoordinatorData(devices=[make_device(1)])

        unread = [make_notification(1, is_read=0)]
        coord.api.get_device_notifications = AsyncMock(return_value=unread)
        coord.api.mark_notifications_read_by_device = AsyncMock()

        tasks = []
        coord.hass.async_create_task = lambda coro: tasks.append(coro) or asyncio.ensure_future(coro)
        coord.async_set_updated_data = MagicMock()

        await coord._run_notifications_tier()
        await asyncio.sleep(0.3)
        # Drain any fire-and-forget tasks
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        coord.api.mark_notifications_read_by_device.assert_awaited_once_with(1, is_read=1)

    async def test_mark_as_read_not_fired_when_not_configured(self):
        coord = make_coordinator(mark_alerts_as_read=False)
        coord.data = CoordinatorData(devices=[make_device(1)])

        coord.api.get_device_notifications = AsyncMock(return_value=[make_notification(1)])
        coord.api.mark_notifications_read_by_device = AsyncMock()

        coord.async_set_updated_data = MagicMock()

        await coord._run_notifications_tier()
        await asyncio.sleep(0.3)

        coord.api.mark_notifications_read_by_device.assert_not_awaited()

    async def test_no_devices_exits_early(self):
        coord = make_coordinator()
        coord.data = CoordinatorData(devices=[])
        coord.api.get_device_notifications = AsyncMock()

        await coord._run_notifications_tier()

        coord.api.get_device_notifications.assert_not_awaited()


# ---------------------------------------------------------------------------
# Alert toggle write path
# ---------------------------------------------------------------------------

class TestAlertToggle(unittest.IsolatedAsyncioTestCase):

    async def test_turn_on_sends_put_immediately(self):
        coord = make_coordinator()
        device = make_device(1, alarmbewegung=0)
        coord.data = CoordinatorData(devices=[device])
        coord.api.update_device = AsyncMock(return_value=make_device(1, alarmbewegung=1))

        received = []
        coord.async_set_updated_data = lambda d: received.append(d)

        await coord.async_update_alert_state(1, alert_type=1, enabled=True)

        coord.api.update_device.assert_awaited_once_with(1, alarmbewegung=1)
        # Optimistic snapshot pushed
        self.assertEqual(len(received), 1)
        updated_device = next(d for d in received[0].devices if d.id == 1)
        self.assertEqual(updated_device.alarmbewegung, 1)

    async def test_turn_off_sends_put_with_zero(self):
        coord = make_coordinator()
        device = make_device(1, alarmsos=1)
        coord.data = CoordinatorData(devices=[device])
        coord.api.update_device = AsyncMock(return_value=make_device(1, alarmsos=0))

        coord.async_set_updated_data = MagicMock()

        await coord.async_update_alert_state(1, alert_type=4, enabled=False)

        coord.api.update_device.assert_awaited_once_with(1, alarmsos=0)

    async def test_api_error_does_not_push_snapshot(self):
        coord = make_coordinator()
        coord.data = CoordinatorData(devices=[make_device(1)])
        coord.api.update_device = AsyncMock(side_effect=PajGpsApiError("fail"))

        received = []
        coord.async_set_updated_data = lambda d: received.append(d)

        await coord.async_update_alert_state(1, alert_type=1, enabled=True)

        self.assertEqual(len(received), 0)

    async def test_unknown_alert_type_does_not_call_api(self):
        coord = make_coordinator()
        coord.data = CoordinatorData(devices=[make_device(1)])
        coord.api.update_device = AsyncMock()

        await coord.async_update_alert_state(1, alert_type=999, enabled=True)

        coord.api.update_device.assert_not_awaited()

    async def test_no_refresh_triggered_after_toggle(self):
        """Coordinator must NOT call async_request_refresh after a toggle."""
        coord = make_coordinator()
        coord.data = CoordinatorData(devices=[make_device(1)])
        coord.api.update_device = AsyncMock(return_value=make_device(1))
        coord.async_request_refresh = AsyncMock()
        coord.async_set_updated_data = MagicMock()

        await coord.async_update_alert_state(1, alert_type=1, enabled=True)

        coord.async_request_refresh.assert_not_awaited()


# ---------------------------------------------------------------------------
# get_device_info helper
# ---------------------------------------------------------------------------

class TestGetDeviceInfo(unittest.TestCase):

    def test_returns_dict_for_known_device(self):
        coord = make_coordinator()
        coord.data = CoordinatorData(devices=[make_device(1)])

        info = coord.get_device_info(1)

        self.assertIsNotNone(info)
        self.assertIn("identifiers", info)
        self.assertIn("name", info)
        self.assertEqual(info["manufacturer"], "PAJ GPS")
        self.assertIn("model", info)
        self.assertIn("sw_version", info)

    def test_returns_none_for_unknown_device(self):
        coord = make_coordinator()
        coord.data = CoordinatorData(devices=[])

        self.assertIsNone(coord.get_device_info(999))

    def test_identifiers_contain_guid_and_device_id(self):
        coord = make_coordinator(guid="my-guid")
        coord.data = CoordinatorData(devices=[make_device(42)])

        info = coord.get_device_info(42)
        identifiers = info["identifiers"]
        self.assertTrue(any("my-guid" in str(i) and "42" in str(i) for i in identifiers))


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------

class TestShutdown(unittest.IsolatedAsyncioTestCase):

    async def test_shutdown_closes_api(self):
        coord = make_coordinator()
        coord.api.close = AsyncMock()

        await coord.async_shutdown()

        coord.api.close.assert_awaited_once()

    async def test_shutdown_cancels_elevation_tasks(self):
        coord = make_coordinator()
        coord.api.close = AsyncMock()

        async def long_running():
            await asyncio.sleep(100)

        task = asyncio.ensure_future(long_running())
        coord._elevation_tasks.add(task)

        await coord.async_shutdown()

        self.assertTrue(task.cancelled())

    async def test_shutdown_empties_elevation_tasks(self):
        coord = make_coordinator()
        coord.api.close = AsyncMock()

        await coord.async_shutdown()

        self.assertEqual(len(coord._elevation_tasks), 0)


# ---------------------------------------------------------------------------
# Integration tests — require real credentials in .env
# ---------------------------------------------------------------------------

class TestCoordinatorIntegration(unittest.IsolatedAsyncioTestCase):
    """
    Integration tests that hit the real PAJ GPS API.
    Skipped automatically when PAJGPS_EMAIL / PAJGPS_PASSWORD are not set.
    """

    def setUp(self):
        load_dotenv()
        email = os.getenv("PAJGPS_EMAIL")
        password = os.getenv("PAJGPS_PASSWORD")
        if not email or not password:
            self.skipTest("PAJGPS_EMAIL / PAJGPS_PASSWORD not set — skipping integration tests")

        self._entry_data = make_entry_data(email=email, password=password)

    def _make_real_coordinator(self) -> PajGpsCoordinator:
        hass = MagicMock()
        hass.async_create_task = lambda coro: asyncio.ensure_future(coro)
        return PajGpsCoordinator(hass, self._entry_data)

    async def test_login_succeeds(self):
        coord = self._make_real_coordinator()
        await coord.api.login()
        # If no exception, login succeeded

    async def test_fetch_devices(self):
        coord = self._make_real_coordinator()
        await coord.api.login()
        await coord._run_devices_tier()

        self.assertGreater(len(coord.data.devices), 0)
        for device in coord.data.devices:
            self.assertIsNotNone(device.id)
            self.assertIsNotNone(device.name)

    async def test_fetch_positions(self):
        coord = self._make_real_coordinator()
        await coord.api.login()
        await coord._run_devices_tier()
        await coord._run_positions_tier()
        await asyncio.sleep(1)  # let queue workers drain

        self.assertGreater(len(coord.data.positions), 0)
        for device_id, tp in coord.data.positions.items():
            self.assertIsNotNone(tp.lat)
            self.assertIsNotNone(tp.lng)
            self.assertGreaterEqual(tp.speed, 0)
            self.assertIn(tp.battery, range(0, 101))

    async def test_fetch_sensor_data(self):
        coord = self._make_real_coordinator()
        await coord.api.login()
        await coord._run_devices_tier()
        await coord._run_positions_tier()
        await asyncio.sleep(1)

        # At least one device should have sensor data
        self.assertGreater(len(coord.data.sensor_data), 0)

    async def test_fetch_notifications(self):
        coord = self._make_real_coordinator()
        await coord.api.login()
        await coord._run_devices_tier()
        await coord._run_notifications_tier()
        await asyncio.sleep(1)

        # Notifications dict should exist for all known devices
        for device in coord.data.devices:
            self.assertIn(device.id, coord.data.notifications)
            self.assertIsInstance(coord.data.notifications[device.id], list)

    async def test_full_initial_refresh(self):
        coord = self._make_real_coordinator()
        result = await coord._async_update_data()

        self.assertIsInstance(result, CoordinatorData)
        self.assertGreater(len(result.devices), 0)
        self.assertTrue(coord._initial_refresh_done)

    async def test_get_device_info_after_refresh(self):
        coord = self._make_real_coordinator()
        await coord._async_update_data()

        device_id = coord.data.devices[0].id
        info = coord.get_device_info(device_id)

        self.assertIsNotNone(info)
        self.assertEqual(info["manufacturer"], "PAJ GPS")

    async def test_elevation_fetch(self):
        coord = self._make_real_coordinator()
        elevation = await coord._fetch_elevation(52.52, 13.41)  # Berlin
        self.assertIsNotNone(elevation)
        self.assertGreaterEqual(elevation, 0)

    async def tearDown(self):
        # Best-effort cleanup
        try:
            coord = self._make_real_coordinator()
            await coord.async_shutdown()
        except Exception:
            pass
