"""Execute lifecycle source with fake HA registry boundaries (not live HA)."""
from __future__ import annotations

import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from enum import Enum
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/pymc_repeater"


class Disabler(Enum):
    INTEGRATION = "integration"
    USER = "user"
    CONFIG_ENTRY = "config_entry"


def load_lifecycle():
    path = ROOT / "radio_lifecycle.py"
    assert path.exists(), "Radio lifecycle implementation is missing"
    spec = importlib.util.spec_from_file_location("lifecycle_monitoring", ROOT / "monitoring.py")
    assert spec is not None and spec.loader is not None
    monitoring = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(monitoring)
    tree = ast.parse(path.read_text())
    tree.body = [node for node in tree.body if not isinstance(node, ast.ImportFrom)
                 or not (node.level or (node.module or "").startswith("homeassistant"))]
    ns = {"DOMAIN": "pymc_repeater", "CONF_RADIO_ID_ALIASES": "radio_id_aliases",
          "parse_radio_aliases": monitoring.parse_radio_aliases,
          "radio_inventory": monitoring.radio_inventory,
          "dr": SimpleNamespace(DeviceEntryDisabler=Disabler,
                                async_get=lambda hass: hass.registry,
                                async_entries_for_config_entry=lambda reg, eid: [
                                    d for d in reg.devices.values() if eid in d.config_entries])}
    exec(compile(tree, str(path), "exec"), ns)
    return ns


def snapshot(*ids):
    return {"stats": {"radio_stack": {"mode": "single" if len(ids) == 1 else "multi",
                                     "radio_ids": list(ids)},
                      "radios": [{"id": rid, "radio": {"frequency": 868000000}} for rid in ids]}}


class Registry:
    def __init__(self):
        self.devices = {}
        self.writes = []

    def add(self, rid, disabled_by=None):
        device = SimpleNamespace(id=rid, identifiers={("pymc_repeater", "example_radio_" + rid)},
                                 config_entries={"entry"}, disabled_by=disabled_by,
                                 name_by_user="Custom " + rid)
        self.devices[rid] = device
        return device

    def async_update_device(self, device_id, **kwargs):
        self.writes.append((device_id, kwargs))
        for key, value in kwargs.items():
            setattr(self.devices[device_id], key, value)


class RadioLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.ns = load_lifecycle()
        self.registry = Registry()
        self.callbacks = []
        self.unloads = []
        self.entry = SimpleNamespace(entry_id="entry", unique_id="example", options={},
                                     async_on_unload=self.unloads.append)
        def add_listener(callback):
            self.callbacks.append(callback)
            return lambda: self.callbacks.remove(callback)
        self.coordinator = SimpleNamespace(data=snapshot("radio0"), last_update_success=True,
            last_successful_poll=datetime(2026, 1, 1, tzinfo=timezone.utc),
            async_add_listener=add_listener)
        self.hass = SimpleNamespace(registry=self.registry)
        self.lifecycle = self.ns["RadioLifecycle"](self.hass, self.entry, self.coordinator)

    def poll(self, *ids):
        self.coordinator.data = snapshot(*ids)
        self.coordinator.last_successful_poll += timedelta(seconds=15)
        self.lifecycle.async_reconcile()

    def test_single_dual_single_dual_preserves_registry_identity_and_names(self):
        original = self.registry.add("radio0")
        self.lifecycle.async_start()
        self.poll("radio0", "link")
        link = self.registry.add("link")  # Existing monitoring discovery owns additions.
        before = (deepcopy(link.identifiers), link.name_by_user)
        self.poll("radio0")
        self.assertIsNone(link.disabled_by)
        self.poll("radio0")
        self.assertIs(link.disabled_by, Disabler.INTEGRATION)
        self.poll("radio0", "link")
        self.assertIsNone(link.disabled_by)
        self.assertIs(self.registry.devices["radio0"], original)
        self.assertIs(self.registry.devices["link"], link)
        self.assertEqual((link.identifiers, link.name_by_user), before)
        self.assertTrue(all(set(fields) == {"disabled_by"} for _, fields in self.registry.writes))

    def test_only_integration_disable_is_reversible(self):
        for reason in (Disabler.USER, Disabler.CONFIG_ENTRY, "device"):
            with self.subTest(reason=reason):
                d = self.registry.add("link", reason)
                self.poll("radio0")
                self.poll("radio0")
                self.poll("radio0", "link")
                self.assertEqual(d.disabled_by, reason)
        self.assertEqual(self.registry.writes, [])

    def test_duplicate_notifications_and_failed_polls_do_not_confirm_absence(self):
        d = self.registry.add("link")
        self.lifecycle.async_start()
        for _ in range(5):
            self.lifecycle.async_reconcile()  # GPS has the same full-poll stamp.
        self.assertIsNone(d.disabled_by)
        self.coordinator.last_update_success = False
        self.lifecycle.async_reconcile()
        self.coordinator.last_update_success = True
        self.poll("radio0")
        self.assertIsNone(d.disabled_by)
        self.poll("radio0")
        self.assertIs(d.disabled_by, Disabler.INTEGRATION)

    def test_bad_inventories_never_mutate_and_reset_confirmation(self):
        bad = [None, {}, {"stats": {"error": "offline"}}]
        for field, value in (("mode", None), ("radio_ids", []), ("radio_ids", ["radio0", "radio0"]),
                             ("radio_ids", [None]), ("radio_ids", ["bad id"])):
            data = snapshot("radio0")
            data["stats"]["radio_stack"][field] = value
            bad.append(data)
        for rows in (None, {}, [None], [{}], [{"id": "extra"}],
                     [{"id": "radio0"}, {"id": "radio0"}],
                     [{"id": "radio0", "radio_id": "other"}]):
            data = snapshot("radio0")
            data["stats"]["radios"] = rows
            bad.append(data)
        data = snapshot("radio0")
        data["stats"]["radio_stack"]["error"] = "offline"
        bad.append(data)
        d = self.registry.add("link")
        for data in bad:
            with self.subTest(data=data):
                self.poll("radio0")
                self.coordinator.data = data
                self.coordinator.last_successful_poll += timedelta(seconds=15)
                self.lifecycle.async_reconcile()
                self.assertIsNone(d.disabled_by)
                self.assertIsNone(self.ns["authoritative_radio_ids"](self.coordinator, self.entry))
        self.assertEqual(self.registry.writes, [])

    def test_unrelated_github_errors_do_not_block_valid_radio_inventory(self):
        d = self.registry.add("link")
        for _ in range(2):
            self.coordinator.data = snapshot("radio0")
            self.coordinator.data["update_status"] = {"error": "GitHub API rate limit exceeded"}
            self.coordinator.last_successful_poll += timedelta(seconds=15)
            self.lifecycle.async_reconcile()
        self.assertIs(d.disabled_by, Disabler.INTEGRATION)

    def test_alias_roundtrip_and_collision_fail_closed(self):
        self.entry.options = {"radio_id_aliases": {"local": "radio0"}}
        d = self.registry.add("radio0", Disabler.INTEGRATION)
        self.poll("local", "link")
        self.assertIsNone(d.disabled_by)
        self.poll("radio0")  # Alias source absent; canonical target itself returns.
        self.assertIsNone(d.disabled_by)
        self.assertEqual(self.ns["authoritative_radio_ids"](self.coordinator, self.entry), {"radio0"})
        self.poll("local", "radio0")
        self.assertIsNone(self.ns["authoritative_radio_ids"](self.coordinator, self.entry))
        self.poll("local", "radio0")
        self.assertIsNone(d.disabled_by)
        self.entry.options["radio_id_aliases"] = {"local": "local"}
        self.poll("radio0")
        self.assertIsNone(self.ns["authoritative_radio_ids"](self.coordinator, self.entry))

    def test_single_fabric_alias_roundtrip_retires_and_restores_without_identity_changes(self):
        self.entry.options = {"radio_id_aliases": {"local": "radio0"}}
        original = self.registry.add("radio0", Disabler.INTEGRATION)
        user_disabled = self.registry.add("user", Disabler.USER)
        link = self.registry.add("link")
        before = (deepcopy(original.identifiers), original.name_by_user)
        self.poll("local", "link", "user")
        self.assertIsNone(original.disabled_by)
        for index in range(2):
            self.coordinator.data = snapshot("radio0")
            self.coordinator.data["stats"]["radio_stack"]["mode"] = "single_fabric"
            self.coordinator.last_successful_poll += timedelta(seconds=15)
            self.lifecycle.async_reconcile()
            self.assertEqual(self.ns["authoritative_radio_ids"](self.coordinator, self.entry), {"radio0"})
            if index == 0:
                self.lifecycle.async_reconcile()  # Same stamp/GPS cannot confirm absence.
                self.assertIsNone(link.disabled_by)
                self.assertFalse(self.lifecycle.can_remove(link))
        self.assertIs(link.disabled_by, Disabler.INTEGRATION)
        self.assertTrue(self.lifecycle.can_remove(link))
        self.assertIs(user_disabled.disabled_by, Disabler.USER)
        self.poll("local", "link", "user")
        self.assertIsNone(link.disabled_by)
        self.assertIs(user_disabled.disabled_by, Disabler.USER)
        self.assertIs(self.registry.devices["radio0"], original)
        self.assertEqual((original.identifiers, original.name_by_user), before)
        self.assertTrue(all(set(fields) == {"disabled_by"} for _, fields in self.registry.writes))

    def test_single_fabric_keeps_single_mode_validation_guards(self):
        cases = [snapshot(), snapshot("radio0", "link"), snapshot("radio0", "radio0")]
        for field, value in (("radio_ids", [None]), ("radio_ids", ["bad id"]), ("error", "offline")):
            data = snapshot("radio0")
            data["stats"]["radio_stack"][field] = value
            cases.append(data)
        for rows in ([None], [{"id": "other"}], [{"id": "radio0"}, {"id": "radio0"}],
                     [{"id": "radio0", "radio_id": "other"}], [{"id": "radio0", "radio": None}]):
            data = snapshot("radio0")
            data["stats"]["radios"] = rows
            cases.append(data)
        absent = self.registry.add("absent")
        for data in cases:
            with self.subTest(data=data):
                self.coordinator.data = snapshot("radio0")
                self.coordinator.data["stats"]["radio_stack"]["mode"] = "single_fabric"
                self.coordinator.last_successful_poll += timedelta(seconds=15)
                self.lifecycle.async_reconcile()
                data["stats"]["radio_stack"]["mode"] = "single_fabric"
                self.coordinator.data = data
                self.coordinator.last_successful_poll += timedelta(seconds=15)
                self.lifecycle.async_reconcile()
                self.assertIsNone(self.ns["authoritative_radio_ids"](self.coordinator, self.entry))
                self.assertIsNone(absent.disabled_by)
                self.assertFalse(self.lifecycle.can_remove(absent))
        self.assertEqual(self.registry.writes, [])

    def test_unload_and_idempotent_start(self):
        self.lifecycle.async_start()
        self.lifecycle.async_start()
        self.assertEqual(len(self.callbacks), 1)
        self.assertEqual(len(self.unloads), 1)
        self.unloads[0]()
        self.assertEqual(self.callbacks, [])

    def test_explicit_removal_requires_confirmed_absence_and_current_valid_inventory(self):
        absent = self.registry.add("link")
        active = self.registry.add("radio0")
        allowed = self.lifecycle.can_remove
        self.lifecycle.async_start()
        self.assertFalse(allowed(absent))
        self.poll("radio0")
        self.assertTrue(allowed(absent))
        self.assertFalse(allowed(active))
        parent = SimpleNamespace(identifiers={("pymc_repeater", "example")}, config_entries={"entry"})
        self.assertFalse(allowed(parent))
        absent.config_entries.add("another_entry")
        self.assertFalse(allowed(absent))
        absent.config_entries.remove("another_entry")
        self.coordinator.data = {"stats": {"error": "offline"}}
        self.assertFalse(allowed(absent))

    def test_setup_and_removal_are_wired_to_owned_lifecycle(self):
        source = (ROOT / "__init__.py").read_text()
        self.assertIn('"radio_lifecycle": lifecycle', source)
        self.assertIn('lifecycle.async_start()', source)
        self.assertIn('lifecycle.can_remove(device_entry)', source)


if __name__ == "__main__":
    unittest.main()
