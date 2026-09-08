"""Execute real freshness helpers without importing Home Assistant."""
import importlib.util
from pathlib import Path
import unittest


PATH = Path(__file__).resolve().parents[1] / "custom_components/pymc_repeater/monitoring.py"
spec = importlib.util.spec_from_file_location("freshness_monitoring", PATH)
assert spec is not None and spec.loader is not None
monitoring = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitoring)


class SensorFreshnessCadenceTests(unittest.TestCase):
    def test_effective_reading_cadence_overrides_global(self):
        reading = {"timestamp": 900, "ok": True, "poll_interval_seconds": 60,
                   "data": {"solar_charge_rate_percent_per_hour": 1}}
        self.assertIs(monitoring.reading_stale(reading, 10, now=1000), False)
        self.assertTrue(monitoring.reading_usable(reading, 10, now=1000))
        self.assertEqual(monitoring.charge_state(reading, 10, now=1000), "charging")
        self.assertIs(monitoring.reading_stale(reading, 10, now=1080), False)
        self.assertIs(monitoring.reading_stale(reading, 10, now=1081), True)

    def test_short_override_does_not_inherit_long_global(self):
        reading = {"timestamp": 900, "poll_interval_seconds": 10}
        self.assertIs(monitoring.reading_stale(reading, 300, now=1000), True)

    def test_legacy_missing_metadata_uses_only_explicit_global_fallback(self):
        self.assertIs(monitoring.reading_stale({"timestamp": 900}, 60, now=1000), False)
        self.assertIs(monitoring.reading_stale({"timestamp": 900}, 10, now=1000), True)
        self.assertIsNone(monitoring.reading_stale({"timestamp": 900}, None, now=1000))

    def test_present_invalid_metadata_is_unknown_not_global_fallback(self):
        for interval in (None, True, False, 0, -1, "bad", "nan", "inf", [], {}):
            with self.subTest(interval=interval):
                reading = {"timestamp": 990, "ok": True, "poll_interval_seconds": interval}
                self.assertIsNone(monitoring.reading_stale(reading, 60, now=1000))
                self.assertFalse(monitoring.reading_usable(reading, 60, now=1000))

    def test_effective_metadata_does_not_bypass_timestamp_or_success(self):
        for timestamp in (None, True, "bad", float("nan"), 1100):
            reading = {"timestamp": timestamp, "ok": True, "poll_interval_seconds": 60}
            self.assertFalse(monitoring.reading_usable(reading, 10, now=1000))
        self.assertFalse(monitoring.reading_usable(
            {"timestamp": 990, "ok": False, "poll_interval_seconds": 60}, 10, now=1000))

    def test_nested_measurement_cannot_override_envelope_cadence(self):
        reading = {"timestamp": 900, "data": {"poll_interval_seconds": 600}}
        self.assertIs(monitoring.reading_stale(reading, 10, now=1000), True)
