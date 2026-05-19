"""Tests Phase 2-C : raccourcis clavier du Shell 3 zones (spec 04 §5).

Couvre :
- Ctrl+B : toggle sidebar (collapsed/expanded)
- Ctrl+I : toggle inspecteur droit (right panel)
- Ctrl+, : aller a Parametres
- Alt+1..7 : navigation vers les 7 vues FR canoniques
- Imports corrects depuis sidebar-v5 et right-panel
- Mise a jour de la modale d'aide (raccourcis listes)
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_KEYBOARD_JS = _ROOT / "web" / "dashboard" / "core" / "keyboard.js"


class ImportsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _KEYBOARD_JS.read_text(encoding="utf-8")

    def test_imports_sidebar_toggle(self) -> None:
        self.assertIn("toggleCollapsed as toggleSidebar", self.js)
        self.assertIn('from "../components/sidebar-v5.js"', self.js)

    def test_imports_right_panel_state(self) -> None:
        self.assertIn("isExpanded as isRightPanelExpanded", self.js)
        self.assertIn("setExpanded as setRightPanelExpanded", self.js)
        self.assertIn('from "../components/right-panel.js"', self.js)


class FrenchRouteListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _KEYBOARD_JS.read_text(encoding="utf-8")

    def test_alt_navigation_targets_french_routes(self) -> None:
        # Spec 04 §2.3 : 7 entrees FR canoniques pour Alt+1..7.
        expected_routes = [
            "/accueil",
            "/traitement",
            "/bibliotheque",
            "/qualite",
            "/historique",
            "/parametres",
            "/aide",
        ]
        # Trouve la liste _ROUTES
        start = self.js.find("_ROUTES = [")
        end = self.js.find("];", start)
        self.assertNotEqual(start, -1, "constante _ROUTES manquante")
        block = self.js[start:end]
        for r in expected_routes:
            self.assertIn(f'"{r}"', block, f"route {r} manquante dans _ROUTES")

    def test_alt_range_is_1_to_7(self) -> None:
        # Phase 2-C : 7 routes (et plus 8 comme avant).
        self.assertIn('e.key >= "1" && e.key <= "7"', self.js)


class NewShortcutsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _KEYBOARD_JS.read_text(encoding="utf-8")

    def test_ctrl_b_toggles_sidebar(self) -> None:
        # On cherche le bloc Ctrl+B qui appelle toggleSidebar().
        ctrl_b_idx = self.js.find('e.key.toLowerCase() === "b"')
        self.assertNotEqual(ctrl_b_idx, -1, "raccourci Ctrl+B introuvable")
        snippet = self.js[ctrl_b_idx : ctrl_b_idx + 250]
        self.assertIn("toggleSidebar()", snippet)

    def test_ctrl_i_toggles_right_panel(self) -> None:
        ctrl_i_idx = self.js.find('e.key.toLowerCase() === "i"')
        self.assertNotEqual(ctrl_i_idx, -1, "raccourci Ctrl+I introuvable")
        snippet = self.js[ctrl_i_idx : ctrl_i_idx + 300]
        self.assertIn("setRightPanelExpanded(!isRightPanelExpanded())", snippet)

    def test_ctrl_comma_goes_to_parametres(self) -> None:
        ctrl_comma_idx = self.js.find('e.key === ","')
        self.assertNotEqual(ctrl_comma_idx, -1, "raccourci Ctrl+, introuvable")
        snippet = self.js[ctrl_comma_idx : ctrl_comma_idx + 200]
        self.assertIn('navigateTo("/parametres")', snippet)


class HelpModalTests(unittest.TestCase):
    """La modale d'aide (? / F1) doit refleter les nouveaux raccourcis."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _KEYBOARD_JS.read_text(encoding="utf-8")

    def test_help_modal_lists_ctrl_b(self) -> None:
        self.assertIn("<kbd>Ctrl</kbd>+<kbd>B</kbd>", self.js)
        self.assertIn("sidebar", self.js)

    def test_help_modal_lists_ctrl_i(self) -> None:
        self.assertIn("<kbd>Ctrl</kbd>+<kbd>I</kbd>", self.js)
        self.assertIn("inspecteur", self.js)

    def test_help_modal_lists_ctrl_comma(self) -> None:
        self.assertIn("<kbd>Ctrl</kbd>+<kbd>,</kbd>", self.js)
        self.assertIn("Parametres", self.js)

    def test_help_modal_links_to_french_help_route(self) -> None:
        # Le lien "Voir l'aide complete" doit pointer vers /aide (route FR canonique).
        self.assertIn('href="#/aide"', self.js)

    def test_help_modal_lists_alt_1_to_7(self) -> None:
        self.assertIn("<kbd>1</kbd>...<kbd>7</kbd>", self.js)


if __name__ == "__main__":
    unittest.main()
