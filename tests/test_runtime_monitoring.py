"""Execute checked-in entity code with minimal HA boundaries, not a HA harness."""
import ast
import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import unittest
import runpy

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / 'custom_components/pymc_repeater'


def extracted(filename, namespace):
    tree = ast.parse((COMPONENT / filename).read_text())
    nodes = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])), filename, 'exec'), namespace)
    return namespace


class Base:
    def __init__(self, entry, coordinator):
        self._entry, self.coordinator = entry, coordinator

    @property
    def available(self):
        return self.coordinator.last_update_success

    @property
    def device_info(self):
        return {'identifiers': {('pymc_repeater', 'entry')}}


class RuntimeMonitoringTests(unittest.TestCase):
    def test_update_readback_versions_and_install_guards(self):
        ns = extracted('update.py', dict(PyMCBaseEntity=Base, UpdateEntity=type('Update', (), {}),
            UpdateEntityFeature=SimpleNamespace(INSTALL=1), HomeAssistantError=RuntimeError,
            PyMCRepeaterApiError=ValueError, DOMAIN='pymc_repeater', datetime=datetime))
        calls = []
        async def install(**kwargs):
            calls.append(kwargs)
        coordinator = SimpleNamespace(last_update_success=True, data={'update_status': {
            'current_version': '1.0', 'latest_version': '1.1', 'has_update': True,
            'channel': 'dev', 'error': None, 'state': 'idle',
            'last_checked': '2026-09-08T12:00:00+00:00'}}, api=SimpleNamespace(async_update_install=install))
        entity = ns['PyMCUpdateEntity'](SimpleNamespace(unique_id='entry', entry_id='fallback'), coordinator)
        self.assertTrue(entity.available)
        self.assertEqual(entity.latest_version, '1.1')
        self.assertEqual(calls, [])
        asyncio.run(entity.async_install(None, False))
        self.assertEqual(calls, [{'force': False}])
        for version, backup in [('1.2', False), (None, True)]:
            with self.assertRaises(RuntimeError):
                asyncio.run(entity.async_install(version, backup))
        coordinator.data['update_status']['error'] = 'check failed'
        self.assertFalse(entity.available, 'errored cached release must not enable install')
        coordinator.data['update_status'] = {'current_version': '1.0', 'has_update': False}
        self.assertIsNone(entity.latest_version)
        with self.assertRaises(RuntimeError):
            asyncio.run(entity.async_install(None, False))
        coordinator.data = {}
        self.assertFalse(entity.available)

    def test_update_requires_completed_valid_check(self):
        ns = extracted('update.py', dict(PyMCBaseEntity=Base, UpdateEntity=type('Update', (), {}),
            UpdateEntityFeature=SimpleNamespace(INSTALL=1), HomeAssistantError=RuntimeError,
            PyMCRepeaterApiError=ValueError, DOMAIN='pymc_repeater', datetime=datetime))
        calls = []
        async def install(**kwargs):
            calls.append(kwargs)
        coordinator = SimpleNamespace(last_update_success=True, data={},
            api=SimpleNamespace(async_update_install=install))
        entity = ns['PyMCUpdateEntity'](SimpleNamespace(unique_id='entry', entry_id='fallback'), coordinator)
        checked = {'current_version': '1.1', 'latest_version': '1.0', 'has_update': False,
                   'channel': 'dev', 'state': 'idle', 'error': None,
                   'last_checked': '2026-09-08T12:00:00+00:00'}
        # Installed source resets these three fields on startup/channel change/forced check.
        for channel in ('dev', 'main'):
            coordinator.data['update_status'] = dict(checked, channel=channel,
                latest_version=None, last_checked=None, has_update=False)
            self.assertTrue(entity.available)
            self.assertIsNone(entity.latest_version, 'unchecked is unknown, not up to date')
        for state in ('idle', 'complete'):
            coordinator.data['update_status'] = dict(checked, state=state)
            self.assertTrue(entity.available)
            self.assertEqual(entity.latest_version, '1.1', 'backend no-update decision avoids downgrade')
        invalid = [
            {'state': 'checking'}, {'state': 'installing'}, {'state': 'error'},
            {'state': None}, {'error': 'GitHub rate limit'}, {'success': False},
            *({'last_checked': value} for value in (None, '', 'invalid', False, 123)),
            *({'latest_version': value} for value in (None, '', '  ', 'unknown', False, 123, {})),
            *({'current_version': value} for value in (None, '', '  ', 'unknown', False, 123)),
            *({'has_update': value} for value in (None, 0, 1, 'false')),
        ]
        for has_update in (False, True):
            for changes in invalid:
                with self.subTest(has_update=has_update, changes=changes):
                    coordinator.data['update_status'] = dict(checked, has_update=has_update)
                    coordinator.data['update_status'].update(changes)
                    self.assertIsNone(entity.latest_version)
                    with self.assertRaises(RuntimeError):
                        asyncio.run(entity.async_install(None, False))
        for key in ('latest_version', 'last_checked', 'state'):
            coordinator.data['update_status'] = dict(checked, has_update=True)
            del coordinator.data['update_status'][key]
            with self.subTest(missing=key):
                self.assertIsNone(entity.latest_version)
                with self.assertRaises(RuntimeError):
                    asyncio.run(entity.async_install(None, False))
        coordinator.data['update_status'] = dict(checked, latest_version='1.2', has_update=True)
        self.assertEqual(entity.latest_version, '1.2')
        coordinator.last_update_success = False
        self.assertFalse(entity.available)
        with self.assertRaises(RuntimeError):
            asyncio.run(entity.async_install(None, False))
        self.assertEqual(calls, [], 'reading status and rejected installs never call backend')

    def test_existing_measurement_becomes_unavailable_when_stale(self):
        helpers = runpy.run_path(str(COMPONENT / 'monitoring.py'))
        tree = ast.parse((COMPONENT / 'sensor.py').read_text())
        wanted = {'PyMCExternalSensorMetricSensor', '_external_sensor_readings',
                  '_external_sensor_identity', '_external_sensor_payload',
                  '_normalize_external_sensor_value', '_nested'}
        nodes = [node for node in tree.body if getattr(node, 'name', None) in wanted]
        ns = dict(helpers, PyMCBaseEntity=Base, SensorEntity=type('Sensor', (), {}),
                  EntityCategory=SimpleNamespace(DIAGNOSTIC='diagnostic'),
                  SensorStateClass=SimpleNamespace(MEASUREMENT='measurement'),
                  PERCENTAGE='%', UnitOfTime=SimpleNamespace(MINUTES='min'),
                  slugify=lambda text: text.lower().replace(' ', '_'))
        nodes.insert(0, ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0))
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), 'sensor.py', 'exec'), ns)
        reading = {'name': 'modem', 'type': 'openhop_modem', 'ok': True,
                   'timestamp': helpers['time'](), 'data': {'battery_percent': 90}}
        coordinator = SimpleNamespace(last_update_success=True, data={
            'stats': {'sensors': {'readings': [reading], 'poll_interval_seconds': 15}}})
        entry = SimpleNamespace(unique_id='entry', entry_id='fallback')
        entity = ns['PyMCExternalSensorMetricSensor'](entry, coordinator, reading, 'battery_percent')
        self.assertTrue(entity.available)
        self.assertEqual(entity.native_value, 90)
        self.assertEqual(entity._attr_device_class, 'battery')
        self.assertIn('pymc_modem', entity._attr_unique_id)
        reading['timestamp'] = 1
        self.assertFalse(entity.available)
        reading['timestamp'] = helpers['time']()
        reading['ok'] = False
        self.assertFalse(entity.available)
        reading['ok'] = True
        reading['data']['battery_percent'] = float('nan')
        self.assertFalse(entity.available)

    def test_snapshot_discovery_late_sources_removal_and_stable_ids(self):
        import json
        helpers = runpy.run_path(str(COMPONENT / 'monitoring.py'))
        def nested(data, *keys):
            for key in keys:
                data = data.get(key) if isinstance(data, dict) else None
            return data
        ns = dict(helpers, json=json, PyMCBaseEntity=Base, SensorEntity=type('Sensor', (), {}),
            BinarySensorEntity=type('Binary', (), {}), EntityCategory=SimpleNamespace(DIAGNOSTIC='diagnostic'),
            SensorDeviceClass=SimpleNamespace(DURATION='duration', TIMESTAMP='timestamp'),
            SensorStateClass=SimpleNamespace(MEASUREMENT='measurement'),
            BinarySensorDeviceClass=SimpleNamespace(PROBLEM='problem', CONNECTIVITY='connectivity'),
            DeviceInfo=dict, DOMAIN='pymc_repeater', MANUFACTURER='openHop', _nested=nested,
            _external_sensor_readings=lambda data: nested(data, 'stats', 'sensors', 'readings') or [],
            _external_sensor_identity=lambda reading: reading['name'])
        ns = extracted('monitoring_entities.py', ns)
        listeners, unload, entities = [], [], []
        coordinator = SimpleNamespace(data={}, last_update_success=True, async_add_listener=lambda cb: listeners.append(cb))
        entry = SimpleNamespace(unique_id='entry', entry_id='fallback', async_on_unload=unload.append)
        ns['setup_monitoring_sensors'](entry, coordinator, entities.extend)
        coordinator.data = {'stats': {'radio_stack': {'radio_ids': ['a', 'a_b']}}}
        listeners[0]()
        count = len(entities)
        listeners[0]()
        self.assertEqual(len(entities), count)
        radios = [e for e in entities if e._key[0] == 'radio']
        self.assertEqual(len(radios), 2)
        self.assertNotEqual(radios[0]._attr_unique_id, radios[1]._attr_unique_id)
        self.assertEqual(radios[0].device_info['via_device'], ('pymc_repeater', 'entry'))
        coordinator.data['stats'].update(sensors={'poll_interval_seconds': 15, 'readings': [
            {'name': 'modem', 'ok': True, 'timestamp': helpers['time'](),
             'data': {'solar_charge_rate_percent_per_hour': -0.416}}]})
        listeners[0]()
        charge = next(e for e in entities if e._key[2] == 'charge_state')
        self.assertEqual(charge.native_value, 'discharging')
        coordinator.data['stats']['sensors']['readings'][0]['timestamp'] = 1
        self.assertIsNone(charge.native_value)
        coordinator.data = {}
        self.assertFalse(charge.available)
        self.assertFalse(radios[0].available)
        self.assertEqual(len(unload), 1)
        coordinator.last_update_success = False
        binary = ns['_snapshot'](coordinator, True)
        self.assertFalse(binary[('component', 'api', 'connected')])
        self.assertIsNone(binary[('component', 'gps', 'problem')])
