"""
Tests for elevation scheduling logic and the HTTP fetch helper.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.pajgps.coordinator_data import CoordinatorData
from custom_components.pajgps.const import MIN_ELEVATION_DISTANCE, MIN_ELEVATION_UPDATE_DELAY

from .test_common import make_coordinator, make_device, make_trackpoint


class TestElevationScheduling(unittest.IsolatedAsyncioTestCase):

    def _coord_with_fetch_elevation(self, fetch_elevation=True):
        coord = make_coordinator(fetch_elevation=fetch_elevation)
        coord.data = CoordinatorData(devices=[make_device(1)])
        coord._fetch_elevation_for = AsyncMock()
        return coord

    async def test_elevation_fetched_when_missing(self):
        coord = self._coord_with_fetch_elevation()
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
        coord._last_elevation_pos[1] = (52.0, 13.0)
        coord._last_elevation_fetch[1] = time.monotonic() - MIN_ELEVATION_UPDATE_DELAY - 10

        new_lat = 52.0 + MIN_ELEVATION_DISTANCE * 2
        positions = {1: make_trackpoint(1, lat=new_lat, lng=13.0)}

        tasks_launched = []
        coord.hass.async_create_task = lambda coro: tasks_launched.append(coro) or asyncio.ensure_future(coro)

        coord._schedule_elevation_tasks(positions)
        self.assertTrue(len(tasks_launched) > 0)

    async def test_elevation_not_fetched_when_moved_but_too_soon(self):
        coord = self._coord_with_fetch_elevation()
        coord.data = dataclasses.replace(coord.data, elevations={1: 100.0})
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
