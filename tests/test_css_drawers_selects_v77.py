"""GATE AUDIT 2026-06-14 (R7-9, complement R6-E) — drawers opaques + selects sombres.

.qualite-drawer et .v5-top-bar-theme-menu utilisaient --surface-1 (~3.5%) ->
transparents. .v5-select/.parametres-select/.input n'avaient pas color-scheme:dark
-> popup natif blanc sur Windows. R6-E n'avait couvert que .v5-input/.modal/.drawer biblio.
"""
from __future__ import annotations
import re, unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_COMP = _ROOT / "web" / "shared" / "components.css"
_STYLES = _ROOT / "web" / "dashboard" / "styles.css"


def _rule(css, selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    return m.group(1) if m else ""


class CssDrawersSelectsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comp = _COMP.read_text(encoding="utf-8")
        cls.styles = _STYLES.read_text(encoding="utf-8")

    def test_qualite_drawer_opaque(self):
        self.assertIn("background: var(--bg-raised)", _rule(self.comp, ".qualite-drawer "))

    def test_theme_menu_opaque(self):
        self.assertIn("background: var(--bg-raised)", _rule(self.comp, ".v5-top-bar-theme-menu"))

    def test_selects_color_scheme(self):
        self.assertIn("color-scheme: dark", _rule(self.comp, ".v5-select"))
        # parametres-select (rule groupee) + .input
        self.assertIn("color-scheme: dark", self.comp[self.comp.find(".parametres-select"):self.comp.find(".parametres-select")+400])
        self.assertIn("color-scheme: dark", _rule(self.styles, ".input"))


if __name__ == "__main__":
    unittest.main()
