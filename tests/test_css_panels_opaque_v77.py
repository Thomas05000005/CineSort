"""GATE AUDIT 2026-06-14 (R6-E) — les panneaux flottants ont un vrai fond.

Trois bugs "sans fond" signales :
- le tiroir de filtre avance (.bibliotheque-drawer-advanced) utilisait
  --surface-1 (3,5% d'opacite) -> page visible derriere ;
- la fenetre showModal (.modal-card) n'avait AUCUN background (la classe .card
  n'en definit aucun) -> modale de decision transparente ;
- les <select> natifs (.v5-input) ouvraient un popup blanc rendu par l'OS.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_COMPONENTS = _ROOT / "web" / "shared" / "components.css"
_STYLES = _ROOT / "web" / "dashboard" / "styles.css"


def _rule(css: str, selector: str) -> str:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    return m.group(1) if m else ""


class CssPanelsOpaqueTests(unittest.TestCase):
    def test_advanced_drawer_opaque(self) -> None:
        body = _rule(_COMPONENTS.read_text(encoding="utf-8"), ".bibliotheque-drawer-advanced")
        self.assertIn("background: var(--bg-raised)", body,
                      "Le tiroir avance doit avoir un fond opaque (--bg-raised).")
        self.assertNotIn("background: var(--surface-1)", body,
                         "Le tiroir avance ne doit plus utiliser --surface-1 (quasi transparent).")

    def test_modal_card_has_background(self) -> None:
        body = _rule(_STYLES.read_text(encoding="utf-8"), ".modal-card")
        self.assertIn("background:", body,
                      "La modale showModal (.modal-card) doit avoir un background opaque.")

    def test_v5_input_color_scheme_dark(self) -> None:
        body = _rule(_COMPONENTS.read_text(encoding="utf-8"), ".v5-input")
        self.assertIn("color-scheme: dark", body,
                      "Les inputs/selects v5 doivent forcer color-scheme: dark.")


if __name__ == "__main__":
    unittest.main()
