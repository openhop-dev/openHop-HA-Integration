"""Execute cached MQTT normalization and sensor values without HA/network.

Synthetic fixtures exercise checked-in implementation, not live HA registration.
Backend contract reviewed at 98444069ee49d21aff1e2a4d67a53ae7c53fecaa.
"""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from typing import Any
from types import SimpleNamespace

from test_installed_api_behavior import client_namespace
from test_traffic_counters import CoordinatorBoundary, SensorBoundary

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components/pymc_repeater"


class MqttUsageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ns = client_namespace()
        self.client = object.__new__(self.ns["PyMCRepeaterApiClient"])
        self.response = {}
        self.calls = []

        async def request(method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            return self.response

        self.client._async_request_json = request

    async def get(self, payload, wrapped=True):
        self.response = {"success": True, "data": payload} if wrapped else payload
        return await self.client.async_get_mqtt_status()

    async def test_cached_counters_raw_wrapped_and_minimized(self):
        payload = {"handler_active": True, "brokers": [
            {"name": "a", "status": {"connected": False},
             "sent": {"messages": 2, "payload_bytes": 123, "private": "PRIVATE"}},
            {"name": "b", "sent": {"messages": 3, "payload_bytes": 0}},
        ]}
        for wrapped in (True, False):
            result = await self.get(payload, wrapped)
            self.assertEqual(result["sent"], {"messages": 5, "payload_bytes": 123})
            self.assertNotIn("PRIVATE", repr(result))
            self.assertNotIn("sent", result["brokers"][0])
            self.assertEqual(result["brokers"][0]["name"], "a")
            self.assertEqual(result["brokers"][0]["status"], {"connected": False})
        self.assertIn("private", payload["brokers"][0]["sent"])
        self.assertEqual([call[:2] for call in self.calls], [("GET", "/api/mqtt_status")] * 2)

    async def test_legacy_malformed_and_missing_are_unknown_not_partial_zero(self):
        valid = {"sent": {"messages": 3, "payload_bytes": 5}}
        for bad in (None, {}, {"sent": {}}, {"sent": []},
                    *({"sent": {"messages": value, "payload_bytes": value}}
                      for value in (True, -1, 1.5, "2", float("nan"), float("inf"), 2**63))):
            result = await self.get({"handler_active": True, "brokers": [valid, bad]})
            self.assertEqual(result["sent"], {})
        for payload in ({}, {"brokers": []}, {"handler_active": False, "brokers": []},
                        {"handler_active": True, "brokers": {}},
                        {"handler_active": True, "brokers": [valid] * 101}):
            self.assertEqual((await self.get(payload))["sent"], {})

    async def test_zero_reset_and_overflow(self):
        self.assertEqual((await self.get({"handler_active": True, "brokers": []}))["sent"],
                         {"messages": 0, "payload_bytes": 0})
        for count in (99, 0, 1):
            result = await self.get({"handler_active": True, "brokers": [
                {"sent": {"messages": count, "payload_bytes": count}}]})
            self.assertEqual(result["sent"]["messages"], count)
        self.assertEqual((await self.get({"handler_active": True, "brokers": [
            {"sent": {"messages": 2**63-1, "payload_bytes": 0}},
            {"sent": {"messages": 1, "payload_bytes": 0}}]}))["sent"], {})

    async def test_backend_failure_and_auth_remain_errors(self):
        self.response = {"success": False, "error": "failure"}
        with self.assertRaises(self.ns["PyMCRepeaterApiError"]):
            await self.client.async_get_mqtt_status()
        async def fail(*args, **kwargs):
            raise self.ns["PyMCRepeaterAuthenticationError"]("auth")
        self.client._async_request_json = fail
        with self.assertRaises(self.ns["PyMCRepeaterAuthenticationError"]):
            await self.client.async_get_mqtt_status()

    def test_sensor_values_translations_units_and_snapshot_semantics(self):
        tree = ast.parse((COMPONENT / "sensor.py").read_text())
        nested = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_nested")
        ns = {"Any": Any}
        exec(compile(ast.Module(body=[nested], type_ignores=[]), "sensor.py", "exec"), ns)
        translations = json.loads((COMPONENT / "translations/en.json").read_text())["entity"]["sensor"]
        found = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fields = {item.arg: item.value for item in node.keywords}
            key = fields.get("key")
            if not isinstance(key, ast.Constant) or key.value not in ("mqtt_sent_messages", "mqtt_sent_payload_bytes"):
                continue
            found.add(key.value)
            field = "messages" if key.value.endswith("messages") else "payload_bytes"
            fn = eval(compile(ast.Expression(fields["value_fn"]), "sensor.py", "eval"), ns)
            for value in (0, 45):
                self.assertEqual(fn({"mqtt_status": {"sent": {field: value}}}), value)
            for data in ({}, {"mqtt_status": {"sent": {}}}, {"mqtt_status": {"error": "failed"}}):
                self.assertIsNone(fn(data))
            self.assertEqual(ast.unparse(fields["state_class"]), "SensorStateClass.MEASUREMENT")
            self.assertEqual(ast.literal_eval(fields["translation_key"]), key.value)
            self.assertIn(key.value, translations)
            self.assertNotIn("attrs_fn", fields)
            if field == "payload_bytes":
                self.assertEqual(ast.unparse(fields["native_unit_of_measurement"]), "UnitOfInformation.BYTES")
        self.assertEqual(found, {"mqtt_sent_messages", "mqtt_sent_payload_bytes"})

    async def test_poll_errors_are_optional_except_authentication_and_connection(self):
        async def empty(*args, **kwargs):
            return {}
        for name in dir(self.client):
            if name.startswith("async_get_"):
                setattr(self.client, name, empty)
        for error_name in ("PyMCRepeaterApiError", "PyMCRepeaterAuthenticationError", "PyMCRepeaterCannotConnect"):
            async def fail():
                raise self.ns[error_name]("test failure")
            self.client.async_get_mqtt_status = fail
            if error_name == "PyMCRepeaterApiError":
                result = await self.client.async_fetch_all()
                self.assertEqual(result["mqtt_status"], {"error": "test failure"})
                self.assertEqual(result["stats"], {})
            else:
                with self.assertRaises(self.ns[error_name]):
                    await self.client.async_fetch_all()

    def test_real_entity_identity_zero_missing_and_resets(self):
        tree = ast.parse((COMPONENT / "sensor.py").read_text())
        scope: dict[str, Any] = dict(CoordinatorEntity=CoordinatorBoundary, SensorEntity=SensorBoundary,
                     DeviceInfo=dict, DOMAIN="pymc_repeater", MANUFACTURER="openHop",
                     MODEL="Repeater", CONF_HOST="host", CONF_PORT="port",
                     DATA_SIZE_SENSOR_KEYS=set(), get_repeater_name_from_stats=lambda stats: None)
        nodes = [node for node in tree.body if getattr(node, "name", None) in
                 ("_nested", "PyMCBaseEntity", "PyMCSensorEntity")]
        # Execute trusted local code only; no remote payload is evaluated.
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "sensor.py", "exec"), scope)
        for unique_id in ("test-node", None):
            entry = SimpleNamespace(unique_id=unique_id, entry_id="test-entry", title="Test",
                                    data={"host": "example.invalid", "port": 8000}, options={})
            coordinator = SimpleNamespace(data={})
            for key, field, unit in (("mqtt_sent_messages", "messages", "messages"),
                                     ("mqtt_sent_payload_bytes", "payload_bytes", "B")):
                call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                            and any(kw.arg == "key" and isinstance(kw.value, ast.Constant)
                                    and kw.value.value == key for kw in node.keywords))
                value_node = next(kw.value for kw in call.keywords if kw.arg == "value_fn")
                fn = eval(compile(ast.Expression(value_node), "sensor.py", "eval"), scope)
                description = SimpleNamespace(key=key, value_fn=fn, native_unit_of_measurement=unit, attrs_fn=None)
                entity = scope["PyMCSensorEntity"](entry, coordinator, description)
                self.assertEqual(entity._attr_unique_id, f"{unique_id or entry.entry_id}_{key}")
                self.assertEqual(entity.device_info["identifiers"], {("pymc_repeater", unique_id or entry.entry_id)})
                self.assertEqual(entity.native_unit_of_measurement, unit)
                self.assertIsNone(entity.extra_state_attributes)
                for value in (100, 0, 2, None):
                    coordinator.data = {"mqtt_status": {"sent": {field: value}}}
                    self.assertEqual(entity.native_value, value)

    def test_poll_set_does_not_add_history_or_new_endpoint(self):
        tree = ast.parse((COMPONENT / "api.py").read_text())
        fetch = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_fetch_all")
        source = ast.unparse(fetch)
        self.assertEqual(source.count("self.async_get_mqtt_status()"), 1)
        self.assertNotIn("network_usage", source)
        self.assertNotIn("history", source)


if __name__ == "__main__":
    unittest.main()
