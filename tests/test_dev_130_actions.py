"""Execute 1.3.0 client/actions with fake HTTP and HA boundaries.

The small schema boundary executes validators/defaults; it is not a substitute
for real Voluptuous/Home Assistant registration or authenticated RF tests.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components/pymc_repeater"
MISSING = object()


def load(filename, ns, predicate):
    tree = ast.parse((COMPONENT / filename).read_text())
    nodes: list[ast.stmt] = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    nodes += [node for node in tree.body if predicate(node)]
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), filename, "exec"), ns)
    return ns


class Invalid(ValueError):
    pass


class Field:
    def __init__(self, key, default=MISSING, required=False):
        self.key, self.default, self.required = key, default, required


class SchemaBoundary:
    Invalid = Invalid

    def Optional(self, key, default=MISSING):
        return Field(key, default)

    def Required(self, key):
        return Field(key, required=True)

    def Schema(self, fields):
        def validate(data):
            result = {}
            if set(data) - {field.key for field in fields}:
                raise Invalid("Unknown field")
            for field, validator in fields.items():
                value = data.get(field.key, field.default)
                if value is MISSING:
                    if field.required:
                        raise Invalid("Required field")
                    continue
                if isinstance(validator, type):
                    if not isinstance(value, validator):
                        raise Invalid("Incorrect type")
                    result[field.key] = value
                else:
                    result[field.key] = validator(value)
            return result
        return validate

    def All(self, *validators):
        def validate(value):
            for validator in validators:
                if isinstance(validator, type):
                    if not isinstance(value, validator):
                        raise Invalid("Incorrect type")
                else:
                    value = validator(value)
            return value
        return validate

    def Coerce(self, kind):
        def validate(value):
            try:
                return kind(value)
            except (ValueError, TypeError, OverflowError) as err:
                raise Invalid(str(err)) from err
        return validate

    def Range(self, min=None, max=None):
        def validate(value):
            if (min is not None and not value >= min) or (max is not None and not value <= max):
                raise Invalid("Out of range")
            return value
        return validate

    def In(self, choices):
        def validate(value):
            if value not in choices:
                raise Invalid("Invalid choice")
            return value
        return validate

    def Length(self, min=0):
        def validate(value):
            if len(value) < min:
                raise Invalid("Too short")
            return value
        return validate

    # Unrelated action validators need construction, not execution here.
    def Any(self, *args):
        return lambda value: value

    def Match(self, *args):
        return lambda value: value


class ActionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ns = load("api.py", {"asyncio": asyncio, "DEFAULT_PACKET_WINDOW_HOURS": 24},
                       lambda n: isinstance(n, ast.Assign) or
                       isinstance(n, ast.ClassDef) and n.name.startswith("PyMCRepeater"))
        self.api = object.__new__(self.ns["PyMCRepeaterApiClient"])
        self.request = self.api._async_request_json = AsyncMock(return_value={"success": True, "data": {}})
        self.error = self.ns["PyMCRepeaterApiError"]
        self.ns.update(vol=SchemaBoundary(), DOMAIN="pymc_repeater", HomeAssistantError=RuntimeError,
                       SupportsResponse=SimpleNamespace(ONLY="only", OPTIONAL="optional"))
        load("__init__.py", self.ns, lambda n:
             isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and
             (t.id.startswith("SERVICE_") or t.id in {"CONF_ENTRY_ID", "LEGACY_CONF_ENTRY_ID"}) for t in n.targets)
             or isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and
             n.name in {"_async_register_services", "_resolve_entry_id", "_async_refresh_entry"})
        self.registry = {}
        self.refresh = AsyncMock()
        self.hass = SimpleNamespace(data={"pymc_repeater": {"example": {"api": self.api,
                                   "coordinator": SimpleNamespace(async_request_refresh=self.refresh)}}},
                                   services=SimpleNamespace(has_service=lambda *a: False,
                                   async_register=lambda domain, name, handler, **kw:
                                   self.registry.update({name: (handler, kw)})))
        await self.ns["_async_register_services"](self.hass)

    async def action(self, name, **data):
        handler, metadata = self.registry[name]
        data = metadata["schema"](data)
        return await handler(SimpleNamespace(data=data, return_response=True))

    async def test_default_queries_and_response_shapes_no_refresh(self):
        cases = [
            ("get_radio_packet_rates", "/api/radio_packet_rates", {"hours": 24}),
            ("get_noise_floor_stats", "/api/noise_floor_stats", {"hours": 24}),
            ("get_crc_error_count", "/api/crc_error_count", {"hours": 24}),
            ("get_companion_stats", "/api/companion/stats", {"type": "packets"}),
            ("get_lbt_diagnostics", "/api/lbt_diagnostics", {"hours": 24}),
        ]
        for name, path, params in cases:
            self.assertEqual(self.registry[name][1]["supports_response"], "only")
            for data in ({"example": 1}, [1, 2], None):
                # Noise retains its established stats dictionary contract.
                if name == "get_noise_floor_stats" and not isinstance(data, dict):
                    continue
                for wrapped in (False, True):
                    self.request.return_value = {"success": True, "data": data} if wrapped else data
                    if not wrapped and not isinstance(data, dict):
                        continue
                    result = await self.action(name)
                    self.assertEqual(result, data if isinstance(data, dict) else {"result": data})
                    self.assertEqual(self.request.call_args.args, ("GET", path))
                    self.assertEqual(self.request.call_args.kwargs["params"], params)
                    self.assertEqual(self.request.call_args.kwargs["auth"], "api_token")
        self.refresh.assert_not_called()

    async def test_explicit_queries_and_limits(self):
        cases = [
            ("get_radio_packet_rates", dict(hours=168, bucket_seconds=86400)),
            ("get_noise_floor_stats", dict(hours=1, radio_id="radio:west")),
            ("get_crc_error_count", dict(hours=168, radio_id="radio:west")),
            ("get_lbt_diagnostics", dict(hours=1, bucket_seconds=3600, severe_attempt_threshold=16)),
        ]
        for name, data in cases:
            await self.action(name, **data)
            self.assertEqual(self.request.call_args.kwargs["params"], data)
        for kind in ("core", "radio", "packets"):
            data = dict(type=kind, companion_name="Example Companion")
            await self.action("get_companion_stats", **data)
            self.assertEqual(self.request.call_args.kwargs["params"], data)
        self.refresh.assert_not_called()

    async def test_invalid_queries_rejected_before_http_client_and_schema(self):
        for name, key, minimum, maximum in [
            ("get_radio_packet_rates", "hours", 1, 168),
            ("get_radio_packet_rates", "bucket_seconds", 60, 86400),
            ("get_noise_floor_stats", "hours", 1, 168),
            ("get_crc_error_count", "hours", 1, 168),
            ("get_lbt_diagnostics", "hours", 1, 168),
            ("get_lbt_diagnostics", "bucket_seconds", 60, 3600),
            ("get_lbt_diagnostics", "severe_attempt_threshold", 2, 16),
        ]:
            for value in (minimum - 1, maximum + 1, float("nan"), float("inf"), -float("inf"), True, minimum + .5):
                with self.subTest(name=name, key=key, value=value):
                    with self.assertRaises(Invalid):
                        await self.action(name, **{key: value})
                    with self.assertRaises(self.error):
                        await getattr(self.api, "async_" + name)(**{key: value})
        for name in ("get_noise_floor_stats", "get_crc_error_count"):
            for value in ("", " ", " radio0", "radio0 ", 1, False):
                with self.assertRaises(Invalid):
                    await self.action(name, radio_id=value)
                with self.assertRaises(self.error):
                    await getattr(self.api, "async_" + name)(radio_id=value)
        with self.assertRaises(Invalid):
            await self.action("get_lbt_diagnostics", radio_id="radio0")
        with self.assertRaises(Invalid):
            await self.action("get_companion_stats", type="wrong")
        with self.assertRaises(self.error):
            await self.api.async_get_companion_stats(type="wrong")
        self.request.assert_not_called()
        self.refresh.assert_not_called()

    async def test_neighbor_defaults_and_split_filter_preserve_payload(self):
        for wrapped in (False, True):
            for data, query in [({"rows": [], "count": 0}, {}),
                                ({"buckets": [{"radio_id": "r:1", "n": 2}], "by_radio": True},
                                 dict(bucket_seconds=300, radio_id="r:1", by_radio=True)),
                                ({"rows": []}, dict(by_radio=False))]:
                self.request.return_value = {"success": True, "data": data} if wrapped else data
                self.assertEqual(await self.action("get_neighbor_link_history", peer_hash="AB", path_hash_size=1, **query), data)
                expected = dict(peer_hash="AB", path_hash_size=1, hours=24, limit=1000, **query)
                if "by_radio" in expected:
                    expected["by_radio"] = str(expected["by_radio"]).lower()
                self.assertEqual(self.request.call_args.kwargs["params"], expected)
        self.request.reset_mock()
        for query in (dict(by_radio=True), dict(by_radio="true"), dict(radio_id=""), dict(bucket_seconds=86401)):
            with self.assertRaises((Invalid, RuntimeError)):
                await self.action("get_neighbor_link_history", peer_hash="AB", path_hash_size=1, **query)
        self.request.assert_not_called()
        self.refresh.assert_not_called()

    async def test_neighbor_schema_does_not_truncate_or_coerce_invalid_numbers(self):
        for field, value in (
            ("hours", 168.9), ("path_hash_size", True), ("limit", 5000.9),
            ("hours", float("nan")), ("limit", float("inf")),
        ):
            with self.subTest(field=field, value=value):
                data = {"peer_hash": "AB", "path_hash_size": 1, field: value}
                with self.assertRaises(Invalid):
                    await self.action("get_neighbor_link_history", **data)
        self.request.assert_not_called()
        self.refresh.assert_not_called()

    async def test_noise_empty_positive_and_legacy_preserve_other_fields(self):
        for stats in ({"measurement_count": 0, "avg_noise_floor": 0, "min_noise_floor": 0},
                      {"measurement_count": 2, "avg_noise_floor": -112},
                      {"avg_noise_floor": -110}, {"avg_noise_floor": 0}):
            original = dict(stats)
            for wrapped in (False, True):
                payload = {"stats": stats, "hours": 24}
                self.request.return_value = {"success": True, "data": payload} if wrapped else payload
                expected = dict(stats)
                if stats.get("measurement_count") == 0:
                    expected["avg_noise_floor"] = None
                self.assertEqual(await self.action("get_noise_floor_stats"), expected)
                self.assertEqual(stats, original)

    async def test_backend_and_transport_errors_become_ha_errors_without_refresh(self):
        for name in ("get_radio_packet_rates", "get_noise_floor_stats", "get_crc_error_count",
                     "get_companion_stats", "get_lbt_diagnostics", "send_advert"):
            self.request.return_value = {"success": False, "error": "Example backend failure"}
            with self.assertRaisesRegex(RuntimeError, "Example backend failure"):
                await self.action(name)
            for error_name in ("PyMCRepeaterCannotConnect", "PyMCRepeaterAuthenticationError"):
                self.request.side_effect = self.ns[error_name]("Example failure")
                with self.assertRaisesRegex(RuntimeError, "Example failure"):
                    await self.action(name)
            self.request.side_effect = None
        self.refresh.assert_not_called()

    async def test_advert_budget_body_and_no_refresh(self):
        for mode in ("flood", "direct"):
            await self.action("send_advert", mode=mode)
            self.assertEqual(self.request.call_args.args, ("POST", "/api/send_advert"))
            self.assertEqual(self.request.call_args.kwargs["json_body"], {"mode": mode})
            self.assertEqual(self.request.call_args.kwargs["timeout_seconds"], 15)
        self.refresh.assert_not_called()

    async def test_real_http_transport_budget_auth_and_errors(self):
        del self.api._async_request_json
        self.api.host, self.api.port, self.api.api_token = "example.invalid", 8000, "example-token"
        self.ns["URL"] = SimpleNamespace(build=lambda **kw: "http://example.invalid:8000")
        self.ns["ClientError"] = type("ClientError", (Exception,), {})
        budgets, calls = [], []
        response = SimpleNamespace(status=200, payload={"success": True, "data": {"example": 1}})

        class Response:
            @property
            def status(self):
                return response.status

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def json(self, **kwargs):
                return response.payload

            async def text(self):
                return "Example HTTP error"

        def request(*args, **kwargs):
            calls.append((args, kwargs))
            return Response()

        def timeout(seconds):
            budgets.append(seconds)
            return asyncio.timeout(seconds)

        self.ns["asyncio"] = SimpleNamespace(timeout=timeout)
        self.api._session = SimpleNamespace(request=request)
        for name in ("get_radio_packet_rates", "get_noise_floor_stats", "get_crc_error_count",
                     "get_companion_stats", "get_lbt_diagnostics", "send_advert"):
            self.assertEqual(await self.action(name), None if name == "send_advert" else {"example": 1})
            self.assertEqual(budgets[-1], 15 if name == "send_advert" else 10)
            self.assertEqual(calls[-1][1]["headers"]["X-API-Key"], "example-token")
            for status in (401, 403, 500):
                response.status = status
                with self.assertRaises(RuntimeError):
                    await self.action(name)
            response.status = 200
        self.refresh.assert_not_called()

    async def test_polling_endpoint_set_unchanged_and_fatal_distinction(self):
        calls = []
        for name in dir(self.api):
            if name.startswith("async_get_"):
                async def empty(*args, _name=name, **kwargs):
                    calls.append((_name, kwargs))
                    return {}
                setattr(self.api, name, empty)
        result = await self.api.async_fetch_all()
        self.assertNotIn("radio_packet_rates", result)
        self.assertNotIn("companion_stats", result)
        self.assertTrue(all(not kwargs.get("radio_id") for _, kwargs in calls))
        for error_name in ("PyMCRepeaterApiError", "PyMCRepeaterCannotConnect", "PyMCRepeaterAuthenticationError"):
            self.api.async_get_noise_floor_stats = AsyncMock(side_effect=self.ns[error_name]("Example failure"))
            if error_name == "PyMCRepeaterApiError":
                self.assertEqual((await self.api.async_fetch_all())["noise_floor_stats"], {"error": "Example failure"})
            else:
                with self.assertRaises(self.ns[error_name]):
                    await self.api.async_fetch_all()
