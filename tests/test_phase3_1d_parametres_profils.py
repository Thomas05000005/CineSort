"""Tests Phase 3.1-D : Parametres - Profils Qualite editables (spec 11 §2.9)."""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PARAMETRES_JS = _ROOT / "web" / "dashboard" / "views" / "parametres.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class ProfilQualiteEditorTests(unittest.TestCase):
    """Spec 11 §2.9 : edition des seuils de tier."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PARAMETRES_JS.read_text(encoding="utf-8")

    def test_render_profils_qualite_panel(self) -> None:
        self.assertIn("_renderProfilsQualitePanel", self.js)

    def test_4_tier_inputs(self) -> None:
        for tier in ("platinum", "gold", "silver", "bronze"):
            self.assertIn(f'data-tier-input="{tier}"', self.js)

    def test_default_tiers_values(self) -> None:
        """Defaults alignes avec cinesort/domain/quality_score.py."""
        self.assertIn("_DEFAULT_TIERS", self.js)
        self.assertIn("platinum: 85", self.js)
        self.assertIn("gold: 68", self.js)
        self.assertIn("silver: 54", self.js)
        self.assertIn("bronze: 30", self.js)

    def test_save_uses_settings_endpoints(self) -> None:
        self.assertIn("settings/get_settings", self.js)
        self.assertIn("settings/save_settings", self.js)

    def test_quality_profile_tiers(self) -> None:
        """Spec : on persiste sous settings.quality_profile.tiers."""
        self.assertIn("quality_profile", self.js)
        self.assertIn("profile.tiers", self.js)

    def test_validation_order(self) -> None:
        """Validation : Platinum > Gold > Silver > Bronze (decroissant)."""
        self.assertIn("strictement décroissants", self.js)

    def test_reset_action(self) -> None:
        self.assertIn('data-parametres-profils-action="reset"', self.js)

    def test_save_action(self) -> None:
        self.assertIn('data-parametres-profils-action="save"', self.js)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_tier_classes(self) -> None:
        for cls in (
            ".parametres-profils-form",
            ".parametres-tier-row",
            ".parametres-tier-badge",
            ".parametres-tier-badge--platinum",
            ".parametres-tier-badge--gold",
            ".parametres-tier-badge--silver",
            ".parametres-tier-badge--bronze",
            ".parametres-profils-message",
            ".parametres-profils-actions",
        ):
            self.assertIn(cls, self.css)


if __name__ == "__main__":
    unittest.main()
