"""Execute trusted local sensor source without importing Home Assistant.

This covers description/value/entity wiring, not HA registry or recorder runtime.
The installed engine's aggregate counters restart at zero; decreases must reach
HA unchanged so TOTAL_INCREASING can recognize a new counter cycle.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "pymc_repeater"
COUNTERS = {
    "recv_flood_count": "Flood packets received",
    "recv_direct_count": "Direct packets received",
    "sent_flood_count": "Flood packets transmitted",
    "sent_direct_count": "Direct packets transmitted",
    "flood_dup_count": "Flood duplicates",
    "direct_dup_count": "Direct duplicates",
}


class CoordinatorBoundary:
    """Only the HA coordinator attachment boundary is replaced."""

    def __init__(self, coordinator):
        self.coordinator = coordinator


class SensorBoundary:
    """No HA registry/recorder emulation."""


class TrafficCounterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = ast.parse((COMPONENT / "sensor.py").read_text())
        # Execute only trusted checked-in helper and entity class bodies.
        names = {"_nested", "PyMCBaseEntity", "PyMCSensorEntity"}
        nodes = [node for node in cls.module.body if getattr(node, "name", None) in names]
        cls.scope = {
            "CoordinatorEntity": CoordinatorBoundary,
            "SensorEntity": SensorBoundary,
            "DeviceInfo": dict,
            "DOMAIN": "pymc_repeater",
            "MANUFACTURER": "openHop",
            "MODEL": "Repeater",
            "CONF_HOST": "host",
            "CONF_PORT": "port",
            "DATA_SIZE_SENSOR_KEYS": set(),
            "get_repeater_name_from_stats": lambda stats: None,
            "PyMCSensorDescription": SimpleNamespace,
            "SensorStateClass": SimpleNamespace(TOTAL_INCREASING="total_increasing", MEASUREMENT="measurement", TOTAL="total"),
            "EntityCategory": SimpleNamespace(DIAGNOSTIC="diagnostic"),
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "sensor.py", "exec"), cls.scope)
        table = next(node.value for node in cls.module.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "SENSORS")
        assert isinstance(table, ast.Tuple)
        cls.descriptions = {}
        for node in table.elts:
            assert isinstance(node, ast.Call)
            fields = {kw.arg: kw.value for kw in node.keywords}
            key = ast.literal_eval(fields["key"])
            if key in COUNTERS:
                if key in cls.descriptions:
                    raise AssertionError(f"Duplicate counter description: {key}")
                cls.descriptions[key] = eval(compile(ast.Expression(node), "sensor.py", "eval"), cls.scope)

    def description(self, key):
        self.assertIn(key, self.descriptions, f"Missing aggregate counter {key}")
        return self.descriptions[key]

    def test_description_metadata(self):
        self.assertEqual(set(self.descriptions), set(COUNTERS))
        for key, name in COUNTERS.items():
            with self.subTest(key=key):
                description = self.description(key)
                self.assertEqual(description.key, key)
                self.assertEqual(description.translation_key, key)
                self.assertEqual(description.name, name)
                self.assertEqual(description.state_class, "total_increasing")
                self.assertEqual(description.native_unit_of_measurement, "packets")
                self.assertEqual(description.entity_category, "diagnostic")
                self.assertIsNone(getattr(description, "device_class", None))

    def test_each_value_uses_aggregate_stats_not_radio_or_packet_history(self):
        stats = {key: index for index, key in enumerate(COUNTERS, start=11)}
        data = {"stats": {**stats, "radios": [{key: 999 for key in COUNTERS}]},
                "packet_stats": {key: 888 for key in COUNTERS}}
        for key in COUNTERS:
            with self.subTest(key=key):
                self.assertEqual(self.description(key).value_fn(data), stats[key])

    def test_explicit_zero_is_preserved(self):
        for key in COUNTERS:
            with self.subTest(key=key):
                self.assertEqual(self.description(key).value_fn({"stats": {key: 0}}), 0)

    def test_missing_null_and_failed_stats_are_unknown(self):
        for key in COUNTERS:
            for data in ({}, {"stats": {}}, {"stats": None}, {"stats": []},
                         {"stats": {"error": "offline"}}, {"stats": {key: None}}):
                with self.subTest(key=key, data=data):
                    self.assertIsNone(self.description(key).value_fn(data))

    def test_real_entity_preserves_resets_and_parent_identity_without_polling(self):
        entity_type = self.scope["PyMCSensorEntity"]
        for unique_id in ("example-repeater", None):
            entry = SimpleNamespace(unique_id=unique_id, entry_id="example-entry", title="Example",
                                    data={"host": "example.invalid", "port": 8000}, options={})
            coordinator = SimpleNamespace(data={"stats": {}})  # No API or refresh method.
            for key in COUNTERS:
                with self.subTest(key=key, unique_id=unique_id):
                    entity = entity_type(entry, coordinator, self.description(key))
                    self.assertEqual(entity._attr_unique_id, f"{unique_id or entry.entry_id}_{key}")
                    self.assertEqual(entity.device_info["identifiers"], {("pymc_repeater", unique_id or entry.entry_id)})
                    self.assertEqual(entity.native_unit_of_measurement, "packets")
                    observed = []
                    for value in (100, 105, None, 0, 2, 1):
                        coordinator.data = {"stats": {key: value}} if value is not None else {"stats": {}}
                        observed.append(entity.native_value)
                    self.assertEqual(observed, [100, 105, None, 0, 2, 1])
        setup = next(node for node in self.module.body if getattr(node, "name", None) == "async_setup_entry")
        self.assertIn("PyMCSensorEntity(entry, coordinator, description) for description in SENSORS", ast.unparse(setup))

    def test_english_translations_match_exact_names(self):
        translations = json.loads((COMPONENT / "translations/en.json").read_text())["entity"]["sensor"]
        for key, name in COUNTERS.items():
            with self.subTest(key=key):
                self.assertEqual(translations.get(key), {"name": name})

    def test_dashboard_counters_are_only_in_existing_packet_flow_card(self):
        dashboard = (ROOT / "dashboards/openhop_repeater_dashboard.yaml").read_text()
        # Source boundaries keep this contract test standard-library-only.
        packet_flow = dashboard.split("      title: Packet Flow\n", 1)[1].split("    grid_options:", 1)[0]
        overview = dashboard.split("    heading: Recent trends", 1)[0]
        for name in COUNTERS.values():
            entity_id = "sensor.REPEATER_SLUG_" + name.lower().replace(" ", "_")
            with self.subTest(entity_id=entity_id):
                self.assertEqual(dashboard.count(f"- entity: {entity_id}\n"), 1)
                self.assertIn(f"- entity: {entity_id}\n        name: {name}\n", packet_flow)
                self.assertNotIn(entity_id, overview)


if __name__ == "__main__":
    unittest.main()
