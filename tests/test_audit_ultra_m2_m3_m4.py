"""AUDIT ULTRA 2026-07-15 — M2 / M3 / M4 : concepts a predicats divergents.

M2 "film non identifie" : la carte Accueil (librarian, section D) rendait un
    verdict OPPOSE au chip Bibliotheque (_row_unidentified) sur le meme film.
    Fix : une seule definition (domain.librarian.row_unidentified), les 2
    surfaces la partagent.

M3 "basse confiance" : 3 seuils (KPI 50, drill-down 50 inclusif, canonique 60).
    Fix : unifier sur CONF_MEDIUM=60, en gardant l'exclusion de conf==0.

M4 "doublons" : les episodes TV etaient comptes par le badge (dashboard_support)
    ET le chip (library_support) alors que le detecteur reel les EXCLUT
    (duplicate_support.find_duplicate_targets : skip kind=="tv_episode").
    Fix : propager le meme filtre aux 2 surfaces de comptage.

Chaque test ECHOUE sur le code d'avant le fix et PASSE apres.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from cinesort.domain import librarian
from cinesort.domain.confidence_thresholds import CONF_MEDIUM
from cinesort.domain.librarian import generate_suggestions, resolve_tmdb_id, row_unidentified
from cinesort.ui.api import library_support
from cinesort.ui.api.dashboard_support import (
    _count_duplicate_films,
    _is_low_confidence_identification,
)
from cinesort.ui.api.library_support import _count_duplicates_and_sagas, _row_unidentified


class _Row:
    """Stub PlanRow : generate_suggestions / compteurs lisent via getattr."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Cand:
    """Stub core.Candidate : le resolveur domaine lit tmdb_id/score via getattr."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FakeStore:
    """Store minimal pour piloter library_support._build_library_rows sans DB.

    Les surfaces optionnelles (perceptual / quality) renvoient vide ; l'absence de
    film_modal fait retomber overlay_tmdb_override sur son no-op (AttributeError
    capturee) — donc AUCUN override n'ecrase le tmdb_id resolu depuis les candidats.
    """

    class _Empty:
        def list_perceptual_reports(self, run_id=None):
            return []

        def list_quality_reports(self, run_id=None):
            return []

    def __init__(self):
        self.perceptual = self._Empty()
        self.quality = self._Empty()


class _FakeApi:
    """api minimal : seules settings/get_settings, _get_or_create_infra et
    run.get_plan sont sollicitees ; posters TMDb et migration legacy echouent
    proprement (except captures) sans toucher au filesystem/DB reels."""

    class _Settings:
        def get_settings(self):
            return {}

    class _Run:
        def __init__(self, rows):
            self._rows = rows

        def get_plan(self, run_id):
            return {"ok": True, "rows": self._rows}

    def __init__(self, plan_rows):
        self.settings = self._Settings()
        self.run = self._Run(plan_rows)

    def _get_or_create_infra(self, state_dir):
        return (_FakeStore(), None)


def _unidentified_details(rows):
    res = generate_suggestions(rows, [], {"subtitle_expected_languages": ["fr"]})
    for sug in res.get("suggestions", []):
        if sug.get("id") == "unidentified":
            return set(sug.get("details", []))
    return set()


# ---------------------------------------------------------------------------
# M2 — un seul predicat "non identifie"
# ---------------------------------------------------------------------------
class M2SingleDefinitionTests(unittest.TestCase):
    def test_library_predicate_is_the_domain_definition(self) -> None:
        # library_support._row_unidentified est un ALIAS de la definition unique.
        self.assertIs(_row_unidentified, row_unidentified)
        self.assertIs(_row_unidentified, librarian.row_unidentified)

    def test_librarian_uses_tmdb_shortcut(self) -> None:
        # tmdb_id resolu => identifie, MEME si source vide/unknown et conf 0.
        # AVANT (librarian section D : `src in ("unknown","") or conf==0`) : compte
        # a tort ce film comme non identifie -> divergence avec le chip biblio.
        rows = [
            _Row(
                row_id="a",
                proposed_title="Alpha",
                tmdb_id=550,
                proposed_source="unknown",
                confidence=0,
                proposed_year=0,
            )
        ]
        self.assertNotIn("Alpha", _unidentified_details(rows))

    def test_librarian_honours_confidence_threshold(self) -> None:
        # source fiable mais confiance < CONF_MEDIUM => non identifie.
        # AVANT : `conf==0` seulement -> conf 45 NON compte (faux negatif).
        rows = [
            _Row(
                row_id="b",
                proposed_title="Bravo",
                tmdb_id=None,
                proposed_source="name",
                confidence=45,
                proposed_year=2019,
            )
        ]
        self.assertIn("Bravo", _unidentified_details(rows))

    def test_librarian_honours_missing_year(self) -> None:
        # source fiable + confiance forte mais AUCUNE annee => non identifie.
        # AVANT : annee ignoree -> NON compte (faux negatif).
        rows = [
            _Row(row_id="e", proposed_title="Echo", tmdb_id=None, proposed_source="nfo", confidence=90, proposed_year=0)
        ]
        self.assertIn("Echo", _unidentified_details(rows))

    def test_librarian_identified_nfo_not_flagged(self) -> None:
        rows = [
            _Row(
                row_id="c",
                proposed_title="Charlie",
                tmdb_id=None,
                proposed_source="nfo",
                confidence=87,
                proposed_year=1957,
            )
        ]
        self.assertNotIn("Charlie", _unidentified_details(rows))

    def test_parity_librarian_vs_chip_on_same_film(self) -> None:
        # Parite du PREDICAT partage lorsqu'on lui passe des champs DEJA resolus.
        # NB : ce cas injecte le meme tmdb_id des 2 cotes -> il ne couvre PAS la
        # divergence reelle (resolution depuis les candidats). Celle-ci est testee
        # par M2CandidateResolutionParityTests ci-dessous, qui laisse chaque
        # surface resoudre le tmdb_id elle-meme a partir des candidats.
        for tmdb_id, src, conf, year in [
            (550, "unknown", 0, 0),  # tmdb shortcut -> identifie
            (None, "name", 45, 2019),  # conf basse -> non identifie
            (None, "nfo", 90, 0),  # annee absente -> non identifie
            (None, "nfo", 87, 1957),  # identifie
        ]:
            plan = _Row(tmdb_id=tmdb_id, proposed_source=src, confidence=conf, proposed_year=year)
            lib = {"tmdb_id": tmdb_id, "proposed_source": src, "confidence": conf, "year": year}
            librarian_verdict = row_unidentified(
                {
                    "tmdb_id": getattr(plan, "tmdb_id", None),
                    "proposed_source": getattr(plan, "proposed_source", None),
                    "confidence": getattr(plan, "confidence", 0),
                    "proposed_year": getattr(plan, "proposed_year", 0),
                }
            )
            self.assertEqual(librarian_verdict, _row_unidentified(lib))


# ---------------------------------------------------------------------------
# M2 (suivi) — parite REELLE : chaque surface resout le tmdb_id depuis les
# candidats, on n'injecte JAMAIS le tmdb_id resolu a la main.
# ---------------------------------------------------------------------------
class M2CandidateResolutionParityTests(unittest.TestCase):
    """Le tmdb_id vit sur les Candidate enfants, PAS au top-level du PlanRow.

    Avant le fix, la carte Accueil (section D) lisait `getattr(row, "tmdb_id")`
    = None (toujours, apres scan) tandis que le chip Bibliotheque resolvait le
    meilleur candidat -> verdicts OPPOSES sur un film identifie uniquement par un
    candidat TMDb. Ces tests ECHOUENT avant le fix (Accueil flaggue "non
    identifie", chip dit "identifie") et PASSENT apres (les 2 resolvent depuis les
    candidats). AUCUN tmdb_id resolu n'est injecte : on ne fournit que candidates.
    """

    # Film SANS identite top-level fiable (source vide, conf 0, aucune annee) mais
    # AVEC un candidat TMDb haute confiance -> le tmdb_id resolu doit suffire.
    RID = "cand1"
    TITLE = "FallbackFilm"
    TMDB = 603
    SCORE = 0.9

    def _plan_dict(self):
        return {
            "row_id": self.RID,
            "proposed_title": self.TITLE,
            "proposed_year": 0,
            "proposed_source": "",
            "confidence": 0,
            "kind": "single",
            "tmdb_id": None,  # top-level TOUJOURS None apres scan
            "candidates": [{"tmdb_id": self.TMDB, "score": self.SCORE}],
        }

    def _plan_row(self):
        # Candidats en OBJETS (mirroir de core.Candidate charge par
        # _load_rows_from_plan_jsonl), pour exercer la branche getattr du resolveur.
        return _Row(
            row_id=self.RID,
            proposed_title=self.TITLE,
            proposed_year=0,
            proposed_source="",
            confidence=0,
            tmdb_id=None,
            candidates=[_Cand(tmdb_id=self.TMDB, score=self.SCORE)],
        )

    def test_setup_is_not_identifiable_without_candidate(self) -> None:
        # Garde anti-tautologie : sans la resolution, ce film EST "non identifie"
        # (le raccourci tmdb_id ne peut venir QUE des candidats).
        raw = {"tmdb_id": None, "proposed_source": "", "confidence": 0, "proposed_year": 0}
        self.assertTrue(row_unidentified(raw))

    def test_accueil_identifies_via_candidate(self) -> None:
        # Accueil (generate_suggestions -> resolve_tmdb_id) : NON flaggue.
        self.assertNotIn(self.TITLE, _unidentified_details([self._plan_row()]))

    def test_chip_identifies_via_candidate(self) -> None:
        # Chip (library_support._build_library_rows) pilote reel via fake api :
        # le tmdb_id resolu = candidat, et identified == True.
        rows = library_support._build_library_rows(_FakeApi([self._plan_dict()]), "run1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tmdb_id"], self.TMDB)
        self.assertTrue(rows[0]["identified"])

    def test_accueil_and_chip_agree(self) -> None:
        # Parite reelle : les 2 surfaces, alimentees par les MEMES candidats (et
        # non par un tmdb_id pre-resolu), rendent le MEME verdict "identifie".
        accueil_unidentified = self.TITLE in _unidentified_details([self._plan_row()])
        chip_rows = library_support._build_library_rows(_FakeApi([self._plan_dict()]), "run1")
        chip_unidentified = not chip_rows[0]["identified"]
        self.assertEqual(accueil_unidentified, chip_unidentified)
        self.assertFalse(accueil_unidentified)  # les deux : identifie

    def test_low_score_candidate_stays_unidentified(self) -> None:
        # Symetrie du seuil : un candidat sous 0.7 n'auto-resolve PAS -> non
        # identifie sur les 2 surfaces (pas de faux positif d'identification).
        plan = self._plan_dict()
        plan["candidates"] = [{"tmdb_id": self.TMDB, "score": 0.65}]
        row = self._plan_row()
        row.candidates = [_Cand(tmdb_id=self.TMDB, score=0.65)]
        self.assertIn(self.TITLE, _unidentified_details([row]))
        chip_rows = library_support._build_library_rows(_FakeApi([plan]), "run1")
        self.assertFalse(chip_rows[0]["identified"])


class M2ResolveTmdbIdUnitTests(unittest.TestCase):
    """Le resolveur domaine resolve_tmdb_id (miroir du chip)."""

    def test_top_level_takes_precedence(self) -> None:
        row = _Row(tmdb_id=42, candidates=[_Cand(tmdb_id=99, score=0.99)])
        self.assertEqual(resolve_tmdb_id(row), 42)

    def test_falls_back_to_best_scoring_candidate(self) -> None:
        row = _Row(
            tmdb_id=None,
            candidates=[
                _Cand(tmdb_id=11, score=0.72),
                _Cand(tmdb_id=22, score=0.95),
                _Cand(tmdb_id=33, score=0.80),
            ],
        )
        self.assertEqual(resolve_tmdb_id(row), 22)

    def test_threshold_is_0_7(self) -> None:
        self.assertIsNone(resolve_tmdb_id(_Row(tmdb_id=None, candidates=[_Cand(tmdb_id=7, score=0.69)])))
        self.assertEqual(resolve_tmdb_id(_Row(tmdb_id=None, candidates=[_Cand(tmdb_id=7, score=0.70)])), 7)

    def test_candidate_without_tmdb_id_ignored(self) -> None:
        row = _Row(
            tmdb_id=None,
            candidates=[
                _Cand(tmdb_id=None, score=0.99),
                _Cand(tmdb_id=0, score=0.99),
                _Cand(tmdb_id=8, score=0.75),
            ],
        )
        self.assertEqual(resolve_tmdb_id(row), 8)

    def test_no_candidates_returns_none(self) -> None:
        self.assertIsNone(resolve_tmdb_id(_Row(tmdb_id=None, candidates=[])))
        self.assertIsNone(resolve_tmdb_id(_Row(tmdb_id=None)))

    def test_dict_candidates_supported(self) -> None:
        # Symetrie avec le resolveur du chip qui lit des candidats dict.
        row = _Row(tmdb_id=None, candidates=[{"tmdb_id": 5, "score": 0.8}])
        self.assertEqual(resolve_tmdb_id(row), 5)


# ---------------------------------------------------------------------------
# M3 — seuil "basse confiance" unifie sur CONF_MEDIUM (60)
# ---------------------------------------------------------------------------
class M3LowConfidenceThresholdTests(unittest.TestCase):
    def test_canonical_threshold_is_60(self) -> None:
        self.assertEqual(CONF_MEDIUM, 60)

    def test_zero_confidence_excluded(self) -> None:
        # conf==0 = "non identifie" (couvert par films_not_identified), pas "basse".
        self.assertFalse(_is_low_confidence_identification(_Row(confidence=0)))

    def test_fifty_five_is_low_confidence(self) -> None:
        # AVANT (seuil 50) : 55 NON compte. APRES (CONF_MEDIUM=60) : compte.
        self.assertTrue(_is_low_confidence_identification(_Row(confidence=55)))

    def test_fifty_is_low_confidence(self) -> None:
        # AVANT (`< 50`) : 50 exclu. APRES (`< 60`) : inclus.
        self.assertTrue(_is_low_confidence_identification(_Row(confidence=50)))

    def test_boundary_at_conf_medium(self) -> None:
        self.assertTrue(_is_low_confidence_identification(_Row(confidence=CONF_MEDIUM - 1)))
        self.assertFalse(_is_low_confidence_identification(_Row(confidence=CONF_MEDIUM)))
        self.assertFalse(_is_low_confidence_identification(_Row(confidence=85)))


class M3DrilldownAlignmentTests(unittest.TestCase):
    """La drill-down Bibliotheque doit produire le MEME intervalle que le KPI."""

    @classmethod
    def setUpClass(cls) -> None:
        repo = Path(__file__).resolve().parents[1]
        cls.js = (repo / "web" / "dashboard" / "views" / "bibliotheque.js").read_text(encoding="utf-8")

    def test_low_confidence_filter_bounds(self) -> None:
        # Filtres backend INCLUSIFS -> [1, 59] == "0 < confidence < 60".
        self.assertIn("_state.advanced.confidence_min = 1;", self.js)
        self.assertIn("_state.advanced.confidence_max = 59;", self.js)

    def test_old_bound_50_removed(self) -> None:
        # L'ancien seuil desaligne (confidence_max=50 sans borne basse) est parti.
        self.assertNotIn("_state.advanced.confidence_max = 50;", self.js)


# ---------------------------------------------------------------------------
# M4 — episodes TV exclus des DEUX compteurs de doublons (miroir detecteur)
# ---------------------------------------------------------------------------
class M4BadgeDuplicatesTests(unittest.TestCase):
    """Badge sidebar (dashboard_support._count_duplicate_films)."""

    def test_two_movies_same_title_year_count_as_duplicates(self) -> None:
        rows = [
            _Row(kind="single", proposed_title="Dune", proposed_year=2021),
            _Row(kind="single", proposed_title="Dune", proposed_year=2021),
        ]
        self.assertEqual(_count_duplicate_films(rows), 2)

    def test_tv_episodes_are_not_duplicates(self) -> None:
        # AVANT : 6 episodes meme titre+annee -> badge annonce 6 doublons que
        # l'ecran Doublons ne montre jamais. APRES : 0.
        rows = [_Row(kind="tv_episode", proposed_title="A Knight", proposed_year=2001) for _ in range(6)]
        self.assertEqual(_count_duplicate_films(rows), 0)

    def test_single_sharing_titleyear_with_tv_episodes_not_counted(self) -> None:
        # 1 vrai film + 2 episodes qui partagent son titre+annee : le film seul
        # n'est PAS un doublon. AVANT : les 3 partageaient la cle -> 3 comptes.
        rows = [
            _Row(kind="single", proposed_title="X", proposed_year=2020),
            _Row(kind="tv_episode", proposed_title="X", proposed_year=2020),
            _Row(kind="tv_episode", proposed_title="X", proposed_year=2020),
        ]
        self.assertEqual(_count_duplicate_films(rows), 0)

    def test_real_movies_still_counted_alongside_tv(self) -> None:
        rows = [
            _Row(kind="single", proposed_title="Y", proposed_year=2021),
            _Row(kind="single", proposed_title="Y", proposed_year=2021),
            _Row(kind="tv_episode", proposed_title="Z", proposed_year=2019),
            _Row(kind="tv_episode", proposed_title="Z", proposed_year=2019),
            _Row(kind="tv_episode", proposed_title="Z", proposed_year=2019),
        ]
        self.assertEqual(_count_duplicate_films(rows), 2)


class M4ChipDuplicatesTests(unittest.TestCase):
    """Chip Bibliotheque (library_support._count_duplicates_and_sagas)."""

    def test_two_single_movies_are_duplicates(self) -> None:
        rows = [
            {"title": "Dune", "year": 2021, "kind": "single"},
            {"title": "Dune", "year": 2021, "kind": "single"},
        ]
        in_dup, _sagas = _count_duplicates_and_sagas(rows)
        self.assertEqual(in_dup, 2)

    def test_tv_episodes_excluded_from_chip(self) -> None:
        # AVANT : 3 episodes meme titre+annee -> chip "Dans doublons" = 3.
        rows = [
            {"title": "Serie", "year": 2010, "kind": "tv_episode"},
            {"title": "Serie", "year": 2010, "kind": "tv_episode"},
            {"title": "Serie", "year": 2010, "kind": "tv_episode"},
        ]
        in_dup, _sagas = _count_duplicates_and_sagas(rows)
        self.assertEqual(in_dup, 0)

    def test_sagas_count_unchanged_for_tv(self) -> None:
        # Le filtre tv_episode ne touche QUE le comptage doublons : une saga
        # contenant un episode reste comptee dans sagas (pas de sur-exclusion).
        rows = [
            {"title": "Serie", "year": 2010, "kind": "tv_episode", "tmdb_collection_name": "Ma Saga"},
        ]
        in_dup, sagas = _count_duplicates_and_sagas(rows)
        self.assertEqual(in_dup, 0)
        self.assertEqual(sagas, 1)

    def test_library_row_exposes_kind(self) -> None:
        # _build_library_rows doit exposer "kind" pour que le filtre s'applique.
        import inspect

        src = inspect.getsource(library_support._build_library_rows)
        self.assertIn('"kind"', src)


if __name__ == "__main__":
    unittest.main()
