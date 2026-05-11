"""H-8/H-9 audit QA 20260429 — tests statiques du polish UI.

Tests qui valident le HTML/CSS/JS sans lancer Playwright (rapide,
CI-friendly, deterministe). Couvrent :

- H-8 : tous les textes UI sont en francais (pas d'anglais residuel
  dans les boutons critiques).
- H-9 : pas d'onclick inline sur #btnQualitySimulate (race condition).
- M-3 : la classe .btn--loading existe dans styles.css.

Ces tests garantissent qu'une regression future re-introduit pas
ces problemes (test_no_personal_strings_in_repo style).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_INDEX_HTML = _PROJECT_ROOT / "web" / "index.html"
_STYLES_CSS = _PROJECT_ROOT / "web" / "styles.css"
_QUALITY_SIM_JS = _PROJECT_ROOT / "web" / "views" / "quality-simulator.js"


class UiPolishH8H9Tests(unittest.TestCase):
    """Tests statiques sur web/index.html pour les fixes H-8 + H-9."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = _INDEX_HTML.read_text(encoding="utf-8")
        cls.styles_css = _STYLES_CSS.read_text(encoding="utf-8")

    def test_h8_undo_preview_button_is_french(self) -> None:
        """H-8 : le bouton #btnUndoV5Preview affiche du francais."""
        # Pattern : <button id="btnUndoV5Preview">...TEXTE...</button>
        match = re.search(
            r'<button[^>]*id=["\']btnUndoV5Preview["\'][^>]*>([^<]+)</button>',
            self.html,
        )
        self.assertIsNotNone(match, "Bouton #btnUndoV5Preview introuvable dans index.html")
        text = match.group(1).strip()
        # Doit contenir "Aperçu" (FR), pas "Preview" (EN)
        self.assertIn("Aper", text, f"Texte attendu en francais ('Aperçu...'), trouve : '{text}'")
        self.assertNotIn("Preview", text, f"Texte EN 'Preview' detecte : '{text}'")

    def test_h8_undo_execute_button_has_accent(self) -> None:
        """H-8 : le bouton 'Annuler la sélection' a bien l'accent restaure."""
        match = re.search(
            r'<button[^>]*id=["\']btnUndoV5Execute["\'][^>]*>([^<]+)</button>',
            self.html,
        )
        self.assertIsNotNone(match, "Bouton #btnUndoV5Execute introuvable")
        text = match.group(1).strip()
        # Doit avoir l'accent é (sélection, pas selection)
        self.assertIn("sélection", text, f"Accent é attendu sur 'sélection', trouve : '{text}'")

    def test_h9_no_inline_onclick_on_btn_quality_simulate(self) -> None:
        """H-9 : #btnQualitySimulate ne doit plus avoir d'onclick inline
        (race condition au boot si openQualitySimulator pas encore charge).
        """
        match = re.search(
            r'<button[^>]*id=["\']btnQualitySimulate["\'][^>]*>',
            self.html,
        )
        self.assertIsNotNone(match, "Bouton #btnQualitySimulate introuvable")
        button_tag = match.group(0)
        self.assertNotIn(
            "onclick",
            button_tag.lower(),
            f"onclick inline encore present sur #btnQualitySimulate : {button_tag}",
        )

    def test_h9_quality_simulator_js_wires_button_listener(self) -> None:
        """H-9 : quality-simulator.js doit attacher un event listener au boot
        pour remplacer l'ancien onclick inline supprime.
        """
        js_content = _QUALITY_SIM_JS.read_text(encoding="utf-8")
        # Recherche d'un addEventListener cible #btnQualitySimulate
        self.assertIn(
            "btnQualitySimulate",
            js_content,
            "quality-simulator.js ne reference pas #btnQualitySimulate",
        )
        self.assertIn(
            "addEventListener",
            js_content,
            "Aucun addEventListener dans quality-simulator.js (H-9 listener manquant)",
        )

    def test_m3_btn_loading_class_exists_in_styles(self) -> None:
        """M-3 : la classe .btn--loading doit etre definie dans styles.css
        (infrastructure spinner pour les boutons en attente API).
        """
        self.assertIn(
            ".btn--loading",
            self.styles_css,
            "Classe .btn--loading manquante dans styles.css (M-3 infrastructure)",
        )
        # Verifier qu'elle a bien un keyframes anime
        self.assertIn(
            "@keyframes btnSpin",
            self.styles_css,
            "Animation @keyframes btnSpin manquante (M-3)",
        )

    def test_m3_btn_loading_respects_reduced_motion(self) -> None:
        """M-3 : la classe respecte prefers-reduced-motion (accessibilite)."""
        # Recherche le bloc media query reduced motion ET dans la suite
        # une override de .btn--loading
        # Approche simple : les deux substrings sont presents quelque part
        self.assertIn("prefers-reduced-motion", self.styles_css)
        self.assertIn("@keyframes btnPulse", self.styles_css)


if __name__ == "__main__":
    unittest.main()
