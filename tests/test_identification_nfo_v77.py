"""GATE AUDIT 2026-06-13 (R5-A) — un film identifie par NFO/nom (sans tmdb_id)
n'est PLUS compte "non identifie".

Bug reel verifie sur la biblio de l'utilisateur (run tri_films_20260612_234833) :
TMDb desactive, 1027 films identifies par NFO (908) + nom (115), AUCUN tmdb_id.
L'ancien _row_unidentified faisait `if tmdb_id <= 0: return True` EN PREMIER ->
les 1027 etaient classes "non identifies" et la grille affichait "Identifier"
partout, alors que les films sont parfaitement identifies (titre + annee +
confiance 87). Le tmdb_id ne sert qu'aux jaquettes, pas a l'identification.
"""

from __future__ import annotations

import unittest

from cinesort.ui.api.library_support import _row_unidentified


class IdentificationNfoTests(unittest.TestCase):
    def test_nfo_identified_without_tmdb_id_is_identified(self) -> None:
        # Cas reel "12 Hommes en colere" : NFO, confiance 87, annee 1957, pas de tmdb_id.
        row = {"proposed_source": "nfo", "confidence": 87, "proposed_year": 1957}
        self.assertFalse(_row_unidentified(row), "NFO + confiance + annee = identifie")

    def test_name_identified_high_confidence_is_identified(self) -> None:
        row = {"proposed_source": "name", "confidence": 75, "proposed_year": 1999}
        self.assertFalse(_row_unidentified(row))

    def test_library_row_shape_year_key(self) -> None:
        # La row Library expose `year` (pas `proposed_year`) : doit aussi marcher.
        row = {"proposed_source": "nfo", "confidence": 90, "year": 2010}
        self.assertFalse(_row_unidentified(row))

    def test_tmdb_id_is_a_sufficient_shortcut(self) -> None:
        # tmdb_id resolu => identifie meme si le reste est faible.
        row = {"tmdb_id": 27205, "proposed_source": "", "confidence": 0, "proposed_year": 0}
        self.assertFalse(_row_unidentified(row))

    # --- Vrais non-identifies ---
    def test_unknown_source_is_unidentified(self) -> None:
        row = {"proposed_source": "unknown", "confidence": 0, "proposed_year": 0}
        self.assertTrue(_row_unidentified(row))

    def test_empty_source_is_unidentified(self) -> None:
        row = {"proposed_source": "", "confidence": 80, "proposed_year": 2010}
        self.assertTrue(_row_unidentified(row))

    def test_low_confidence_is_unidentified(self) -> None:
        row = {"proposed_source": "name", "confidence": 40, "proposed_year": 2010}
        self.assertTrue(_row_unidentified(row))

    def test_missing_year_is_unidentified(self) -> None:
        row = {"proposed_source": "nfo", "confidence": 90, "proposed_year": 0}
        self.assertTrue(_row_unidentified(row))


if __name__ == "__main__":
    unittest.main()
