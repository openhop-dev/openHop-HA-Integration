"""Executable pure monitoring contracts; no Home Assistant or network."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / 'custom_components/pymc_repeater'


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        path = COMPONENT / 'monitoring.py'
        self.assertTrue(path.exists(), 'monitoring normalization is not implemented')
        spec = importlib.util.spec_from_file_location('monitoring', path)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_freshness_unknown_stale_future_and_failure(self):
        for timestamp in (None, 'invalid', True, 1100):
            self.assertIsNone(self.m.reading_age({'timestamp': timestamp}, now=1000))
        self.assertEqual(self.m.reading_age({'timestamp': 900}, now=1000), 100)
        self.assertTrue(self.m.reading_stale({'timestamp': 900}, 15, now=1000))
        self.assertFalse(self.m.reading_stale({'timestamp': 990}, 15, now=1000))
        self.assertIsNone(self.m.reading_stale({}, 15, now=1000))
        self.assertFalse(self.m.reading_usable({'ok': False, 'timestamp': 990}, 15, now=1000))
        self.assertFalse(self.m.reading_usable({'ok': True}, 15, now=1000))

    def test_radio_inventory_does_not_allocate_aggregate_metrics(self):
        data = {'stats': {'radio_stack': {'radio_ids': ['a', 'b']}, 'radio_status': 'ok',
                          'packets_received': 88, 'radios': [{'id': 'a', 'type': 'modem_tcp', 'radio': {'frequency': 915}}]}}
        radios = self.m.radio_inventory(data)
        self.assertEqual(set(radios), {'a', 'b'})
        self.assertNotIn('packets_received', radios['a'])
        self.assertNotIn('status', radios['b'])
        self.assertEqual(radios['a']['type'], 'modem_tcp')
        self.assertEqual(self.m.radio_inventory({'stats': {'radios': []}}), {})

    def test_radio_fields_and_single_default_fallback(self):
        fields = {'frequency': 915000000, 'bandwidth': 125000, 'tx_power': 20,
                  'spreading_factor': 7, 'coding_rate': 5, 'preamble_length': 8}
        data = {'stats': {'radio_stack': {'mode': 'single', 'radio_ids': ['a'], 'default_radio': 'a'}, 'radios': []},
                'config': {'radio': dict(fields, secret='excluded')}}
        radio = self.m.radio_inventory(data)['a']
        for key, value in fields.items():
            self.assertEqual(radio[key], value)
        self.assertNotIn('secret', radio)
        data['stats']['radio_stack']['mode'] = 'multi'
        self.assertNotIn('frequency', self.m.radio_inventory(data)['a'])
        data['stats']['radios'] = [{'id': 'a', 'radio': fields}]
        self.assertEqual(self.m.radio_inventory(data)['a']['frequency'], 915000000)

    def test_charge_state_requires_fresh_finite_signed_rate(self):
        reading = {'ok': True, 'timestamp': 990, 'data': {}}
        for rate, expected in [(1, 'charging'), (-0.416, 'discharging'), (0, 'neutral'), ('nan', None), (True, None)]:
            reading['data']['solar_charge_rate_percent_per_hour'] = rate
            self.assertEqual(self.m.charge_state(reading, 15, now=1000), expected)
        reading['data']['solar_charge_rate_percent_per_hour'] = 1
        for stamp in (1, None, 'invalid', 'inf', 1100):
            reading['timestamp'] = stamp
            self.assertIsNone(self.m.charge_state(reading, 15, now=1000))
        reading.update(timestamp=990, ok=False)
        self.assertIsNone(self.m.charge_state(reading, 15, now=1000))

    def test_plugin_problem_requires_runtime_and_explicit_evidence(self):
        self.assertFalse(self.m.plugin_problem({'enabled': True, 'has_runtime': False, 'state': 'STOPPED'}))
        self.assertTrue(self.m.plugin_problem({'enabled': True, 'has_runtime': True, 'state': 'FAILED'}))
        self.assertFalse(self.m.plugin_problem({'enabled': False, 'state': 'FAILED'}))
        self.assertIsNone(self.m.plugin_problem({}))
        self.assertIsNone(self.m.plugin_problem({'enabled': True, 'has_runtime': True, 'state': 'STARTING'}))

    def test_battery_semantics_and_finite_numeric_values(self):
        self.assertEqual(self.m.measurement_class('battery_percent'), 'battery')
        self.assertEqual(self.m.measurement_class('voltage_v'), 'voltage')
        self.assertEqual(self.m.measurement_class('die_temperature_c'), 'temperature')
        self.assertIsNone(self.m.measurement_class('solar_charge_rate_percent_per_hour'))
        self.assertEqual(self.m.finite_number('-0.416'), -0.416)
        for value in ('nan', 'inf', True, None):
            self.assertIsNone(self.m.finite_number(value))

    def test_update_platform_is_explicit_install_only(self):
        path = COMPONENT / 'update.py'
        self.assertTrue(path.exists(), 'native update platform missing')
        source = path.read_text()
        self.assertIn('async_update_install(force=False)', source)
        self.assertNotIn('async_update_check(', source)
        self.assertNotIn('async_update_set_channel(', source)
        self.assertNotIn('PROGRESS', source)
        self.assertIn('Platform.UPDATE', (COMPONENT / '__init__.py').read_text())

    def test_blueprints_and_compact_view(self):
        for name in ('unavailable', 'broker_disconnected', 'low_battery', 'high_temperature', 'stale_sensor', 'plugin_failure', 'update_available'):
            path = ROOT / 'blueprints/automation/openhop' / (name + '.yaml')
            self.assertTrue(path.exists(), name)
            source = path.read_text()
            self.assertIn('!input actions', source)
            self.assertIn('for:', source)
            self.assertNotIn('notify.', source)
        self.assertTrue((ROOT / 'dashboards/openhop_operations.yaml').exists())
