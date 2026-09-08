"""Guard static radio alias help against accidental HA placeholders."""
import json
from pathlib import Path
import unittest


class TranslationPlaceholderTests(unittest.TestCase):
    def test_radio_alias_help_has_no_literal_json_braces(self):
        root = Path(__file__).resolve().parents[1]
        translations = json.loads((root / 'custom_components/pymc_repeater/translations/en.json').read_text())
        text = translations['options']['step']['init']['data_description']['radio_id_aliases']
        self.assertNotIn('{', text)
        self.assertNotIn('}', text)
        self.assertIn('local', text)
        self.assertIn('radio0', text)
