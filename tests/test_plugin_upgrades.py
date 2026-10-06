"""Plugin actions execute extracted production bodies, not a live HA instance."""
import asyncio
import unittest
import test_dev_130_actions as boundary


class PluginUpgradeTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = boundary.ActionTests.asyncSetUp
    action = boundary.ActionTests.action

    def inventory(self, *ids):
        return {"success": True, "plugins": [
            {"id": ident, "version": "1.0", "source": "catalogue", "repository": "example/repo"}
            for ident in ids]}

    def check(self, ident, available=True):
        return {"success": True, "id": ident, "installedVersion": "1.0", "latestVersion": "2.0", "updateAvailable": available}

    async def test_update_all_continues_failure_and_verifies_enabled_reply_version(self):
        self.assertIn("update_all_plugins", self.registry)
        self.request.side_effect = [self.inventory("a", "b", "c"),
            self.check("a"), {"success": False, "error": "SECRET pip log"},
            self.check("b"), {"success": True, "plugin": {"id": "b", "version": "2.0", "enabled": True, "config": "SECRET"}},
            self.check("c", False)]
        result = await self.action("update_all_plugins")
        self.assertEqual([r["outcome"] for r in result["results"]], ["failure", "success", "skipped"])
        self.assertFalse(result["stopped"])
        self.assertEqual(result["counts"], dict(success=1, skipped=1, failure=1, unknown=0))
        self.assertNotIn("SECRET", str(result))
        posts = [call for call in self.request.call_args_list if call.args[0] == "POST"]
        self.assertEqual([c.kwargs["json_body"] for c in posts], [
            {"id": "a", "version": "2.0", "force_refresh": False},
            {"id": "b", "version": "2.0", "force_refresh": False}])
        self.assertTrue(all(c.kwargs["timeout_seconds"] == 930 for c in posts))
        self.assertFalse(self.api._plugin_upgrade_active)
        self.refresh.assert_not_called()

    async def test_timeout_stops_batch_without_retry_and_quarantines_client(self):
        self.assertIn("update_all_plugins", self.registry)
        self.request.side_effect = [self.inventory("a", "b"), self.check("a"),
            self.ns["PyMCRepeaterCannotConnect"]("SECRET timeout")]
        result = await self.action("update_all_plugins")
        self.assertEqual([r["outcome"] for r in result["results"]], ["unknown", "skipped"])
        self.assertTrue(result["stopped"])
        self.assertEqual(self.request.call_count, 3)
        self.assertNotIn("SECRET", str(result))
        self.assertFalse(self.api._plugin_upgrade_active)
        with self.assertRaisesRegex(RuntimeError, "uncertain"):
            await self.action("update_all_plugins")
        self.assertEqual(self.request.call_count, 3)

    async def test_malformed_version_metadata_is_not_returned_as_raw_text(self):
        inventory = self.inventory("a")
        inventory["plugins"][0]["version"] = "SECRET raw installation log\n"
        self.request.side_effect = [inventory, self.check("a", False)]
        result = await self.action("check_plugin_updates")
        self.assertIsNone(result["results"][0]["installed_version"])
        self.assertNotIn("SECRET", str(result))

    async def test_conflict_and_ipc_unknown_stop_sequential_upgrades(self):
        for error in ({"success": False, "http_status": 409, "error": "SECRET"},
                      {"success": False, "http_status": 504, "outcome": "unknown"}):
            self.api._plugin_upgrade_uncertain = False
            self.request.side_effect = [self.inventory("a", "b"), self.check("a"), error]
            result = await self.action("update_all_plugins")
            self.assertEqual([r["outcome"] for r in result["results"]], ["unknown", "skipped"])
            self.assertEqual(self.request.call_count % 3, 0)
            self.assertNotIn("SECRET", str(result))
            self.assertFalse(self.api._plugin_upgrade_active)

    async def test_successful_overlap_rejection_releases_admission_for_next_call(self):
        reached, release = asyncio.Event(), asyncio.Event()
        async def request(method, path, **kwargs):
            if path == "/api/plugins/":
                return self.inventory("a")
            if path == "/api/plugins/updates":
                return self.check("a")
            reached.set()
            await release.wait()
            return {"success": True, "plugin": {"id": "a", "version": "2.0", "updated": True}}
        self.request.side_effect = request
        task = asyncio.create_task(self.action("update_all_plugins"))
        await reached.wait()
        with self.assertRaisesRegex(RuntimeError, "in progress"):
            await self.action("update_plugin", plugin_id="a")
        release.set()
        self.assertEqual((await task)["counts"]["success"], 1)
        self.assertFalse(self.api._plugin_upgrade_active)
        self.assertFalse(getattr(self.api, "_plugin_upgrade_uncertain", False))
        self.request.side_effect = [self.inventory("a"), self.check("a", False)]
        self.assertEqual((await self.action("update_all_plugins"))["counts"]["skipped"], 1)

    async def test_wrapped_failures_are_sanitized_and_stop_ambiguous_batch(self):
        for payload in ({"success": True, "data": {"success": False, "error": "SECRET"}},
                        {"success": False, "outcome": "unknown", "error": "SECRET"}):
            self.api._plugin_upgrade_uncertain = False
            self.request.side_effect = [self.inventory("a", "b"), self.check("a"), payload]
            if payload.get("outcome") != "unknown":
                self.request.side_effect = [self.inventory("a", "b"), self.check("a"), payload,
                                            self.check("b", False)]
            result = await self.action("update_all_plugins")
            self.assertNotIn("SECRET", str(result))
            self.assertEqual(result["results"][0]["outcome"], "unknown" if payload.get("outcome") == "unknown" else "failure")

    async def test_missing_check_metadata_stops_before_writes(self):
        self.request.side_effect = [self.inventory("a", "b"), {"success": True, "id": "a"}]
        result = await self.action("update_all_plugins")
        self.assertEqual([r["outcome"] for r in result["results"]], ["unknown", "skipped"])
        self.assertEqual(self.request.call_count, 2)

    async def test_multiple_entry_selection_and_only_response_registration(self):
        for name in ("check_plugin_updates", "update_plugin", "update_all_plugins"):
            self.assertEqual(self.registry[name][1]["supports_response"], "only")
        self.hass.data["pymc_repeater"]["another"] = self.hass.data["pymc_repeater"]["example"]
        with self.assertRaisesRegex(RuntimeError, "Multiple"):
            await self.action("update_all_plugins")
        self.request.return_value = self.inventory()
        await self.action("update_all_plugins", config_entry_id="example")
        self.assertEqual(self.request.call_count, 1)

    async def test_plugin_http_budget_overrides_shared_session_and_redacts_errors(self):
        del self.api._async_request_json
        from types import SimpleNamespace
        self.api.host, self.api.port, self.api.api_token = "example.invalid", 8000, "example-token"
        self.ns["URL"] = SimpleNamespace(build=lambda **kw: "http://example.invalid:8000")
        self.ns["ClientError"] = type("ClientError", (Exception,), {})
        self.ns["ClientTimeout"] = lambda **kw: SimpleNamespace(**kw)
        status, payload, calls = 200, {"success": True, "plugins": []}, []

        class Response:
            @property
            def status(self):
                return status
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def json(self, **kwargs):
                return payload
            async def text(self):
                return "SECRET backend settings and logs"

        def request(*args, **kwargs):
            calls.append((args, kwargs))
            return Response()

        self.api._session = SimpleNamespace(request=request)
        self.assertEqual((await self.action("update_all_plugins"))["results"], [])
        self.assertEqual(calls[0][1]["timeout"].total, 930)
        self.assertEqual(calls[0][1]["headers"]["X-API-Key"], "example-token")
        for code in (400, 409, 500, 502, 504):
            status = code
            payload = {"success": False, "error": "SECRET", "outcome": "unknown" if code == 504 else "failure"}
            result = await self.api._async_plugin_payload("POST", "/api/plugins/update")
            self.assertNotIn("SECRET", str(result))
            self.assertEqual(result["outcome"], "unknown" if code in (409, 502, 504) else "failure")

    async def test_version_and_identity_inputs_are_bounded_before_http(self):
        from test_dev_130_actions import Invalid
        for field in ("plugin_id", "version"):
            for value in ("", " ", " a", "a ", "../a", "a/b", "a?b", "a\nb", "é", 12, True, "a" * 129):
                with self.subTest(field=field, value=value):
                    data = {"plugin_id": "a", field: value}
                    with self.assertRaises(Invalid):
                        await self.action("update_plugin", **data)
                    with self.assertRaises(self.error):
                        await self.api.async_update_plugin(**data)
        self.request.assert_not_called()

    async def test_no_updates_empty_local_unavailable_and_uninstalled(self):
        for plugins in ([], [{"id": "local", "version": "1.0", "source": "local", "repository": "example/repo"}],
                        [{"id": "missing", "version": "1.0", "source": "catalogue"}]):
            self.request.side_effect = None
            self.request.return_value = {"success": True, "plugins": plugins}
            result = await self.action("update_all_plugins")
            self.assertEqual(result["counts"]["success"], 0)
            self.assertEqual(result["counts"]["skipped"], len(plugins))
        self.request.return_value = self.inventory()
        result = await self.action("update_plugin", plugin_id="absent")
        self.assertEqual(result["results"][0]["reason"], "not_installed")
        self.assertTrue(all(c.args[0] == "GET" for c in self.request.call_args_list))

    async def test_overlap_rejected_cancellation_preserved_and_guard_cleaned(self):
        reached, release = asyncio.Event(), asyncio.Event()
        async def request(method, path, **kwargs):
            if path == "/api/plugins/":
                return self.inventory("a")
            if path == "/api/plugins/updates":
                return self.check("a")
            reached.set()
            await release.wait()
            return {"success": True, "plugin": {"id": "a", "version": "2.0"}}
        self.request.side_effect = request
        task = asyncio.create_task(self.action("update_plugin", plugin_id="a"))
        await reached.wait()
        with self.assertRaisesRegex(RuntimeError, "in progress"):
            await self.action("update_all_plugins")
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.api._plugin_upgrade_active)
        self.assertTrue(self.api._plugin_upgrade_uncertain)
        self.assertEqual(self.request.call_count, 3)

    async def test_explicit_version_and_updated_false(self):
        self.request.side_effect = [self.inventory("a"), self.check("a", False),
            {"success": True, "plugin": {"id": "a", "version": "1.0", "updated": False}}]
        result = await self.action("update_plugin", plugin_id="a", version="v2.0", force_refresh=True)
        self.assertEqual(result["results"][0]["outcome"], "skipped")
        self.assertEqual(self.request.call_args.kwargs["json_body"], {"id": "a", "version": "v2.0", "force_refresh": True})

    async def test_invalid_success_envelope_or_wrong_target_is_unknown(self):
        for reply in ({"success": True}, {"success": True, "plugin": {"id": "b", "version": "2.0"}},
                      {"success": True, "plugin": {"id": "a", "version": "1.0"}}):
            self.api._plugin_upgrade_uncertain = False
            self.request.side_effect = [self.inventory("a", "b"), self.check("a"), reply]
            result = await self.action("update_all_plugins")
            self.assertEqual([r["outcome"] for r in result["results"]], ["unknown", "skipped"])
            self.assertTrue(result["stopped"])

    async def test_inventory_error_or_bounds_cleanup_without_write(self):
        for payload in ({"success": False, "error": "SECRET"}, {"plugins": "bad"},
                        self.inventory("a", "a"), self.inventory(*(f"p{i}" for i in range(101)))):
            self.request.return_value = payload
            with self.assertRaises(RuntimeError):
                await self.action("update_all_plugins")
            self.assertFalse(self.api._plugin_upgrade_active)
        self.assertTrue(all(c.args[0] == "GET" for c in self.request.call_args_list))

    async def test_check_eligible_and_local_inventory_is_minimized(self):
        self.assertIn("check_plugin_updates", self.registry)
        self.request.side_effect = [
            {"success": True, "plugins": [
                {"id": "openhop.example", "version": "1.0", "source": "catalogue", "repository": "example/repo", "config": {"token": "SECRET"}},
                {"id": "local.example", "version": "1.0", "source": "local"}]},
            {"success": True, "id": "openhop.example", "installedVersion": "1.0", "latestVersion": "2.0", "updateAvailable": True, "releaseNotes": "SECRET"},
        ]
        result = await self.action("check_plugin_updates")
        self.assertEqual([r["outcome"] for r in result["results"]], ["success", "skipped"])
        self.assertTrue(result["results"][0]["update_available"])
        self.assertNotIn("SECRET", str(result))
        self.assertEqual(self.request.call_args.args, ("GET", "/api/plugins/updates"))
        self.assertEqual(self.request.call_args.kwargs["params"], {"id": "openhop.example", "refresh": "false"})
        self.refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
