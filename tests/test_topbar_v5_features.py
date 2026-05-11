"""V5A-02 — Verifie top-bar-v5 enrichi avec FAB + notification dynamic + V4-09 audit."""

from __future__ import annotations

import unittest
from pathlib import Path


class TopBarV5FeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/dashboard/components/top-bar-v5.js").read_text(encoding="utf-8")

    def test_v3_08_help_fab_export(self):
        self.assertIn("export function mountHelpFab", self.src)
        self.assertIn("export function unmountHelpFab", self.src)
        self.assertIn("v5HelpFab", self.src)
        self.assertIn("v5-help-fab", self.src)

    def test_notification_badge_dynamic_export(self):
        self.assertIn("export function updateNotificationBadge", self.src)
        self.assertIn("data-v5-notif-badge", self.src)

    def test_v4_09_no_aria_mismatch(self):
        # top-bar-v5 ne doit PAS avoir l'avatar avec aria-label="Profil utilisateur" + texte visible "CS"
        # (c'est uniquement dans v4 — top-bar-v5 ne l'a jamais eu)
        self.assertNotIn("topbarAvatar", self.src)

    def test_existing_features_preserved(self):
        # Search Cmd+K
        self.assertIn("data-v5-search-trigger", self.src)
        # Theme menu
        self.assertIn("data-v5-theme-trigger", self.src)
        # Notification cloche
        self.assertIn("data-v5-notif-trigger", self.src)


if __name__ == "__main__":
    unittest.main()
