"""Tests Phase 3.4 : Historique onglets inspecteur 4 vues (spec 09 §3)."""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_HISTORIQUE_JS = _ROOT / "web" / "dashboard" / "views" / "historique.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class InspectorTabsTests(unittest.TestCase):
    """Spec 09 §3 : 4 onglets inspecteur (Films / Apply / Doublons / Log)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_inspector_tabs_defined(self) -> None:
        self.assertIn("_INSPECTOR_TABS", self.js)
        for tab in ('"films"', '"apply"', '"doublons"', '"log"'):
            self.assertIn(tab, self.js)

    def test_renders_tab_content_function(self) -> None:
        self.assertIn("_renderInspectorTabContent", self.js)

    def test_tabs_have_handlers(self) -> None:
        self.assertIn("data-historique-inspector-tab", self.js)

    def test_films_tab_links_to_bibliotheque(self) -> None:
        self.assertIn("#/bibliotheque?run_id=", self.js)

    def test_doublons_tab_links_to_doublons(self) -> None:
        self.assertIn("#/doublons", self.js)

    def test_log_tab_has_viewer(self) -> None:
        # Phase 5 : tab Log remplace par viewer monospace + bouton recharger.
        # L'ancien lien #/aide n'est plus pertinent (logs lus directement dans la vue).
        self.assertIn("historique-log-viewer", self.js)


class DangerActionsTests(unittest.TestCase):
    """Actions dangereuses : confirmation modale (cf feedback-cinesort-actions-dangereuses)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")

    def test_undo_apply_confirms(self) -> None:
        # P0 #233 : window.confirm() remplace par dangerConfirmModal() (modale dediee
        # actions dangereuses cf feedback-cinesort-actions-dangereuses).
        self.assertIn("Annuler l'apply", self.js)
        self.assertIn("dangerConfirmModal", self.js)

    def test_delete_run_confirms(self) -> None:
        self.assertIn("Supprimer le run", self.js)
        # P0 #233 : assertion explicite que la suppression utilise dangerConfirmModal.
        self.assertIn("dangerConfirmModal", self.js)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_classes(self) -> None:
        for cls in (
            ".historique-inspector-tabs",
            ".historique-inspector-tab",
            ".historique-inspector-tab.is-active",
            ".historique-inspector-tab-content",
            ".historique-tab-stat",
        ):
            self.assertIn(cls, self.css)


if __name__ == "__main__":
    unittest.main()
