"""Portable comprehensive dashboard coverage without Home Assistant imports."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ComprehensiveDashboardTests(unittest.TestCase):
    def test_monitoring_features_are_in_comprehensive_view(self):
        text = (ROOT / 'dashboards/openhop_repeater_dashboard.yaml').read_text()
        for token in ('Component Health', 'Radio Inventory and Settings',
                      'Source Freshness', 'Individual Plugins', 'Battery Trend',
                      'update.REPEATER_SLUG_repeater_software',
                      'component_hardware_stats_problem', 'component_update_status_problem',
                      'reading_modem_pymc_modem_charge_state'):
            self.assertIn(token, text)
        self.assertNotIn('custom:', text)
        self.assertIn('REPEATER_SLUG', text)
        self.assertIn('exact entity IDs', text)

    def test_density_uses_natural_height_columns_and_named_badges(self):
        text = (ROOT / 'dashboards/openhop_repeater_dashboard.yaml').read_text()
        self.assertIn('type: vertical-stack', text)
        self.assertIn('column_span: 1', text)
        self.assertIn('show_name: true', text)
        overview = text.split('heading: Recent trends')[0]
        self.assertNotIn('name: Current Airtime', overview)
        self.assertNotIn('name: Avg Score 24h', overview)
        self.assertNotIn('name: GPS Fix', overview)

    def test_ordered_native_sections_keep_diagnostics_below_essentials(self):
        text = (ROOT / 'dashboards/openhop_repeater_dashboard.yaml').read_text()
        self.assertIn('type: sections', text)
        self.assertIn('max_columns: 3', text)
        self.assertIn('dense_section_placement: false', text)
        headings = ['Live overview', 'Recent trends', 'Operations',
                    'Diagnostics · system & radio', 'Diagnostics · traffic & routing',
                    'Diagnostics · plugins & connections',
                    'Diagnostics · GPS & external sensors',
                    'Diagnostics · tuning & storage', 'Reference notes']
        positions = [text.index('heading: ' + title) for title in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(text.count('column_span: 3'), len(headings))
        self.assertNotIn('type: history-graph', text)
        overview = text.split('heading: Recent trends')[0]
        self.assertNotIn('title: Component Health', overview)
        self.assertNotIn('component_gps_problem', overview)
        for suffix in ('packets_received_per_hour', 'packets_forwarded_per_hour',
                       'packet_drop_rate_24h', 'current_noise_floor', 'radio_utilization'):
            self.assertIn('sensor.REPEATER_SLUG_' + suffix, overview)
