"""Tests de regression pour les 8 cas catastrophiques du run 857 films.

Ces tests garantissent que le scoring TMDb ne propose PLUS de renames absurdes
comme "Ca (2017) -> Pirates des Caraibes (2003)". Chaque test reproduit un cas
reel observe en production sur NAS.
"""

from __future__ import annotations

import unittest

import cinesort.domain.core as core


class _FakeTmdbResult:
    """Mock minimal de TmdbResult pour les tests."""

    def __init__(
        self,
        *,
        id: int,
        title: str,
        year: int,
        original_title: str = "",
        popularity: float = 10.0,
        vote_count: int = 100,
        vote_average: float = 7.0,
        poster_path: str = "",
    ):
        self.id = id
        self.title = title
        self.year = year
        self.original_title = original_title or title
        self.popularity = popularity
        self.vote_count = vote_count
        self.vote_average = vote_average
        self.poster_path = poster_path


class _FakeTmdbClient:
    """Mock TmdbClient qui retourne des resultats preconfigures."""

    def __init__(self, results: list):
        self._results = results

    def search_movie(self, query: str, year=None, language: str = "fr-FR", max_results: int = 8):
        return list(self._results[:max_results])


class TmdbScoringRejectsCatastrophicMatchesTests(unittest.TestCase):
    """Les 8 cas catastrophiques du run 20260410_122423_021 ne doivent PAS
    produire de candidats TMDb acceptes (ou doivent etre marques LOW).
    """

    def _build_candidates(self, query: str, year: int, fake_results: list):
        client = _FakeTmdbClient(fake_results)
        return core.build_candidates_from_tmdb(
            tmdb=client,
            query=query,
            year=year,
            language="fr-FR",
        )

    def test_rejects_ca_vs_pirates_des_caraibes(self) -> None:
        """'Ca' (2017) ne doit PAS matcher 'Pirates des Caraibes' (2003)."""
        results = [
            _FakeTmdbResult(
                id=22,
                title="Pirates des Caraibes : La Malediction du Black Pearl",
                year=2003,
                original_title="Pirates of the Caribbean: The Curse of the Black Pearl",
            ),
        ]
        cands = self._build_candidates("Ca", 2017, results)
        self.assertEqual(cands, [], f"Aucun candidat attendu, obtenu : {cands}")

    def test_rejects_bac_nord_vs_norm_of_the_north(self) -> None:
        """'BAC Nord' (2020) ne doit PAS matcher 'Norm of the North' (2019)."""
        results = [
            _FakeTmdbResult(
                id=1,
                title="Norm of the North King Sized Adventure",
                year=2019,
                original_title="Norm of the North: King Sized Adventure",
            ),
        ]
        cands = self._build_candidates("BAC Nord", 2020, results)
        self.assertEqual(cands, [], f"Aucun candidat attendu, obtenu : {cands}")

    def test_rejects_burn_e_vs_swedish_title(self) -> None:
        """'BURN·E' (2008) ne doit PAS matcher un titre suedois aleatoire."""
        results = [
            _FakeTmdbResult(
                id=2,
                title="Finns det ett helvete kommer jag att brinna dar",
                year=2008,
                original_title="Finns det ett helvete kommer jag att brinna dar",
            ),
        ]
        cands = self._build_candidates("BURN·E", 2008, results)
        self.assertEqual(cands, [], f"Aucun candidat attendu, obtenu : {cands}")

    def test_rejects_noe_vs_un_nouveau_depart_noel(self) -> None:
        """'Noe' (2014) ne doit PAS matcher 'Un nouveau depart pour Noel' (2014)."""
        results = [
            _FakeTmdbResult(id=3, title="Un nouveau depart pour Noel", year=2014, original_title="A Christmas Detour"),
        ]
        cands = self._build_candidates("Noe", 2014, results)
        self.assertEqual(cands, [], f"Aucun candidat attendu, obtenu : {cands}")

    def test_filters_bonus_documentary_mutant_watch(self) -> None:
        """'X-Men' ne doit PAS retourner 'X-Men The Mutant Watch' (documentaire promo)."""
        results = [
            _FakeTmdbResult(id=4, title="X-Men The Mutant Watch", year=2000, original_title="X-Men: The Mutant Watch"),
            _FakeTmdbResult(id=36657, title="X-Men", year=2000, original_title="X-Men"),
        ]
        cands = self._build_candidates("X-Men", 2000, results)
        # The Mutant Watch doit etre filtre (keyword), seul X-Men doit rester
        self.assertEqual(len(cands), 1, f"Un seul candidat attendu : {cands}")
        self.assertEqual(cands[0].tmdb_id, 36657)

    def test_short_title_strict_accepts_exact(self) -> None:
        """'Ca' doit accepter un match quasi-exact avec 'Ça'."""
        results = [
            _FakeTmdbResult(id=346364, title="Ça", year=2017, original_title="It"),
        ]
        cands = self._build_candidates("Ca", 2017, results)
        # "Ça" est normalise en "ca" → match parfait → accepte
        self.assertGreaterEqual(len(cands), 1, f"Match quasi-exact attendu : {cands}")

    def test_short_title_strict_rejects_noise(self) -> None:
        """'Ca' ne doit PAS matcher un titre long qui contient 'ca' (ecart annee massif)."""
        results = [
            _FakeTmdbResult(id=289, title="Carmen Miranda Fame", year=1942, original_title="Carmen Miranda Fame"),
        ]
        cands = self._build_candidates("Ca", 2017, results)
        self.assertEqual(cands, [], f"Aucun candidat attendu : {cands}")

    def test_year_delta_heavy_penalty(self) -> None:
        """Un ecart d'annee de 14 ans est fortement penalise."""
        results = [
            # Meme titre, annee tres differente
            _FakeTmdbResult(
                id=5, title="Test Movie Year Mismatch", year=2003, original_title="Test Movie Year Mismatch"
            ),
        ]
        cands = self._build_candidates("Test Movie Year Mismatch", 2017, results)
        if cands:
            # Le candidat a pu passer grace a la similarite textuelle parfaite,
            # mais son score doit etre fortement penalise par le delta annee
            self.assertLess(cands[0].score, 0.80, f"Score trop eleve malgre ecart annee 14 ans : {cands[0]}")


class NfoImdbLookupRejectsPollutedNfoTests(unittest.TestCase):
    """Le NFO pollue qui pointe vers un IMDb ID different du film doit etre rejete.
    Test statique sur le code source : le bloc de verification post-lookup existe.
    """

    def test_plan_support_has_post_imdb_lookup_verification(self) -> None:
        """Le code source de plan_support.py doit verifier la similarite apres IMDb lookup."""
        from pathlib import Path

        src = Path("cinesort/app/plan_support.py").read_text(encoding="utf-8")
        # Les patterns du fix doivent etre presents
        self.assertIn("find_by_imdb_id", src)
        # Verification de similarite apres lookup
        self.assertIn("_title_similarity", src)
        self.assertIn("NFO IMDb lookup rejete", src)
        self.assertIn("NFO probablement pollue", src)


class CollectionBoostRequiresTextualProofTests(unittest.TestCase):
    """FIX 6 : la collection TMDb n'est associee que si le nom de la saga
    partage un mot significatif avec le dossier source ou le titre.
    """

    def test_plan_support_has_collection_token_check(self) -> None:
        """Le code source verifie que la collection partage au moins un mot avec le folder."""
        from pathlib import Path

        src = Path("cinesort/app/plan_support.py").read_text(encoding="utf-8")
        self.assertIn("pas de mot commun avec", src)
        self.assertIn("Collection", src)


class ConfidenceHonestyTests(unittest.TestCase):
    """FIX 7 : la confiance affichee ne peut pas etre 'med' si la similarite
    reelle est inferieure a 0.60.
    """

    def test_low_similarity_caps_confidence_below_med(self) -> None:
        from cinesort.domain.core import Candidate, compute_confidence, Config
        from pathlib import Path

        cand_low = Candidate(
            title="Pirates des Caraibes",
            year=2003,
            source="tmdb",
            tmdb_id=22,
            score=0.95,  # Score interne haut (bonus bonus)
            note="sim=0.10, dY=14",  # Mais sim reelle = 0.10
        )
        cfg = Config(root=Path("/tmp"), enable_tmdb=True)
        score, label = compute_confidence(cfg, cand_low, nfo_ok=False, year_delta_reject=False, tmdb_used=True)
        self.assertLess(score, 60, f"Score trop eleve avec sim=0.10 : {score}")
        self.assertEqual(label, "low")

    def test_moderate_similarity_capped_below_med(self) -> None:
        from cinesort.domain.core import Candidate, compute_confidence, Config
        from pathlib import Path

        cand_mid = Candidate(
            title="X-Men The Mutant Watch",
            year=2000,
            source="tmdb",
            tmdb_id=4,
            score=0.80,
            note="sim=0.45, dY=0",  # Similarite 0.45 < 0.60
        )
        cfg = Config(root=Path("/tmp"), enable_tmdb=True)
        score, label = compute_confidence(cfg, cand_mid, nfo_ok=False, year_delta_reject=False, tmdb_used=True)
        # Cap a 59 minimum
        self.assertLess(score, 60)


if __name__ == "__main__":
    unittest.main(verbosity=2)
