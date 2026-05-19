"""Tests pour l'affichage des posters TMDb dans les candidats (issue #93)."""

from __future__ import annotations

import unittest
from pathlib import Path

# Migration B (PR1 #257 + PR2) : legacy frontend supprime.
# TODO Phase 2/3 : porter les invariants utiles vers de nouveaux tests dashboard
# une fois le Shell 3 zones + les 12 ecrans implementes.
if not (Path(__file__).resolve().parents[1] / "web" / "views" / "home.js").exists():
    raise unittest.SkipTest(
        "Legacy frontend removed (PR #257 + PR2 migration B). "
        "Tests rely on web/views/*.js files which were deleted "
        "(home.js, help.js, quality.js, settings.js, validation.js, etc.)."
    )

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_JS = PROJECT_ROOT / "web" / "views" / "validation.js"
DOM_JS = PROJECT_ROOT / "web" / "core" / "dom.js"


class SafeUrlHelperTests(unittest.TestCase):
    """Issue #93 : web/core/dom.js doit exposer safeUrl pour valider les URLs poster."""

    def test_safe_url_function_exists(self) -> None:
        src = DOM_JS.read_text(encoding="utf-8")
        self.assertIn("function safeUrl", src)
        # Doit valider http/https et data:image
        self.assertIn("http:", src)
        self.assertIn("https:", src)


class ValidationCandidatePostersTests(unittest.TestCase):
    """Issue #93 : validation.js doit afficher poster TMDb pour chaque candidat."""

    def setUp(self) -> None:
        self.src = VALIDATION_JS.read_text(encoding="utf-8")

    def test_uses_safe_url_for_poster(self) -> None:
        """safeUrl doit etre utilise pour valider l'URL du poster avant injection."""
        # Pattern : safeUrl(c.poster_url ...)
        self.assertIn("safeUrl(c.poster_url", self.src)

    def test_renders_img_tag_with_poster(self) -> None:
        """Quand poster_url present, render un <img> avec loading=lazy."""
        # Chercher la creation d'un <img dans le rendu candidats
        # On verifie la presence des tokens caracteristiques sans assertion ordre strict
        self.assertIn("<img src=", self.src)
        self.assertIn('loading="lazy"', self.src)

    def test_renders_placeholder_when_no_poster(self) -> None:
        """Sans poster, on doit afficher un placeholder (pas un <img> vide)."""
        # Le placeholder utilise un emoji 🎬 dans le code
        self.assertIn("🎬", self.src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
