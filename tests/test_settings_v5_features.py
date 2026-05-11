"""V5A-03 — Vérifie settings-v5 enrichi avec V3-02 expert + V3-03 glossaire."""

from __future__ import annotations

import unittest
from pathlib import Path


class SettingsV5FeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/settings-v5.js").read_text(encoding="utf-8")

    def test_v3_02_expert_mode_toggle(self):
        self.assertIn("v5CkExpertMode", self.src)
        self.assertIn("expert_mode", self.src)
        self.assertIn("_applyExpertMode", self.src)

    def test_v3_02_advanced_fields_marker(self):
        # Au moins quelques fields doivent être marqués advanced: true
        self.assertGreaterEqual(self.src.count("advanced: true"), 5)

    def test_v3_02_data_advanced_render(self):
        self.assertIn('data-advanced="true"', self.src)

    def test_v3_03_glossary_imported(self):
        self.assertIn("glossaryTooltip", self.src)
        # Au moins 3 fields doivent avoir un glossaryTerm
        self.assertGreaterEqual(self.src.count("glossaryTerm:"), 3)

    def test_v3_09_danger_zone_present(self):
        self.assertIn("danger-zone", self.src)
        self.assertIn("reset_all_user_data", self.src)

    def test_v3_12_updates_section_present(self):
        self.assertIn("updates-section", self.src)
        self.assertIn("update_github_repo", self.src)


if __name__ == "__main__":
    unittest.main()
