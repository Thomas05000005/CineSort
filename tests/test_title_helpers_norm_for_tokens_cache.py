"""Memoisation de `_norm_for_tokens` : le cache, sa borne, et sa transparence.

`_norm_for_tokens` est appelee en O(n) par candidat sur le chemin chaud du
matching (`cinesort.domain.core._candidate_consensus_bonus` normalise le titre
du candidat, puis re-normalise le titre de CHAQUE candidat de la liste pour le
comparer) : n candidats coutent donc n(n+1) normalisations alors que la plupart
des titres sont identiques. D'ou `@lru_cache`.

Trois proprietes solidaires, un test dedie chacune — aucun ne couvre le cas
d'un autre :
  (1) la reutilisation est effective sur le chemin chaud reel (pas seulement
      "un decorateur est present") ;
  (2) le cache est BORNE : un `lru_cache(maxsize=None)` sur des titres
      arbitraires est une fuite memoire sur une grosse bibliotheque ;
  (3) le cache est TRANSPARENT : memoiser ne vaut que si la fonction est pure,
      donc le resultat memoise doit rester egal a celui de l'implementation
      non decoree (`__wrapped__`), tags providers et accents compris.

Le 4e test garde la PRECONDITION de la memoisation : un resultat mutable serait
partage entre tous les appelants et une mutation chez l'un corromprait le cache
de tous les autres.
"""

from __future__ import annotations

import unittest

from cinesort.domain.core import Candidate, _candidate_consensus_bonus
from cinesort.domain.title_helpers import _norm_for_tokens

# Corpus volontairement varie : accents (NFKD), tag provider (B02-TAGS-BRACKETS,
# ajoute a la fonction APRES l'ecriture du cache), tags techniques NOISE_RE,
# esperluette, annee parenthesee, chaine vide.
CORPUS = (
    "",
    "Avatar",
    "Amelie",
    "Le Fabuleux Destin d'Amelie Poulain",
    "L'Auberge Espagnole (2002)",
    "Avatar {tmdb-19995}",
    "Ford v Ferrari [imdbid-tt1950186]",
    "Fast & Furious",
    "Dune.Part.Two.2024.2160p.BluRay.x265.DTS-HD",
    "Cafe   de   Flore",
)


class NormForTokensCacheTests(unittest.TestCase):
    def test_hot_path_reuses_cached_normalization(self):
        """Chemin chaud reel : n candidats de meme titre => 1 seul calcul."""
        _norm_for_tokens.cache_clear()
        cands = [
            Candidate(title="Avatar", year=2009, source=src, score=0.5)
            for src in ("nfo", "name", "tmdb", "omdb", "trakt")
        ]
        _candidate_consensus_bonus(cands[0], cands)

        info = _norm_for_tokens.cache_info()
        # 1 normalisation du title_key + 5 dans la boucle sur les candidats :
        # sans cache ce sont 6 calculs, avec cache 1 miss et 5 hits.
        self.assertEqual(info.misses, 1)
        self.assertEqual(info.hits, 5)

    def test_cache_is_bounded(self):
        """Borne obligatoire : maxsize=None = fuite memoire sur grosse biblio."""
        maxsize = _norm_for_tokens.cache_info().maxsize
        self.assertIsNotNone(maxsize, "lru_cache non borne : fuite memoire sur titres arbitraires")
        self.assertGreaterEqual(maxsize, 1, "maxsize=0 desactive la memoisation")
        self.assertLessEqual(maxsize, 4096, "borne trop large pour un cache de titres")

    def test_cache_is_transparent(self):
        """Le resultat memoise est identique a celui de la fonction non decoree."""
        uncached = _norm_for_tokens.__wrapped__
        _norm_for_tokens.cache_clear()
        for raw in CORPUS:
            with self.subTest(raw=raw):
                expected = uncached(raw)
                # Premier appel (miss) ET deuxieme appel (hit) doivent coincider.
                self.assertEqual(_norm_for_tokens(raw), expected)
                self.assertEqual(_norm_for_tokens(raw), expected)

    def test_result_is_immutable(self):
        """Precondition de la memoisation : un resultat mutable serait partage."""
        for raw in CORPUS:
            with self.subTest(raw=raw):
                self.assertIsInstance(_norm_for_tokens(raw), str)


if __name__ == "__main__":
    unittest.main()
