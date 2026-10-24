"""GATE — `_norm_for_tokens` ne rend plus la chaine VIDE sur un titre absorbe.

`title_helpers.NOISE_RE` retire ses ~70 jetons techniques INCONDITIONNELLEMENT,
donc aussi a l'interieur du titre. Quelques-uns de ces jetons sont des titres de
films reels, et le depot les NOMME deja — mais pour l'AUTRE table de tags, celle
de `scene_parser` :

    tests/test_scene_parser_title_mutilation_v77.py
        ::MotsAmbigusDeLaListeINCONDITIONNELLETests
    -> « Opus » (2025), « Hybrid » (2007), « Limited » (2019), « Proper » (2022)

    cinesort/domain/scene_parser.py::_AUDIO_RESIDUE_RE (commentaire)
    -> « 71 (2014) -> 2014 », cite comme mutilation MESUREE

Le correctif avait ete pose la, pas ici. Resultat : l'EXTRACTION du titre rend
bien « Opus », et la fonction qui le COMPARE au candidat TMDb le vide.

Ce que ce fichier eprouve, et dans les deux sens :
  1. le titre absorbe garde desormais ses tokens ;
  2. le candidat TMDb EXACT n'est plus ecarte (VRAI corps de
     `core.build_candidates_from_tmdb`, pas une reimplementation) ;
  3. CONTRE-TEST : le repli ne rend pas le matching permissif — un titre absorbe
     ne matche pas un titre sans rapport ;
  4. deux films DIFFERENTS de la meme annee ne partagent plus la cle de doublon ;
  5. CONTRE-TEST : les titres ordinaires et les noms de release ne bougent pas
     d'un caractere.
"""

from __future__ import annotations

import unittest

import cinesort.domain.core as core
from cinesort.domain.duplicate_support import movie_key
from cinesort.domain.title_helpers import _norm_for_tokens

#: Titres de films REELS que `NOISE_RE` absorbe INTEGRALEMENT. Les quatre
#: premiers sont nommes comme films par le depot lui-meme (cf. en-tete) ; le
#: cinquieme est un titre externe verifiable (Cronenberg, 1969).
#:
#: « 2.0 » (2018) et « 71 » (2014) relevent de la MEME famille mais sont EXCLUS
#: de ce fichier a dessein : leur sort se joue AVANT, dans `clean_title_guess`,
#: par deux causes distinctes de celle corrigee ici (l'une dans
#: `scene_parser._AUDIO_RESIDUE_RE`, l'autre dans le `Path(...).stem` du repli de
#: `clean_title_guess`). Les melanger ferait passer ce garde pour la preuve d'un
#: correctif qu'il ne porte pas.
TITRES_ABSORBES = ("Opus", "Hybrid", "Limited", "Proper", "Stereo")

#: Titres ordinaires : leur normalisation ne passe PAS par le repli, elle doit
#: donc rester identique au caractere pres.
TITRES_ORDINAIRES = {
    "Inception": "inception",
    "Dune": "dune",
    "Avatar": "avatar",
    "Blade Runner 2049": "blade runner 2049",
    "21 Jump Street": "21 jump street",
}


class _FauxResultatTmdb:
    """Faux TmdbResult : les 6 attributs que `build_candidates_from_tmdb` lit."""

    def __init__(self, *, id: int, title: str, year: int, original_title: str = "") -> None:
        self.id = id
        self.title = title
        self.year = year
        self.original_title = original_title or title
        self.vote_count = 100
        self.poster_path = ""


class _FauxClientTmdb:
    def __init__(self, resultats: list) -> None:
        self._resultats = resultats

    def search_movie(self, query: str, year=None, language: str = "fr-FR", max_results: int = 8):
        return list(self._resultats[:max_results])


class NormalisationAbsorbanteTests(unittest.TestCase):
    def test_un_titre_entierement_absorbe_garde_ses_tokens(self) -> None:
        for titre in TITRES_ABSORBES:
            with self.subTest(titre=titre):
                self.assertTrue(
                    _norm_for_tokens(titre),
                    f"« {titre} » est un titre de film : sa normalisation ne peut pas etre vide",
                )

    def test_la_similarite_d_un_titre_avec_lui_meme_n_est_plus_nulle(self) -> None:
        """Le symptome direct : `_title_similarity(t, t)` valait 0.00."""
        for titre in TITRES_ABSORBES:
            with self.subTest(titre=titre):
                self.assertGreaterEqual(core._title_similarity(titre, titre), 0.9)

    def test_le_candidat_tmdb_exact_n_est_plus_ecarte(self) -> None:
        """VRAI corps de production : le seuil absolu 0,50 rejetait l'exact."""
        for titre in TITRES_ABSORBES:
            with self.subTest(titre=titre):
                client = _FauxClientTmdb([_FauxResultatTmdb(id=42, title=titre, year=2019)])
                candidats = core.build_candidates_from_tmdb(
                    tmdb=client,
                    query=titre,
                    year=2019,
                    language="fr-FR",
                )
                self.assertTrue(candidats, f"aucun candidat pour « {titre} » alors que TMDb rend l'exact")
                self.assertIn(42, [c.tmdb_id for c in candidats])

    def test_un_titre_absorbe_ne_matche_pas_n_importe_quoi(self) -> None:
        """CONTRE-TEST : le repli ne relache aucun seuil.

        Sans lui, ce test passerait pour la mauvaise raison (tout est rejete).
        Avec lui, il prouve que seul l'EXACT remonte.
        """
        sans_rapport = _FauxResultatTmdb(id=22, title="La Malediction du Black Pearl", year=2003)
        client = _FauxClientTmdb([sans_rapport])
        candidats = core.build_candidates_from_tmdb(tmdb=client, query="Opus", year=2025, language="fr-FR")
        self.assertEqual(candidats, [])

    def test_deux_films_absorbes_ne_partagent_plus_la_cle_de_doublon(self) -> None:
        """`movie_key` rendait « |2019 » pour TOUS ces films : un seul groupe."""
        cles = {titre: movie_key(titre, 2019, norm_for_tokens=_norm_for_tokens) for titre in TITRES_ABSORBES}
        for titre, cle in cles.items():
            with self.subTest(titre=titre):
                self.assertNotEqual(cle, "|2019", f"cle degeneree pour « {titre} »")
        self.assertEqual(
            len(set(cles.values())),
            len(TITRES_ABSORBES),
            "des films DIFFERENTS de la meme annee partagent encore une cle de doublon",
        )

    def test_les_titres_ordinaires_ne_bougent_pas(self) -> None:
        """CONTRE-TEST de monotonie : le repli n'est atteint que sur du vide."""
        for brut, attendu in TITRES_ORDINAIRES.items():
            with self.subTest(brut=brut):
                self.assertEqual(_norm_for_tokens(brut), attendu)

    def test_un_nom_de_release_perd_toujours_ses_tags(self) -> None:
        """CONTRE-TEST : `NOISE_RE` fait toujours son travail quand il reste un titre."""
        norm = _norm_for_tokens("Dune.Part.Two.2024.2160p.BluRay.x265")
        self.assertIn("dune", norm)
        for tag in ("2160p", "bluray", "x265"):
            self.assertNotIn(tag, norm)

    def test_une_entree_sans_aucun_token_reste_vide(self) -> None:
        """Le repli ne fabrique rien : sans caractere exploitable, on rend « »."""
        for brut in ("", "   ", "(2025)", "---"):
            with self.subTest(brut=brut):
                self.assertEqual(_norm_for_tokens(brut), "")


if __name__ == "__main__":
    unittest.main()
