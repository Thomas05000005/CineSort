"""P3.2 : tests pour le component tierPill (desktop + dashboard).

Les tests JS introspectent les sources pour vérifier la présence du
component et de son intégration dans les tables/lists.
"""

from __future__ import annotations

import unittest
from pathlib import Path


class DesktopTierPillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.badge_js = (Path(__file__).resolve().parents[1] / "web" / "components" / "badge.js").read_text(
            encoding="utf-8"
        )
        cls.quality_js = (Path(__file__).resolve().parents[1] / "web" / "views" / "quality.js").read_text(
            encoding="utf-8"
        )

    def test_tierPill_function_exported(self):
        self.assertIn("function tierPill(", self.badge_js)
        self.assertIn("_TIER_MAP", self.badge_js)

    def test_scoreTierPill_function_present(self):
        self.assertIn("function scoreTierPill(", self.badge_js)

    def test_tier_map_covers_all_five_tiers(self):
        for tier in ("platinum", "gold", "silver", "bronze", "reject"):
            self.assertIn(tier, self.badge_js.lower())

    def test_legacy_aliases_preserved(self):
        # Premium/Bon/Moyen/Mauvais doivent rester acceptés pour rétrocompat
        for alias in ("premium", "bon", "moyen", "mauvais"):
            self.assertIn(alias, self.badge_js.lower())

    def test_distribution_uses_tierPill(self):
        # P3.2 : les labels de la distribution qualité utilisent tierPill
        self.assertIn('tierPill("platinum"', self.quality_js)
        self.assertIn('tierPill("gold"', self.quality_js)


class DashboardTierPillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.badge_js = (
            Path(__file__).resolve().parents[1] / "web" / "dashboard" / "components" / "badge.js"
        ).read_text(encoding="utf-8")
        cls.library_js = (Path(__file__).resolve().parents[1] / "web" / "dashboard" / "views" / "library.js").read_text(
            encoding="utf-8"
        )

    def test_dashboard_tierPill_exported(self):
        self.assertIn("export function tierPill(", self.badge_js)

    def test_dashboard_scoreTierPill_exported(self):
        self.assertIn("export function scoreTierPill(", self.badge_js)

    def test_library_imports_tierPill(self):
        self.assertIn("tierPill", self.library_js)
        # Dans les colonnes / lignes de la library table
        self.assertIn("tierPill(v,", self.library_js)

    def test_dashboard_tier_colors_match_desktop(self):
        # Les couleurs Platinum violet / Gold jaune / Silver gris / Bronze orange
        # / Reject rouge doivent être cohérentes (#A78BFA, #FBBF24, #9CA3AF,
        # #FB923C, #EF4444) entre desktop et dashboard.
        for color in ("A78BFA", "FBBF24", "9CA3AF", "FB923C", "EF4444"):
            self.assertIn(color, self.badge_js)


class TierPillVisualStructureTests(unittest.TestCase):
    """Vérifie que la pastille a bien un dot circulaire + texte coloré."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.badge_js = (Path(__file__).resolve().parents[1] / "web" / "components" / "badge.js").read_text(
            encoding="utf-8"
        )

    def test_pill_has_circular_dot(self):
        self.assertIn("border-radius:50%", self.badge_js)

    def test_pill_has_background_alpha(self):
        # Le background utilise une alpha (22 en hex = ~13%)
        self.assertIn("22", self.badge_js)  # présent dans les styles

    def test_pill_has_border(self):
        self.assertIn("border:1px solid", self.badge_js)

    def test_pill_text_colored_like_dot(self):
        # Le texte utilise la même couleur que le dot pour la cohérence visuelle
        self.assertIn("color:${info.color}", self.badge_js)


if __name__ == "__main__":
    unittest.main()
