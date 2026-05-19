"""Tests Phase 3.5 : USER_GUIDE_v2.md exists and covers the 7 screens (spec 12)."""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_USER_GUIDE = _ROOT / "docs" / "USER_GUIDE_v2.md"


class FileExistsTests(unittest.TestCase):
    def test_user_guide_exists(self) -> None:
        self.assertTrue(_USER_GUIDE.is_file())

    def test_user_guide_min_size(self) -> None:
        size = _USER_GUIDE.stat().st_size
        self.assertGreater(size, 5000, f"USER_GUIDE_v2.md too short ({size} bytes)")


class ContentCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _USER_GUIDE.read_text(encoding="utf-8")

    def test_covers_7_views(self) -> None:
        """Spec 12 : guide couvre les 7 vues principales."""
        for view in ("Accueil", "Traitement", "Bibliothèque", "Qualité", "Historique", "Paramètres", "Aide"):
            self.assertIn(view, self.text, f"Vue {view} non documentee")

    def test_covers_shell_3_zones(self) -> None:
        self.assertIn("Shell 3 zones", self.text)
        self.assertIn("Sidebar", self.text)
        self.assertIn("Inspecteur", self.text)

    def test_covers_keyboard_shortcuts(self) -> None:
        for sc in ("Ctrl+B", "Ctrl+I", "Ctrl+K", "Alt+1"):
            self.assertIn(sc, self.text, f"Raccourci {sc} manquant")

    def test_covers_score_v2(self) -> None:
        self.assertIn("Score V2", self.text)
        for tier in ("Platinum", "Gold", "Silver", "Bronze", "Reject"):
            self.assertIn(tier, self.text)

    def test_covers_alert_labels(self) -> None:
        """Doit lister les alertes humanisees principales (mapping alert-labels.js)."""
        for flag in ("subtitle_missing_fr", "nfo_title_mismatch", "duplicate_cross_root", "omdb_disagree"):
            self.assertIn(flag, self.text)

    def test_covers_dangerous_actions(self) -> None:
        self.assertIn("Actions dangereuses", self.text)
        self.assertIn("countdown", self.text)
        self.assertIn("_user_marked_for_deletion", self.text)

    def test_covers_perceptual_modal_states(self) -> None:
        """Spec 02 §4 : 5 etats de la modal perceptuelle."""
        for state in ("Normal", "Missing", "Disabled", "ffmpeg"):
            self.assertIn(state, self.text)

    def test_covers_remote_server(self) -> None:
        self.assertIn("--api", self.text)
        self.assertIn("QR", self.text)


if __name__ == "__main__":
    unittest.main()
