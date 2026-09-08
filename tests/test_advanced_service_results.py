"""Execute real advanced client/service bodies with fake HTTP and HA boundaries."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components/pymc_repeater"


def load_source(filename, namespace, predicate):
    tree = ast.parse((COMPONENT / filename).read_text())
    nodes: list[ast.stmt] = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    nodes.extend(node for node in tree.body if predicate(node))
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), filename, "exec"), namespace)
    return namespace


def api_namespace():
    return load_source("api.py", {"asyncio": asyncio, "DEFAULT_PACKET_WINDOW_HOURS": 24},
                       lambda n: isinstance(n, ast.Assign) or
                       isinstance(n, ast.ClassDef) and n.name.startswith("PyMCRepeater"))


class AdvancedClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ns = api_namespace()
        self.api = object.__new__(self.ns["PyMCRepeaterApiClient"])
        self.request = self.api._async_request_json = AsyncMock(return_value={"success": True, "data": {}})

    async def test_http_budgets_cover_backend_waits(self):
        cases = [
            ("companion_request_status", {"pub_key": "example"}, 25),
            ("companion_request_telemetry", {"pub_key": "example"}, 30),
            ("companion_request_status", {"pub_key": "example", "timeout": 120}, 130),
            ("companion_request_telemetry", {"pub_key": "example", "timeout": 1}, 11),
            ("companion_login", {"pub_key": "example"}, 20),
            ("companion_send_command", {"pub_key": "example", "command": "example"}, 25),
            ("companion_send_text", {"pub_key": "example", "text": "example"}, 35),
            ("companion_send_channel_message", {"channel_idx": 0, "text": "example"}, 35),
            ("ping_neighbor", {"target_id": "01"}, 16),
            ("ping_neighbor", {"target_id": "01", "timeout": 60}, 66),
            ("cad_manual_check", {}, 10),
            ("cad_manual_check", {"samples": 32, "cad_timeout_ms": 5000}, 167),
            ("cad_manual_check", {"samples": 320, "cad_timeout_ms": 50000}, 167),
            ("cad_calibration_start", {"samples": 64, "cad_timeout_ms": 5000}, 10),
        ]
        for name, kwargs, budget in cases:
            with self.subTest(name=name, kwargs=kwargs):
                await getattr(self.api, "async_" + name)(**kwargs)
                self.assertEqual(self.request.call_args.kwargs["timeout_seconds"], budget)
                for key, value in kwargs.items():
                    self.assertEqual(self.request.call_args.kwargs["json_body"][key], value)

    async def test_real_http_body_applies_budget_and_preserves_auth(self):
        # Restore the real JSON method; fake only the session/response boundary.
        del self.api._async_request_json
        self.api.host, self.api.port, self.api.api_token = "example.invalid", 8000, "example-token"
        self.ns["URL"] = SimpleNamespace(build=lambda **kw: "http://example.invalid:8000")
        self.ns["ClientError"] = type("ClientError", (Exception,), {})
        budgets = []
        http_calls = []

        class Response:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def json(self, **kwargs):
                return {"success": True, "data": {"status_data": {"battery": 3.5}}}

        def request(*args, **kwargs):
            http_calls.append((args, kwargs))
            return Response()

        def timeout(seconds):
            budgets.append(seconds)
            return asyncio.timeout(seconds)

        self.ns["asyncio"] = SimpleNamespace(timeout=timeout)
        self.api._session = SimpleNamespace(request=request)
        result = await self.api.async_companion_request_status(pub_key="example", timeout=120)
        self.assertEqual(result, {"status_data": {"battery": 3.5}})
        self.assertEqual(budgets, [130])
        self.assertEqual(http_calls[0][0], ("POST", "http://example.invalid:8000/api/companion/request_status"))
        self.assertEqual(http_calls[0][1]["json"]["timeout"], 120)
        self.assertEqual(http_calls[0][1]["headers"]["X-API-Key"], "example-token")

    async def test_invalid_timeouts_never_reach_http(self):
        for name, key, maximum in [("companion_request_status", "pub_key", 120),
                                   ("companion_request_telemetry", "pub_key", 120),
                                   ("ping_neighbor", "target_id", 60)]:
            for timeout in [0, -1, maximum + 1, float("nan"), float("inf")]:
                with self.subTest(name=name, timeout=timeout):
                    with self.assertRaises(self.ns["PyMCRepeaterApiError"]):
                        await getattr(self.api, "async_" + name)(**{key: "example", "timeout": timeout})
        self.request.assert_not_called()

    async def test_explicit_send_failure_is_not_success(self):
        for name, kwargs in [("companion_send_text", {"pub_key": "example", "text": "example"}),
                             ("companion_send_channel_message", {"channel_idx": 0, "text": "example"})]:
            for payload in [{"success": True, "data": {"sent": False}}, {"sent": False}]:
                self.request.return_value = payload
                with self.subTest(name=name, payload=payload):
                    with self.assertRaises(self.ns["PyMCRepeaterApiError"]):
                        await getattr(self.api, "async_" + name)(**kwargs)
            for data in [{"sent": True, "expected_ack": 123}, {}]:
                self.request.return_value = {"success": True, "data": data}
                self.assertEqual(await getattr(self.api, "async_" + name)(**kwargs), data)


class SchemaBoundary:
    """Only stand in for dependency construction; not HA schema validation."""
    def __getattr__(self, name):
        return lambda *args, **kwargs: (name, repr(args), repr(kwargs))


class AdvancedServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_optional_response_preserves_legacy_calls_and_payload(self):
        registry = {}
        ns = api_namespace()
        ns.update(vol=SchemaBoundary(), DOMAIN="pymc_repeater", HomeAssistantError=RuntimeError,
                  SupportsResponse=SimpleNamespace(ONLY="only", OPTIONAL="optional"))
        load_source("__init__.py", ns, lambda n:
                    isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and
                    (t.id.startswith("SERVICE_") or t.id in {"CONF_ENTRY_ID", "LEGACY_CONF_ENTRY_ID"}) for t in n.targets)
                    or isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and
                    n.name in {"_async_register_services", "_resolve_entry_id", "_async_refresh_entry"})
        api = object.__new__(ns["PyMCRepeaterApiClient"])
        api._async_request_json = AsyncMock()
        refresh = AsyncMock()
        hass = SimpleNamespace(data={"pymc_repeater": {"example": {"api": api, "coordinator": SimpleNamespace(async_request_refresh=refresh)}}},
                               services=SimpleNamespace(has_service=lambda *a: False,
                               async_register=lambda domain, service, handler, **kw: registry.update({service: (handler, kw)})))
        await ns["_async_register_services"](hass)
        for service in ["companion_request_status", "companion_request_telemetry"]:
            handler, metadata = registry[service]
            self.assertEqual(metadata.get("supports_response"), "optional")
            for result in [{"status_data": {"battery": 3.5}}, {"telemetry_data": {"sensors": []}}, None, [1, 2]]:
                api._async_request_json.return_value = {"success": True, "data": result}
                for requested in [True, False]:
                    call = SimpleNamespace(data={"pub_key": "example", "config_entry_id": "example"}, return_response=requested)
                    actual = await handler(call)
                    expected = result if isinstance(result, dict) else {"result": result}
                    self.assertEqual(actual, expected if requested else None)
        for service, data in [
            ("companion_send_text", {"pub_key": "example", "text": "example"}),
            ("companion_send_channel_message", {"channel_idx": 0, "text": "example"}),
            ("companion_request_status", {"pub_key": "example"}),
            ("companion_request_telemetry", {"pub_key": "example"}),
        ]:
            api._async_request_json.return_value = (
                {"success": True, "data": {"sent": False}} if "send" in service
                else {"success": False, "error": "Example backend failure"}
            )
            with self.subTest(service=service):
                with self.assertRaises(RuntimeError):
                    await registry[service][0](SimpleNamespace(data=data, return_response=True))
        refresh.assert_not_called()
