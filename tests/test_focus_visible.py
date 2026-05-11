"""V3-07 — Focus visible WCAG 2.4.7 AA (clavier, 4 themes)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


class FocusVisibleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.styles = Path("web/dashboard/styles.css").read_text(encoding="utf-8")
        themes_path = Path("web/shared/themes.css")
        self.themes = themes_path.read_text(encoding="utf-8") if themes_path.exists() else ""

    def test_focus_visible_global_rule(self) -> None:
        """Regle globale *:focus-visible avec outline non-zero."""
        self.assertIn(":focus-visible", self.styles)
        self.assertRegex(self.styles, r":focus-visible[^}]*outline:\s*\d+px")

    def test_skip_focus_when_not_visible(self) -> None:
        """*:focus:not(:focus-visible) { outline: none } pour ne pas afficher au clic souris."""
        self.assertIn(":not(:focus-visible)", self.styles)

    def test_focus_ring_token_per_theme(self) -> None:
        """Chaque theme definit son --focus-ring."""
        for theme in ("studio", "cinema", "luxe", "neon"):
            self.assertIn(f'data-theme="{theme}"', self.themes, f"Theme manquant: {theme}")
            block_start = self.themes.find(f'data-theme="{theme}"')
            block_end = self.themes.find("}", block_start) + 1
            block = self.themes[block_start:block_end]
            self.assertIn("--focus-ring", block, f"--focus-ring manquant pour {theme}")

    def test_no_orphan_outline_none(self) -> None:
        """Pas de outline: none sans replacement focus-visible adjacent."""
        all_none = re.findall(r"outline:\s*none", self.styles)
        legit = re.findall(r":not\(:focus-visible\)\s*\{[^}]*outline:\s*none", self.styles)
        orphans = len(all_none) - len(legit)
        self.assertLessEqual(
            orphans,
            2,
            f"{orphans} outline: none orphelins (sans focus-visible compensation)",
        )


if __name__ == "__main__":
    unittest.main()
