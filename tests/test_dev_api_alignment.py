"""Contract tests for openHop Repeater dev API alignment.

These tests intentionally use the Python AST so they can run without installing
Home Assistant while still pinning the integration's public API/service contract.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "pymc_repeater"


def _module(name: str) -> ast.Module:
    return ast.parse((COMPONENT / name).read_text(encoding="utf-8"))


def _class_method(module: ast.Module, class_name: str, method_name: str) -> ast.AsyncFunctionDef:
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.AsyncFunctionDef) and child.name == method_name:
                    return child
    raise AssertionError(f"Missing {class_name}.{method_name}")


def _async_function(module: ast.Module, name: str) -> ast.AsyncFunctionDef:
    for node in module.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Missing async function {name}")


class DevApiAlignmentTests(unittest.TestCase):
    def test_neighbor_link_client_methods_and_polling_exist(self) -> None:
        module = _module("api.py")
        client = next(
            node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "PyMCRepeaterApiClient"
        )
        source = ast.unparse(client)

        self.assertIn("async_get_neighbor_links", source)
        self.assertIn("/api/neighbor_links", source)
        self.assertIn("active_within_seconds", source)
        self.assertIn("async_get_neighbor_link_history", source)
        self.assertIn("/api/neighbor_link_history", source)
        self.assertIn("'neighbor_links': self.async_get_neighbor_links()", source)

    def test_neighbor_scope_and_direct_advert_contracts_exist(self) -> None:
        module = _module("api.py")
        client = next(
            node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "PyMCRepeaterApiClient"
        )
        source = ast.unparse(client)

        for expected in (
            "async_get_neighbor_scopes",
            "'/api/neighbor_scopes'",
            "async_query_neighbor_scopes",
            "'/api/query_neighbor_scopes'",
            "async_publish_neighbors",
            "'/api/publish_neighbors'",
            "NEIGHBOR_SCOPE_QUERY_TIMEOUT",
            "{'mode': mode}",
        ):
            self.assertIn(expected, source)

        buttons = (COMPONENT / "button.py").read_text(encoding="utf-8")
        numbers = (COMPONENT / "number.py").read_text(encoding="utf-8")
        sensor = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
        self.assertIn('key="send_direct_advert"', buttons)
        self.assertIn('key="publish_neighbors"', buttons)
        self.assertIn('key="flood_advert_interval_hours"', numbers)
        self.assertIn('key="direct_advert_interval_hours"', numbers)
        self.assertIn('key="mqtt_neighbors_phase"', sensor)

    def test_cad_client_contract_includes_new_dev_fields(self) -> None:
        module = _module("api.py")
        start = ast.unparse(
            _class_method(module, "PyMCRepeaterApiClient", "async_cad_calibration_start")
        )
        manual = ast.unparse(
            _class_method(module, "PyMCRepeaterApiClient", "async_cad_manual_check")
        )
        save = ast.unparse(
            _class_method(module, "PyMCRepeaterApiClient", "async_save_cad_settings")
        )

        for field in ("known_signal_present", "cad_symbol_num", "cad_timeout_ms"):
            self.assertIn(field, start)
        for field in (
            "samples",
            "det_peak",
            "det_min",
            "cad_symbol_num",
            "cad_timeout_ms",
            "apply_live",
        ):
            self.assertIn(field, manual)
        self.assertIn("/api/cad_manual_check", manual)
        self.assertIn("cad_symbol_num", save)

    def test_home_assistant_services_cover_new_routes_and_bounds(self) -> None:
        module = _module("__init__.py")
        setup = ast.unparse(_async_function(module, "_async_register_services"))

        for service in (
            "SERVICE_CAD_MANUAL_CHECK",
            "SERVICE_GET_NEIGHBOR_LINKS",
            "SERVICE_GET_NEIGHBOR_LINK_HISTORY",
            "SERVICE_SEND_ADVERT",
            "SERVICE_PUBLISH_NEIGHBORS",
            "SERVICE_GET_NEIGHBOR_SCOPES",
            "SERVICE_QUERY_NEIGHBOR_SCOPES",
        ):
            self.assertIn(service, setup)
        self.assertIn("vol.In([1, 2, 4, 8, 16])", setup)
        self.assertIn("vol.Range(min=50, max=5000)", setup)
        self.assertIn("vol.Range(min=1, max=3)", setup)
        self.assertIn("vol.Range(min=1, max=168)", setup)
        self.assertIn("vol.Range(min=1, max=5000)", setup)

    def test_new_diagnostics_are_exposed_as_sensors(self) -> None:
        source = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
        self.assertIn('key="neighbor_link_count"', source)
        self.assertIn('key="active_neighbor_link_count"', source)
        self.assertIn('key="metrics_data_source"', source)
        self.assertIn('key="radio_stack_mode"', source)
        self.assertIn('key="configured_radio_count"', source)

    def test_current_external_sensor_payloads_have_units(self) -> None:
        source = (COMPONENT / "sensor.py").read_text(encoding="utf-8")

        for field, unit in (
            ("battery_voltage_v", "V"),
            ("bus_voltage_v", "V"),
            ("current_ma", "mA"),
            ("power_mw", "mW"),
            ("pressure_hpa", "hPa"),
            ("die_temperature_c", "°C"),
            ("last_rssi_dbm", "dBm"),
            ("last_snr_db", "dB"),
            ("noise_floor_dbm", "dBm"),
            ("frequency_hz", "Hz"),
            ("bandwidth_hz", "Hz"),
            ("tx_power_dbm", "dBm"),
            ("solar_charge_rate_percent_per_hour", "%/h"),
        ):
            self.assertIn(f'"{field}": "{unit}"', source)
        self.assertIn('if sensor_type == "openhop_modem"', source)
        self.assertIn('sensor_type = "pymc_modem"', source)

    def test_external_sensor_battery_percentage_alias_is_additive(self) -> None:
        module = _module("sensor.py")
        helpers = [
            node
            for node in module.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_external_sensor_payload"
        ]
        self.assertTrue(helpers, "Missing external sensor payload normalizer")
        namespace: dict[str, Any] = {"Any": Any}
        exec(
            compile(ast.Module(body=[helpers[0]], type_ignores=[]), "<sensor-payload>", "exec"),
            namespace,
        )
        normalize = namespace["_external_sensor_payload"]

        payload = normalize({"data": {"battery_percentage": "74"}})
        self.assertEqual(payload["battery_percentage"], "74")
        self.assertEqual(payload["battery_percent"], "74")
        canonical = normalize(
            {"data": {"battery_percentage": 74, "battery_percent": 73}}
        )
        self.assertEqual(canonical["battery_percent"], 73)

    def test_external_sensor_measurements_normalize_numeric_strings(self) -> None:
        module = _module("sensor.py")
        source = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
        helpers = [
            node
            for node in module.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_normalize_external_sensor_value"
        ]
        self.assertTrue(helpers, "Missing external sensor value normalizer")
        helper = helpers[0]
        namespace: dict[str, Any] = {"Any": Any}
        exec(
            compile(ast.Module(body=[helper], type_ignores=[]), "<sensor-value>", "exec"),
            namespace,
        )
        normalize = namespace["_normalize_external_sensor_value"]

        self.assertEqual(normalize("12.5", has_unit=True), 12.5)
        self.assertEqual(normalize(0, has_unit=True), 0)
        self.assertIsNone(normalize("not-a-number", has_unit=True))
        self.assertEqual(normalize("active", has_unit=False), "active")
        self.assertIn("_normalize_external_sensor_value", source)
        self.assertIn("has_unit=self._attr_native_unit_of_measurement is not None", source)

    def test_flood_advert_number_enforces_repeater_bounds(self) -> None:
        source = (COMPONENT / "number.py").read_text(encoding="utf-8")

        self.assertIn("async def _async_set_flood_advert_interval", source)
        self.assertIn("hours != 0 and not 3 <= hours <= 168", source)
        self.assertIn("Flood advert interval must be 0 (off) or 3-168 hours", source)
        self.assertIn("set_fn=_async_set_flood_advert_interval", source)

    def test_identity_polling_drops_private_configuration(self) -> None:
        module = _module("api.py")
        method = ast.unparse(
            _class_method(module, "PyMCRepeaterApiClient", "async_get_identities")
        )
        source = (COMPONENT / "api.py").read_text(encoding="utf-8")

        self.assertIn("_drop_sensitive_fields", method)
        for key in (
            "identity_key",
            "private_key",
            "admin_password",
            "guest_password",
            "password",
            "token",
            "transport_key",
            "jwt_secret",
        ):
            self.assertIn(f'"{key}"', source)

        helper = next(
            node
            for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name == "_drop_sensitive_fields"
        )
        namespace: dict[str, Any] = {
            "Any": Any,
            "SENSITIVE_RESPONSE_KEYS": {
                "identity_key",
                "private_key",
                "admin_password",
                "guest_password",
                "password",
                "token",
                "transport_key",
                "jwt_secret",
            },
        }
        exec(
            compile(ast.Module(body=[helper], type_ignores=[]), "<sanitizer>", "exec"),
            namespace,
        )
        sanitized = namespace["_drop_sensitive_fields"](
            {
                "configured": [
                    {
                        "name": "Example",
                        "identity_key": "secret",
                        "settings": {"admin_password": "secret", "port": 5000},
                    }
                ]
            }
        )
        self.assertEqual(
            sanitized,
            {"configured": [{"name": "Example", "settings": {"port": 5000}}]},
        )

    def test_transport_key_polling_drops_key_material(self) -> None:
        module = _module("api.py")
        method = ast.unparse(
            _class_method(module, "PyMCRepeaterApiClient", "async_get_transport_keys")
        )

        self.assertIn("transport_key", method)
        self.assertIn("safe_item.pop", method)
        self.assertNotIn(
            'return await self._async_request_wrapped("GET", "/api/transport_keys")',
            method,
        )

    def test_diagnostics_redact_runtime_installation_data(self) -> None:
        source = (COMPONENT / "diagnostics.py").read_text(encoding="utf-8")

        self.assertIn('"data": async_redact_data(coordinator.data, TO_REDACT)', source)
        for key in (
            "token",
            "password",
            "jwt_secret",
            "identity_key",
            "private_key",
            "transport_key",
            "latitude",
            "longitude",
            "network_current_ip",
            "public_key",
            "pubkey",
        ):
            self.assertIn(f'"{key}"', source)

    def test_new_entities_have_translation_keys(self) -> None:
        translations = json.loads(
            (COMPONENT / "translations" / "en.json").read_text(encoding="utf-8")
        )["entity"]
        expected = {
            "button": ("send_direct_advert", "publish_neighbors"),
            "number": (
                "flood_advert_interval_hours",
                "direct_advert_interval_hours",
            ),
            "sensor": (
                "mqtt_neighbors_phase",
                "radio_stack_mode",
                "configured_radio_count",
            ),
        }

        for platform, keys in expected.items():
            source = (COMPONENT / f"{platform}.py").read_text(encoding="utf-8")
            for key in keys:
                self.assertIn(key, translations.get(platform, {}))
                self.assertIn(f'translation_key="{key}"', source)
        number_source = (COMPONENT / "number.py").read_text(encoding="utf-8")
        self.assertIn("self._attr_translation_key = description.translation_key", number_source)

    def test_service_descriptions_include_new_actions(self) -> None:
        source = (COMPONENT / "services.yaml").read_text(encoding="utf-8")
        self.assertIn("cad_manual_check:", source)
        self.assertIn("get_neighbor_links:", source)
        self.assertIn("get_neighbor_link_history:", source)
        self.assertIn("send_advert:", source)
        self.assertIn("publish_neighbors:", source)
        self.assertIn("get_neighbor_scopes:", source)
        self.assertIn("query_neighbor_scopes:", source)
        self.assertIn("cad_symbol_num:", source)
        self.assertIn("known_signal_present:", source)

    def test_integration_polling_is_configurable_and_defaults_to_15_seconds(self) -> None:
        constants = (COMPONENT / "const.py").read_text(encoding="utf-8")
        coordinator = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
        config_flow = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")

        self.assertIn("CONF_SCAN_INTERVAL", constants)
        self.assertIn("DEFAULT_SCAN_INTERVAL_SECONDS = 15", constants)
        self.assertIn("CONF_SCAN_INTERVAL", coordinator)
        self.assertIn("update_interval=timedelta(seconds=configured_scan_interval)", coordinator)
        self.assertNotIn("_sensor_poll_task", coordinator)
        self.assertNotIn("_async_sensor_poll_loop", coordinator)
        self.assertIn("CONF_SCAN_INTERVAL", config_flow)
        self.assertIn("MIN_SCAN_INTERVAL_SECONDS", config_flow)
        self.assertIn("MAX_SCAN_INTERVAL_SECONDS", config_flow)
        self.assertIn("async_update_listeners()", coordinator)
        self.assertNotIn("async_set_updated_data", coordinator)

    def test_release_metadata_and_changelog_are_v1_1_6(self) -> None:
        manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/python-smoke.yaml").read_text(
            encoding="utf-8"
        )

        self.assertEqual(manifest["version"], "1.1.6")
        self.assertIn("## 1.1.6", changelog)
        self.assertIn("## Unreleased", changelog)
        for expected in (
            "15 seconds",
            "GPS stream",
            "neighbor-link snapshots and history",
            "manual CAD check",
            "metrics storage source",
            "contract tests",
            "actions/setup-python@v7",
        ):
            self.assertIn(expected, changelog)
        self.assertIn("actions/setup-python@v7", workflow)

    def test_dashboard_percentage_cards_use_percentage_states_and_dynamic_modem_lookup(self) -> None:
        dashboard = (ROOT / "dashboards/openhop_repeater_dashboard.yaml").read_text(
            encoding="utf-8"
        )
        gauge_stack = dashboard.split("  - type: horizontal-stack", 1)[1].split(
            "  - type: history-graph", 1
        )[0]

        self.assertIn("sensor.REPEATER_SLUG_cpu_usage", gauge_stack)
        self.assertIn("sensor.REPEATER_SLUG_radio_utilization", gauge_stack)
        self.assertIn("sensor.REPEATER_SLUG_packet_drop_rate_24h", gauge_stack)
        self.assertNotIn("sensor.REPEATER_SLUG_current_airtime", gauge_stack)
        self.assertIn(
            "'REPEATER_SLUG_sensor_modem_battery_percent' in item.entity_id",
            dashboard,
        )
        self.assertIn(
            "'REPEATER_SLUG_sensor_modem_solar_charge_rate_percent_per_hour' in item.entity_id",
            dashboard,
        )
        self.assertNotIn(
            "entity: sensor.REPEATER_SLUG_sensor_modem_battery_percent\n",
            dashboard,
        )
        self.assertNotIn(
            "entity: sensor.REPEATER_SLUG_sensor_modem_solar_charge_rate_percent_per_hour\n",
            dashboard,
        )
        self.assertIn("area prefixes or numeric suffixes", dashboard)

    def test_example_dashboard_is_anonymized_and_includes_v1_1_6_entities(self) -> None:
        dashboard = (ROOT / "dashboards/openhop_repeater_dashboard.yaml").read_text(
            encoding="utf-8"
        )

        self.assertIn("REPEATER_SLUG", dashboard)
        self.assertIn("sensor.REPEATER_SLUG_observed_neighbor_links", dashboard)
        self.assertIn("sensor.REPEATER_SLUG_active_neighbor_links", dashboard)
        self.assertIn("sensor.REPEATER_SLUG_metrics_data_source", dashboard)
        self.assertIn("sensor.REPEATER_SLUG_mqtt_neighbors_phase", dashboard)
        self.assertIn("sensor.REPEATER_SLUG_radio_stack_mode", dashboard)
        self.assertIn("sensor.REPEATER_SLUG_configured_radio_count", dashboard)
        self.assertIn("sensor.REPEATER_SLUG_sensor_modem_current_ma", dashboard)
        self.assertIn("sensor.REPEATER_SLUG_sensor_modem_power_mw", dashboard)
        self.assertIn("button.REPEATER_SLUG_send_direct_advert", dashboard)
        self.assertIn("button.REPEATER_SLUG_publish_mqtt_neighbors", dashboard)
        self.assertIn("number.REPEATER_SLUG_direct_advert_interval", dashboard)
        self.assertIn("External Modem Status", dashboard)
        self.assertIn("Example Broker 1", dashboard)
        self.assertIn("Example Companion", dashboard)
        for private_value in (
            "Pleasant Cove",
            "pleasant-cove",
            "shop_pleasant",
            "Boston Mesh",
            "Cove Companion",
            "Cove Bridge",
        ):
            self.assertNotIn(private_value, dashboard)


if __name__ == "__main__":
    unittest.main()
