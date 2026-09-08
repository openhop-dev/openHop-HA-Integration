"""Radio identity aliases: real source execution with fake HA boundaries."""
import ast
import asyncio
import copy
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest

from test_runtime_monitoring import Base, extracted

COMPONENT = Path(__file__).resolve().parents[1] / 'custom_components/pymc_repeater'


def fixture(*ids):
    return {'stats': {'radio_stack': {'mode': 'multi', 'radio_ids': list(ids)},
                      'radios': [{'id': rid, 'type': 'serial', 'radio': {
                          'frequency': 915000000, 'tx_power': 22, 'bandwidth': 125000,
                          'spreading_factor': 7, 'coding_rate': 5, 'preamble_length': 8}}
                                 for rid in ids]}}


def entity_namespace():
    ns = runpy.run_path(str(COMPONENT / 'monitoring.py'))
    ns.update(runpy.run_path(str(COMPONENT / 'const.py')))
    ns.update(json=json, PyMCBaseEntity=Base, SensorEntity=type('Sensor', (), {}),
              BinarySensorEntity=type('Binary', (), {}), DeviceInfo=dict,
              EntityCategory=SimpleNamespace(DIAGNOSTIC='diagnostic'),
              SensorDeviceClass=SimpleNamespace(DURATION='duration', TIMESTAMP='timestamp'),
              SensorStateClass=SimpleNamespace(MEASUREMENT='measurement'),
              BinarySensorDeviceClass=SimpleNamespace(PROBLEM='problem', CONNECTIVITY='connectivity'),
              _nested=lambda *args: None, _external_sensor_readings=lambda data: [])
    return extracted('monitoring_entities.py', ns)


class FakeOptionsFlow:
    def async_create_entry(self, **kwargs):
        return dict(type='create_entry', **kwargs)

    def async_show_form(self, **kwargs):
        return dict(type='form', **kwargs)


class RadioAliasTests(unittest.TestCase):
    def setUp(self):
        self.helpers = runpy.run_path(str(COMPONENT / 'monitoring.py'))

    def parser(self):
        self.assertIn('parse_radio_aliases', self.helpers, 'explicit alias validation is missing')
        return self.helpers['parse_radio_aliases']

    def test_alias_parser_accepts_exact_mapping_and_empty(self):
        parse = self.parser()
        for value in ('{"local":"radio0"}', {'local': 'radio0'}):
            self.assertEqual(parse(value), {'local': 'radio0'})
        self.assertEqual(parse('{}'), {})
        self.assertEqual(parse({}), {})
        self.assertEqual(parse({'local': 'radio0'}, radio_ids=iter(['radio0', 'link'])),
                         {'local': 'radio0'}, 'canonical-only inventory is not a collision')

    def test_alias_parser_rejects_malformed_ambiguous_cycles_and_collisions(self):
        parse = self.parser()
        invalid = [None, '', 'null', '[]', '{', 1, True, [], {'': 'radio0'},
                   {' local': 'radio0'}, {'local': 'radio0 '}, {'lo\ncal': 'radio0'},
                   {'local': ''}, {'local': 1}, {1: 'radio0'}, {'local': ['radio0']},
                   {'local': 'local'}, {'a': 'b', 'b': 'a'}, {'a': 'b', 'b': 'c'},
                   {'local': 'radio0', 'link': 'radio0'},
                   '{"local":"radio0","local":"radio1"}']
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse(value)
        with self.assertRaises(ValueError):
            parse({'local': 'radio0'}, radio_ids={'local', 'radio0', 'link'})

    def test_legacy_identity_and_all_seven_entities_survive_rename(self):
        ns = entity_namespace()
        entry = SimpleNamespace(unique_id='example:8000', entry_id='entry', options={}, async_on_unload=lambda cb: None)
        coordinator = SimpleNamespace(data=fixture('radio0'), config_entry=entry,
                                      last_update_success=True, async_add_listener=lambda cb: None)
        old = []
        ns['setup_monitoring_sensors'](entry, coordinator, old.extend)
        old = {e._key[2]: e for e in old if e._key[0] == 'radio'}
        self.assertEqual(len(old), 7)
        entry.options = {'radio_id_aliases': {'local': 'radio0'}}
        coordinator.data = fixture('local', 'link')
        untouched = copy.deepcopy(coordinator.data)
        created, listeners = [], []
        coordinator.async_add_listener = lambda cb: listeners.append(cb)
        ns['setup_monitoring_sensors'](entry, coordinator, created.extend)
        radios = [e for e in created if e._key[0] == 'radio']
        self.assertEqual({e._key[1] for e in radios}, {'radio0', 'link'})
        for entity in radios:
            if entity._key[1] == 'radio0':
                self.assertEqual(entity._attr_unique_id, old[entity._key[2]]._attr_unique_id)
                self.assertEqual(entity.device_info, old[entity._key[2]].device_info)
                self.assertTrue(entity.available)
                self.assertEqual(entity.native_value, old[entity._key[2]].native_value)
        self.assertEqual(coordinator.data, untouched)
        count = len(created)
        listeners[0]()
        self.assertEqual(len(created), count)
        coordinator.data = fixture('link')
        listeners[0]()
        self.assertTrue(all(not e.available for e in radios if e._key[1] == 'radio0'))
        coordinator.data = fixture('local', 'link')
        listeners[0]()
        self.assertEqual(len(created), count)
        self.assertTrue(all(e.available for e in radios))
        # Keep the alias installed across the return to legacy single mode.
        coordinator.data = fixture('radio0')
        coordinator.data['stats']['radio_stack'].update(mode='single', default_radio='radio0')
        listeners[0]()
        self.assertEqual(len(created), count)
        for entity in radios:
            if entity._key[1] == 'radio0':
                self.assertTrue(entity.available)
                self.assertEqual(entity._attr_unique_id, old[entity._key[2]]._attr_unique_id)
                self.assertEqual(entity.device_info, old[entity._key[2]].device_info)
                self.assertEqual(entity.native_value, old[entity._key[2]].native_value)
            else:
                self.assertFalse(entity.available)

    def test_runtime_collision_does_not_publish_wrong_radio_or_fallback_identity(self):
        ns = entity_namespace()
        entry = SimpleNamespace(options={'radio_id_aliases': {'local': 'radio0'}})
        coordinator = SimpleNamespace(data=fixture('local', 'radio0', 'link'), config_entry=entry)
        radio_keys = lambda: {key[1] for key in ns['_snapshot'](coordinator, False) if key[0] == 'radio'}
        self.assertEqual(radio_keys(), {'link'})
        coordinator.data = fixture('radio0', 'link')
        self.assertEqual(radio_keys(), {'radio0', 'link'}, 'canonical ID survives when alias source is absent')
        for source, target in (('local', 'radio0'), ('radio0', 'local')):
            coordinator.data = fixture(source, 'link')
            coordinator.data['stats']['radios'].append({'id': 123, 'radio_id': target})
            self.assertEqual(radio_keys(), {'link'}, 'ambiguous declarations still occupy both identities')
        coordinator.data = fixture('radio0', 'link')
        entry.options['radio_id_aliases'] = {'local': 'radio0', 'link': 'radio0'}
        self.assertEqual(radio_keys(), set(), 'corrupt stored aliases must not silently revert identities')

    def test_invalid_stored_values_fail_closed_without_default_fallback(self):
        inventory = self.helpers['radio_inventory']
        for invalid in (None, False, [], 'null', {'local': 'local'}):
            with self.subTest(invalid=invalid):
                self.assertEqual(inventory(fixture('local', 'link'), invalid), {})
        self.assertEqual(set(inventory(fixture('local', 'link'))), {'local', 'link'})

    def test_duplicate_or_conflicting_source_rows_are_not_merged(self):
        inventory = self.helpers['radio_inventory']
        data = fixture('local', 'link')
        data['stats']['radios'].append({'id': 'local', 'radio': {'frequency': 123}})
        self.assertEqual(set(inventory(data)), {'link'})
        data = fixture('local', 'link')
        data['stats']['radios'][0]['radio_id'] = 'other'
        self.assertEqual(set(inventory(data)), {'link'})
        data = fixture('local', 'link')
        data['stats']['radio_stack']['radio_ids'].append('local')
        self.assertEqual(set(inventory(data)), {'link'})
        data = fixture('local', 'link')
        data['stats']['radios'].append({'id': 123, 'radio_id': 'local'})
        self.assertEqual(set(inventory(data)), {'link'})
        data = fixture('local')
        data['stats']['success'] = False
        self.assertEqual(inventory(data), {})

    def test_options_flow_persists_validated_mapping_and_rejects_invalid(self):
        ns = dict(self.helpers)
        ns.update(runpy.run_path(str(COMPONENT / 'const.py')))
        ns.update(json=json, config_entries=SimpleNamespace(OptionsFlow=FakeOptionsFlow))
        # Fake schema constructors only; execute the real options-flow methods.
        ns['vol'] = SimpleNamespace(Schema=lambda value: value,
                                   Required=lambda key, **kwargs: key,
                                   Optional=lambda key, **kwargs: key,
                                   In=lambda value: value, All=lambda *args: args,
                                   Coerce=lambda value: value, Range=lambda **kwargs: kwargs)
        tree = ast.parse((COMPONENT / 'config_flow.py').read_text())
        nodes = [ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)]
        nodes += [node for node in tree.body if getattr(node, 'name', None) == 'PyMCRepeaterOptionsFlow']
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), 'config_flow.py', 'exec'), ns)
        entry = SimpleNamespace(entry_id='entry', options={'unrelated': 'preserve'})
        flow = ns['PyMCRepeaterOptionsFlow'](entry)
        coordinator = SimpleNamespace(data=fixture('local', 'link'))
        flow.hass = SimpleNamespace(data={'pymc_repeater': {'entry': {'coordinator': coordinator}}})
        form = asyncio.run(flow.async_step_init())
        self.assertIn('radio_id_aliases', form['data_schema'])
        payload = {'radio_id_aliases': '{"local":"radio0"}', 'scan_interval': 15,
                   'uptime_unit': 'hours', 'data_size_unit': 'mebibytes'}
        saved = asyncio.run(flow.async_step_init(payload))
        self.assertEqual(saved['data']['radio_id_aliases'], {'local': 'radio0'})
        self.assertEqual(saved['data']['unrelated'], 'preserve')
        for value in ('null', '{"a":"b","b":"a"}', '{"local":"link"}'):
            result = asyncio.run(flow.async_step_init(dict(payload, radio_id_aliases=value)))
            self.assertEqual(result['type'], 'form')
            self.assertEqual(result['errors'], {'radio_id_aliases': 'invalid_radio_aliases'})
        coordinator.data = fixture('local', 'link', 'radio0', 'radio0')
        self.assertEqual(asyncio.run(flow.async_step_init(payload))['type'], 'form',
                         'even ambiguous runtime IDs must block alias targets')
        self.assertEqual(asyncio.run(flow.async_step_init(dict(payload, radio_id_aliases='{}')))['data']['radio_id_aliases'], {})


if __name__ == '__main__':
    unittest.main()
