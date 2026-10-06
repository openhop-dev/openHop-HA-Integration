"""Execute checked-in management actions with fake HTTP/HA boundaries only."""
import asyncio
import json
import unittest
import test_dev_130_actions as boundary


class ManagementTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = boundary.ActionTests.asyncSetUp
    action = boundary.ActionTests.action

    async def test_lifecycle_paths_metadata_and_preserved_uninstall_default(self):
        self.assertIn("enable_plugin", self.registry)
        for operation in ("enable", "disable", "start", "stop", "restart", "uninstall"):
            reply = {"id": "openhop.example", "version": "1.0", "enabled": True,
                     "state": "RUNNING", "uninstalled": True, "data_deleted": False,
                     "config": {"token": "SECRET"}, "logs": "SECRET"}
            if operation == "disable":
                reply["enabled"] = False
            if operation in ("disable", "stop"):
                reply["state"] = "STOPPED"
            self.request.return_value = {"success": True, "plugin": reply} if operation != "uninstall" else {"success": True, **reply}
            result = await self.action(operation + "_plugin", plugin_id="openhop.example")
            self.assertEqual(result["outcome"], "success")
            self.assertNotIn("SECRET", str(result))
            self.assertEqual(self.request.call_args.args, ("POST", "/api/plugins/" + operation))
            expected = {"id": "openhop.example"}
            if operation == "uninstall":
                expected["delete_data"] = False
            self.assertEqual(self.request.call_args.kwargs["json_body"], expected)
            self.assertEqual(self.request.call_args.kwargs["timeout_seconds"], 930)
        self.refresh.assert_not_called()

    async def test_catalogue_list_and_install_are_explicit_bounded_actions(self):
        self.assertIn("get_plugin_catalogue", self.registry)
        self.request.return_value = {"success": True, "schema": 2, "plugins": [
            {"id": "openhop.example", "name": "Example", "description": "Example service",
             "latestVersion": "2.0", "installed": False, "updateAvailable": False,
             "repository": "SECRET", "releasesError": "SECRET", "settings": {"token": "SECRET"}}]}
        result = await self.action("get_plugin_catalogue", force_refresh=True)
        self.assertEqual(result["plugins"][0]["id"], "openhop.example")
        self.assertNotIn("SECRET", str(result))
        self.assertEqual(self.request.call_args.kwargs["params"], {"refresh": "true"})
        self.request.return_value = {"success": True, "plugin": {"id": "openhop.example", "version": "2.0"}}
        self.assertEqual((await self.action("install_catalogue_plugin", plugin_id="openhop.example", version="2.0"))["outcome"], "success")
        self.assertEqual(self.request.call_args.args, ("POST", "/api/plugins/catalogue_install"))
        self.assertEqual(self.request.call_args.kwargs["json_body"], {"id": "openhop.example", "version": "2.0", "force_refresh": False})
        self.refresh.assert_not_called()

    async def test_settings_json_and_sensitive_read_are_not_normal_metadata(self):
        self.assertIn("get_plugin_settings", self.registry)
        self.ns["json"] = json
        self.request.return_value = {"success": True, "id": "openhop.example", "path": "SECRET path",
                                     "config": {"nested": {"api_token": "SECRET"}, "port": 8090}}
        result = await self.action("get_plugin_settings", plugin_id="openhop.example")
        self.assertEqual(result["config"]["nested"]["api_token"], "[REDACTED]")
        self.assertNotIn("SECRET", str(result))
        result = await self.action("get_plugin_settings", plugin_id="openhop.example", include_sensitive=True)
        self.assertEqual(result["config"]["nested"]["api_token"], "SECRET")
        self.assertNotIn("path", result)
        self.request.return_value = {"success": True, "id": "openhop.example", "config": {"token": "SECRET"}, "restarted": True}
        result = await self.action("update_plugin_settings", plugin_id="openhop.example", config={"token": "new"}, restart=True)
        self.assertNotIn("SECRET", str(result))
        self.assertTrue(result["restarted"])
        self.assertEqual(self.request.call_args.kwargs["json_body"], {"id": "openhop.example", "config": {"token": "new"}, "restart": True})
        self.request.reset_mock()
        for value in ([], "{}", {1: "x"}, {"x": float("nan")}, {"x": object()}, {"x": "[REDACTED]"}, {"x": "a" * (256 * 1024)}):
            with self.subTest(value=type(value)):
                with self.assertRaises(boundary.Invalid):
                    await self.action("update_plugin_settings", plugin_id="openhop.example", config=value)
                with self.assertRaises(self.error):
                    await self.api.async_update_plugin_settings(plugin_id="openhop.example", config=value)
        self.request.assert_not_called()
        self.refresh.assert_not_called()

    async def test_sensor_full_replacement_preserves_masks_and_origins(self):
        self.assertIn("get_sensor_configuration", self.registry)
        config = {"enabled": True, "poll_interval_seconds": 30.0, "auto_install_packages": False,
                  "definitions": [{"name": "Modem", "type": "openhop_modem", "_original_name": "Old modem",
                                   "settings": {"password": "*****", "host": "example.invalid"}}]}
        self.request.return_value = {"success": True, "data": config}
        self.assertEqual(await self.action("get_sensor_configuration"), config)
        self.assertEqual(self.request.call_args.args, ("GET", "/api/sensors_config"))
        self.request.return_value = {"success": True, "data": {"saved": True, "restart_required": True, "message": "SECRET"}}
        result = await self.action("update_sensor_configuration", config=config)
        self.assertEqual(result, {"saved": True, "restart_required": True})
        self.assertEqual(self.request.call_args.args, ("POST", "/api/sensors_config_update"))
        self.assertEqual(self.request.call_args.kwargs["json_body"], config)
        self.assertEqual(config["definitions"][0]["settings"]["password"], "*****")
        self.request.return_value = {"success": True, "data": {"types": [{"type": "bme280", "settings": []}]}}
        self.assertEqual((await self.action("get_sensor_types"))["types"][0]["type"], "bme280")
        self.request.reset_mock()
        for malformed in ({}, {**config, "definitions": "bad"}, {**config, "poll_interval_seconds": float("inf")},
                          {**config, "definitions": config["definitions"] * 2}):
            with self.assertRaises(boundary.Invalid):
                await self.action("update_sensor_configuration", config=malformed)
            with self.assertRaises(self.error):
                await self.api.async_update_sensor_configuration(config=malformed)
        self.request.assert_not_called()
        self.refresh.assert_not_called()

    async def test_acl_permissions_bounds_role_bytes_and_legacy_named_removal(self):
        self.assertIn("set_acl_permissions", self.registry)
        key = "AB" * 32
        self.request.return_value = {"success": True, "data": {"permissions_value": 255, "persisted": False}}
        result = await self.action("set_acl_permissions", identity_name="Example room", client_pubkey=key, permissions=255)
        self.assertFalse(result["persisted"])
        self.assertEqual(self.request.call_args.args, ("POST", "/api/acl_set_permissions"))
        self.assertEqual(self.request.call_args.kwargs["json_body"], {"identity_name": "Example room", "client_pubkey": key, "permissions": 255})
        self.assertEqual(self.refresh.call_count, 1)
        for permission in (1, 2, 3, 5, 254, 255):
            await self.action("set_acl_permissions", identity_name="repeater", client_pubkey=key, permissions=permission)
        await self.action("remove_acl_client", public_key=key, identity_name="Example room", identity_hash="0x42")
        self.assertEqual(self.request.call_args.kwargs["json_body"], {"public_key": key, "identity_name": "Example room", "identity_hash": "0x42"})
        self.request.reset_mock()
        for permission in (0, 4, 252, 256, -1, True, 1.5, "3"):
            with self.assertRaises(boundary.Invalid):
                await self.action("set_acl_permissions", identity_name="repeater", client_pubkey=key, permissions=permission)
            with self.assertRaises(self.error):
                await self.api.async_set_acl_permissions(identity_name="repeater", client_pubkey=key, permissions=permission)
        for invalid in ("A" * 63, "G" * 64, " " + key, "A B" * 32, True):
            with self.assertRaises(boundary.Invalid):
                await self.action("set_acl_permissions", identity_name="repeater", client_pubkey=invalid, permissions=3)
        self.request.assert_not_called()

    async def test_plugin_write_guard_unknown_and_cancellation_cover_lifecycle(self):
        self.request.return_value = {"success": True, "plugin": {"id": "a"}}
        result = await self.action("enable_plugin", plugin_id="a")
        self.assertEqual(result["outcome"], "unknown")
        with self.assertRaisesRegex(RuntimeError, "uncertain"):
            await self.action("uninstall_plugin", plugin_id="a")
        self.assertEqual(self.request.call_count, 1)
        self.api._plugin_upgrade_uncertain = False
        reached = asyncio.Event()
        async def pending(*args, **kwargs):
            reached.set()
            await asyncio.Event().wait()
        self.request.side_effect = pending
        task = asyncio.create_task(self.action("restart_plugin", plugin_id="a"))
        await reached.wait()
        for name, data in [("update_all_plugins", {}), ("install_catalogue_plugin", {"plugin_id": "b"}),
                           ("update_plugin_settings", {"plugin_id": "b", "config": {}})]:
            with self.assertRaisesRegex(RuntimeError, "in progress"):
                await self.action(name, **data)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.api._plugin_upgrade_active)
        self.assertTrue(self.api._plugin_upgrade_uncertain)
        self.refresh.assert_not_called()

    async def test_bounded_management_http_overrides_session_without_reading_logs(self):
        del self.api._async_request_json
        from types import SimpleNamespace
        self.api.host, self.api.port, self.api.api_token = "example.invalid", 8000, "example-token"
        self.ns["URL"] = SimpleNamespace(build=lambda **kw: "http://example.invalid:8000")
        self.ns["ClientError"] = type("ClientError", (Exception,), {})
        self.ns["ClientTimeout"] = lambda **kw: SimpleNamespace(**kw)
        self.ns["json"] = json
        calls = []
        class Content:
            def __init__(self, body):
                self.body, self.read_bytes = body, 0
            async def read(self, maximum):
                chunk, self.body = self.body[:maximum], self.body[maximum:]
                self.read_bytes += len(chunk)
                return chunk
        class Response:
            status = 200
            def __init__(self, body):
                self.content = Content(body)
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                self.closed = True
            async def json(self, **kwargs):
                return json.loads(self.content.body)
        reply = Response(json.dumps({"success": True, "data": {"types": []}}).encode())
        def request(*args, **kwargs):
            calls.append(kwargs)
            return reply
        self.api._session = SimpleNamespace(request=request)
        await self.action("get_sensor_types")
        self.assertEqual(calls[-1]["timeout"].total, 30)
        self.assertGreater(reply.content.read_bytes, 0)
        reply = Response(b"x" * (1024 * 1024 + 100))
        with self.assertRaisesRegex(RuntimeError, "Management"):
            await self.action("get_sensor_types")
        self.assertLessEqual(reply.content.read_bytes, 1024 * 1024 + 1)
        self.assertTrue(reply.closed)
        reply = Response(b"[" * 2000 + b"0" + b"]" * 2000)
        with self.assertRaisesRegex(RuntimeError, "Management"):
            await self.action("get_sensor_types")
        self.assertTrue(reply.closed)
        reply = Response(json.dumps({"success": True, "plugin": {"id": "a", "enabled": True, "state": "RUNNING"}}).encode())
        result = await self.action("enable_plugin", plugin_id="a")
        self.assertEqual(result["outcome"], "success")
        self.assertEqual(calls[-1]["timeout"].total, 930)
        for status in (409, 502, 504):
            self.api._plugin_upgrade_uncertain = False
            reply = Response(json.dumps({"success": False, "error": "SECRET settings and logs"}).encode())
            reply.status = status
            result = await self.action("restart_plugin", plugin_id="a")
            self.assertEqual(result["outcome"], "unknown")
            self.assertNotIn("SECRET", str(result))
            self.assertTrue(reply.closed)
            self.assertTrue(self.api._plugin_upgrade_uncertain)
        self.api._plugin_upgrade_uncertain = False
        reply = Response(b'{"success":true,"plugin":{"id":"a","state":"RUNNING"},"extra":'
                         + b"[" * 100000 + b"0" + b"]" * 100000 + b"}")
        self.assertLess(len(reply.content.body), 1024 * 1024)
        count_before = len(calls)
        # Decoder nesting limits vary by Python build and thread stack size.
        # Inject the decoder exception to verify transport/quarantine behavior
        # independently of whether this runtime accepts the nested envelope.
        from unittest.mock import patch
        with patch("json.loads", side_effect=RecursionError("decoder nesting limit")):
            result = await self.action("start_plugin", plugin_id="a")
        self.assertEqual(result["outcome"], "unknown")
        self.assertTrue(self.api._plugin_upgrade_uncertain)
        self.assertFalse(self.api._plugin_upgrade_active)
        self.assertTrue(reply.closed)
        with self.assertRaisesRegex(RuntimeError, "uncertain"):
            await self.action("restart_plugin", plugin_id="a")
        self.assertEqual(len(calls), count_before + 1)
        self.refresh.assert_not_called()

    async def test_registered_handlers_are_native_async_functions(self):
        import inspect
        for name, (handler, _) in self.registry.items():
            with self.subTest(action=name):
                self.assertTrue(inspect.iscoroutinefunction(handler))

    async def test_new_actions_select_entries_and_optional_acl_response(self):
        self.assertEqual(self.registry["set_acl_permissions"][1]["supports_response"], "optional")
        only = ("get_plugin_catalogue", "install_catalogue_plugin", "get_plugin_settings", "update_plugin_settings",
                "enable_plugin", "disable_plugin", "start_plugin", "stop_plugin", "restart_plugin", "uninstall_plugin",
                "get_sensor_types", "get_sensor_configuration", "update_sensor_configuration")
        for name in only:
            self.assertEqual(self.registry[name][1]["supports_response"], "only")
        self.hass.data["pymc_repeater"]["another"] = self.hass.data["pymc_repeater"]["example"]
        with self.assertRaisesRegex(RuntimeError, "Multiple"):
            await self.action("get_sensor_types")
        self.request.return_value = {"success": True, "data": {"types": []}}
        await self.action("get_sensor_types", config_entry_id="example")
        with self.assertRaisesRegex(RuntimeError, "Unknown"):
            await self.action("get_sensor_types", config_entry_id="absent")
        self.request.return_value = {"success": True, "data": {"permissions_value": 3, "persisted": True}}
        handler, metadata = self.registry["set_acl_permissions"]
        from types import SimpleNamespace
        self.assertIsNone(await handler(SimpleNamespace(return_response=False, data=metadata["schema"]({
            "config_entry_id": "example", "identity_name": "repeater", "client_pubkey": "AA" * 32, "permissions": 3}))))
        self.assertEqual(self.refresh.call_count, 1)

    async def test_plugin_known_failure_unknown_timeout_and_malformed_success_no_retry(self):
        for payload in ({"success": False, "error": "SECRET"},
                        {"success": False, "http_status": 409, "error": "SECRET"},
                        {"success": False, "http_status": 504, "outcome": "unknown"},
                        {"success": True, "plugin": {"id": "wrong", "enabled": True}},
                        {"success": True, "plugin": {"id": "a", "state": []}}):
            self.api._plugin_upgrade_uncertain = False
            self.request.return_value = payload
            self.request.reset_mock()
            result = await self.action("start_plugin", plugin_id="a")
            self.assertNotIn("SECRET", str(result))
            self.assertEqual(result["outcome"], "failure" if payload.get("error") == "SECRET" and "http_status" not in payload else "unknown")
            self.assertFalse(self.api._plugin_upgrade_active)
            self.assertEqual(self.request.call_count, 1)
        self.api._plugin_upgrade_uncertain = False
        self.request.side_effect = self.ns["PyMCRepeaterCannotConnect"]("SECRET timeout")
        self.assertEqual((await self.action("enable_plugin", plugin_id="a"))["outcome"], "unknown")
        self.assertTrue(self.api._plugin_upgrade_uncertain)
        self.refresh.assert_not_called()

    async def test_sensitive_management_errors_are_fixed_and_no_refresh(self):
        for reply in ({"success": False, "error": "SECRET"},
                      {"success": True, "data": {"success": False, "error": "SECRET"}},
                      {"success": True, "data": []}):
            self.request.return_value = reply
            for name, data in (("get_sensor_types", {}), ("get_plugin_settings", {"plugin_id": "a"}),
                               ("set_acl_permissions", {"identity_name": "repeater", "client_pubkey": "AA" * 32, "permissions": 3})):
                with self.assertRaises(RuntimeError) as ctx:
                    await self.action(name, **data)
                self.assertNotIn("SECRET", str(ctx.exception))
        self.refresh.assert_not_called()

    async def test_sensor_credentials_redaction_preserves_backend_mask_not_secret(self):
        config = {"enabled": True, "poll_interval_seconds": 30, "auto_install_packages": False,
                  "definitions": [{"name": "Example", "type": "openhop_modem", "_original_name": "Old example",
                                   "settings": {"password": "*****", "token": "SECRET"}}]}
        for wrapped in (True, False):
            self.request.return_value = {"success": True, "data": config} if wrapped else config
            result = await self.action("get_sensor_configuration")
            self.assertEqual(result["definitions"][0]["settings"]["password"], "*****")
            self.assertEqual(result["definitions"][0]["_original_name"], "Old example")
            self.assertNotIn("SECRET", str(result))
            with self.assertRaises(boundary.Invalid):
                await self.action("update_sensor_configuration", config=result)
            sensitive = await self.action("get_sensor_configuration", include_sensitive=True)
            self.assertEqual(sensitive["definitions"][0]["settings"]["token"], "SECRET")
        self.refresh.assert_not_called()

    async def test_input_bounds_and_delete_data_true_survive_exact_payload(self):
        self.request.return_value = {"success": True, "id": "a", "uninstalled": True, "data_deleted": True}
        self.assertTrue((await self.action("uninstall_plugin", plugin_id="a", delete_data=True))["data_deleted"])
        self.assertTrue(self.request.call_args.kwargs["json_body"]["delete_data"])
        self.request.reset_mock()
        for name in ("enable_plugin", "install_catalogue_plugin", "get_plugin_settings", "update_plugin_settings"):
            for plugin_id in ("../a", "a/b", "a?b", "a ", "", "a" * 129):
                data = {"plugin_id": plugin_id}
                if name == "update_plugin_settings":
                    data["config"] = {}
                with self.assertRaises(boundary.Invalid):
                    await self.action(name, **data)
        deep = {}; cursor = deep
        for _ in range(34):
            cursor["child"] = {}; cursor = cursor["child"]
        for config in (deep, {"items": [0] * 10001}, {"value": float("inf")}):
            with self.assertRaises(self.error):
                await self.api.async_update_plugin_settings(plugin_id="a", config=config)
        self.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
