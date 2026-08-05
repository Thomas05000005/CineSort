"""F34 — le filtre "bonus" TMDb ne doit plus rejeter des films legitimes.

Contexte du finding (revue post-merge 2026-07-18) : `build_candidates_from_tmdb`
ecartait tout resultat dont le titre CONTIENT un mot-cle bonus, en simple
sous-chaine et sans frontiere de mot :

    "promo"   in "the promotion"          -> True
    "trailer" in "trailer park boys..."   -> True

Resultat : TOUS les resultats TMDb corrects etaient jetes pour ces titres. Le
film n'obtenait jamais de tmdb_id, ni jaquette, ni annee confirmee, et recevait
+25 pts "pas de match TMDb".

Deux gardes sont necessaires et testees ici :
  1. frontiere de mot -> "promo" ne matche plus dans "promotion" ;
  2. si la REQUETE porte elle-meme le mot-cle, le filtre ne s'applique pas
     (sinon "Trailer Park Boys" reste introuvable, le mot y est bien isole).
"""

from __future__ import annotations

import unittest
from typing import List, Optional

from cinesort.domain import core
from cinesort.infra.tmdb_client import TmdbResult


class _FakeTmdb:
    """Client TMDb minimal : rend toujours la meme liste de resultats."""

    def __init__(self, results: List[TmdbResult]) -> None:
        self._results = results
        self.queries: List[str] = []

    def search_movie(
        self, query: str, year: Optional[int] = None, *, language: str = "fr-FR", max_results: int = 8
    ) -> List[TmdbResult]:
        self.queries.append(query)
        return list(self._results)


def _result(tmdb_id: int, title: str, year: Optional[int]) -> TmdbResult:
    return TmdbResult(
        id=tmdb_id,
        title=title,
        year=year,
        original_title=title,
        popularity=10.0,
        vote_count=500,
        vote_average=7.0,
    )


class TmdbBonusKeywordBoundaryTests(unittest.TestCase):
    def test_promotion_n_est_pas_filtre_par_le_mot_cle_promo(self) -> None:
        tmdb = _FakeTmdb([_result(12345, "The Promotion", 2008)])
        candidats = core.build_candidates_from_tmdb(tmdb, "The Promotion", 2008, "fr-FR")

        self.assertTrue(
            candidats,
            "'promo' ne doit plus matcher a l'interieur de 'promotion' : le film perdait tout candidat TMDb",
        )
        self.assertEqual(candidats[0].tmdb_id, 12345)

    def test_requete_portant_le_mot_cle_desactive_le_filtre(self) -> None:
        tmdb = _FakeTmdb([_result(222, "Trailer Park Boys: The Movie", 2006)])
        candidats = core.build_candidates_from_tmdb(tmdb, "Trailer Park Boys The Movie", 2006, "fr-FR")

        self.assertTrue(
            candidats,
            "quand l'utilisateur cherche explicitement un titre contenant 'trailer', "
            "le filtre bonus ne doit pas supprimer le film",
        )
        self.assertEqual(candidats[0].tmdb_id, 222)

    def test_frontiere_de_mot_seule_suffit_quand_la_requete_est_neutre(self) -> None:
        """Isole le volet « frontiere de mot », sans l'aide de la garde requete.

        Defaut trouve en revue adversaire : les tests precedents pouvaient tous
        passer avec un filtre revenu en sous-chaine nue, parce que la garde
        requete les sauvait. Ici la requete ne contient AUCUN mot-cle : seule la
        frontiere de mot peut empecher le rejet.
        """
        # Chaque regex par mot-cle doit refuser de matcher A L'INTERIEUR d'un mot.
        # On interroge les objets regex reellement utilises par le filtre : c'est
        # une propriete de COMPORTEMENT, pas une comparaison de texte source.
        colles = [rx.pattern for rx in core._TMDB_BONUS_KEYWORD_RES if rx.search("the promotion")]
        self.assertEqual(
            colles,
            [],
            f"un mot-cle matche a l'interieur de 'promotion' : {colles}",
        )
        colles_trailer = [rx.pattern for rx in core._TMDB_BONUS_KEYWORD_RES if rx.search("trailerpark boys")]
        self.assertEqual(colles_trailer, [], f"un mot-cle matche a l'interieur de 'trailerpark' : {colles_trailer}")

        # Contre-epreuve : isole par des espaces, le mot-cle DOIT matcher, sinon
        # le test ci-dessus serait satisfait par un regex qui ne matche jamais.
        self.assertTrue(
            any(rx.search("inception promo reel") for rx in core._TMDB_BONUS_KEYWORD_RES),
            "un mot-cle isole doit toujours etre detecte",
        )

    def test_neutralisation_selective_par_mot_cle(self) -> None:
        """Un mot-cle present dans la requete ne desarme QUE lui-meme.

        Sinon chercher « Trailer Park Boys » reactiverait aussi 'making of',
        'behind the scenes', etc., et un vrai bonus redeviendrait candidat.
        """
        tmdb = _FakeTmdb(
            [
                _result(222, "Trailer Park Boys: The Movie", 2006),
                _result(999, "Trailer Park Boys: Behind the Scenes", 2006),
            ]
        )
        candidats = core.build_candidates_from_tmdb(tmdb, "Trailer Park Boys The Movie", 2006, "fr-FR")
        ids = [c.tmdb_id for c in candidats]

        self.assertIn(222, ids, "le film cherche doit rester candidat")
        self.assertNotIn(
            999,
            ids,
            "'behind the scenes' n'est pas dans la requete : ce mot-cle doit continuer d'ecarter le bonus",
        )

    def test_vrai_bonus_reste_filtre(self) -> None:
        """NON-REGRESSION : l'intention d'origine du filtre doit rester intacte."""
        tmdb = _FakeTmdb(
            [
                _result(1, "Inception: Behind the Scenes", 2010),
                _result(2, "Inception Trailer", 2010),
                _result(3, "Inception - Making Of", 2010),
            ]
        )
        candidats = core.build_candidates_from_tmdb(tmdb, "Inception", 2010, "fr-FR")

        self.assertEqual(
            [c.tmdb_id for c in candidats],
            [],
            "les vrais bonus (mots-cles isoles) doivent toujours etre ecartes",
        )

    def test_film_normal_toujours_accepte(self) -> None:
        """NON-REGRESSION : le chemin nominal ne bouge pas."""
        tmdb = _FakeTmdb([_result(27205, "Inception", 2010)])
        candidats = core.build_candidates_from_tmdb(tmdb, "Inception", 2010, "fr-FR")
        self.assertTrue(candidats)
        self.assertEqual(candidats[0].tmdb_id, 27205)


if __name__ == "__main__":
    unittest.main(verbosity=2)
