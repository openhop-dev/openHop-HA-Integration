"""Contract tests for openHop Repeater dev API alignment.

These tests intentionally use the Python AST so they can run without installing
Home Assistant while still pinning the integration's public API/service contract.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
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

    def test_service_descriptions_include_new_actions(self) -> None:
        source = (COMPONENT / "services.yaml").read_text(encoding="utf-8")
        self.assertIn("cad_manual_check:", source)
        self.assertIn("get_neighbor_links:", source)
        self.assertIn("get_neighbor_link_history:", source)
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
        self.assertNotIn("## Unreleased", changelog)
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

    def test_example_dashboard_is_anonymized_and_includes_v1_1_6_entities(self) -> None:
        dashboard = (ROOT / "dashboards/pymc_repeater_dashboard.yaml").read_text(
            encoding="utf-8"
        )

        self.assertIn("REPEATER_SLUG", dashboard)
        self.assertIn("sensor.REPEATER_SLUG_observed_neighbor_links", dashboard)
        self.assertIn("sensor.REPEATER_SLUG_active_neighbor_links", dashboard)
        self.assertIn("sensor.REPEATER_SLUG_metrics_data_source", dashboard)
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
