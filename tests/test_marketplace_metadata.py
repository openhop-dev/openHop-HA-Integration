"""Marketplace metadata and documented installation contracts (source-only)."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MarketplaceMetadataTests(unittest.TestCase):
    def test_categories_and_existing_identity(self):
        manifest = json.loads((ROOT / "custom_components/pymc_repeater/manifest.json").read_text())
        self.assertEqual(manifest["domain"], "pymc_repeater")
        self.assertTrue(manifest["config_flow"])
        # Validated against HA 2026.11.0 generated integration_categories.json.
        self.assertEqual(manifest["categories"], [
            "computers_network.routers_network", "computers_network.monitoring",
        ])
        self.assertEqual(list(manifest)[:2], ["domain", "name"])
        self.assertEqual(list(manifest)[2:], sorted(list(manifest)[2:]))

    def test_installation_methods_and_restart_boundaries(self):
        readme = (ROOT / "README.md").read_text()
        self.assertLess(readme.index("[![Add to Home Assistant]"),
                        readme.index("### Marketplace"))
        self.assertEqual(readme.count("https://my.home-assistant.io/badges/hacs_repository.svg"), 1)
        self.assertIn("then confirm **Add** and **Install** when prompted", readme)
        for text in (
            "Marketplace — Home Assistant 2026.11 and newer",
            "Settings → Marketplace", "Add from link",
            "custom repositories require a GitHub connection",
            "HACS — older Home Assistant versions", "### Manual installation",
            "without a Home Assistant restart",
            "Updating an already-loaded integration still requires a Home Assistant",
            "Reloading the integration entry is",
            "https://github.com/openhop-dev/openHop-HA-Integration",
        ):
            self.assertIn(text, readme)
        self.assertNotIn("After installation and restart:", readme)
