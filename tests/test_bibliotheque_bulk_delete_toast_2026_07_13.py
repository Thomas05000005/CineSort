"""REVUE ADVERSAIRE 2026-07-13 (defaut 7) — toast du marquage bulk suppression.

`_confirmBulkDelete` affichait "N film(s) marqué(s) pour suppression." des que
`ok !== false`, avec N = nombre de films SELECTIONNES — sans jamais lire `count`
ni `failed` renvoyes par library/mark_for_deletion_bulk. Un bulk partiellement
refuse (row_id absent du plan, base SQLite verrouillee -> tous en `failed`)
annoncait donc un succes TOTAL sur une action DESTRUCTIVE : l'utilisateur croyait
ses films marques alors qu'aucun ne l'etait.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_BIB = Path(__file__).resolve().parents[1] / "web" / "dashboard" / "views" / "bibliotheque.js"


def _on_confirm_block(js: str) -> str:
    """Corps du onConfirm de la modale de suppression bulk."""
    m = re.search(
        r'const res = await apiPost\("library/mark_for_deletion_bulk".*?\n      \} catch',
        js,
        re.DOTALL,
    )
    assert m is not None, "bloc onConfirm de _confirmBulkDelete introuvable"
    return m.group(0)


class BulkDeleteToastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIB.read_text(encoding="utf-8")
        cls.block = _on_confirm_block(cls.js)

    def test_toast_reads_count_from_payload(self) -> None:
        self.assertIn("_payload.count", self.block)

    def test_toast_reads_failed_from_payload(self) -> None:
        self.assertIn("_payload.failed", self.block)

    def test_warns_when_some_rows_failed(self) -> None:
        self.assertRegex(
            self.block,
            r"if \(failed\.length\)",
            "aucun avertissement quand des films n'ont PAS ete marques",
        )
        self.assertIn('"warning"', self.block)

    def test_success_toast_no_longer_hardcodes_selection_size(self) -> None:
        # Avant : `${n} film${n > 1 ? "s" : ""} marqué...` (n = taille de la selection).
        self.assertNotIn(
            '${n} film${n > 1 ? "s" : ""} marqué${n > 1 ? "s" : ""} pour suppression.',
            self.block,
        )
        self.assertIn("${count} film", self.block)


if __name__ == "__main__":
    unittest.main()
