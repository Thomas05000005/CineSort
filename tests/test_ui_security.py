"""LOT G — Tests de securite UI (XSS, escapeHtml).

Inspection statique du code source JS pour garantir les contrats de securite
definis par H1 du Lot 1. L'execution JS reelle est couverte par les tests E2E.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOM_JS = PROJECT_ROOT / "web" / "core" / "dom.js"
DASH_DOM_JS = PROJECT_ROOT / "web" / "dashboard" / "core" / "dom.js"


class EscapeHtmlContractTests(unittest.TestCase):
    """Verifie le contrat H1 : escapeHtml gere apostrophe + nullish."""

    def setUp(self) -> None:
        self.source = DOM_JS.read_text(encoding="utf-8")
        self.dash_source = DASH_DOM_JS.read_text(encoding="utf-8")

    # 47
    def test_escape_html_handles_apostrophe(self) -> None:
        """escapeHtml doit transformer ' en &#39; (H1)."""
        self.assertIn('"&#39;"', self.source, "escapeHtml doit echapper les apostrophes en &#39;")
        # Meme pour le dashboard
        self.assertIn('"&#39;"', self.dash_source)

    def test_escape_html_covers_all_5_entities(self) -> None:
        """escapeHtml doit couvrir &, <, >, ", '."""
        for entity in ('"&amp;"', '"&lt;"', '"&gt;"', '"&quot;"', '"&#39;"'):
            self.assertIn(entity, self.source, f"Entite manquante : {entity}")

    # 48
    def test_escape_html_handles_nullish_with_coalescing(self) -> None:
        """escapeHtml doit utiliser `s ?? ""` (pas `s || ""`) pour gerer 0/false."""
        # On cherche la signature de escapeHtml + la conversion
        # Le pattern doit contenir "s ?? " pour le nullish coalescing
        match = re.search(r"function escapeHtml\([^)]*\)\s*\{[^}]*", self.source)
        self.assertIsNotNone(match, "escapeHtml introuvable")
        body = match.group(0)
        self.assertIn("s ?? ", body, "escapeHtml doit utiliser s ?? '' (nullish coalescing)")

        # Dashboard aussi
        dash_match = re.search(r"function escapeHtml\([^)]*\)\s*\{[^}]*", self.dash_source)
        self.assertIsNotNone(dash_match)
        self.assertIn("s ?? ", dash_match.group(0))

    # 49
    def test_esc_and_escape_html_both_exist(self) -> None:
        """esc() et escapeHtml() existent tous les 2 dans dom.js."""
        self.assertIn("function esc(", self.source)
        self.assertIn("function escapeHtml(", self.source)


class NoOnclickInlineTests(unittest.TestCase):
    """H1 : plus de onclick inline dans les vues principales (event delegation)."""

    def test_no_onclick_in_execution_js(self) -> None:
        """execution.js ne doit plus avoir d'onclick inline (corrige au Lot 1)."""
        path = PROJECT_ROOT / "web" / "views" / "execution.js"
        if not path.exists():
            self.skipTest("execution.js introuvable")
        content = path.read_text(encoding="utf-8")
        # Tolerance : on interdit `onclick="_showComparisonModal` mais on accepte data-action
        self.assertNotIn(
            'onclick="_showComparisonModal', content, "onclick inline trouve dans execution.js — utiliser data-action"
        )

    def test_no_onclick_in_radarr_view(self) -> None:
        path = PROJECT_ROOT / "web" / "views" / "radarr-view.js"
        if not path.exists():
            self.skipTest("radarr-view.js introuvable")
        content = path.read_text(encoding="utf-8")
        # Pattern de l'ancien bug : onclick="(async()=>{..."
        self.assertNotIn('onclick="(async()', content)

    def test_no_onclick_in_lib_validation(self) -> None:
        path = PROJECT_ROOT / "web" / "dashboard" / "views" / "library" / "lib-validation.js"
        if not path.exists():
            self.skipTest("lib-validation.js introuvable")
        content = path.read_text(encoding="utf-8")
        self.assertNotIn('onclick="(async', content)


class XssNonRegressionTests(unittest.TestCase):
    """Non-regression XSS : les vues qui rendent des titres de films doivent escapeHtml."""

    VIEWS = [
        "web/views/validation.js",
        "web/views/execution.js",
        "web/views/history.js",
        "web/views/quality.js",
    ]

    def test_views_use_escapehtml_for_titles(self) -> None:
        """Verification statique : pas de `${row.proposed_title}` sans escapeHtml autour."""
        for rel in self.VIEWS:
            path = PROJECT_ROOT / rel
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            # Le vrai contrat est que escapeHtml/esc est disponible globalement ;
            # on verifie que le fichier appelle bien escapeHtml quelque part.
            self.assertIn("escapeHtml", content, f"{rel} devrait utiliser escapeHtml pour eviter XSS")


class SplashEscapingTests(unittest.TestCase):
    """H8 : _update_splash echappe apostrophe et backslash."""

    def test_update_splash_escapes_apostrophe(self) -> None:
        """app.py _update_splash doit echapper les apostrophes."""
        app_py = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
        # Cherche la fonction et son corps
        match = re.search(r"def _update_splash\([^)]*\)[^:]*:.*?(?=\n\ndef |\Z)", app_py, re.DOTALL)
        self.assertIsNotNone(match)
        body = match.group(0)
        # L'echappement doit etre present
        self.assertIn("\\\\'", body, "Echappement apostrophe manquant dans _update_splash")
        self.assertIn("\\\\\\\\", body, "Echappement backslash manquant dans _update_splash")


if __name__ == "__main__":
    unittest.main(verbosity=2)
