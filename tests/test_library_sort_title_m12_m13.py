"""M12 + M13 : tri Bibliotheque par titre.

M12 : le tri titre par defaut (sort="title") doit classer les accents avec
      leur lettre de base (fold Unicode), pas apres "z" (point de code brut).
M13 : le tri descendant (sort="title_desc") doit etre l'inverse EXACT du tri
      ascendant (reverse=True), pas une cle -ord tronquee a 50 caracteres qui
      inverse mal les paires prefixe et perd le tie-break annee.
"""

from __future__ import annotations

import unittest

from cinesort.ui.api.library_support import _apply_sort


def _titles(rows):
    return [r["title"] for r in rows]


def _title_years(rows):
    return [(r["title"], r["year"]) for r in rows]


class TitleSortAccentTests(unittest.TestCase):
    """M12 : classement accent-insensible du tri titre par defaut."""

    def test_accented_titles_sort_with_base_letter(self) -> None:
        rows = [
            {"title": "Zoo", "year": 2000},
            {"title": "Élan", "year": 2000},
            {"title": "Amour", "year": 2000},
            {"title": "Été", "year": 2000},
            {"title": "Bob", "year": 2000},
        ]
        out = _titles(_apply_sort(rows, "title"))
        # "Élan"/"Été" doivent se classer avec les E, PAS apres "Zoo"
        # (point de code 'é'=0xE9 > 'z'=0x7A dans le code buggue).
        self.assertEqual(out, ["Amour", "Bob", "Élan", "Été", "Zoo"])


class TitleDescSortTests(unittest.TestCase):
    """M13 : title_desc = inverse exact de l'ascendant."""

    def test_desc_is_exact_reverse_of_asc(self) -> None:
        rows = [
            {"title": "Avatar 2", "year": 2022},
            {"title": "Amour", "year": 1990},
            {"title": "Élan", "year": 2011},
            {"title": "Avatar", "year": 2009},
            {"title": "Zoo", "year": 1975},
        ]
        asc = _titles(_apply_sort(rows, "title"))
        desc = _titles(_apply_sort(rows, "title_desc"))
        self.assertEqual(desc, list(reversed(asc)))

    def test_prefix_pair_descending(self) -> None:
        # "Avatar" est un prefixe de "Avatar 2" : en Z->A, "Avatar 2" d'abord.
        # La cle -ord buggue classe le tuple le plus court (prefixe) AVANT.
        rows = [
            {"title": "Avatar", "year": 2009},
            {"title": "Avatar 2", "year": 2022},
        ]
        desc = _titles(_apply_sort(rows, "title_desc"))
        self.assertEqual(desc, ["Avatar 2", "Avatar"])

    def test_year_tiebreak_preserved_in_desc(self) -> None:
        # Meme titre : tie-break annee descendante (recente d'abord).
        # La cle -ord buggue n'a pas d'annee -> ordre d'entree conserve.
        rows = [
            {"title": "Dune", "year": 1984},
            {"title": "Dune", "year": 2021},
        ]
        desc = _title_years(_apply_sort(rows, "title_desc"))
        self.assertEqual(desc, [("Dune", 2021), ("Dune", 1984)])


if __name__ == "__main__":
    unittest.main()
