"""Exercise the HA removal hook with the real confirmed-absence lifecycle."""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

from test_radio_lifecycle import Registry, load_lifecycle, snapshot

ROOT = Path(__file__).resolve().parents[1] / 'custom_components/pymc_repeater'


class RadioRemovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_removal_hook_requires_confirmed_absence(self):
        tree = ast.parse((ROOT / '__init__.py').read_text())
        functions = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                     and n.name == 'async_remove_config_entry_device']
        self.assertEqual(len(functions), 1)
        ns = {'DOMAIN': 'pymc_repeater'}
        module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *functions], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), 'removal', 'exec'), ns)
        registry = Registry()
        old = registry.add('local')
        active = registry.add('radio0')
        entry = SimpleNamespace(entry_id='entry', unique_id='example', options={'radio_id_aliases': {'local': 'radio0'}})
        coordinator = SimpleNamespace(last_update_success=True, data=snapshot('radio0'),
                                      last_successful_poll=datetime(2026, 1, 1, tzinfo=timezone.utc))
        hass = SimpleNamespace(registry=registry, data={'pymc_repeater': {'entry': {}}})
        hook = ns['async_remove_config_entry_device']
        self.assertFalse(await hook(hass, entry, old))
        lifecycle = load_lifecycle()['RadioLifecycle'](hass, entry, coordinator)
        hass.data['pymc_repeater']['entry']['radio_lifecycle'] = lifecycle
        lifecycle.async_reconcile()
        self.assertFalse(await hook(hass, entry, old))
        coordinator.last_successful_poll += timedelta(seconds=15)
        lifecycle.async_reconcile()
        self.assertTrue(await hook(hass, entry, old))
        self.assertFalse(await hook(hass, entry, active))
        coordinator.last_update_success = False
        self.assertFalse(await hook(hass, entry, old))
