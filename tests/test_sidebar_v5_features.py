"""V5A-01 — Verifie que sidebar-v5 contient les 5 features V1-V4 portees."""

from __future__ import annotations
import unittest
from pathlib import Path


class SidebarV5FeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/dashboard/components/sidebar-v5.js").read_text(encoding="utf-8")

    def test_v3_04_badge_data_key(self):
        self.assertIn("data-badge-key", self.src)
        self.assertIn("v5-sidebar-badge", self.src)
        self.assertIn("updateSidebarBadges", self.src)

    def test_v3_01_integration_disabled(self):
        self.assertIn("markIntegrationState", self.src)
        self.assertIn("v5-sidebar-item--disabled", self.src)

    def test_v1_12_about_button(self):
        self.assertIn("data-v5-about-btn", self.src)
        self.assertIn("onAboutClick", self.src)

    def test_v1_13_update_badge(self):
        self.assertIn("setUpdateBadge", self.src)
        self.assertIn("v5-sidebar-update-badge", self.src)

    def test_v1_14_help_entry(self):
        # V7-fusion Phase 3 : QIJ remplace 5 items (quality/journal/jellyfin/
        # plex/radarr) -> sidebar reduite a 6 entrees (home, processing,
        # library, qij, settings, help). Aide doit toujours etre presente.
        self.assertIn('"help"', self.src)
        nav_items_count = self.src.count('shortcut: "Alt+')
        self.assertGreaterEqual(nav_items_count, 6)

    def test_v4_09_aria_current(self):
        self.assertIn('aria-current="page"', self.src)
        # Plus de aria-selected en mode navigation
        self.assertNotIn('aria-selected="true"', self.src)


if __name__ == "__main__":
    unittest.main()
