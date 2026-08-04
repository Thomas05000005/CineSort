"""Tests Phase 3.4 : nouvelle vue Historique (spec 09-historique.md).

Couvre : timeline groupee par jour + filtres + toggle Timeline/Tableau +
inspecteur droit + actions placeholder.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_HISTORIQUE_JS = _ROOT / "web" / "dashboard" / "views" / "historique.js"
_APP_JS = _ROOT / "web" / "dashboard" / "app.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class FileExistsTests(unittest.TestCase):
    def test_view_exists(self) -> None:
        self.assertTrue(_HISTORIQUE_JS.is_file(), f"manquant : {_HISTORIQUE_JS}")


class EsModuleApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_exports_init(self) -> None:
        self.assertIn("export async function initHistorique(", self.js)

    def test_exports_unmount(self) -> None:
        self.assertIn("export function unmountHistorique(", self.js)


class FiltersTests(unittest.TestCase):
    """Spec 09 §2 : 4 filtres (statut, période, type, recherche)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_status_filter(self) -> None:
        self.assertIn('data-historique-filter="status"', self.js)

    def test_period_filter(self) -> None:
        self.assertIn('data-historique-filter="period"', self.js)
        for period in ("today", "7d", "30d", "90d", "all"):
            self.assertIn(f'value="{period}"', self.js, f"période {period} manquante")

    def test_type_filter(self) -> None:
        self.assertIn('data-historique-filter="type"', self.js)
        for typ in ("plan", "apply"):
            self.assertIn(f'value="{typ}"', self.js, f"type {typ} manquant")

    def test_search_input(self) -> None:
        self.assertIn("data-historique-search", self.js)


class TimelineGroupingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_group_by_day_function(self) -> None:
        self.assertIn("function _groupByDay(runs)", self.js)

    def test_day_labels(self) -> None:
        # Aujourd'hui, Hier, Il y a N jours puis "5 mai" / similaire.
        self.assertIn("Aujourd'hui", self.js)
        self.assertIn("Hier", self.js)
        self.assertIn("Il y a", self.js)

    def test_renders_timeline_function(self) -> None:
        self.assertIn("function _renderTimeline(runs", self.js)


class TableViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_table_view_toggle(self) -> None:
        self.assertIn('data-historique-view="timeline"', self.js)
        self.assertIn('data-historique-view="table"', self.js)

    def test_render_table_function(self) -> None:
        self.assertIn("function _renderTable(runs", self.js)

    def test_view_mode_persisted(self) -> None:
        self.assertIn("cinesort.historique.view", self.js)


class StatusDerivationTests(unittest.TestCase):
    """Reutilise la convention Accueil (Phase 3.1) : ERROR / PARTIAL / DONE / APPLIED."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_derive_status_function(self) -> None:
        self.assertIn("function _deriveStatus(run)", self.js)

    def test_status_classes(self) -> None:
        # Revue post-merge 2026-08-03 : ce test cherchait aussi `is-pending`,
        # classe qui n'a JAMAIS ete declaree dans web/shared/components.css — le
        # statut AWAITING_VALIDATION s'affichait donc sans couleur, et
        # l'assertion restait verte parce qu'elle ne regardait que le texte
        # source. On verifie desormais que chaque classe citee par le JS existe
        # bien cote CSS. Le mapping statut -> classe est teste au runtime dans
        # tests/test_revue_20260803_historique_statuts.py.
        css = _COMPONENTS_CSS.read_text(encoding="utf-8")
        for cls in ("is-error", "is-partial", "is-done", "is-applied", "is-cancelled"):
            self.assertIn(cls, self.js, f"classe statut {cls} manquante")
            self.assertIn(
                f".historique-run-status.{cls}",
                css,
                f"classe statut {cls} utilisee par le JS mais absente du CSS",
            )


class InspectorTests(unittest.TestCase):
    """Spec 09 §3 : inspecteur droit avec details du run + onglets + actions."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_imports_right_panel(self) -> None:
        self.assertIn('from "../components/right-panel.js"', self.js)
        self.assertIn("rightPanel.setSections", self.js)

    def test_build_inspector_sections_function(self) -> None:
        self.assertIn("function _buildInspectorSections(", self.js)

    def test_inspector_actions(self) -> None:
        # Spec §4 : 4 actions standard.
        for action in ("view-report", "resume", "undo-apply", "delete-run"):
            self.assertIn(f'data-historique-action="{action}"', self.js, f"action {action} manquante")


class AppJsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _APP_JS.read_text(encoding="utf-8")

    def test_imports_init(self) -> None:
        self.assertIn('from "./views/historique.js"', self.js)
        self.assertIn("initHistorique", self.js)
        self.assertIn("unmountHistorique", self.js)

    def test_route_uses_init_historique(self) -> None:
        line_start = self.js.find('registerRoute("/historique"')
        self.assertNotEqual(line_start, -1)
        line_end = self.js.find("\n", line_start)
        snippet = self.js[line_start:line_end]
        self.assertIn("initHistorique", snippet)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_root_class(self) -> None:
        self.assertIn(".historique-view", self.css)

    def test_day_label_class(self) -> None:
        self.assertIn(".historique-day-label", self.css)

    def test_run_row_class(self) -> None:
        self.assertIn(".historique-run", self.css)
        self.assertIn(".historique-run.is-selected", self.css)

    def test_status_severity_classes(self) -> None:
        for cls in ("is-done", "is-applied", "is-partial", "is-error", "is-cancelled"):
            self.assertIn(f".historique-run-status.{cls}", self.css)

    def test_inspector_classes(self) -> None:
        self.assertIn(".historique-inspector-dl", self.css)
        self.assertIn(".historique-inspector-actions", self.css)


if __name__ == "__main__":
    unittest.main()
