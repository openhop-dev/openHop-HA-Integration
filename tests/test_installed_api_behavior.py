"""Execute actual client methods with stdlib-only fake HTTP boundaries.

No Home Assistant imports, network, installed source or private fixtures required.
AST extraction removes dependency imports, not the implementation under test.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/pymc_repeater"


def client_namespace():
    tree = ast.parse((COMPONENT / "api.py").read_text())
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)
               and (node.name.startswith("PyMCRepeater"))]
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *classes], type_ignores=[])
    namespace = {"Any": Any, "asyncio": asyncio, "DEFAULT_PACKET_WINDOW_HOURS": 24,
                 "REQUEST_TIMEOUT": 10, "NEIGHBOR_SCOPE_QUERY_TIMEOUT": 50}
    exec(compile(ast.fix_missing_locations(module), "api.py", "exec"), namespace)
    return namespace


class InstalledApiBehaviorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ns = client_namespace()
        self.client = object.__new__(self.ns["PyMCRepeaterApiClient"])
        self.calls = []
        self.response = {}

        async def request(method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            return self.response

        self.client._async_request_json = request

    async def test_plugin_list_is_reduced_to_counts_without_private_metadata(self):
        self.assertTrue(hasattr(self.client, "async_get_plugin_summary"))
        self.response = {"success": True, "plugins": [
            {"id": "example", "enabled": True, "state": "RUNNING", "data_dir": "PRIVATE", "repository": "PRIVATE"},
            {"enabled": True, "state": "FAILED"},
            {"enabled": False, "state": "DISABLED"},
            {"enabled": True, "state": "STOPPED", "has_runtime": False},
        ]}
        result = await self.client.async_get_plugin_summary()
        self.assertEqual({key: result[key] for key in ("installed", "enabled", "running", "failed")},
                         {"installed": 4, "enabled": 3, "running": 1, "failed": 1})
        self.assertEqual(result["plugins"], [{"id": "example", "enabled": True, "state": "RUNNING"}])
        self.assertNotIn("PRIVATE", repr(result))
        self.assertEqual(self.calls[0][:2], ("GET", "/api/plugins/"))
        self.assertEqual(self.calls[0][2]["auth"], "api_token")

    async def test_empty_plugin_list_means_zero_not_unavailable(self):
        self.assertTrue(hasattr(self.client, "async_get_plugin_summary"))
        self.response = {"success": True, "plugins": []}
        self.assertEqual(await self.client.async_get_plugin_summary(),
                         dict(installed=0, enabled=0, running=0, failed=0, plugins=[]))

    async def test_malformed_plugin_list_is_not_reported_as_zero(self):
        self.assertTrue(hasattr(self.client, "async_get_plugin_summary"))
        for payload in ({}, {"plugins": None}, {"plugins": {}}, {"plugins": [None]},
                        {"plugins": [{"enabled": "false", "state": "RUNNING"}]}):
            self.response = payload
            with self.assertRaises(self.ns["PyMCRepeaterApiError"]):
                await self.client.async_get_plugin_summary()

    async def test_plugin_api_failure_is_not_a_successful_empty_inventory(self):
        self.assertTrue(hasattr(self.client, "async_get_plugin_summary"))
        self.response = {"success": False, "error": "Plugin manager unavailable"}
        with self.assertRaises(self.ns["PyMCRepeaterApiError"]):
            await self.client.async_get_plugin_summary()

    async def test_bucket_history_preserves_bucket_response_and_query(self):
        import inspect
        self.assertIn("bucket_seconds", inspect.signature(self.client.async_get_neighbor_link_history).parameters)
        self.response = {"success": True, "data": {"count": 1, "bucket_seconds": 300, "buckets": [{"count": 2}]}}
        result = await self.client.async_get_neighbor_link_history(peer_hash="AB", path_hash_size=1, bucket_seconds=300)
        self.assertEqual(result, self.response["data"])
        self.assertEqual(self.calls[0][2]["params"], dict(peer_hash="AB", path_hash_size=1, hours=24, limit=1000, bucket_seconds=300))

    async def test_legacy_history_omits_bucket_parameter(self):
        self.response = {"success": True, "data": {"count": 0, "rows": []}}
        self.assertEqual(await self.client.async_get_neighbor_link_history(peer_hash="AB", path_hash_size=1), self.response["data"])
        self.assertNotIn("bucket_seconds", self.calls[0][2]["params"])

    async def test_polling_is_optional_for_plugin_api_errors_but_not_auth(self):
        self.assertTrue(hasattr(self.client, "async_get_plugin_summary"))
        async def empty(*args, **kwargs):
            return {}
        for name in dir(self.client):
            if name.startswith("async_get_"):
                setattr(self.client, name, empty)
        for error_name in ("PyMCRepeaterApiError", "PyMCRepeaterAuthenticationError", "PyMCRepeaterCannotConnect"):
            async def fail():
                raise self.ns[error_name]("test failure")
            self.client.async_get_plugin_summary = fail
            if error_name == "PyMCRepeaterApiError":
                result = await self.client.async_fetch_all()
                self.assertEqual(result["plugin_summary"], {"error": "test failure"})
                self.assertEqual(result["stats"], {})
            else:
                with self.assertRaises(self.ns[error_name]):
                    await self.client.async_fetch_all()

    def test_new_sensor_values_and_missing_data(self):
        tree = ast.parse((COMPONENT / "sensor.py").read_text())
        expected = {f"plugins_{key}": key for key in ("installed", "enabled", "running", "failed")}
        found = {}
        nested = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_nested")
        ns = {"Any": Any}
        exec(compile(ast.Module(body=[nested], type_ignores=[]), "sensor.py", "exec"), ns)
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            fields = {k.arg: k.value for k in call.keywords}
            key = fields.get("key")
            if isinstance(key, ast.Constant) and key.value in expected:
                # Execute only a lambda from our checked-in trusted source, never API data.
                fn = eval(compile(ast.Expression(fields["value_fn"]), "sensor.py", "eval"), ns)
                found[key.value] = fn
        self.assertEqual(set(found), set(expected))
        for name, fn in found.items():
            self.assertEqual(fn({"plugin_summary": {expected[name]: 2}}), 2)
            self.assertIsNone(fn({"plugin_summary": {"error": "unavailable"}}))
            self.assertIsNone(fn({}))

    def test_metadata_matches_new_entities_and_history_bounds(self):
        import json
        translations = json.loads((COMPONENT / "translations/en.json").read_text())["entity"]["sensor"]
        dashboard = (ROOT / "dashboards/openhop_repeater_dashboard.yaml").read_text()
        for key, label in (("installed", "Installed"), ("enabled", "Enabled"),
                           ("running", "Running"), ("failed", "Failed")):
            self.assertEqual(translations[f"plugins_{key}"]["name"], f"{label} plugins")
            self.assertIn(f"sensor.REPEATER_SLUG_{key}_plugins", dashboard)
        tree = ast.parse((COMPONENT / "__init__.py").read_text())
        bucket_schema = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Call) and key.args and isinstance(key.args[0], ast.Constant) and key.args[0].value == "bucket_seconds":
                        bucket_schema = ast.unparse(value)
                        self.assertFalse(key.keywords, "Bucket mode must stay opt-in without a default")
        self.assertEqual(bucket_schema, "vol.All(vol.Coerce(int), vol.Range(min=60))")
        services = (COMPONENT / "services.yaml").read_text()
        history = services.split("get_neighbor_link_history:", 1)[1].split("get_adverts_by_contact_type:", 1)[0]
        self.assertIn("bucket_seconds:", history)
        self.assertIn("min: 60", history)

    def test_history_service_bucket_wiring_and_no_history_polling(self):
        source = (COMPONENT / "__init__.py").read_text()
        self.assertIn('bucket_seconds=call.data.get("bucket_seconds")', source)
        self.assertIn('vol.Optional("bucket_seconds")', source)
        client = ast.parse((COMPONENT / "api.py").read_text())
        fetch = next(n for n in ast.walk(client) if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_fetch_all")
        self.assertNotIn("async_get_neighbor_link_history", ast.unparse(fetch))
        self.assertNotIn("progress", ast.unparse(fetch))


if __name__ == "__main__":
    unittest.main()
