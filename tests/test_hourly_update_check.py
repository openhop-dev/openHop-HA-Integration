"""Execute the real coordinator with fake HA scheduling and HTTP boundaries.

These stdlib tests verify registration and callback behavior, not HA's clock/DST
implementation. Only trusted checked-in source is executed; no live requests.
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
import json
import logging
from types import SimpleNamespace
import unittest

from test_installed_api_behavior import COMPONENT, client_namespace


class FakeCoordinator:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, hass, **kwargs):
        self.hass = hass
        self.data = {}
        self.update_interval = kwargs['update_interval']
        self.refreshes = 0
        self.refresh_error = None

    async def async_request_refresh(self):
        self.refreshes += 1
        if self.refresh_error:
            raise self.refresh_error
        self.data = await self._async_update_data()


class HourlyUpdateCheckTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.registrations = []
        self.active = []
        self.unload_callbacks = []
        self.tasks = []
        self.calls = []
        self.check_error = None
        self.check_gate = None

        def track(hass, action, **kwargs):
            self.registrations.append((hass, action, kwargs))
            self.active.append(action)
            def cancel():
                self.active.remove(action)
            return cancel

        def create_task(coro):
            task = asyncio.create_task(coro)
            self.tasks.append(task)
            return task

        ns = client_namespace()
        api = object.__new__(ns['PyMCRepeaterApiClient'])
        async def request(method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            if self.check_gate:
                await self.check_gate.wait()
            if self.check_error:
                raise self.check_error
            return {'state': 'checking'}
        api._async_request_wrapped = request
        async def fetch_all():
            return {'update_status': {'state': 'checking'}}
        api.async_fetch_all = fetch_all
        self.hass = SimpleNamespace(async_create_task=create_task)
        entry = SimpleNamespace(options={}, entry_id='test', async_on_unload=self.unload_callbacks.append)
        ns.update(DataUpdateCoordinator=FakeCoordinator, asyncio=asyncio,
                  contextlib=contextlib, datetime=datetime, timedelta=timedelta,
                  timezone=timezone, json=json, _LOGGER=logging.getLogger('hourly_test'),
                  callback=lambda fn: fn, async_track_time_change=track,
                  CONF_SCAN_INTERVAL='scan_interval', DEFAULT_SCAN_INTERVAL_SECONDS=15,
                  MIN_SCAN_INTERVAL_SECONDS=5, MAX_SCAN_INTERVAL_SECONDS=300,
                  DOMAIN='pymc_repeater', GPS_STREAM_RETRY_SECONDS=15,
                  ConfigEntryAuthFailed=type('ConfigEntryAuthFailed', (Exception,), {}),
                  UpdateFailed=type('UpdateFailed', (Exception,), {}))
        tree = ast.parse((COMPONENT / 'coordinator.py').read_text())
        body = [ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)]
        body.extend(node for node in tree.body if isinstance(node, ast.ClassDef))
        exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), 'coordinator.py', 'exec'), ns)
        self.coordinator = ns['PyMCRepeaterDataUpdateCoordinator'](self.hass, entry, api)
        # GPS transport is unrelated; retain real start/stop task ownership.
        async def gps_wait():
            await asyncio.Event().wait()
        self.coordinator._async_gps_stream_loop = gps_wait

    async def asyncTearDown(self):
        await self.coordinator.async_stop_runtime()
        for task in self.tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def start(self):
        await self.coordinator.async_start_runtime()
        self.assertEqual(len(self.active), 1, 'hourly listener must be registered')
        return self.active[0]

    async def test_local_hourly_registration_no_startup_check_or_duplicate(self):
        await self.start()
        await self.coordinator.async_start_runtime()
        self.assertEqual(len(self.registrations), 1)
        self.assertIs(self.registrations[0][0], self.hass)
        self.assertEqual(self.registrations[0][2], {'minute': 1, 'second': 0})
        self.assertEqual(self.calls, [])
        self.assertEqual(self.coordinator.refreshes, 0)
        self.assertEqual(self.coordinator.update_interval, timedelta(seconds=15))
        self.assertEqual(len(self.tasks), 1)
        imports = ast.parse((COMPONENT / 'coordinator.py').read_text())
        self.assertTrue(any(isinstance(n, ast.ImportFrom) and n.module == 'homeassistant.helpers.event'
                            and any(a.name == 'async_track_time_change' for a in n.names) for n in imports.body))

    async def test_hourly_check_is_not_forced_then_refreshes_cached_status(self):
        action = await self.start()
        await action(datetime(2026, 9, 8, 12, 1, tzinfo=timezone.utc))
        self.assertEqual(self.calls, [('POST', '/api/update/check', {'json_body': {'force': False}})])
        self.assertEqual(self.coordinator.refreshes, 1)
        self.assertEqual(self.coordinator.data['update_status']['state'], 'checking')

    async def test_busy_backend_skips_check_and_refresh(self):
        action = await self.start()
        for state in ('installing', 'checking'):
            self.coordinator.data = {'update_status': {'state': state}}
            await action(None)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.coordinator.refreshes, 0)

    async def test_missing_or_malformed_optional_status_does_not_break_check(self):
        action = await self.start()
        for data in (None, {}, {'update_status': None}, {'update_status': []}):
            self.coordinator.data = data
            await action(None)
        self.assertEqual(len(self.calls), 4)

    async def test_errors_are_contained_and_next_hour_can_retry(self):
        action = await self.start()
        self.check_error = RuntimeError('test check failure')
        self.coordinator.refresh_error = RuntimeError('test refresh failure')
        with self.assertLogs('hourly_test', level='WARNING'):
            await action(None)
        self.assertEqual(self.coordinator.refreshes, 1)
        self.check_error = self.coordinator.refresh_error = None
        await action(None)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.coordinator.refreshes, 2)

    async def test_overlapping_callbacks_do_not_duplicate_requests(self):
        action = await self.start()
        self.check_gate = asyncio.Event()
        task = asyncio.create_task(action(None))
        await asyncio.sleep(0)
        await action(None)
        self.assertEqual(len(self.calls), 1)
        self.check_gate.set()
        await task

    async def test_stop_unregisters_and_queued_callback_is_harmless(self):
        action = await self.start()
        await self.coordinator.async_stop_runtime()
        await self.coordinator.async_stop_runtime()
        self.assertEqual(self.active, [])
        await action(None)
        self.assertEqual(self.calls, [])
        await self.start()
        self.assertEqual(len(self.registrations), 2)

    async def test_entry_unload_cleans_listener_even_after_failed_setup(self):
        action = await self.start()
        self.assertTrue(self.unload_callbacks, 'entry must own listener cleanup')
        for cancel in self.unload_callbacks:
            cancel()
        self.assertEqual(self.active, [])
        await action(None)
        self.assertEqual(self.calls, [])

    async def test_stop_during_request_does_not_refresh_unloaded_entry(self):
        action = await self.start()
        self.check_gate = asyncio.Event()
        task = asyncio.create_task(action(None))
        await asyncio.sleep(0)
        await self.coordinator.async_stop_runtime()
        self.check_gate.set()
        await task
        self.assertEqual(self.coordinator.refreshes, 0)
