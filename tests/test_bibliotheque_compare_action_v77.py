"""GATE AUDIT 2026-06-14 (R6-B) — action "Comparer" de la bibliotheque.

Avant : l'action bulk "compare" se contentait de window.location.hash="#/doublons"
(R5-F), forcant l'utilisateur a re-trouver son film. Desormais elle ouvre
DIRECTEMENT le comparateur sur les films selectionnes en mode lecture seule.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_BIB = Path(__file__).resolve().parents[1] / "web" / "dashboard" / "views" / "bibliotheque.js"


class BibliothequeCompareActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIB.read_text(encoding="utf-8")

    def test_imports_comparator_modal(self) -> None:
        self.assertIn("import { openDuplicateComparatorModal }", self.js)

    def test_compare_opens_modal_readonly(self) -> None:
        # Le bloc compare doit appeler le modal en readOnly, pas seulement naviguer.
        m = re.search(r'if \(action === "compare"\) \{(.+?)\n  \}', self.js, re.DOTALL)
        self.assertIsNotNone(m, "bloc action compare introuvable")
        body = m.group(1)
        self.assertIn("openDuplicateComparatorModal(", body)
        self.assertIn("readOnly: true", body)
        self.assertNotIn('window.location.hash = "#/doublons"', body,
                         "compare ne doit plus se limiter a naviguer vers #/doublons.")

    def test_compare_guards_min_two(self) -> None:
        m = re.search(r'if \(action === "compare"\) \{(.+?)\n  \}', self.js, re.DOTALL)
        self.assertIn("selectedRows.length < 2", m.group(1),
                      "garde : au moins 2 films requis pour comparer.")


if __name__ == "__main__":
    unittest.main()
