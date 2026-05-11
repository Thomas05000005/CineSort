"""V3-08 — Decouvrabilite des raccourcis clavier.

Verifications structurelles (sans navigateur) que la decoration kbd, la vue
Aide enrichie, le FAB et la CSS associee sont bien en place. Sans navigateur
on ne valide pas le rendu visuel mais ces structural tests detectent les
regressions de cablage (composant absent, section retiree, FAB perdu).
"""

from __future__ import annotations

import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
TOOLTIP = REPO / "web" / "dashboard" / "components" / "shortcut-tooltip.js"
HELP_VIEW = REPO / "web" / "dashboard" / "views" / "help.js"
APP_JS = REPO / "web" / "dashboard" / "app.js"
CSS = REPO / "web" / "dashboard" / "styles.css"


@unittest.skip("V5C-01: dashboard/views/help.js supprime — vue Aide portee en v5 (couvert par test_help_v5_features et test_help_v5_ported)")
class ShortcutsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tooltip = TOOLTIP.read_text(encoding="utf-8")
        self.help = HELP_VIEW.read_text(encoding="utf-8")
        self.app = APP_JS.read_text(encoding="utf-8")
        self.css = CSS.read_text(encoding="utf-8")

    # --- Composant ---------------------------------------------------

    def test_tooltip_module_exists(self) -> None:
        self.assertTrue(TOOLTIP.is_file(), f"Composant manquant : {TOOLTIP}")

    def test_kbd_hint_function_exported(self) -> None:
        self.assertIn("export function kbdHint", self.tooltip)
        self.assertIn("export function decorateWithKbd", self.tooltip)
        self.assertIn("export function decorateMainButtons", self.tooltip)

    def test_tooltip_uses_escape_html(self) -> None:
        """Defense XSS : le composant doit echapper la chaine fournie."""
        self.assertIn("escapeHtml", self.tooltip)

    def test_tooltip_idempotent(self) -> None:
        """decorateWithKbd ne doit pas re-injecter si deja present."""
        self.assertIn(".kbd-hint", self.tooltip)

    # --- Cablage app.js ---------------------------------------------

    def test_app_imports_decorator(self) -> None:
        self.assertIn("shortcut-tooltip.js", self.app)
        self.assertIn("decorateMainButtons", self.app)

    def test_app_creates_help_fab(self) -> None:
        # V5B-01 : le FAB est monte par top-bar-v5.mountHelpFab() (classe v5-help-fab).
        self.assertIn("mountHelpFab", self.app)
        top_bar = (REPO / "web" / "dashboard" / "components" / "top-bar-v5.js").read_text(encoding="utf-8")
        self.assertIn("export function mountHelpFab", top_bar)
        self.assertIn("v5-help-fab", top_bar)

    # --- Vue Aide enrichie ------------------------------------------

    def test_help_has_shortcuts_section(self) -> None:
        self.assertIn("Raccourcis clavier", self.help)
        self.assertIn("helpShortcutsSection", self.help)

    def test_help_lists_min_15_shortcuts(self) -> None:
        # Le rendu est dynamique (template literal unique) ; on compte plutot
        # les entrees du catalogue SHORTCUTS via leur cle "keys:".
        import re

        keys_count = len(re.findall(r"\bkeys:\s*\"", self.help))
        self.assertGreaterEqual(
            keys_count,
            15,
            f"Catalogue SHORTCUTS trop maigre : {keys_count} entrees",
        )

    def test_help_three_categories(self) -> None:
        for cat in ("Navigation", "Actions globales", "Validation"):
            self.assertIn(cat, self.help, f"Categorie manquante : {cat}")

    # --- CSS ---------------------------------------------------------

    def test_css_kbd_hint_styled(self) -> None:
        self.assertIn(".kbd-hint", self.css)

    def test_css_kbd_global_rule(self) -> None:
        # Une regle "kbd {" globale doit exister (heritage du theme).
        self.assertRegex(self.css, r"(^|\s)kbd\s*\{")

    def test_css_help_fab_present(self) -> None:
        self.assertIn(".help-fab", self.css)

    def test_css_reduced_motion_guard(self) -> None:
        # Le FAB respecte prefers-reduced-motion.
        self.assertIn("prefers-reduced-motion", self.css)


if __name__ == "__main__":
    unittest.main()
