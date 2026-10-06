"""Execute checked-in radio normalization/entities with only HA boundaries stubbed.

No live Home Assistant registration, HTTP, hardware or RF operations are used.
"""
import ast
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/pymc_repeater"


def load_monitoring():
    spec = importlib.util.spec_from_file_location("radio_monitoring", COMPONENT / "monitoring.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def entity_namespace():
    class CoordinatorEntity:
        def __init__(self, coordinator):
            self.coordinator = coordinator

        @property
        def available(self):
            return self.coordinator.last_update_success

    ns = dict(vars(load_monitoring()), json=json, CoordinatorEntity=CoordinatorEntity,
              SensorEntity=type("Sensor", (), {}), BinarySensorEntity=type("Binary", (), {}),
              DeviceInfo=dict, DOMAIN="pymc_repeater", MANUFACTURER="openHop",
              CONF_RADIO_ID_ALIASES="radio_id_aliases",
              EntityCategory=SimpleNamespace(DIAGNOSTIC="diagnostic"),
              SensorDeviceClass=SimpleNamespace(DURATION="duration", TIMESTAMP="timestamp", SIGNAL_STRENGTH="signal_strength"),
              SensorStateClass=SimpleNamespace(MEASUREMENT="measurement"),
              BinarySensorDeviceClass=SimpleNamespace(PROBLEM="problem", CONNECTIVITY="connectivity"))
    wanted = {"PyMCBaseEntity", "_nested", "_external_sensor_readings", "_external_sensor_identity"}
    for filename in ("sensor.py", "monitoring_entities.py"):
        tree = ast.parse((COMPONENT / filename).read_text())
        nodes = [node for node in tree.body
                 if (getattr(node, "name", None) in wanted if filename == "sensor.py"
                     else not isinstance(node, (ast.Import, ast.ImportFrom)))]
        nodes.insert(0, ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0))
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), filename, "exec"), ns)
    return ns


def fixture(ids=("a", "b")):
    return {"stats": {"radio_stack": {"mode": "multi", "radio_ids": list(ids)},
                      "radios": [{"id": rid} for rid in ids],
                      "airtime_radios": [{"radio_id": rid, "utilization_percent": 20,
                                          "current_airtime_ms": 200, "max_airtime_ms": 1000,
                                          "total_airtime_ms": 9000} for rid in ids],
                      "noise_floor_radios": [{"radio_id": rid, "noise_floor_dbm": -110} for rid in ids]},
            "packet_stats_1h": {"radios": [{"radio_id": rid, "received": 5, "duplicates": 2,
                                            "transmissions": 8, "avg_rssi": -90, "avg_snr": 6} for rid in ids]},
            "packet_stats": {"radios": [{"radio_id": rid, "received": 50, "duplicates": 20,
                                         "transmissions": 80, "avg_rssi": -95, "avg_snr": 4} for rid in ids]},
            "lbt_diagnostics": {"radios": [{"radio_id": rid,
                                           "summary": {"has_lbt_data": True, "total_transmissions": 80,
                                                       "retry_packets": 10, "retry_rate_pct": 12.5,
                                                       "avg_attempts": 1.25, "p95_attempts": 2,
                                                       "max_attempts": 4, "failed_transmissions": 1,
                                                       "busy_channel_events": 20,
                                                       "severe_contention_count": 2,
                                                       "severe_contention_pct": 2.5,
                                                       "worst_bucket": {"timestamp": 123}},
                                           "buckets": [{"timestamp": 123}]} for rid in ids]}}


class RadioTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.m = load_monitoring()

    def test_existing_polled_summaries_supply_child_measurements(self):
        self.assertTrue(callable(getattr(self.m, "radio_telemetry", None)),
                        "child radio telemetry normalization is missing")
        data = fixture()
        before = copy.deepcopy(data)
        result = self.m.radio_telemetry(data)
        self.assertEqual(result["a"]["channel_utilization"], 20)
        self.assertEqual(result["a"]["current_channel_airtime"], 200)
        self.assertEqual(result["a"]["max_channel_airtime"], 1000)
        self.assertEqual(result["a"]["noise_floor"], -110)
        for window, received in (("1h", 5), ("24h", 50)):
            self.assertEqual(result["a"][f"received_{window}"], received)
            for field in ("duplicates", "transmissions", "avg_rssi", "avg_snr"):
                self.assertIn(f"{field}_{window}", result["a"])
        self.assertEqual(result["a"]["lbt_retry_rate_pct_24h"], 12.5)
        self.assertEqual(result["a"]["lbt_busy_channel_events_24h"], 20)
        self.assertEqual(data, before)
        self.assertTrue(all(isinstance(value, (int, float)) for metrics in result.values() for value in metrics.values()))
        self.assertNotIn("total_airtime_ms", result["a"])
        self.assertNotIn("buckets", result["a"])
        self.assertNotIn("worst_bucket", result["a"])


    def test_alias_source_and_canonical_round_trip_keep_identity(self):
        for runtime_id in ("local", "radio0", "local"):
            with self.subTest(runtime_id=runtime_id):
                data = fixture((runtime_id, "b"))
                result = self.m.radio_telemetry(data, {"local": "radio0"})
                self.assertEqual(set(result), {"radio0", "b"})
                self.assertEqual(result["radio0"]["received_1h"], 5)
                self.assertEqual(result["radio0"]["noise_floor"], -110)
                self.assertEqual(result["radio0"]["lbt_retry_packets_24h"], 10)
        collision = fixture(("local", "radio0", "b"))
        self.assertEqual(set(self.m.radio_telemetry(collision, {"local": "radio0"})), {"b"})
        for aliases in ('{"local":"radio0","local":"old"}', {"local": "local"}, None):
            self.assertEqual(self.m.radio_telemetry(fixture(), aliases), {})

    def test_duplicate_unknown_and_alias_telemetry_ids_fail_closed(self):
        for endpoint, field in (("stats", "airtime_radios"), ("stats", "noise_floor_radios"),
                                ("packet_stats_1h", "radios"), ("packet_stats", "radios"),
                                ("lbt_diagnostics", "radios")):
            data = fixture(("local", "b"))
            rows = data[endpoint][field]
            rows.extend([copy.deepcopy(rows[0]), dict(rows[0], radio_id="unknown")])
            result = self.m.radio_telemetry(data, {"local": "radio0"})
            expected_absent = {("stats", "airtime_radios"): "channel_utilization",
                               ("stats", "noise_floor_radios"): "noise_floor",
                               ("packet_stats_1h", "radios"): "received_1h",
                               ("packet_stats", "radios"): "received_24h",
                               ("lbt_diagnostics", "radios"): "lbt_retry_packets_24h"}[(endpoint, field)]
            self.assertNotIn(expected_absent, result["radio0"])
            self.assertIn(expected_absent, result["b"])
            self.assertNotIn("unknown", result)
        data = fixture(("local", "b"))
        data["packet_stats"]["radios"].append(dict(data["packet_stats"]["radios"][0], radio_id="radio0"))
        self.assertNotIn("received_24h", self.m.radio_telemetry(data, {"local": "radio0"})["radio0"])
        data = fixture()
        data["stats"]["radios"].append({"id": "a"})
        self.assertNotIn("a", self.m.radio_telemetry(data))
        data = fixture()
        data["packet_stats"]["radios"].extend([{}, None, {"radio_id": ["a"]}])
        self.assertEqual(self.m.radio_telemetry(data)["a"]["received_24h"], 50)


    def test_absence_nonfinite_errors_empty_windows_and_no_lbt_samples(self):
        self.assertEqual(self.m.radio_telemetry({}), {})
        legacy = {"stats": {"radio_stack": {"radio_ids": ["a"]}, "packets_received": 99,
                            "noise_floor": -99, "utilization_percent": 42},
                  "packet_stats": {"total_packets": 44}, "lbt_diagnostics": {"summary": {"retry_packets": 12}}}
        self.assertEqual(self.m.radio_telemetry(legacy), {"a": {}})
        for invalid in (None, True, "nan", "inf", float("-inf"), {}, []):
            data = fixture()
            data["stats"]["noise_floor_radios"][0]["noise_floor_dbm"] = invalid
            data["packet_stats"]["radios"][0]["avg_snr"] = invalid
            self.assertNotIn("noise_floor", self.m.radio_telemetry(data)["a"])
            self.assertNotIn("avg_snr_24h", self.m.radio_telemetry(data)["a"])
        for error in ({"error": "failed"}, {"success": False}):
            data = fixture()
            data["packet_stats"].update(error)
            self.assertNotIn("received_24h", self.m.radio_telemetry(data)["a"])
            data = fixture()
            data["stats"]["noise_floor_radios"][0].update(error)
            self.assertNotIn("noise_floor", self.m.radio_telemetry(data)["a"])
            data = fixture()
            data["lbt_diagnostics"]["radios"][0]["summary"].update(error)
            self.assertNotIn("lbt_retry_packets_24h", self.m.radio_telemetry(data)["a"])
        data = fixture()
        data["packet_stats"]["radios"][0].update(received=0, duplicates=0, transmissions=0, avg_rssi=None, avg_snr=None)
        data["lbt_diagnostics"]["radios"][0]["summary"].update(has_lbt_data=False, retry_packets=0)
        result = self.m.radio_telemetry(data)["a"]
        self.assertEqual(result["received_24h"], 0)
        self.assertNotIn("avg_rssi_24h", result)
        self.assertNotIn("lbt_retry_packets_24h", result)


    def test_real_entities_discover_once_keep_alias_ids_and_become_unavailable(self):
        ns = entity_namespace()
        listeners, unload, entities = [], [], []
        def listen(callback):
            listeners.append(callback)
            return lambda: listeners.remove(callback)
        entry = SimpleNamespace(unique_id="entry", entry_id="fallback", options={"radio_id_aliases": {"local": "radio0"}},
                                async_on_unload=unload.append)
        coordinator = SimpleNamespace(data=fixture(("local", "b")), config_entry=entry,
                                      last_update_success=True, async_add_listener=listen)
        ns["setup_monitoring_sensors"](entry, coordinator, entities.extend)
        key = ("radio", "radio0", "received_1h")
        matches = [entity for entity in entities if entity._key == key]
        self.assertEqual(len(matches), 1, "child telemetry must be discovered")
        entity = matches[0]
        self.assertEqual(entity._attr_unique_id, 'entry_monitor_["radio","radio0","received_1h"]')
        self.assertEqual(entity.device_info["identifiers"], {("pymc_repeater", "entry_radio_radio0")})
        self.assertEqual(entity.device_info["via_device"], ("pymc_repeater", "entry"))
        self.assertTrue(entity.available)
        self.assertEqual(entity.native_value, 5)
        initial_ids = [item._attr_unique_id for item in entities]
        listeners[0]()
        self.assertEqual([item._attr_unique_id for item in entities], initial_ids)
        coordinator.data = fixture(("radio0", "b"))
        listeners[0]()
        self.assertTrue(entity.available)
        self.assertEqual([item._attr_unique_id for item in entities], initial_ids)
        coordinator.data = fixture(("b",))
        listeners[0]()
        self.assertFalse(entity.available)
        self.assertIsNone(entity.native_value)
        coordinator.data = fixture(("local", "b"))
        coordinator.data["packet_stats_1h"]["radios"][0]["received"] = float("nan")
        self.assertFalse(entity.available)
        coordinator.data = fixture(("local", "b"))
        coordinator.last_update_success = False
        self.assertFalse(entity.available)
        coordinator.last_update_success = True
        self.assertTrue(entity.available)
        self.assertEqual(len(unload), 1)
        unload[0]()
        self.assertEqual(listeners, [])


    def test_window_metadata_translations_shared_channel_no_summing(self):
        ns = entity_namespace()
        entry = SimpleNamespace(unique_id="entry", entry_id="fallback", options={})
        data = fixture()
        data["stats"]["utilization_percent"] = 20
        data["stats"]["current_airtime_ms"] = 200
        coordinator = SimpleNamespace(data=data, config_entry=entry, last_update_success=True)
        snapshot = ns["_snapshot"](coordinator, False)
        self.assertEqual(snapshot[("radio", "a", "current_channel_airtime")], 200)
        self.assertEqual(snapshot[("radio", "b", "current_channel_airtime")], 200)
        self.assertEqual(coordinator.data["stats"]["current_airtime_ms"], 200)
        translations = json.loads((COMPONENT / "translations/en.json").read_text())["entity"]["sensor"]
        self.assertIn("RADIO_TELEMETRY", ns, "telemetry metadata table is missing")
        self.assertEqual(set(ns["RADIO_TELEMETRY"]), set(self.m.radio_telemetry(data)["a"]))
        for field, (name, unit) in ns["RADIO_TELEMETRY"].items():
            with self.subTest(field=field):
                entity = ns["MonitoringSensor"](entry, coordinator, ("radio", "a", field))
                self.assertEqual(entity._attr_state_class, "measurement")
                self.assertEqual(entity._attr_name, name)
                self.assertEqual(entity._attr_native_unit_of_measurement, unit)
                self.assertEqual(entity._attr_translation_key, f"radio_{field}")
                self.assertEqual(translations[f"radio_{field}"]["name"], name)
        self.assertEqual(ns["MonitoringSensor"](entry, coordinator, ("radio", "a", "current_channel_airtime"))._attr_device_class, "duration")
        self.assertEqual(ns["MonitoringSensor"](entry, coordinator, ("radio", "a", "noise_floor"))._attr_device_class, "signal_strength")
        # Existing child configuration and unique IDs are not renamed.
        existing = ns["MonitoringSensor"](entry, coordinator, ("radio", "a", "frequency"))
        self.assertEqual(existing._attr_unique_id, 'entry_monitor_["radio","a","frequency"]')
        self.assertEqual(existing._attr_name, "Radio a frequency")


    def test_every_measurement_rejects_nonfinite_values_and_late_sources_discover(self):
        ns = entity_namespace()
        entry = SimpleNamespace(unique_id="entry", entry_id="fallback", options={}, async_on_unload=lambda callback: None)
        listeners, entities = [], []
        coordinator = SimpleNamespace(data={"stats": {"radio_stack": {"radio_ids": ["a", "b"]}}},
                                      config_entry=entry, last_update_success=True,
                                      async_add_listener=listeners.append)
        ns["setup_monitoring_sensors"](entry, coordinator, entities.extend)
        self.assertFalse(any(item._key[2] == "received_1h" for item in entities))
        coordinator.data = fixture()
        listeners[0]()
        received = next(item for item in entities if item._key == ("radio", "a", "received_1h"))
        self.assertTrue(received.available)
        coordinator.data["packet_stats_1h"]["radios"][0]["received"] = 0
        self.assertEqual(received.native_value, 0, "a falling window is a measurement, not a lifetime counter")
        for invalid in (True, "nan", "inf", None):
            data = fixture()
            for endpoint, source in (("stats", "airtime_radios"), ("stats", "noise_floor_radios"),
                                     ("packet_stats", "radios"), ("packet_stats_1h", "radios"),
                                     ("lbt_diagnostics", "radios")):
                row = data[endpoint][source][0]
                payload = row["summary"] if endpoint == "lbt_diagnostics" else row
                for field in list(payload):
                    if field not in ("radio_id", "has_lbt_data", "worst_bucket"):
                        payload[field] = invalid
            self.assertEqual(self.m.radio_telemetry(data)["a"], {})
            coordinator.data = data
            self.assertFalse(received.available)
        coordinator.data = fixture()
        coordinator.data["packet_stats_1h"]["radios"].append(copy.deepcopy(coordinator.data["packet_stats_1h"]["radios"][0]))
        self.assertFalse(received.available)


if __name__ == "__main__":
    unittest.main()
