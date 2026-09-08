"""Radio configuration parity, executing real helpers without Home Assistant."""
from copy import deepcopy
from pathlib import Path
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/pymc_repeater"


def single_fabric():
    return {"stats": {"radio_stack": {"mode": "single_fabric", "radio_ids": ["radio0"],
                                      "default_radio": "radio0", "fabric": True},
                      "radios": [], "config": {"radio": {"frequency": 868000000,
                                                           "tx_power": 22}}}}


class RadioInventoryTests(unittest.TestCase):
    def setUp(self):
        self.inventory = runpy.run_path(str(ROOT / "monitoring.py"))["radio_inventory"]

    def test_single_fabric_sole_default_gets_global_settings_before_aliasing(self):
        data = single_fabric()
        before = deepcopy(data)
        self.assertEqual(self.inventory(data, {"radio0": "original"}),
                         {"original": {"frequency": 868000000, "tx_power": 22}})
        self.assertEqual(data, before)

    def test_explicit_row_settings_override_global_single_fabric_settings(self):
        data = single_fabric()
        data["stats"]["radios"] = [{"id": "radio0", "radio": {"frequency": 915000000}}]
        self.assertEqual(self.inventory(data)["radio0"], {"frequency": 915000000, "tx_power": 22})

    def test_global_settings_require_valid_sole_default_topology(self):
        mutations = [
            ("stack", "mode", "multi"), ("stack", "mode", "unknown"),
            ("stack", "default_radio", "other"), ("stack", "default_radio", None),
            ("stack", "radio_ids", []), ("stack", "radio_ids", None),
            ("stack", "radio_ids", ["radio0", None]),
            ("stack", "radio_ids", ["radio0", "radio0"]),
            ("stack", "radio_ids", ["radio0", "other"]),
            ("stack", "error", "offline"), ("stack", "success", False),
            ("stats", "radios", [None]), ("stats", "radios", None),
            ("stats", "radios", [{"id": "other"}]),
            ("stats", "radios", [{"id": "radio0", "radio": None}]),
            ("stats", "radios", [{"id": "radio0", "error": "offline"}]),
            ("stats", "radios", [{"id": "radio0", "success": False}]),
            ("stats", "radios", [{"id": "radio0", "radio": {"error": "offline"}}]),
            ("stats", "radios", [{"id": "radio0", "radio_id": "other"}]),
            ("stats", "radios", [{"id": "radio0"}, {"id": "radio0"}]),
            ("config", "success", False), ("config", "error", "offline"),
        ]
        for mode in ("single", "single_fabric"):
            for section, key, value in mutations:
                with self.subTest(mode=mode, section=section, key=key, value=value):
                    data = single_fabric()
                    data["stats"]["radio_stack"]["mode"] = mode
                    target = (data["stats"]["radio_stack"] if section == "stack" else
                              data["stats"]["config"] if section == "config" else data["stats"])
                    target[key] = value
                    self.assertTrue(all("frequency" not in row and "tx_power" not in row
                                        for row in self.inventory(data).values()))

    def test_radio_type_is_preferred_with_legacy_string_fallback(self):
        for row, expected in [
            ({"radio_type": "modem_usb"}, "modem_usb"),
            ({"radio_type": "modem_tcp", "type": "legacy"}, "modem_tcp"),
            ({"type": "legacy"}, "legacy"),
            ({"radio_type": None, "type": "legacy"}, "legacy"),
            ({"radio_type": {}, "type": "legacy"}, "legacy"),
        ]:
            with self.subTest(row=row):
                data = single_fabric()
                data["stats"]["radios"] = [{"id": "radio0", **row}]
                self.assertEqual(self.inventory(data)["radio0"]["type"], expected)


if __name__ == "__main__":
    unittest.main()
