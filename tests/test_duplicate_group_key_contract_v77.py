"""GATE AUDIT 2026-06-10 (REAL 2/2) — contrat de la cle de groupe doublons.

Le fallback JS `_groupKey` (web/dashboard/views/doublons.js) DOIT produire
exactement la meme cle que le backend `_group_key_for` (run_flow_support.py),
sinon `mark_duplicate_winner` ne retrouve jamais le groupe -> losers=[] ->
aucun fichier perdant deplace a l'apply (decisions Garder A/B perdues).

Ce test epingle les sorties backend. Si elles changent, le fallback JS doit
etre mis a jour en miroir (title.lower()|year, "|" strippe en tete/fin).
"""

from __future__ import annotations

import unittest

from cinesort.ui.api.run_flow_support import _group_key_for


class DuplicateGroupKeyContractTests(unittest.TestCase):
    def test_backend_group_key_pinned_outputs(self) -> None:
        cases = [
            ({"title": "The Matrix", "year": 1999}, "the matrix|1999"),
            ({"title": "Inception", "year": ""}, "inception"),
            ({"title": "Amelie", "proposed_year": 2001}, "amelie|2001"),
            ({"title": "", "year": 2020}, "2020"),
            ({"group_key": "explicit_key", "title": "X", "year": 1}, "explicit_key"),
        ]
        for group, expected in cases:
            with self.subTest(group=group):
                self.assertEqual(_group_key_for(group), expected)

    def test_explicit_key_takes_priority(self) -> None:
        for key in ("group_key", "id", "signature"):
            self.assertEqual(_group_key_for({key: "K", "title": "t", "year": 1}), "K")

    def test_lowercase_and_pipe_separator(self) -> None:
        # Invariants critiques du contrat JS<->backend.
        k = _group_key_for({"title": "MixedCase Title", "year": 2010})
        self.assertEqual(k, "mixedcase title|2010")
        self.assertNotIn("::", k)


if __name__ == "__main__":
    unittest.main()
