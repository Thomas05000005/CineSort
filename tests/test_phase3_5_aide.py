"""Tests Phase 3.5 : nouvelle vue Aide refondue (spec 12-aide.md).

Couvre 5 sections + recherche + cablage route /aide vers initAide.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_AIDE_JS = _ROOT / "web" / "dashboard" / "views" / "aide.js"
_APP_JS = _ROOT / "web" / "dashboard" / "app.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class FileExistsTests(unittest.TestCase):
    def test_aide_view_exists(self) -> None:
        self.assertTrue(_AIDE_JS.is_file(), f"manquant : {_AIDE_JS}")


class EsModuleApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _AIDE_JS.read_text(encoding="utf-8")

    def test_exports_init_aide(self) -> None:
        self.assertIn("export async function initAide(", self.js)

    def test_exports_unmount(self) -> None:
        self.assertIn("export function unmountAide(", self.js)


class FiveSectionsTests(unittest.TestCase):
    """Spec 12 §1 : 5 sections obligatoires."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _AIDE_JS.read_text(encoding="utf-8")

    def test_doc_section_present(self) -> None:
        self.assertIn("function _renderDocSection(", self.js)
        self.assertIn("Documentation", self.js)

    def test_shortcuts_section_present(self) -> None:
        self.assertIn("function _renderShortcutsSection(", self.js)
        self.assertIn("Raccourcis clavier", self.js)

    def test_diagnostic_section_present(self) -> None:
        self.assertIn("function _renderDiagnosticSection(", self.js)
        self.assertIn("Diagnostic", self.js)

    def test_logs_section_present(self) -> None:
        self.assertIn("function _renderLogsSection(", self.js)
        # Section appellee "Logs" (sans diacritique).
        self.assertIn(">📝 Logs<", self.js)

    def test_about_section_present(self) -> None:
        self.assertIn("function _renderAboutSection(", self.js)
        self.assertIn("À propos", self.js)


class DocTopicsTests(unittest.TestCase):
    """Spec 12 §1 : 8 topics initiaux dans la doc."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _AIDE_JS.read_text(encoding="utf-8")

    def test_topics_list_present(self) -> None:
        self.assertIn("_DOC_TOPICS", self.js)

    def test_key_topics_listed(self) -> None:
        for topic in (
            "Premiers pas",
            "Comment lancer un scan",
            "Comment résoudre des doublons",
            "Configurer OMDb",
            "Apply réel vs dry-run",
            "Undo",
            "Sécurité torrents",
        ):
            self.assertIn(topic, self.js, f"topic manquant : {topic}")


class ShortcutsTests(unittest.TestCase):
    """Spec 12 §1 : table des raccourcis alignee sur core/keyboard.js (Phase 2-C)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _AIDE_JS.read_text(encoding="utf-8")

    def test_critical_shortcuts_listed(self) -> None:
        # Ctrl+K, Ctrl+B, Ctrl+I, Ctrl+, Ctrl+S, Esc, ?, Alt+1..7.
        self.assertIn('["Ctrl", "K"]', self.js)
        self.assertIn('["Ctrl", "B"]', self.js)
        self.assertIn('["Ctrl", "I"]', self.js)
        self.assertIn('["Ctrl", ","]', self.js)
        self.assertIn('["Ctrl", "S"]', self.js)
        self.assertIn('["Esc"]', self.js)
        self.assertIn('["?"]', self.js)
        self.assertIn('["Alt", "1..7"]', self.js)


class DiagnosticEndpointsTests(unittest.TestCase):
    """Phase 5 : endpoint dedie runtime/get_diagnostic (PR #300)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _AIDE_JS.read_text(encoding="utf-8")

    def test_uses_runtime_get_diagnostic(self) -> None:
        self.assertIn('"runtime/get_diagnostic"', self.js)


class ActionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _AIDE_JS.read_text(encoding="utf-8")

    def test_copy_diagnostic_action(self) -> None:
        self.assertIn('data-aide-action="copy-diagnostic"', self.js)
        self.assertIn("function _copyToClipboard(", self.js)

    def test_open_logs_action(self) -> None:
        self.assertIn('data-aide-action="open-logs"', self.js)
        # Accepte `"open_logs_folder"` ou `"runtime/open_logs_folder"` (prefix REST).
        self.assertIn("open_logs_folder", self.js)

    def test_github_issues_link(self) -> None:
        self.assertIn("https://github.com/Thomas05000005/CineSort/issues/new", self.js)


class SearchInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _AIDE_JS.read_text(encoding="utf-8")

    def test_search_input_present(self) -> None:
        self.assertIn("data-aide-search", self.js)
        self.assertIn("Rechercher dans la doc", self.js)


class AppJsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _APP_JS.read_text(encoding="utf-8")

    def test_imports_init_aide(self) -> None:
        self.assertIn('from "./views/aide.js"', self.js)
        self.assertIn("initAide", self.js)
        self.assertIn("unmountAide", self.js)

    def test_route_aide_uses_init_aide(self) -> None:
        line_start = self.js.find('registerRoute("/aide"')
        self.assertNotEqual(line_start, -1)
        line_end = self.js.find("\n", line_start)
        snippet = self.js[line_start:line_end]
        self.assertIn("initAide", snippet)

    def test_legacy_help_route_kept_for_compat(self) -> None:
        # /help doit rester registre pour la retrocompat des bookmarks, mais
        # redirige desormais vers /aide (la vue legacy help.js a ete remplacee
        # par aide.js, refonte 2026-05).
        self.assertIn('registerRoute("/help"', self.js)
        # La route /help ne doit plus utiliser initHelpV4 (vue legacy retiree
        # apres refonte) : elle redirige vers /aide via _legacyRedirect.
        self.assertNotIn("initHelpV4", self.js)
        # Verifie la redirection vers /aide (helper _legacyRedirect ou litteral).
        line_start = self.js.find('registerRoute("/help"')
        self.assertNotEqual(line_start, -1)
        block_end = self.js.find("});", line_start)
        snippet = self.js[line_start:block_end]
        self.assertTrue(
            "#/aide" in snippet or '_legacyRedirect("help", "/aide")' in snippet,
            f"redirection /help -> /aide non detectee : {snippet}",
        )


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_root_class(self) -> None:
        self.assertIn(".aide-view", self.css)

    def test_section_class(self) -> None:
        self.assertIn(".aide-section", self.css)
        self.assertIn(".aide-section-title", self.css)

    def test_doc_classes(self) -> None:
        self.assertIn(".aide-doc-list", self.css)
        self.assertIn(".aide-doc-item", self.css)

    def test_shortcuts_table_class(self) -> None:
        self.assertIn(".aide-shortcuts-table", self.css)
        self.assertIn(".aide-shortcut-keys kbd", self.css)

    def test_diagnostic_classes(self) -> None:
        self.assertIn(".aide-diag-list", self.css)
        self.assertIn(".aide-diag-row", self.css)


if __name__ == "__main__":
    unittest.main()
