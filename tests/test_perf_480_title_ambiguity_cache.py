"""GATE #480 — `normalize_title_for_ambiguity` ne renormalise plus le meme titre.

La fonction est pure et le chemin d'appel la rejoue au moins DEUX fois sur la
meme liste de candidats : `detect_title_ambiguity` normalise chaque candidat
TMDb, puis `disambiguate_by_context` renormalise TOUS les candidats pour trouver
ceux du groupe ambigu. Sur une bibliotheque, les franchises repetent en plus les
memes titres d'un film a l'autre.

Grandeur mesuree : le nombre de normalisations REELLEMENT calculees
(`cache_info().misses`), pas des millisecondes. Elle est deterministe et donne la
loi d'echelle exacte :

    films |  appels a normaliser | calculs reels (avant) | calculs reels (apres)
    ------+----------------------+-----------------------+----------------------
       50 |                  600 |                   600 |                     5
      500 |                 6000 |                  6000 |                     5

(5 = le nombre de titres DISTINCTS du jeu, la constante attendue.)

Deux verrous distincts sont poses, car un seul laisserait passer une des deux
regressions possibles :
  - `hits + misses == appels attendus` echoue si la fonction publique cesse de
    deleguer au corps memoise (correctif hors du chemin d'appel) ;
  - `misses == titres distincts` echoue si la memoisation est neutralisee.
"""

from __future__ import annotations

import unittest
from typing import List

from cinesort.domain.core import Candidate
from cinesort.domain.title_ambiguity import (
    _normalize_title_for_ambiguity_cached,
    detect_title_ambiguity,
    disambiguate_by_context,
    normalize_title_for_ambiguity,
)

# "Dune" est present deux fois -> ambiguite detectee -> la seconde passe de
# normalisation (celle de `disambiguate_by_context`) a bien lieu.
_POOL = ("Dune", "The Thing", "Dune", "Le Petit Prince", "Les Misérables", "Avatar")
_DISTINCT_TITLES = 5
# 1 normalisation par candidat dans `detect_title_ambiguity`, puis 1 par candidat
# dans la boucle de `disambiguate_by_context`.
_NORMALIZATIONS_PER_FILM = 2 * len(_POOL)


def _candidates() -> List[Candidate]:
    return [Candidate(title=title, year=1980 + i, source="tmdb", score=0.5) for i, title in enumerate(_POOL)]


class NormalizeTitleBehaviourTests(unittest.TestCase):
    """La memoisation ne doit RIEN changer a la sortie, y compris aux cas limites."""

    def test_sorties_inchangees(self) -> None:
        cases = [
            ("L'Été", "ete"),
            ("Dune: Part One!", "dune part one"),
            ("The Thing", "thing"),
            ("Le Petit Prince", "petit prince"),
            ("Les Misérables", "miserables"),
            ("Hello   world", "hello world"),
            ("", ""),
            (None, ""),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_title_for_ambiguity(raw), expected)  # type: ignore[arg-type]

    def test_argument_non_hachable_ne_leve_pas(self) -> None:
        """Anti-regression du piege signale dans #480 lui-meme.

        Decorer directement la fonction publique avec `lru_cache` aurait converti
        tout appel avec un argument non hachable en `TypeError`, la ou l'ancien
        corps normalisait `str(title)`. La coercition doit rester HORS du cache.
        """
        self.assertEqual(normalize_title_for_ambiguity(["Dune"]), "dune")  # type: ignore[arg-type]
        self.assertEqual(normalize_title_for_ambiguity({"zz": 1}), "zz 1")  # type: ignore[arg-type]
        self.assertEqual(normalize_title_for_ambiguity(2001), "2001")  # type: ignore[arg-type]

    def test_detection_ambiguite_toujours_correcte(self) -> None:
        ambiguous, key = detect_title_ambiguity(_candidates())
        self.assertTrue(ambiguous)
        self.assertEqual(key, "dune")


class NormalizeTitleCallBudgetTests(unittest.TestCase):
    """Le nombre de normalisations calculees ne doit pas croitre avec les films."""

    def setUp(self) -> None:
        _normalize_title_for_ambiguity_cached.cache_clear()

    def tearDown(self) -> None:
        _normalize_title_for_ambiguity_cached.cache_clear()

    def _run(self, films: int) -> tuple[int, int]:
        for _ in range(films):
            disambiguate_by_context(_candidates(), {})
        info = _normalize_title_for_ambiguity_cached.cache_info()
        return int(info.hits + info.misses), int(info.misses)

    def test_calculs_reels_constants_sur_deux_tailles(self) -> None:
        measured = {}
        for films in (3, 12):
            _normalize_title_for_ambiguity_cached.cache_clear()
            calls, computed = self._run(films)
            measured[films] = (calls, computed)

        # 1) Le chemin d'appel REEL passe bien par le corps memoise : si la
        #    fonction publique cessait de deleguer, ce compte tomberait a 0.
        for films, (calls, _computed) in measured.items():
            with self.subTest(films=films):
                self.assertEqual(
                    calls,
                    films * _NORMALIZATIONS_PER_FILM,
                    "le nombre d'appels normalises attendu a change : le chemin d'appel n'est plus celui mesure",
                )

        # 2) Le travail reel ne depend pas du nombre de films.
        self.assertEqual(measured[3][1], _DISTINCT_TITLES)
        self.assertEqual(measured[12][1], _DISTINCT_TITLES)

        # 3) La loi d'echelle : x4 films -> x4 appels, calculs reels inchanges.
        self.assertEqual(measured[12][0], 4 * measured[3][0])
        self.assertEqual(measured[12][1], measured[3][1])


if __name__ == "__main__":
    unittest.main()
