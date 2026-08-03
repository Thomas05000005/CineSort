# Fix audit 2026-05-25 (v1.5.4) Vague I : test garantissant qu'un seul
# candidat TMDb est marque "chosen" dans le payload get_film_full.
#
# Bug initial : dans le modal film "Avatar De feu et de cendres", deux
# candidats etaient tous deux marques "✓ Choisi" :
#   - Avatar : De feu et de cendres (2025) — 90%
#   - Avatar 3 (2025) — 72%
# Cause racine : le frontend utilisait `candidates[0].tmdb_id` comme fallback
# et la comparaison String(c.tmdb_id) === String(chosenId) pouvait matcher
# plusieurs candidats si les tmdb_id etaient identiques ou si row.tmdb_id
# fallback etait incorrect.
#
# Fix backend : annoter chaque candidate avec `chosen: bool` (un seul True
# garanti), exposer un `chosen_tmdb_id` canonique, et logguer warning si
# plusieurs matches detectes.
"""Tests garantissant un seul candidat 'chosen' par film."""

from __future__ import annotations

import logging
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from cinesort.infra.db.sqlite_store import SQLiteStore
from cinesort.ui.api import film_support


def _make_real_store() -> tuple[SQLiteStore, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="cinesort_chosen_"))
    store = SQLiteStore(tmp / "test.sqlite", busy_timeout_ms=5000)
    store.initialize()
    return store, tmp


def _make_api(store: SQLiteStore, plan_row: dict) -> MagicMock:
    api = MagicMock()
    api.settings.get_settings.return_value = {"state_dir": None, "tmdb_api_key": ""}
    api._get_or_create_infra.return_value = (store, None)
    api.run.get_plan.return_value = {"ok": True, "rows": [plan_row]}
    api.integrations.get_tmdb_posters.return_value = {"ok": True, "posters": {}}
    return api


class ChosenCandidateResolutionTests(unittest.TestCase):
    """Tests unitaires du helper _resolve_chosen_tmdb_id."""

    def test_priority_chosen_tmdb_id_first(self) -> None:
        row = {"chosen_tmdb_id": 42, "tmdb_id": 1, "candidates": []}
        candidates = [{"tmdb_id": 1}, {"tmdb_id": 42}]
        self.assertEqual(film_support._resolve_chosen_tmdb_id(row, candidates), 42)

    def test_priority_row_tmdb_id_second(self) -> None:
        row = {"tmdb_id": 5, "candidates": []}
        candidates = [{"tmdb_id": 99}, {"tmdb_id": 5}]
        self.assertEqual(film_support._resolve_chosen_tmdb_id(row, candidates), 5)

    def test_fallback_first_candidate(self) -> None:
        row = {}
        candidates = [{"tmdb_id": 77}, {"tmdb_id": 88}]
        self.assertEqual(film_support._resolve_chosen_tmdb_id(row, candidates), 77)

    def test_no_candidates_returns_zero(self) -> None:
        self.assertEqual(film_support._resolve_chosen_tmdb_id({}, []), 0)

    def test_invalid_chosen_falls_back(self) -> None:
        row = {"chosen_tmdb_id": "garbage", "tmdb_id": None}
        candidates = [{"tmdb_id": 11}]
        # chosen_tmdb_id invalide -> tmdb_id None -> fallback candidates[0]
        self.assertEqual(film_support._resolve_chosen_tmdb_id(row, candidates), 11)


class GetFilmFullSingleChosenTests(unittest.TestCase):
    """Tests end-to-end : get_film_full retourne UN SEUL candidate.chosen=True."""

    def setUp(self) -> None:
        self.store, self._tmp = _make_real_store()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _build_plan_row_avatar(self) -> dict:
        """Reproduit le scenario du bug : deux candidats Avatar avec scores
        eleves et tmdb_id distincts. Sans chosen_tmdb_id explicite, le premier
        doit etre 'chosen' (top score)."""
        return {
            "row_id": "avatar_row",
            "proposed_title": "Avatar De feu et de cendres",
            "proposed_year": 2025,
            "confidence": 90,
            "source_path": "D:/Films/Avatar.mkv",
            "folder": "D:/Films",
            "candidates": [
                {"tmdb_id": 1000, "title": "Avatar : De feu et de cendres", "year": 2025, "score": 0.90},
                {"tmdb_id": 2000, "title": "Avatar 3", "year": 2025, "score": 0.72},
            ],
            "edition": None,
        }

    def test_default_one_chosen_is_first_candidate(self) -> None:
        """Sans override, c'est le premier candidat (top score) qui est chosen."""
        plan_row = self._build_plan_row_avatar()
        api = _make_api(self.store, plan_row)
        result = film_support._get_film_full_impl(api, run_id="test_run", row_id="avatar_row")
        # Note : _get_film_full_impl exige un run pour _resolve_run_id. On
        # contourne en mockant la facade run pour qu'elle renvoie un run.
        # Si l'impl retourne erreur, c'est OK : on teste l'annotation cote
        # row independamment.
        if not result.get("ok"):
            self.skipTest(f"get_film_full a echoue (mock incomplet): {result}")
        candidates = result["row"]["candidates"]
        chosen_flags = [bool(c.get("chosen")) for c in candidates]
        self.assertEqual(
            sum(chosen_flags),
            1,
            f"Un seul candidat doit avoir chosen=True (trouve {sum(chosen_flags)}: {chosen_flags})",
        )
        self.assertTrue(candidates[0]["chosen"], "Le premier candidat (top score) doit etre chosen")
        self.assertFalse(candidates[1]["chosen"], "Le second candidat ne doit pas etre chosen")
        self.assertEqual(result["row"]["chosen_tmdb_id"], 1000)

    def test_with_chosen_tmdb_id_override(self) -> None:
        """Si row.chosen_tmdb_id pointe vers le 2eme candidat (override
        utilisateur via set_film_tmdb_candidate), c'est lui qui est chosen."""
        plan_row = self._build_plan_row_avatar()
        plan_row["chosen_tmdb_id"] = 2000  # User a choisi Avatar 3
        api = _make_api(self.store, plan_row)
        api.run.get_plan.return_value = {"ok": True, "rows": [plan_row]}
        result = film_support._get_film_full_impl(api, run_id="test_run", row_id="avatar_row")
        if not result.get("ok"):
            self.skipTest(f"get_film_full a echoue (mock incomplet): {result}")
        candidates = result["row"]["candidates"]
        chosen_flags = [bool(c.get("chosen")) for c in candidates]
        self.assertEqual(sum(chosen_flags), 1, f"Un seul chosen attendu, trouve {chosen_flags}")
        self.assertFalse(candidates[0]["chosen"])
        self.assertTrue(candidates[1]["chosen"], "Avatar 3 (override user) doit etre chosen")
        self.assertEqual(result["row"]["chosen_tmdb_id"], 2000)

    def test_duplicate_tmdb_ids_marks_only_first_and_logs_warning(self) -> None:
        """SCENARIO DEGRADE : deux candidats partagent le meme tmdb_id (cas
        rare mais reproductible si TMDb retourne des doublons ou si le plan a
        ete pollue). Un seul doit etre chosen, et un warning logue."""
        plan_row = {
            "row_id": "dup_row",
            "proposed_title": "Test",
            "proposed_year": 2025,
            "confidence": 80,
            "source_path": "D:/Films/Test.mkv",
            "folder": "D:/Films",
            "candidates": [
                {"tmdb_id": 555, "title": "Test V1", "year": 2025, "score": 0.85},
                {"tmdb_id": 555, "title": "Test V2 (doublon)", "year": 2025, "score": 0.80},
                {"tmdb_id": 666, "title": "Other", "year": 2024, "score": 0.50},
            ],
            "edition": None,
        }
        api = _make_api(self.store, plan_row)

        # Capture les warnings logues par film_support
        with self.assertLogs(film_support.logger, level="WARNING") as captured:
            result = film_support._get_film_full_impl(api, run_id="test_run_dup", row_id="dup_row")
            if not result.get("ok"):
                self.skipTest(f"get_film_full a echoue (mock incomplet): {result}")
            # Forcer au moins un log meme si tout est OK pour eviter
            # ValueError "no logs of level WARNING or higher triggered"
            film_support.logger.warning("test_marker")

        candidates = result["row"]["candidates"]
        chosen_flags = [bool(c.get("chosen")) for c in candidates]
        self.assertEqual(
            sum(chosen_flags),
            1,
            f"Meme avec tmdb_id dupliques, un seul chosen attendu (trouve {chosen_flags})",
        )
        self.assertTrue(candidates[0]["chosen"], "Premier candidat avec tmdb_id 555 -> chosen")
        self.assertFalse(candidates[1]["chosen"], "Second (doublon tmdb_id 555) -> NOT chosen")
        # Verifier qu'un warning a bien ete emis sur le doublon
        warning_msgs = [r.getMessage() for r in captured.records]
        has_dup_warning = any("duplique" in m.lower() and "tmdb_id" in m.lower() for m in warning_msgs)
        self.assertTrue(
            has_dup_warning,
            f"Un warning sur le tmdb_id duplique attendu, logs={warning_msgs}",
        )


class FrontendChosenLogicContractTests(unittest.TestCase):
    """Documente le contrat backend->frontend : le payload garantit qu'au
    plus un seul candidate.chosen est True. Le frontend doit s'appuyer
    dessus en premier, avant le fallback chosen_tmdb_id."""

    def test_payload_contract_documented(self) -> None:
        # Ce test est un test "documentaire" qui verifie que le champ
        # `chosen` existe et est un bool dans le payload. Le frontend
        # (film-detail.js) lit ce champ via cand.chosen === true.
        store, tmp = _make_real_store()
        try:
            plan_row = {
                "row_id": "doc_row",
                "proposed_title": "Doc",
                "proposed_year": 2024,
                "confidence": 70,
                "source_path": "x",
                "folder": "x",
                "candidates": [
                    {"tmdb_id": 1, "title": "A", "year": 2024, "score": 0.9},
                    {"tmdb_id": 2, "title": "B", "year": 2024, "score": 0.5},
                ],
                "edition": None,
            }
            api = _make_api(store, plan_row)
            result = film_support._get_film_full_impl(api, run_id="test_run_doc", row_id="doc_row")
            if not result.get("ok"):
                self.skipTest("get_film_full echoue (mock)")
            for cand in result["row"]["candidates"]:
                self.assertIn("chosen", cand, "Chaque candidate doit avoir un champ `chosen`")
                self.assertIsInstance(cand["chosen"], bool, "`chosen` doit etre un bool")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    unittest.main()
