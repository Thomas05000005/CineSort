"""V5A-04 — Verifie home.js v5 enrichi avec 5 features V1-V4."""

from __future__ import annotations

import unittest
from pathlib import Path


class HomeV5FeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/home.js").read_text(encoding="utf-8")

    def test_v2_04_promise_allsettled(self):
        self.assertIn("Promise.allSettled", self.src)

    def test_v2_08_skeleton(self):
        self.assertIn("v5-skeleton", self.src)
        self.assertIn("_renderSkeleton", self.src)

    def test_v1_07_probe_banner(self):
        self.assertIn("get_probe_tools_status", self.src)
        self.assertIn("v5-home-probe-banner", self.src)
        self.assertIn("auto_install_probe_tools", self.src)

    def test_v1_06_integrations_cta(self):
        self.assertIn("v5-home-integrations", self.src)
        self.assertIn("focus=jellyfin", self.src)
        self.assertIn("Configurer", self.src)

    def test_v3_05_demo_wizard(self):
        self.assertIn("showDemoWizardIfFirstRun", self.src)
        self.assertIn("renderDemoBanner", self.src)


if __name__ == "__main__":
    unittest.main()
