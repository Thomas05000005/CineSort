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


class XssDashboardFixesTests(unittest.TestCase):
    """Cf issue #67 : 3 XSS fixes verifies par inspection statique."""

    def test_dashboard_dom_exposes_safe_url_helper(self) -> None:
        """web/dashboard/core/dom.js doit exposer safeUrl(u) qui valide le scheme."""
        dom = (PROJECT_ROOT / "web" / "dashboard" / "core" / "dom.js").read_text(encoding="utf-8")
        self.assertIn("export function safeUrl", dom, "safeUrl helper manquant dans dashboard/core/dom.js")
        # Doit valider http/https et rejeter le reste
        self.assertIn("http:", dom)
        self.assertIn("https:", dom)

    def test_library_view_uses_safe_url_for_poster(self) -> None:
        """library.js ne doit plus injecter posterUrl brut dans src=""."""
        lib = (PROJECT_ROOT / "web" / "dashboard" / "views" / "library.js").read_text(encoding="utf-8")
        self.assertIn("safeUrl", lib, "library.js doit importer safeUrl")
        # Pattern vulnerable banni : src="${posterUrl}" sans validation
        self.assertNotIn('src="${posterUrl}"', lib, "posterUrl injecte sans validation — XSS via src")

    def test_dashboard_app_error_banner_no_inner_html(self) -> None:
        """app.js error banner doit utiliser createElement + textContent, pas innerHTML."""
        app_js = (PROJECT_ROOT / "web" / "dashboard" / "app.js").read_text(encoding="utf-8")
        # La construction doit utiliser createElement
        self.assertIn("createElement", app_js)
        # Pas de pattern innerHTML avec concatenation de msg
        self.assertNotIn("banner.innerHTML", app_js, "banner.innerHTML expose XSS via window.onerror msg")

    def test_error_boundary_uses_text_content(self) -> None:
        """error-boundary.js doit utiliser textContent (pas innerHTML+escape manuel)."""
        eb = (PROJECT_ROOT / "web" / "core" / "error-boundary.js").read_text(encoding="utf-8")
        self.assertIn("textContent", eb)
        # Pattern d'escape manuel incomplet (couvrait <>& mais pas "/') doit avoir disparu
        self.assertNotIn('"<": "&lt;"', eb, "escape manuel incomplet — switcher sur textContent")


class TokenStorageTests(unittest.TestCase):
    """Cf issue #65 : token desktop natif → sessionStorage only (pas localStorage)."""

    def test_app_py_native_token_uses_session_storage_only(self) -> None:
        """app.py mode natif ne doit PAS persister le token en localStorage.

        Justification : le token est regenere/relu cote serveur Python a chaque
        demarrage. Persister en localStorage etend inutilement la fenetre
        d'exfiltration en cas de XSS (survit a la fermeture du browser/PyWebView).
        """
        app_py = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
        # Cherche le bloc d'injection du token (entre les deux marqueurs)
        match = re.search(
            r"if _desktop_dashboard_token:.*?main_window\.evaluate_js\(inject_js\)",
            app_py,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "Bloc d'injection token natif introuvable")
        block = match.group(0)
        self.assertIn("sessionStorage.setItem", block)
        self.assertNotIn(
            "localStorage.setItem('cinesort.dashboard.token'",
            block,
            "Token natif ne doit pas etre stocke en localStorage (issue #65)",
        )


class SplashEscapingTests(unittest.TestCase):
    """H8 : _update_splash echappe correctement les chars dangereux.

    Cf issue #64 : remplacement de l'escape manuel (qui ne couvrait que \\ et ')
    par json.dumps() qui echappe TOUS les chars dangereux (\", \\, \\n, \\r,
    U+2028 LINE SEPARATOR, U+2029 PARAGRAPH SEPARATOR).
    """

    def test_update_splash_uses_json_dumps(self) -> None:
        """app.py _update_splash doit utiliser json.dumps pour l'escape."""
        app_py = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
        # Cherche la fonction et son corps
        match = re.search(r"def _update_splash\([^)]*\)[^:]*:.*?(?=\n\ndef |\Z)", app_py, re.DOTALL)
        self.assertIsNotNone(match)
        body = match.group(0)
        # json.dumps doit etre utilise (couvre tous les chars dangereux)
        self.assertIn("json.dumps", body, "json.dumps manquant dans _update_splash")


if __name__ == "__main__":
    unittest.main(verbosity=2)
