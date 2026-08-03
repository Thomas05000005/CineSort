"""GATE — watchlist : un remake (meme titre, annee differente) n'est pas "owned".

Bug (AUDIT REAL 2/2, watchlist.py:121) : le fallback "titre seul" du pass 1
testait `norm in local_title_only`, un set qui contient TOUS les titres locaux
y compris ceux ayant une annee. Resultat : un film watchlist AVEC annee (ex.
Dune 2021) etait marque "owned" si la bibliotheque contenait un film de meme
titre d'une AUTRE annee (Dune 1984) -> couverture watchlist gonflee, films
reellement manquants jamais signales.

Fix : le fallback titre-seul ne matche desormais que les titres locaux SANS
annee connue (proposed_year == 0). Ces tests verrouillent que les remakes
restent distingues et que le fallback legitime (watchlist datee, local non date)
fonctionne encore.

NB : ce fichier de test n'a PAS le skip-guard `web/index.html` de
test_watchlist.py (qui rend toute la suite watchlist inactive). Il teste la
logique pure compare_watchlist directement, donc il s'execute reellement.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from cinesort.app.watchlist import compare_watchlist


def _row(title: str, year: int) -> SimpleNamespace:
    return SimpleNamespace(proposed_title=title, proposed_year=year)


class WatchlistRemakeTests(unittest.TestCase):
    def test_remake_different_year_not_owned(self) -> None:
        # Dune 2021 (watchlist) vs Dune 1984 (biblio) : remakes differents.
        report = compare_watchlist([{"title": "Dune", "year": 2021}], [_row("Dune", 1984)])
        self.assertEqual(report["owned_count"], 0)
        self.assertEqual(report["missing_count"], 1)
        self.assertEqual(report["missing"][0]["title"], "Dune")

    def test_fallback_matches_local_without_year(self) -> None:
        # Fallback legitime : watchlist datee, local d'annee inconnue (0) -> match.
        report = compare_watchlist([{"title": "Dune", "year": 2021}], [_row("Dune", 0)])
        self.assertEqual(report["owned_count"], 1)
        self.assertEqual(report["missing_count"], 0)

    def test_exact_year_match_preserved(self) -> None:
        report = compare_watchlist([{"title": "Dune", "year": 2021}], [_row("Dune", 2021)])
        self.assertEqual(report["owned_count"], 1)

    def test_watchlist_without_year_matches_local_with_year(self) -> None:
        # Pass 1 branche "watchlist sans annee" : inchangee.
        report = compare_watchlist([{"title": "Inception", "year": 0}], [_row("Inception", 2010)])
        self.assertEqual(report["owned_count"], 1)

    def test_library_with_both_years_matches_correct_one(self) -> None:
        report = compare_watchlist(
            [{"title": "Dune", "year": 2021}],
            [_row("Dune", 1984), _row("Dune", 2021)],
        )
        self.assertEqual(report["owned_count"], 1)
        self.assertEqual(report["missing_count"], 0)

    def test_remake_not_rescued_by_fuzzy_pass(self) -> None:
        # Garde-fou : meme apres le pass 2 fuzzy, un remake d'annee differente
        # reste "missing" (le fuzzy filtre par annee exacte + locaux sans annee).
        report = compare_watchlist(
            [{"title": "The Lion King", "year": 2019}],
            [_row("Lion King", 1994)],
        )
        self.assertEqual(report["owned_count"], 0)
        self.assertEqual(report["missing_count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
