"""Bundled management workflow contracts; no HA or network access."""
from pathlib import Path
import unittest

try:
    import yaml
except ImportError:
    yaml = None

try:
    from jinja2 import Environment
except ImportError:
    Environment = None

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "examples/openhop_dashboard_scripts.yaml"


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


class DashboardManagementTests(unittest.TestCase):
    def test_action_buttons_use_compact_text_layout(self):
        for name in ('openhop_repeater_dashboard.yaml', 'openhop_operations.yaml'):
            text = (ROOT / 'dashboards' / name).read_text()
            with self.subTest(view=name):
                self.assertGreater(text.count('type: button'), 0)
                self.assertEqual(text.count('type: button'), text.count('show_icon: false'))

    def test_read_only_checks_have_companion_scripts(self):
        self.assertTrue(SCRIPTS.exists(), "response-only dashboard calls need companion scripts")
        text = SCRIPTS.read_text()
        dashboard = (ROOT / "dashboards/openhop_repeater_dashboard.yaml").read_text()
        for action in ("get_plugin_catalogue", "check_plugin_updates"):
            self.assertIn("pymc_repeater." + action, text)
            self.assertIn("script.openhop_example_" + action, dashboard)
        self.assertIn("EXAMPLE_CONFIG_ENTRY_ID", text)
        self.assertIn("response_variable:", text)

    @unittest.skipIf(yaml is None or Environment is None, 'PyYAML/Jinja optional')
    def test_acl_removal_fails_closed_without_a_named_identity(self):
        assert yaml is not None and Environment is not None
        scripts = yaml.safe_load(SCRIPTS.read_text())
        guard = scripts['openhop_example_remove_acl_client']['sequence'][0]['value_template']
        template = Environment().from_string(guard)
        for identity in ('', None, '   '):
            self.assertEqual(template.render(confirmed=True, identity_name=identity).strip(), 'False')
        self.assertEqual(template.render(confirmed=True, identity_name='Example room').strip(), 'True')
        self.assertEqual(template.render(confirmed=False, identity_name='Example room').strip(), 'False')

    def test_private_reads_and_installation_are_documented_not_control_entities(self):
        guide = (ROOT / 'docs/dashboard-management.md').read_text()
        readme = (ROOT / 'README.md').read_text()
        for token in ('get_plugin_settings', 'get_sensor_configuration', 'include_sensitive',
                      'response_variable', '_original_name', '*****', 'persisted',
                      'EXAMPLE_CONFIG_ENTRY_ID', 'REPEATER_SLUG', 'scripts.yaml'):
            self.assertIn(token, guide)
        self.assertIn('entity prefix, not an entry ID', readme)
        self.assertIn('examples/openhop_dashboard_scripts.yaml', readme)
        scripts = SCRIPTS.read_text()
        for forbidden in ('input_text.', 'input_select.', 'sensor.set', 'pymc_repeater.get_logs'):
            self.assertNotIn(forbidden, scripts)

    @unittest.skipIf(yaml is None or Environment is None, 'PyYAML/Jinja optional')
    def test_notifications_render_bounded_summaries_not_private_responses(self):
        assert yaml is not None and Environment is not None
        scripts = yaml.safe_load(SCRIPTS.read_text())
        result = {'config': {'password': 'NEVER_EXPOSE'}, 'client_pubkey': 'NEVER_EXPOSE',
                  'logs': 'NEVER_EXPOSE', 'plugins': [], 'results': [],
                  'counts': {'success': 1, 'failure': 2, 'unknown': 3, 'skipped': 4},
                  'stopped': True}
        for node in walk(scripts):
            if node.get('service') == 'persistent_notification.create':
                message = Environment().from_string(node['data']['message']).render(result=result)
                self.assertNotIn('NEVER_EXPOSE', message)
                self.assertLess(len(message), 600)

    @unittest.skipIf(yaml is None, "PyYAML optional; run /usr/bin/python3 for parsed contracts")
    def test_editor_workflows_and_dashboard_calls_follow_service_contracts(self):
        assert yaml is not None
        scripts = yaml.safe_load(SCRIPTS.read_text())
        services = yaml.safe_load((ROOT / 'custom_components/pymc_repeater/services.yaml').read_text())
        actions = {'install_catalogue_plugin', 'update_plugin', 'update_all_plugins',
                   'enable_plugin', 'disable_plugin', 'start_plugin', 'stop_plugin',
                   'restart_plugin', 'uninstall_plugin', 'update_plugin_settings',
                   'update_sensor_configuration', 'set_acl_permissions', 'remove_acl_client',
                   'get_sensor_types', 'get_radio_packet_rates', 'get_noise_floor_stats',
                   'get_crc_error_count', 'get_companion_stats', 'get_lbt_diagnostics'}
        calls = {n['service'].split('.')[1]: n for n in walk(scripts)
                 if str(n.get('service', '')).startswith('pymc_repeater.')}
        self.assertTrue(actions <= calls.keys(), f'missing usable wrappers: {actions - calls.keys()}')
        for name, call in calls.items():
            with self.subTest(action=name):
                self.assertEqual(call['response_variable'], 'result')
                self.assertNotIn('response_variable', call['data'])
                self.assertEqual(call['data']['config_entry_id'], 'EXAMPLE_CONFIG_ENTRY_ID')
                fields = services[name]['fields']
                self.assertTrue(call['data'].keys() <= fields.keys())
                self.assertTrue({k for k, v in fields.items() if v.get('required')} <= call['data'].keys())
                for field, value in call['data'].items():
                    if field == 'config_entry_id' or isinstance(value, str) and '{{' in value:
                        continue
                    metadata = fields[field]
                    if 'default' in metadata:
                        self.assertEqual(value, metadata['default'])
                        self.assertIs(type(value), type(metadata['default']))
                    selector = metadata.get('selector', {})
                    if 'number' in selector:
                        self.assertIs(type(value), int)
                        self.assertGreaterEqual(value, selector['number']['min'])
                        self.assertLessEqual(value, selector['number']['max'])
        self.assertEqual(scripts['openhop_example_set_acl_permissions']['fields']['permissions']['selector'],
                         services['set_acl_permissions']['fields']['permissions']['selector'])
        self.assertNotIn('radio_id', calls['get_lbt_diagnostics']['data'])
        self.assertIs(calls['uninstall_plugin']['data']['delete_data'], False)
        self.assertIn('identity_name', calls['remove_acl_client']['data'])
        for name in actions:
            if not name.startswith('get_'):
                script = scripts['openhop_example_' + name]
                self.assertEqual(script['fields']['confirmed']['default'], False)
                self.assertIn('confirmed', script['sequence'][0]['value_template'])
        for name in ('update_plugin_settings', 'update_sensor_configuration'):
            script = scripts['openhop_example_' + name]
            self.assertTrue(script['fields']['config']['required'])
            self.assertIn('object', script['fields']['config']['selector'])
            self.assertNotIn('default', script['fields']['config'])
        for path in ('dashboards/openhop_repeater_dashboard.yaml', 'dashboards/openhop_operations.yaml'):
            view = yaml.safe_load((ROOT / path).read_text())
            self.assertNotIn('views', view)
            for n in walk(view):
                action = n.get('perform_action', '')
                self.assertFalse(action.startswith('pymc_repeater.'), action)
                if action.startswith('script.'):
                    target = action.split('.', 1)[1]
                    self.assertIn(target, scripts)
                    if 'confirmed' in scripts[target].get('fields', {}):
                        self.assertIn('confirmation', n)
                        self.assertIs(n['data']['confirmed'], True)
                    self.assertNotIn('config', n.get('data', {}))
                    self.assertNotIn('client_pubkey', n.get('data', {}))
        self.assertNotIn('pymc_repeater.get_plugin_settings', SCRIPTS.read_text())
        self.assertNotIn('pymc_repeater.get_sensor_configuration', SCRIPTS.read_text())
        for n in walk(scripts):
            if n.get('service') == 'persistent_notification.create':
                for unsafe in ('tojson', 'result }}', 'client_pubkey', "get('config'", "get('types'"):
                    self.assertNotIn(unsafe, n['data']['message'])
