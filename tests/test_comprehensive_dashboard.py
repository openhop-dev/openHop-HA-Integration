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

    def test_radio_130_rows_use_explicit_independent_child_examples(self):
        text = (ROOT / 'dashboards/openhop_repeater_dashboard.yaml').read_text()
        self.assertIn('title: Radio Telemetry · Example Radio', text)
        self.assertIn('Replace each full example ID with exact entity IDs', text)
        suffixes = [
            'channel_utilization', 'current_channel_airtime', 'maximum_channel_airtime',
            'cached_noise_floor',
            *[f'{field}_{window}' for window in ('1h', '24h')
              for field in ('packets_received', 'duplicate_packets', 'physical_transmissions',
                            'average_rssi', 'average_snr')],
            *[f'lbt_{field}_24h' for field in (
                'transmissions', 'retry_packets', 'retry_rate', 'average_attempts',
                'p95_attempts', 'maximum_attempts', 'failed_transmissions',
                'busy_channel_events', 'severe_contention_count', 'severe_contention_rate')],
        ]
        for suffix in suffixes:
            self.assertIn('sensor.EXAMPLE_RADIO_' + suffix, text)
        self.assertIn('airtime budgets must not be summed', text)
        self.assertIn('Packet counts are sliding windows', text)
        overview = text.split('heading: Recent trends')[0]
        self.assertNotIn('EXAMPLE_RADIO', overview)
        self.assertNotIn('custom:', text)

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
