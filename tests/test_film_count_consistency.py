# Fix audit 2026-05-25 (v1.5.4) Vague I : test de consistance du compteur
# "nombre de films" entre les differents endpoints UI.
#
# Bug initial : Accueil/Qualite/Bibliotheque/Apply affichaient 853 films alors
# que les etapes Validation/Doublons affichaient 855. Cause racine : certains
# endpoints utilisaient stats.planned_rows (snapshot DB potentiellement obsolete
# si plan.jsonl a ete reecrit), d'autres utilisaient len(rows) charge live
# depuis plan.jsonl.
#
# Fix : tous les endpoints alignes sur la source unique de verite =
# count_plan_rows(plan.jsonl) (run_data_support.py).
"""Tests de consistance du compteur de films entre endpoints UI."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import cinesort.ui.api.cinesort_api as backend
from cinesort.ui.api.run_data_support import count_plan_rows


class FilmCountConsistencyTests(unittest.TestCase):
    """Verifie qu'un meme run retourne le meme total de films sur tous les
    endpoints qui exposent ce compteur."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_count_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.api = backend.CineSortApi()
        self.api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
            }
        )
        self.store, _ = self.api._get_or_create_infra(self.state_dir)  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_row(self, rid: str, title: str, year: int = 2020) -> dict:
        return {
            "row_id": rid,
            "kind": "single",
            "folder": str(self.root / title),
            "video": str(self.root / title / f"{title}.mkv"),
            "proposed_title": title,
            "proposed_year": year,
            "proposed_source": "name",
            "confidence": 70,
            "confidence_label": "med",
            "candidates": [],
            "notes": "",
        }

    def _write_plan(self, run_id: str, rows: list[dict]) -> None:
        run_dir = self.state_dir / "runs" / f"tri_films_{run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)
        payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
        (run_dir / "plan.jsonl").write_text(payload, encoding="utf-8")

    def _insert_run_done(self, run_id: str, *, planned_rows_snapshot: int) -> None:
        started = time.time() - 60.0
        self.store.run.insert_run_pending(
            run_id=run_id,
            root=str(self.root),
            state_dir=str(self.state_dir),
            config={"tmdb_enabled": False},
            created_ts=started - 2.0,
        )
        self.store.run.mark_run_running(run_id, started_ts=started)
        # On enregistre intentionnellement un snapshot DIFFERENT de la verite
        # du plan.jsonl pour reproduire le bug 853 vs 855.
        self.store.run.mark_run_done(
            run_id,
            stats={"planned_rows": planned_rows_snapshot, "applied_count": 0},
            ended_ts=started + 5.0,
        )

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_count_plan_rows_helper_returns_jsonl_count(self) -> None:
        """Le helper count_plan_rows() retourne le nombre exact de PlanRow
        valides dans plan.jsonl, ignorant les lignes vides ou malformees."""
        run_id = "20260525_120000_001"
        rows = [self._make_row(f"r{i}", f"Film {i}") for i in range(5)]
        self._write_plan(run_id, rows)
        # Ajouter une ligne vide + une ligne malformee pour tester la robustesse
        plan = self.state_dir / "runs" / f"tri_films_{run_id}" / "plan.jsonl"
        with plan.open("a", encoding="utf-8") as f:
            f.write("\n")  # ligne vide
            f.write("not json garbage\n")  # ligne malformee
            f.write('{"no_row_id": "ignored"}\n')  # dict sans row_id -> ignore

        run_paths = self.api._run_paths_for(self.state_dir, run_id, ensure_exists=False)
        self.assertEqual(count_plan_rows(run_paths), 5)

    def test_count_plan_rows_missing_file_returns_fallback(self) -> None:
        """Si plan.jsonl n'existe pas, on retourne le fallback fourni."""
        run_id = "20260525_120000_002"
        # On ne cree pas plan.jsonl
        run_paths = self.api._run_paths_for(self.state_dir, run_id, ensure_exists=True)
        self.assertEqual(count_plan_rows(run_paths, fallback=42), 42)
        self.assertEqual(count_plan_rows(run_paths), 0)

    def test_dashboard_total_movies_aligned_on_plan_jsonl_not_stats_snapshot(self) -> None:
        """REGRESSION BUG 853 vs 855 : si stats.planned_rows en DB diverge du
        nombre reel de PlanRow dans plan.jsonl, le dashboard doit retourner
        len(plan.jsonl) comme source de verite, pas le snapshot DB.
        """
        run_id = "20260525_120000_003"
        # plan.jsonl contient 5 films
        rows = [self._make_row(f"r{i}", f"Film {i}") for i in range(5)]
        self._write_plan(run_id, rows)
        # Mais le snapshot DB dit 3 (simule le bug observe en prod : snapshot
        # fige avant un cross-check qui aurait ajoute des rows).
        self._insert_run_done(run_id, planned_rows_snapshot=3)

        dashboard = self.api._get_dashboard_impl(run_id)
        self.assertTrue(dashboard.get("ok"), dashboard)
        total_movies = int(dashboard.get("kpis", {}).get("total_movies") or 0)
        # AVANT le fix : total_movies == 3 (snapshot DB)
        # APRES le fix : total_movies == 5 (len(rows) reel)
        self.assertEqual(
            total_movies,
            5,
            "total_movies du dashboard doit refleter len(plan.jsonl), pas le snapshot DB obsolete",
        )

    def test_runs_history_total_rows_aligned_on_plan_jsonl(self) -> None:
        """Le compteur des runs dans runs_history (vue Historique) doit aussi
        utiliser plan.jsonl comme source de verite."""
        run_id = "20260525_120000_004"
        rows = [self._make_row(f"r{i}", f"Film {i}") for i in range(7)]
        self._write_plan(run_id, rows)
        self._insert_run_done(run_id, planned_rows_snapshot=4)  # snapshot fausse

        dashboard = self.api._get_dashboard_impl(run_id)
        history = dashboard.get("runs_history") or []
        entry = next((h for h in history if str(h.get("run_id") or "") == run_id), None)
        self.assertIsNotNone(entry, "Le run doit etre dans runs_history")
        assert entry is not None
        self.assertEqual(
            int(entry.get("total_rows") or 0),
            7,
            "runs_history.total_rows doit utiliser plan.jsonl, pas stats.planned_rows",
        )

    def test_history_stats_total_rows_aligned_on_plan_jsonl(self) -> None:
        """get_history_stats (vue Historique detail) doit aussi etre aligne."""
        run_id = "20260525_120000_005"
        rows = [self._make_row(f"r{i}", f"Film {i}") for i in range(9)]
        self._write_plan(run_id, rows)
        self._insert_run_done(run_id, planned_rows_snapshot=2)  # snapshot tres faux

        from cinesort.ui.api import history_support

        result = history_support._get_history_stats_impl(self.api, run_id)
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(
            int(result.get("run", {}).get("total_rows") or 0),
            9,
            "get_history_stats.total_rows doit utiliser plan.jsonl",
        )

    def test_validation_and_dashboard_counts_match(self) -> None:
        """SCENARIO BUG : la vue Validation (qui charge len(get_plan)) et la
        vue Accueil (qui lit dashboard.total_movies) doivent retourner le meme
        nombre, meme si stats.planned_rows en DB est obsolete.
        """
        run_id = "20260525_120000_006"
        # 11 films dans plan.jsonl, snapshot DB ment et dit 9 (delta de 2,
        # exactement le bug observe par l'utilisateur sur 855 vs 853).
        rows = [self._make_row(f"r{i}", f"Film {i}") for i in range(11)]
        self._write_plan(run_id, rows)
        self._insert_run_done(run_id, planned_rows_snapshot=9)

        # Vue Validation : charge le plan brut et compte les rows
        plan_result = self.api.run.get_plan(run_id)
        self.assertTrue(plan_result.get("ok"), plan_result)
        validation_total = len(plan_result.get("rows") or [])

        # Vue Accueil : kpis.total_movies du dashboard
        dashboard = self.api._get_dashboard_impl(run_id)
        self.assertTrue(dashboard.get("ok"), dashboard)
        dashboard_total = int(dashboard.get("kpis", {}).get("total_movies") or 0)

        self.assertEqual(
            validation_total,
            dashboard_total,
            f"Validation ({validation_total}) doit avoir le meme compteur que "
            f"Accueil/Dashboard ({dashboard_total}). C'est exactement le bug "
            f"reproduit : 855 vs 853 sur le meme run.",
        )
        self.assertEqual(validation_total, 11)


if __name__ == "__main__":
    unittest.main()
