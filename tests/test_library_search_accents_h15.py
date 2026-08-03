"""GATE AUDIT ULTRA 2026-07-13 (H15) — recherche Bibliotheque insensible aux accents.

Avant : `_row_matches` faisait `q = search.strip().lower()` puis un substring brut
`q not in title.lower()`, sans repli d'accents. Les titres TMDb sont stockes
accentues (windows_safe force NFC sans replier les accents), donc "amelie" ne
trouvait pas "Amelie", "elysium" ne trouvait pas "Elysium", etc. — un film present
et visible sans filtre retournait 0 resultat.

Fix : replier les accents des DEUX cotes (query ET titre) via le helper domaine
existant normalize_for_fuzzy (deja utilise par le fuzzy des doublons).
"""

from __future__ import annotations

import unittest

from cinesort.ui.api.library_support import _row_matches


class LibrarySearchAccentTests(unittest.TestCase):
    @staticmethod
    def _row(title: str) -> dict:
        return {"title": title}

    def _search(self, title: str, query: str) -> bool:
        return _row_matches(self._row(title), {"search": query})

    # --- ECHOUE avant / PASSE apres : query sans accent trouve titre accentue ---
    def test_amelie_finds_accented_title(self) -> None:
        # "Amelie" (accentue) doit etre trouve par "amelie" (sans accent).
        self.assertTrue(self._search("Amélie", "amelie"))
        # Symetrie : query accentuee trouve titre sans accent.
        self.assertTrue(self._search("Amelie", "amélie"))

    def test_elysium_finds_accented_title(self) -> None:
        # "Elysium" (E accent aigu majuscule) trouve par "elysium".
        self.assertTrue(self._search("Élysium", "elysium"))

    def test_cesar_finds_accented_title(self) -> None:
        self.assertTrue(self._search("César", "cesar"))

    # --- Non-regression : un non-match reste un non-match ---
    def test_non_match_stays_non_match(self) -> None:
        self.assertFalse(self._search("Amélie", "matrix"))

    # --- Non-regression : le match ASCII simple marche toujours ---
    def test_plain_ascii_still_matches(self) -> None:
        self.assertTrue(self._search("Alien", "alien"))
        self.assertTrue(self._search("The Matrix", "matrix"))

    # --- Non-regression : recherche vide = pas de filtre (matche tout) ---
    def test_empty_search_matches_all(self) -> None:
        self.assertTrue(_row_matches(self._row("Amélie"), {"search": ""}))
        self.assertTrue(_row_matches(self._row("Amélie"), {}))


if __name__ == "__main__":
    unittest.main()
