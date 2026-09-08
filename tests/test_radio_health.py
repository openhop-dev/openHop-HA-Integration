"""Aggregate radio health contracts; real source with minimal HA boundaries."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/pymc_repeater"


def load_health():
    namespace = {"PyMCSensorDescription": lambda **kw: SimpleNamespace(**kw),
                 "PyMCBinarySensorDescription": lambda **kw: SimpleNamespace(**kw),
                 "EntityCategory": SimpleNamespace(DIAGNOSTIC="diagnostic"),
                 "SensorDeviceClass": SimpleNamespace(ENUM="enum"),
                 "BinarySensorDeviceClass": SimpleNamespace(PROBLEM="problem")}
    descriptions = {}
    for filename in ("sensor.py", "binary_sensor.py"):
        tree = ast.parse((COMPONENT / filename).read_text())
        nodes: list[ast.stmt] = [n for n in tree.body if isinstance(n, ast.FunctionDef) and
                 n.name in {"_nested", "_radio_status", "_radio_error", "_radio_problem"}]
        nodes.insert(0, ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0))
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), filename, "exec"), namespace)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id not in ("PyMCSensorDescription", "PyMCBinarySensorDescription"):
                continue
            key = next((kw.value.value for kw in node.keywords
                        if kw.arg == "key" and isinstance(kw.value, ast.Constant)), None)
            if key in ("radio_status", "radio_problem"):
                # Only execute trusted checked-in descriptions, never API data.
                descriptions[key] = eval(compile(ast.Expression(node), filename, "eval"), namespace)
    return namespace, descriptions


class RadioHealthTests(unittest.TestCase):
    def setUp(self):
        self.ns, self.descriptions = load_health()

    def descriptions_present(self):
        self.assertEqual(set(self.descriptions), {"radio_status", "radio_problem"})
        return self.descriptions["radio_status"], self.descriptions["radio_problem"]

    def test_backend_states_and_safe_error_presence(self):
        sensor, binary = self.descriptions_present()
        for status, error, problem in (("ok", False, False), ("degraded", False, True),
                                       ("disabled", False, True), ("ok", True, True)):
            data = {"stats": {"radio_status": status}}
            if error:
                data["stats"]["radio_error"] = "synthetic-private-path token=DO_NOT_EXPOSE"
            with self.subTest(status=status, error=error):
                self.assertEqual(sensor.value_fn(data), status)
                self.assertIs(binary.value_fn(data), problem)
                self.assertEqual(sensor.attrs_fn(data), {"radio_error": error})
                self.assertNotIn("DO_NOT_EXPOSE", json.dumps(sensor.attrs_fn(data)))
        self.assertEqual(binary.device_class, "problem")

    def test_missing_malformed_and_failed_stats_are_unknown(self):
        sensor, binary = self.descriptions_present()
        for stats in (None, [], {}, {"radio_status": "unknown"}, {"radio_status": "future-state"},
                      {"radio_status": []}, {"radio_status": True},
                      {"radio_status": "ok", "success": False},
                      {"radio_status": "ok", "error": "endpoint failed"}):
            with self.subTest(stats=stats):
                data = {"stats": stats}
                self.assertIsNone(sensor.value_fn(data))
                self.assertIsNone(binary.value_fn(data))
                self.assertEqual(sensor.attrs_fn(data), {"radio_error": None})
        for raw in (False, 0, [], {}):
            data = {"stats": {"radio_status": "ok", "radio_error": raw}}
            self.assertIsNone(binary.value_fn(data))
            self.assertEqual(sensor.attrs_fn(data), {"radio_error": None})

    def test_error_without_known_status_is_still_a_problem(self):
        sensor, binary = self.descriptions_present()
        data = {"stats": {"radio_error": "synthetic failure"}}
        self.assertIsNone(sensor.value_fn(data))
        self.assertIs(binary.value_fn(data), True)
        self.assertEqual(sensor.attrs_fn(data), {"radio_error": True})

    def test_raw_radio_error_is_redacted_from_diagnostics(self):
        tree = ast.parse((COMPONENT / "diagnostics.py").read_text())
        assignment = next(n for n in tree.body if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == "TO_REDACT" for t in n.targets))
        namespace = {"CONF_API_TOKEN": "api_token"}
        exec(compile(ast.Module(body=[assignment], type_ignores=[]), "diagnostics.py", "exec"), namespace)
        self.assertIn("radio_error", namespace["TO_REDACT"])

    def test_configuration_does_not_prove_health(self):
        sensor, binary = self.descriptions_present()
        data = {"stats": {"radio_stack": {"mode": "multi", "radio_ids": ["a", "b"]},
                          "radios": [{"id": "a", "type": "kiss"}, {"id": "b", "type": "null"}],
                          "config": {"radio": {"enabled": True}}}}
        self.assertIsNone(sensor.value_fn(data))
        self.assertIsNone(binary.value_fn(data))
        self.assertEqual(sensor.attrs_fn(data), {"radio_error": None})

    def test_translation_and_builtin_parent_dashboard_contract(self):
        translations = json.loads((COMPONENT / "translations/en.json").read_text())["entity"]
        self.assertIn("radio_status", translations["sensor"])
        self.assertIn("radio_problem", translations["binary_sensor"])
        dashboard = (ROOT / "dashboards/openhop_repeater_dashboard.yaml").read_text()
        self.assertIn("sensor.REPEATER_SLUG_radio_status", dashboard)
        self.assertIn("binary_sensor.REPEATER_SLUG_radio_problem", dashboard)
        self.assertIn("Aggregate radio", dashboard)
        self.assertNotIn("custom:", dashboard)


if __name__ == "__main__":
    unittest.main()
