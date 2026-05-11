"""Test E2E desktop — 16. Verification encodage (pas de mojibake).

Lancer : CINESORT_E2E=1 pytest tests/e2e_desktop/test_16_encodage.py -v

Verifie que tous les textes visibles sont correctement encodes en UTF-8,
sans caracteres de remplacement ni artefacts Windows-1252 → UTF-8.
"""

from __future__ import annotations

import os

import pytest

try:
    import allure
except ImportError:
    allure = None

from .pages.base_page import BasePage

# Patterns typiques de mojibake Windows-1252 → UTF-8
_MOJIBAKE_PATTERNS = [
    "\ufffd",  # Caractere de remplacement Unicode
    "Ã©",  # e accent aigu mal encode
    "Ã¨",  # e accent grave
    "Ã ",  # a accent grave
    "Ã®",  # i accent circonflex
    "Ã´",  # o accent circonflex
    "Ã§",  # c cedille
    "Ã¹",  # u accent grave
    "Ã¢",  # a accent circonflex
    "Ã«",  # e trema
]


@pytest.mark.skipif(os.environ.get("CINESORT_E2E") != "1", reason="CINESORT_E2E non defini")
class TestEncodage:
    """Verifie l'absence de problemes d'encodage dans toutes les vues."""

    def _get_all_visible_text(self, page) -> str:
        """Recupere tout le texte visible de la page."""
        return page.evaluate("() => document.body.innerText || ''")

    def test_accueil_no_mojibake(self, page):
        """L'accueil n'a pas de caracteres mal encodes."""
        base = BasePage(page)
        base.navigate_to("home")
        page.wait_for_timeout(500)
        text = self._get_all_visible_text(page)
        for pattern in _MOJIBAKE_PATTERNS:
            assert pattern not in text, f"Mojibake detecte dans l'accueil : '{pattern}'"
        BasePage(page).screenshot("16_01_accueil_encoding")

    def test_all_views_no_mojibake(self, page):
        """Aucune vue n'a de caracteres mal encodes."""
        base = BasePage(page)
        views = ["home", "library", "quality", "logs", "settings"]
        for view in views:
            base.navigate_to(view)
            page.wait_for_timeout(500)
            text = self._get_all_visible_text(page)
            for pattern in _MOJIBAKE_PATTERNS:
                assert pattern not in text, f"Mojibake detecte dans vue '{view}' : '{pattern}'"

    def test_french_labels_present(self, page):
        """Des labels francais accentues sont bien affiches."""
        base = BasePage(page)
        base.navigate_to("home")
        page.wait_for_timeout(500)
        html = page.evaluate("() => document.body.innerHTML || ''")
        # Verifier que les accents sont bien presents dans le HTML
        # (au moins dans la sidebar ou les titres)
        french_words = ["Bibliothèque", "Qualité", "Paramètres", "Journaux"]
        found = sum(1 for w in french_words if w in html)
        BasePage(page).screenshot("16_02_french_labels")
        assert found >= 2, f"Trop peu de labels francais trouves ({found}/4)"
