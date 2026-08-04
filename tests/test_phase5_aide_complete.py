"""Tests Phase 5 : vue Aide complete cablee sur les 4 endpoints backend.

Cf docs/internal/design/refonte_2026_05_17/screens/12-aide.md.

Couvre :
    - get_diagnostic cable (runtime/get_diagnostic)
    - get_recent_logs cable sur bouton "Copier les 100 dernieres lignes"
    - Clic topic appelle get_doc (runtime/get_doc)
    - Recherche live appelle search_docs (runtime/search_docs)
    - Mini-markdown renderer + drawer present
    - Raccourci ↑/↓ ajoute dans la table
    - Template GitHub issue avec diagnostic pre-rempli
    - Facade runtime ajoutee a _FACADE_ATTR_NAMES (routage REST)
    - CSS drawer + search-results + markdown styles presents
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_AIDE_JS = _ROOT / "web" / "dashboard" / "views" / "aide.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"
_REST_SERVER = _ROOT / "cinesort" / "infra" / "rest_server.py"


# ---------------------------------------------------------------------------
# 1. get_diagnostic cable via endpoint dedie
# ---------------------------------------------------------------------------


class DiagnosticEndpointTests(unittest.TestCase):
    """Le frontend appelle runtime/get_diagnostic au lieu de l'agregation legacy."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _AIDE_JS.read_text(encoding="utf-8")

    def test_uses_runtime_get_diagnostic_endpoint(self) -> None:
        self.assertIn('"runtime/get_diagnostic"', self.js)

    def test_no_more_legacy_aggregation(self) -> None:
        # L'ancienne agregation Promise.all([server_info, settings, stats])
        # n'a plus de raison d'etre.
        self.assertNotIn("get_global_stats", self.js)
        self.assertNotIn('"get_server_info"', self.js)

    def test_fetch_diagnostic_function_present(self) -> None:
        self.assertIn("async function _fetchDiagnostic(", self.js)

    def test_copy_diagnostic_includes_15_fields(self) -> None:
        # _diagnosticToText doit lister les champs cles (cf docstring endpoint).
        for field in (
            "Build",
            "Plateforme",
            "DB schema",
            "ffprobe",
            "MediaInfo",
            "TMDb",
            "OMDb",
            "Jellyfin",
            "Plex",
            "Radarr",
            "Roots actifs",
            "Bibliothèque",
            "Dernier run",
            "Log",
            "Settings",
            "Timestamp",
        ):
            self.assertIn(field, self.js, f"champ diagnostic manquant : {field}")


# ---------------------------------------------------------------------------
# 2. get_recent_logs cable sur bouton "Copier 100 dernieres lignes"
# ---------------------------------------------------------------------------


class RecentLogsActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _AIDE_JS.read_text(encoding="utf-8")

    def test_uses_runtime_get_recent_logs(self) -> None:
        self.assertIn('"runtime/get_recent_logs"', self.js)

    def test_passes_limit_100(self) -> None:
        # Le frontend doit explicitement passer { limit: 100 }.
        self.assertIn("limit: 100", self.js)

    def test_copies_lines_joined(self) -> None:
        # Les lignes recuperees sont joinees par \n et copiees dans clipboard.
        self.assertIn("lines.join", self.js)
        self.assertIn("_copyToClipboard", self.js)

    def test_no_more_placeholder_message(self) -> None:
        # Ancien comportement : "Endpoint backend non encore disponible".
        self.assertNotIn("Endpoint backend non encore disponible", self.js)


# ---------------------------------------------------------------------------
# 3. Clic topic appelle get_doc
# ---------------------------------------------------------------------------


class GetDocActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _AIDE_JS.read_text(encoding="utf-8")

    def test_uses_runtime_get_doc(self) -> None:
        self.assertIn('"runtime/get_doc"', self.js)

    def test_open_doc_drawer_function(self) -> None:
        self.assertIn("async function _openDocDrawer(", self.js)

    def test_topics_have_doc_id(self) -> None:
        # Chaque _DOC_TOPICS doit avoir un doc_id pour appeler get_doc.
        self.assertIn("doc_id:", self.js)
        # user-guide est la cible principale.
        self.assertIn('doc_id: "user-guide"', self.js)

    def test_no_more_placeholder_drawer(self) -> None:
        # Ancien : "La doc complète arrive bientôt".
        self.assertNotIn("La doc complète arrive bientôt", self.js)


# ---------------------------------------------------------------------------
# 4. Recherche live cable + debounce + dropdown + highlight
# ---------------------------------------------------------------------------


class LiveSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _AIDE_JS.read_text(encoding="utf-8")

    def test_uses_runtime_search_docs(self) -> None:
        self.assertIn('"runtime/search_docs"', self.js)

    def test_search_function_present(self) -> None:
        self.assertIn("async function _doLiveSearch(", self.js)

    def test_debounce_300ms(self) -> None:
        # Implementation doit avoir un setTimeout 300 (debounce).
        self.assertIn("300", self.js)
        self.assertIn("setTimeout", self.js)

    def test_dropdown_results_container(self) -> None:
        self.assertIn("data-aide-search-results", self.js)
        self.assertIn("aide-search-result", self.js)

    def test_highlight_function_present(self) -> None:
        self.assertIn("function _highlightQuery(", self.js)
        self.assertIn("aide-search-highlight", self.js)


# ---------------------------------------------------------------------------
# 5. Raccourci fleches haut/bas
# ---------------------------------------------------------------------------


class ShortcutsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _AIDE_JS.read_text(encoding="utf-8")

    def test_arrow_keys_shortcut_present(self) -> None:
        # Ligne ↑/↓ ajoutee dans _SHORTCUTS pour spec 12 §1.
        self.assertIn('["↑", "↓"]', self.js)
        # Revue post-merge 2026-08-03 : le libelle disait « Navigation dans
        # listes (films, doublons, runs) » alors que SEULE la vue Doublons
        # implemente ArrowUp/ArrowDown. Le contenu du libelle est desormais
        # verifie au RUNTIME (rendu reel de _renderShortcutsSection) par
        # tests/test_revue_20260803_raccourcis_promesses.py ; ici on se contente
        # de garantir que la ligne existe toujours.
        self.assertIn("Navigation dans la liste", self.js)


# ---------------------------------------------------------------------------
# 6. Template GitHub issue avec diagnostic pre-rempli
# ---------------------------------------------------------------------------


class BugReportTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _AIDE_JS.read_text(encoding="utf-8")

    def test_open_issue_function_present(self) -> None:
        self.assertIn("_openIssueWithDiagnostic", self.js)

    def test_issue_url_includes_title_and_body(self) -> None:
        # Le template doit construire title= + body= encodes.
        self.assertIn("title=", self.js)
        self.assertIn("body=", self.js)
        self.assertIn("encodeURIComponent", self.js)

    def test_button_report_bug_present(self) -> None:
        self.assertIn('data-aide-action="report-bug"', self.js)


# ---------------------------------------------------------------------------
# 7. Mini-markdown renderer
# ---------------------------------------------------------------------------


class MarkdownRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _AIDE_JS.read_text(encoding="utf-8")

    def test_render_markdown_function_present(self) -> None:
        self.assertIn("function _renderMarkdown(", self.js)

    def test_supports_headings(self) -> None:
        # Le JS genere les classes dynamiquement via aide-markdown-h${level}.
        # On valide l'expression template + la regex de matching des #..####.
        self.assertIn("aide-markdown-h${level}", self.js)
        self.assertIn("#{1,4}", self.js)

    def test_supports_lists(self) -> None:
        self.assertIn("aide-markdown-list", self.js)

    def test_supports_code_blocks(self) -> None:
        self.assertIn("aide-markdown-code-block", self.js)
        self.assertIn("aide-markdown-code-inline", self.js)

    def test_supports_links(self) -> None:
        self.assertIn("aide-markdown-link", self.js)

    def test_supports_blockquote(self) -> None:
        self.assertIn("aide-markdown-quote", self.js)

    def test_supports_hr(self) -> None:
        self.assertIn("aide-markdown-hr", self.js)

    def test_escapes_html_for_xss(self) -> None:
        # _renderInline applique escapeHtml AVANT toute transformation.
        self.assertIn("escapeHtml", self.js)
        # Validation des liens : seuls http(s)/mailto/# sont autorises.
        self.assertIn("https?:|mailto:|#", self.js)


# ---------------------------------------------------------------------------
# 8. Drawer markdown
# ---------------------------------------------------------------------------


class DrawerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _AIDE_JS.read_text(encoding="utf-8")

    def test_drawer_open_close_functions(self) -> None:
        self.assertIn("_openDocDrawer", self.js)
        self.assertIn("_closeDrawer", self.js)

    def test_drawer_has_close_button_and_backdrop(self) -> None:
        self.assertIn("data-aide-drawer-close", self.js)
        self.assertIn("aide-doc-drawer-backdrop", self.js)

    def test_drawer_supports_expand_to_route(self) -> None:
        # "Ouvrir en grand" -> route /aide/doc/:topic_id.
        self.assertIn("drawer-expand", self.js)
        self.assertIn("/aide/doc/", self.js)

    def test_drawer_closes_on_escape(self) -> None:
        # Esc key fermeture du drawer.
        self.assertIn('"Escape"', self.js)


# ---------------------------------------------------------------------------
# 9. Facade runtime exposee via REST (routage /api/runtime/get_diagnostic)
# ---------------------------------------------------------------------------


class RestServerRoutingTests(unittest.TestCase):
    """rest_server doit lister 'runtime' dans _FACADE_ATTR_NAMES pour exposer
    /api/runtime/get_diagnostic via le dispatcher Pass 2.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _REST_SERVER.read_text(encoding="utf-8")

    def test_runtime_in_facade_attr_names(self) -> None:
        # Pattern : _FACADE_ATTR_NAMES: tuple = (... "runtime")
        self.assertIn("_FACADE_ATTR_NAMES", self.src)
        # Cherche la ligne et verifie qu'elle contient "runtime".
        for line in self.src.splitlines():
            if line.lstrip().startswith("_FACADE_ATTR_NAMES"):
                self.assertIn('"runtime"', line, f"_FACADE_ATTR_NAMES doit inclure 'runtime' : {line}")
                return
        self.fail("_FACADE_ATTR_NAMES not found in rest_server.py")


# ---------------------------------------------------------------------------
# 10. CSS : nouveaux styles drawer / search-results / markdown
# ---------------------------------------------------------------------------


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_drawer_classes_present(self) -> None:
        for cls_name in (
            ".aide-doc-drawer",
            ".aide-doc-drawer-backdrop",
            ".aide-doc-drawer-header",
            ".aide-doc-drawer-title",
            ".aide-doc-content",
        ):
            self.assertIn(cls_name, self.css, f"classe manquante : {cls_name}")

    def test_search_results_classes_present(self) -> None:
        for cls_name in (
            ".aide-search-results",
            ".aide-search-result",
            ".aide-search-highlight",
        ):
            self.assertIn(cls_name, self.css, f"classe manquante : {cls_name}")

    def test_markdown_classes_present(self) -> None:
        for cls_name in (
            ".aide-markdown-h1",
            ".aide-markdown-h2",
            ".aide-markdown-p",
            ".aide-markdown-list",
            ".aide-markdown-code-block",
            ".aide-markdown-code-inline",
            ".aide-markdown-link",
            ".aide-markdown-quote",
            ".aide-markdown-hr",
        ):
            self.assertIn(cls_name, self.css, f"classe manquante : {cls_name}")

    def test_css_balance(self) -> None:
        opens = self.css.count("{")
        closes = self.css.count("}")
        self.assertEqual(opens, closes, f"CSS desequilibre : {opens} '{{' vs {closes} '}}'")


# ---------------------------------------------------------------------------
# 11. Integration : RuntimeFacade expose les 4 methodes via getattr
# ---------------------------------------------------------------------------


class RuntimeFacadeIntegrationTests(unittest.TestCase):
    """La facade runtime expose bien les 4 methodes utilisees par aide.js."""

    def test_facade_methods_callable(self) -> None:
        from cinesort.ui.api.cinesort_api import CineSortApi

        api = CineSortApi()
        facade = api.runtime
        for method_name in ("get_diagnostic", "get_recent_logs", "get_doc", "search_docs"):
            self.assertTrue(hasattr(facade, method_name), f"facade.runtime.{method_name} manquant")
            self.assertTrue(callable(getattr(facade, method_name)))

    def test_facade_discovered_by_rest_dispatcher(self) -> None:
        from cinesort.infra.rest_server import _FACADE_ATTR_NAMES, _get_api_methods
        from cinesort.ui.api.cinesort_api import CineSortApi

        self.assertIn("runtime", _FACADE_ATTR_NAMES)
        api = CineSortApi()
        methods = _get_api_methods(api)
        for method_name in ("get_diagnostic", "get_recent_logs", "get_doc", "search_docs"):
            self.assertIn(
                f"runtime/{method_name}",
                methods,
                f"endpoint /api/runtime/{method_name} non expose par le dispatcher",
            )


if __name__ == "__main__":
    unittest.main()
