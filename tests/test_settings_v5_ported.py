"""V5bis-05 — Vérifie settings-v5.js porté."""

from __future__ import annotations
import unittest
from pathlib import Path


class SettingsV5PortedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/settings-v5.js").read_text(encoding="utf-8")

    def test_es_module_export(self):
        self.assertIn("export async function initSettings", self.src)

    def test_no_iife(self):
        self.assertNotIn("window.SettingsV5", self.src)

    def test_no_pywebview_api(self):
        self.assertNotIn("window.pywebview.api", self.src)

    def test_helpers_imported(self):
        self.assertIn('from "./_v5_helpers.js"', self.src)

    def test_settings_groups_preserved(self):
        self.assertIn("SETTINGS_GROUPS", self.src)
        # 9 groupes (count "id:" approximatif dans le schema)
        # Plus précis : compter "label:" qui apparaît à chaque field/group
        self.assertGreaterEqual(self.src.count('id: "'), 9)

    def test_autosave_500ms(self):
        self.assertIn("_scheduleSave", self.src)
        self.assertIn("500", self.src)

    def test_v3_02_expert_mode(self):
        self.assertIn("expert_mode", self.src)
        self.assertIn("_applyExpertMode", self.src)
        self.assertIn("data-advanced", self.src)

    def test_v3_03_glossary(self):
        self.assertIn("glossaryTooltip", self.src)

    def test_v3_09_danger_zone(self):
        self.assertIn("danger-zone", self.src)
        self.assertIn("reset_all_user_data", self.src)

    def test_v3_12_updates(self):
        self.assertIn("updates-section", self.src)
        self.assertIn("update_github_repo", self.src)


if __name__ == "__main__":
    unittest.main()
