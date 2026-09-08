"""Ensure automatic polling reads update state without initiating checks."""
import ast
import unittest

from test_installed_api_behavior import COMPONENT, client_namespace


class UpdatePollingTests(unittest.IsolatedAsyncioTestCase):
    async def test_polling_never_discovers_branches_or_forces_update_checks(self):
        ns = client_namespace()
        client = object.__new__(ns["PyMCRepeaterApiClient"])
        calls = []

        async def record(name):
            calls.append(name)
            return {}

        for name in dir(client):
            if name.startswith("async_get_") or name == "async_update_check":
                async def request(*args, _name=name, **kwargs):
                    return await record(_name)
                setattr(client, name, request)
        for _ in range(3):
            await client.async_fetch_all()
        self.assertNotIn("async_get_update_channels", calls)
        self.assertNotIn("async_update_check", calls)
        self.assertEqual(calls.count("async_get_update_status"), 3)
        self.assertEqual(calls.count("async_get_stats"), 3)

    async def test_explicit_update_check_sends_force(self):
        ns = client_namespace()
        client = object.__new__(ns["PyMCRepeaterApiClient"])
        calls = []

        async def request(*args, **kwargs):
            calls.append((args, kwargs))
            return {}

        client._async_request_wrapped = request
        await client.async_update_check(force=True)
        self.assertEqual(calls, [(("POST", "/api/update/check"), {"json_body": {"force": True}})])

    def test_check_button_keeps_explicit_force_action(self):
        tree = ast.parse((COMPONENT / "button.py").read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fields = {kw.arg: kw.value for kw in node.keywords}
            key = fields.get("key")
            if isinstance(key, ast.Constant) and key.value == "update_check":
                self.assertIn("async_update_check(force=True)", ast.unparse(fields["press_fn"]))
                return
        self.fail("Check for updates button missing")
