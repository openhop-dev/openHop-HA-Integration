"""Execute actual MQTT normalization/discovery/entities with fake HA boundaries.

No Home Assistant installation, HTTP traffic, registry or recorder is exercised.
"""
from __future__ import annotations

import ast
import json
import re
import sys
import types
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from test_installed_api_behavior import client_namespace

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components/pymc_repeater"


class CoordinatorBoundary:
    _attr_unique_id: str

    def __init__(self, coordinator):
        self.coordinator = coordinator

    @property
    def available(self):
        return self.coordinator.last_update_success

    @property
    def unique_id(self):
        return self._attr_unique_id


class SensorBoundary:
    @property
    def extra_state_attributes(self):
        return getattr(self, "_attr_extra_state_attributes", None)


class Coordinator:
    def __init__(self):
        self.data = {}
        self.last_update_success = True
        self.listeners = []

    def async_add_listener(self, callback):
        self.listeners.append(callback)
        return lambda: self.listeners.remove(callback)

    def publish(self, data):
        self.data = data
        for callback in list(self.listeners):
            callback()


class BrokerUsageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tree = ast.parse((COMPONENT / "sensor.py").read_text())
        names = {"_nested", "_mqtt_usage_brokers", "_setup_mqtt_usage_sensors",
                 "PyMCBaseEntity", "PyMCMqttBrokerUsageSensor"}
        # Replace only HA's boundary and slug utility, executing checked-in bodies.
        self.scope: dict[str, Any] = dict(CoordinatorEntity=CoordinatorBoundary, SensorEntity=SensorBoundary,
                          EntityCategory=SimpleNamespace(DIAGNOSTIC="diagnostic"),
                          SensorStateClass=SimpleNamespace(MEASUREMENT="measurement"),
                          SensorDeviceClass=SimpleNamespace(DATA_SIZE="data_size"),
                          UnitOfInformation=SimpleNamespace(BYTES="B"),
                          slugify=lambda value: re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_"),
                          DeviceInfo=dict, DOMAIN="pymc_repeater", MANUFACTURER="openHop",
                          MODEL="Repeater", CONF_HOST="host", CONF_PORT="port",
                          get_repeater_name_from_stats=lambda stats: None)
        nodes = [node for node in self.tree.body if getattr(node, "name", None) in names]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "sensor.py", "exec"), self.scope)
        self.coordinator = Coordinator()
        self.unload = []
        self.entry = SimpleNamespace(unique_id="test-node", entry_id="entry", title="Test",
                                     data={"host": "example.invalid", "port": 8000},
                                     async_on_unload=self.unload.append)
        self.entities = []
        ns = client_namespace()
        self.client = object.__new__(ns["PyMCRepeaterApiClient"])
        self.calls = []

        async def request(method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            return {"success": True, "data": self.raw}

        self.client._async_request_json = request

    @staticmethod
    def row(name: Any = "Example Broker 1", count=7, **kwargs):
        return {"name": name, "sent": {"messages": count, "payload_bytes": count * 10}, **kwargs}

    async def publish(self, rows, **kwargs):
        self.raw = {"handler_active": True, "brokers": rows, **kwargs}
        result = await self.client.async_get_mqtt_status()
        self.coordinator.publish({"mqtt_status": result})
        return result

    def discover(self):
        self.scope["_setup_mqtt_usage_sensors"](self.entry, self.coordinator, self.entities.extend)

    async def test_setup_late_discovery_removal_reappearance_and_unload(self):
        self.discover()
        self.assertEqual(self.entities, [])
        self.assertEqual(len(self.coordinator.listeners), 1)
        await self.publish([self.row()])
        first = list(self.entities)
        self.assertEqual(len(first), 2)
        self.assertEqual([e.native_value for e in first], [7, 70])
        await self.publish([self.row(), self.row("Second", 0)])
        self.assertEqual(len(self.entities), 4)
        self.assertTrue(all(e.available for e in self.entities))
        await self.publish([])
        self.assertTrue(all(not e.available and e.native_value is None for e in self.entities))
        for count in (99, 0, 1):
            await self.publish([self.row(count=count)])
            self.assertEqual([e.native_value for e in first], [count, count * 10])
            self.assertTrue(all(e.available for e in first))
            self.assertEqual(len(self.entities), 4)
        for callback in self.unload:
            callback()
        self.assertEqual(self.coordinator.listeners, [])
        await self.publish([self.row("Late after unload")])
        self.assertEqual(len(self.entities), 4)
        setup = next(n for n in self.tree.body if getattr(n, "name", None) == "async_setup_entry")
        self.assertIn("_setup_mqtt_usage_sensors(entry, coordinator, async_add_entities)", ast.unparse(setup))

    async def test_actual_platform_setup_discovers_current_and_future_brokers(self):
        await self.publish([self.row()])
        setup = next(n for n in self.tree.body if getattr(n, "name", None) == "async_setup_entry")
        self.scope.update(__package__="mqtt_test_boundary", SENSORS=(),
                          _room_items=lambda data: [], _companion_items=lambda data: [],
                          _external_sensor_data_items=lambda data: [])
        monitoring = types.ModuleType("mqtt_test_boundary.monitoring_entities")
        setattr(monitoring, "setup_monitoring_sensors", lambda *args: None)
        exec(compile(ast.Module(body=[setup], type_ignores=[]), "sensor.py", "exec"), self.scope)
        hass = SimpleNamespace(data={"pymc_repeater": {"entry": {"coordinator": self.coordinator}}})
        with patch.dict(sys.modules, {monitoring.__name__: monitoring}):
            await self.scope["async_setup_entry"](hass, self.entry, self.entities.extend)
        self.assertEqual(len(self.entities), 2)
        await self.publish([self.row(), self.row("Future")])
        self.assertEqual(len(self.entities), 4)
        self.assertEqual(len(self.unload), 2)  # Existing external + new MQTT listeners.
        for callback in self.unload:
            callback()
        self.assertEqual(self.coordinator.listeners, [])

    async def test_identity_translations_metadata_no_private_attributes(self):
        self.entry.unique_id = None
        await self.publish([self.row(host="private.invalid", password="PRIVATE")])
        self.discover()
        translations = json.loads((COMPONENT / "translations/en.json").read_text())["entity"]["sensor"]
        for entity, field, suffix, unit in zip(self.entities, ("messages", "payload_bytes"),
                                              ("messages sent", "payload sent"), ("messages", "B")):
            self.assertEqual(entity.unique_id, f"entry_mqtt_broker_example_broker_1_sent_{field}")
            self.assertEqual(entity._attr_name, f"MQTT Example Broker 1 session {suffix}")
            self.assertEqual(entity._attr_native_unit_of_measurement, unit)
            self.assertEqual(entity._attr_state_class, "measurement")
            self.assertEqual(entity._attr_entity_category, "diagnostic")
            self.assertEqual(entity.device_info["identifiers"], {("pymc_repeater", "entry")})
            self.assertIsNone(entity.extra_state_attributes)
            self.assertNotIn("PRIVATE", repr(vars(entity)))
            self.assertNotIn("private.invalid", repr(vars(entity)))
            self.assertEqual(translations[entity._attr_translation_key]["name"].format(
                **entity._attr_translation_placeholders), entity._attr_name)
        # Host changes are not a broker-name identity change.
        await self.publish([self.row(host="changed.invalid")])
        self.assertTrue(all(e.available for e in self.entities))
        self.coordinator.last_update_success = False
        self.assertTrue(all(not e.available for e in self.entities))

    async def test_duplicates_collisions_and_name_takeover_fail_closed(self):
        self.discover()
        for rows in ([self.row(), self.row()],
                     [self.row("Broker-A"), self.row("Broker A")],
                     [self.row(), {"name": "Example Broker 1", "sent": {}}]):
            await self.publish(rows)
            self.assertEqual(self.scope["_mqtt_usage_brokers"](self.coordinator.data), {})
            self.assertEqual(self.entities, [])
        await self.publish([self.row("Broker-A")])
        self.assertEqual(len(self.entities), 2)
        await self.publish([self.row("Broker A")])
        self.assertEqual(len(self.entities), 2)
        self.assertTrue(all(not e.available for e in self.entities))
        await self.publish([self.row("Broker-A")])
        self.assertTrue(all(e.available for e in self.entities))

    async def test_legacy_disabled_failed_malformed_and_unknown_do_not_become_zero(self):
        await self.publish([self.row()])
        self.discover()
        for bad in (None, {}, [], {"messages": 1}, {"payload_bytes": 1},
                    *({"messages": value, "payload_bytes": 1} for value in
                      (True, -1, 1.5, "2", float("nan"), float("inf"), 2**63))):
            result = await self.publish([{"name": "Example Broker 1", "sent": bad}])
            self.assertEqual(result["sent"], {})
            self.assertNotIn("sent", result["brokers"][0])
            self.assertTrue(all(not e.available and e.native_value is None for e in self.entities))
        for rows, overrides in (([self.row()], {"handler_active": False}),
                                ([self.row()], {"error": "failed"}),
                                ([self.row(error="failed")], {}),
                                ([{"host": "no-name", "sent": {"messages": 1, "payload_bytes": 1}}], {}),
                                ([self.row(name=5)], {}),
                                ([self.row(name="!!!")], {}),
                                ([self.row()] * 101, {}),
                                ({"sent": {"private": "PRIVATE"}}, {})):
            await self.publish(rows, **overrides)
            self.assertTrue(all(not e.available for e in self.entities))
        self.coordinator.publish({"mqtt_status": {"error": "endpoint failed"}})
        self.assertTrue(all(not e.available for e in self.entities))
        result = await self.publish([self.row(sent={"messages": 0, "payload_bytes": 0, "private": "PRIVATE"})])
        self.assertNotIn("PRIVATE", repr(result))
        self.assertEqual(result["brokers"][0]["sent"], {"messages": 0, "payload_bytes": 0})
        self.assertTrue(all(e.available and e.native_value == 0 for e in self.entities))

    async def test_partial_inventory_and_sum_overflow_preserve_individuals(self):
        self.discover()
        result = await self.publish([self.row(), {"name": "Legacy"}])
        self.assertEqual(result["sent"], {})
        self.assertEqual(len(self.entities), 2)
        self.assertEqual(self.entities[0].native_value, 7)
        result = await self.publish([self.row(sent={"messages": 2**63-1, "payload_bytes": 0}), self.row("Second", 1)])
        self.assertEqual(result["sent"], {})
        self.assertEqual(self.entities[0].native_value, 2**63-1)
        self.assertTrue(all(e.available for e in self.entities))
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(all(call[:2] == ("GET", "/api/mqtt_status") for call in self.calls))


if __name__ == "__main__":
    unittest.main()
