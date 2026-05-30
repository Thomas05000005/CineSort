# Fix audit 2026-05-26 (v1.5.6) Vague L : tests cluster endpoints.
#
# Couvre :
#   - dash-1 : get_global_stats doit rattraper RuntimeError (catch trop etroit
#              avant le fix) et renvoyer {ok:False, error:"global_stats_failed",
#              user_message:...}.
#   - count-1: get_dashboard.kpis.total_movies utilise count_plan_rows(plan.jsonl),
#              pas len(rows). Si rows en memoire diverge du plan.jsonl, la verite
#              c'est plan.jsonl.
#   - count-2: trois endpoints (get_dashboard runs_history / get_history_stats /
#              get_status DB-only) doivent partager le meme fallback quand
#              plan.jsonl est absent. Avant le fix : 3 priorites divergentes.
"""Tests Vague L : durcissement get_global_stats + alignement compteurs."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest import mock

import cinesort.ui.api.cinesort_api as backend
from cinesort.ui.api import dashboard_support, history_support, run_flow_support
from cinesort.ui.api.run_data_support import compute_total_fallback


class GlobalStatsHardeningTests(unittest.TestCase):
    """dash-1 : get_global_stats doit renvoyer un payload structure sur
    n'importe quelle exception (auparavant RuntimeError remontait en HTTP 500)."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_vl_dash1_")
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
        self.store, _ = self.api._get_or_create_infra(self.state_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _seed_run(self, run_id: str) -> None:
        ts = time.time()
        self.store.run.insert_run_pending(
            run_id=run_id, root=str(self.root), state_dir=str(self.state_dir),
            config={}, created_ts=ts - 1,
        )
        self.store.run.mark_run_running(run_id, started_ts=ts)
        self.store.run.mark_run_done(run_id, stats={"planned_rows": 2}, ended_ts=ts + 5)

    def test_global_stats_catches_runtime_error(self) -> None:
        """REGRESSION dash-1 : RuntimeError dans la chaine d'aggregation ne
        doit plus remonter (avant : catch (OSError, KeyError, TypeError,
        ValueError) laissait passer RuntimeError -> HTTP 500)."""
        self._seed_run("20260526_120000_a")

        # On stubbe get_quality_counts_for_runs pour lever RuntimeError au
        # milieu de get_global_stats (apres get_runs_summary, avant tier_data).
        with mock.patch.object(
            self.store.quality, "get_quality_counts_for_runs",
            side_effect=RuntimeError("simulated dependency failure"),
        ):
            result = dashboard_support.get_global_stats(self.api, limit_runs=10)

        self.assertIsInstance(result, dict)
        # AVANT le fix : pas de catch -> exception remonte
        # APRES le fix : payload structure
        self.assertEqual(result.get("ok"), False, result)
        self.assertEqual(result.get("error"), "global_stats_failed", result)
        self.assertIn("user_message", result)
        self.assertTrue(result["user_message"], "user_message doit etre non vide")
        # le detail technique reste accessible pour diagnostic
        self.assertIn("simulated dependency failure", result.get("message", ""))

    def test_global_stats_catches_attribute_error(self) -> None:
        """Verifie qu'AttributeError (autre exception non couverte par l'ancien
        tuple) est aussi rattrapee."""
        self._seed_run("20260526_120000_b")

        with mock.patch.object(
            self.store.quality, "get_global_tier_distribution",
            side_effect=AttributeError("missing method on stub"),
        ):
            result = dashboard_support.get_global_stats(self.api, limit_runs=10)

        self.assertFalse(result.get("ok"), result)
        self.assertEqual(result.get("error"), "global_stats_failed", result)

    def test_global_stats_empty_returns_ok(self) -> None:
        """Cas nominal : aucun run -> ok:True avec payload vide (sanity)."""
        result = dashboard_support.get_global_stats(self.api, limit_runs=10)
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("summary", {}).get("total_runs"), 0)


class DashboardCountAlignmentTests(unittest.TestCase):
    """count-1 : get_dashboard.kpis.total_movies doit etre aligne sur
    count_plan_rows(plan.jsonl), pas len(rows)."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_vl_count1_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api.settings.save_settings(
            {"root": str(self.root), "state_dir": str(self.state_dir), "tmdb_enabled": False}
        )
        self.store, _ = self.api._get_or_create_infra(self.state_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_row(self, rid: str, title: str = "X") -> Dict[str, Any]:
        return {
            "row_id": rid, "kind": "single",
            "folder": str(self.root / title), "video": str(self.root / title / f"{title}.mkv"),
            "proposed_title": title, "proposed_year": 2020,
            "proposed_source": "name", "confidence": 70,
            "confidence_label": "med", "candidates": [], "notes": "",
        }

    def _write_plan(self, run_id: str, rows: list) -> None:
        run_dir = self.state_dir / "runs" / f"tri_films_{run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)
        payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
        (run_dir / "plan.jsonl").write_text(payload, encoding="utf-8")

    def _insert_run(self, run_id: str, planned_snapshot: int) -> None:
        ts = time.time()
        self.store.run.insert_run_pending(
            run_id=run_id, root=str(self.root), state_dir=str(self.state_dir),
            config={}, created_ts=ts - 1,
        )
        self.store.run.mark_run_running(run_id, started_ts=ts)
        self.store.run.mark_run_done(
            run_id, stats={"planned_rows": planned_snapshot}, ended_ts=ts + 5,
        )

    def test_total_movies_reads_plan_jsonl_when_rows_memory_diverges(self) -> None:
        """REGRESSION count-1 : si rows en memoire est tronque (ex: une
        manipulation interne aurait filtre les rows AVANT _build_dashboard_section,
        ou bien rs.rows ne contient qu'un sous-ensemble apres un cleanup),
        total_movies doit refleter plan.jsonl (8) pas len(rows) (3).

        Avant le fix : total_movies = int(len(rows) or stats.planned_rows or 0)
                       -> 3 si rows tronque
        Apres le fix : total_movies = count_plan_rows(run_paths, ...)
                       -> 8 (verite du plan)
        """
        run_id = "20260526_count1_a"
        rows = [self._make_row(f"r{i}", f"Film{i}") for i in range(8)]
        self._write_plan(run_id, rows)
        self._insert_run(run_id, planned_snapshot=8)

        # On force le path "rows tronques" : _build_dashboard_section
        # recoit une liste reduite (simule un bug de chargement). Le compteur
        # doit quand meme valoir 8.
        truncated_rows_objs = self.api._load_rows_from_plan_jsonl(
            self.api._run_paths_for(self.state_dir, run_id, ensure_exists=False)
        )[:3]

        run_row, _store = self.api._find_run_row(run_id)
        run_paths = self.api._run_paths_for(self.state_dir, run_id, ensure_exists=False)
        section = dashboard_support._build_dashboard_section(
            self.api,
            run_id=run_id,
            run_row=run_row,
            run_paths=run_paths,
            store=self.store,
            rows=truncated_rows_objs,
        )
        # AVANT fix : len(rows) = 3
        # APRES fix : count_plan_rows = 8
        self.assertEqual(
            section["kpis"]["total_movies"], 8,
            "total_movies doit refleter plan.jsonl (8), pas len(rows tronque) (3)",
        )


class FallbackAlignmentTests(unittest.TestCase):
    """count-2 : compute_total_fallback() doit donner la meme reponse pour
    les 3 endpoints (dashboard / history / run_flow get_status) quand
    plan.jsonl est absent."""

    def test_fallback_prefers_planned_rows_over_total(self) -> None:
        """Choix senior : stats.planned_rows > run_row.total > 0. Verifie
        que les 3 priorites concordent."""
        run_row = {"total": 855}
        stats_obj = {"planned_rows": 853}
        # stats.planned_rows = 853 plus precis que run_row.total = 855
        # (discover_total).
        self.assertEqual(compute_total_fallback(run_row, stats_obj), 853)

    def test_fallback_falls_back_to_total_when_no_stats(self) -> None:
        """Si stats absent / planned_rows = 0 -> run_row.total."""
        self.assertEqual(compute_total_fallback({"total": 100}, None), 100)
        self.assertEqual(compute_total_fallback({"total": 100}, {}), 100)
        self.assertEqual(compute_total_fallback({"total": 100}, {"planned_rows": 0}), 100)

    def test_fallback_returns_zero_when_nothing(self) -> None:
        """Si tout absent -> 0."""
        self.assertEqual(compute_total_fallback(None, None), 0)
        self.assertEqual(compute_total_fallback({}, {}), 0)
        self.assertEqual(compute_total_fallback({"total": 0}, {"planned_rows": 0}), 0)

    def test_fallback_handles_garbage_input(self) -> None:
        """Inputs deformes (str non-numerique, None, etc) -> 0 sans crash."""
        self.assertEqual(compute_total_fallback({"total": "abc"}, {"planned_rows": "xyz"}), 0)
        self.assertEqual(compute_total_fallback({"total": None}, {"planned_rows": None}), 0)


class DashboardCountAlignedWithStatusTests(unittest.TestCase):
    """count-2 (test obligatoire) : test_dashboard_count_aligned_with_status.

    Verifie que get_dashboard (runs_history.total_rows) et get_status retournent
    la meme valeur pour un meme run, AVEC et SANS plan.jsonl."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_vl_count2_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api.settings.save_settings(
            {"root": str(self.root), "state_dir": str(self.state_dir), "tmdb_enabled": False}
        )
        self.store, _ = self.api._get_or_create_infra(self.state_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_row(self, rid: str, title: str = "X") -> Dict[str, Any]:
        return {
            "row_id": rid, "kind": "single",
            "folder": str(self.root / title), "video": str(self.root / title / f"{title}.mkv"),
            "proposed_title": title, "proposed_year": 2020,
            "proposed_source": "name", "confidence": 70,
            "confidence_label": "med", "candidates": [], "notes": "",
        }

    def _write_plan(self, run_id: str, n: int) -> None:
        run_dir = self.state_dir / "runs" / f"tri_films_{run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)
        rows = [self._make_row(f"r{i}", f"Film{i}") for i in range(n)]
        payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
        (run_dir / "plan.jsonl").write_text(payload, encoding="utf-8")

    def _insert_run(self, run_id: str, planned_snapshot: int, total_db: int) -> None:
        ts = time.time()
        self.store.run.insert_run_pending(
            run_id=run_id, root=str(self.root), state_dir=str(self.state_dir),
            config={}, created_ts=ts - 1,
        )
        self.store.run.mark_run_running(run_id, started_ts=ts)
        # Forcer total separement de planned_rows via update direct (pour
        # tester le fallback divergent quand plan.jsonl absent).
        self.store.run.mark_run_done(
            run_id, stats={"planned_rows": planned_snapshot}, ended_ts=ts + 5,
        )
        # patch direct du champ total (discover_total) pour simuler le bug 853/855
        with self.store._managed_conn() as conn:
            conn.execute("UPDATE runs SET total=? WHERE run_id=?", (total_db, run_id))

    def test_dashboard_runs_history_and_history_stats_align_with_plan_jsonl(self) -> None:
        """AVEC plan.jsonl : les 3 endpoints (dashboard runs_history,
        get_history_stats, get_status DB-only) retournent count_plan_rows."""
        run_id = "20260526_align_a"
        self._write_plan(run_id, n=11)  # verite plan.jsonl = 11
        self._insert_run(run_id, planned_snapshot=9, total_db=12)  # snapshots faux

        dashboard = self.api._get_dashboard_impl(run_id)
        self.assertTrue(dashboard.get("ok"), dashboard)
        history_entry = next(
            (h for h in (dashboard.get("runs_history") or []) if h.get("run_id") == run_id),
            None,
        )
        self.assertIsNotNone(history_entry, "Run absent de runs_history")
        assert history_entry is not None
        dashboard_total = int(history_entry.get("total_rows") or 0)

        history_payload = history_support._get_history_stats_impl(self.api, run_id)
        self.assertTrue(history_payload.get("ok"), history_payload)
        history_total = int(history_payload.get("run", {}).get("total_rows") or 0)

        # get_status DB-only : on force la disparition de RAM
        self.api._runs.pop(run_id, None)
        status = run_flow_support._get_status_impl(self.api, run_id, last_log_index=0)
        self.assertTrue(status.get("ok"), status)
        status_total = int(status.get("total") or 0)

        # Verite : 11 partout
        self.assertEqual(dashboard_total, 11, f"dashboard runs_history.total_rows = {dashboard_total}")
        self.assertEqual(history_total, 11, f"get_history_stats.total_rows = {history_total}")
        self.assertEqual(status_total, 11, f"get_status.total = {status_total}")
        self.assertEqual(dashboard_total, history_total)
        self.assertEqual(dashboard_total, status_total)

    def test_three_endpoints_align_when_plan_jsonl_absent(self) -> None:
        """SANS plan.jsonl : les 3 endpoints doivent partager le meme fallback
        (avant : 3 priorites divergentes -> 3 valeurs possibles)."""
        run_id = "20260526_align_b"
        # pas de plan.jsonl ecrit
        self._insert_run(run_id, planned_snapshot=120, total_db=130)
        # stats.planned_rows=120, run_row.total=130
        # Avant le fix :
        #   dashboard fallback = stats.planned_rows or total = 120
        #   history fallback   = total or stats.planned_rows = 130
        #   run_flow fallback  = total = 130
        # Apres le fix : tous = compute_total_fallback() = stats.planned_rows
        # car > 0 -> 120 partout.

        dashboard = self.api._get_dashboard_impl(run_id)
        self.assertTrue(dashboard.get("ok"), dashboard)
        history_entry = next(
            (h for h in (dashboard.get("runs_history") or []) if h.get("run_id") == run_id),
            None,
        )
        assert history_entry is not None
        dashboard_total = int(history_entry.get("total_rows") or 0)

        history_payload = history_support._get_history_stats_impl(self.api, run_id)
        self.assertTrue(history_payload.get("ok"), history_payload)
        history_total = int(history_payload.get("run", {}).get("total_rows") or 0)

        self.api._runs.pop(run_id, None)
        status = run_flow_support._get_status_impl(self.api, run_id, last_log_index=0)
        self.assertTrue(status.get("ok"), status)
        status_total = int(status.get("total") or 0)

        # AVANT fix : 120 / 130 / 130 (divergence)
        # APRES fix : 120 / 120 / 120 (cohere via compute_total_fallback)
        self.assertEqual(
            dashboard_total, history_total,
            f"dashboard ({dashboard_total}) != history ({history_total}) sans plan.jsonl",
        )
        self.assertEqual(
            dashboard_total, status_total,
            f"dashboard ({dashboard_total}) != status ({status_total}) sans plan.jsonl",
        )
        self.assertEqual(dashboard_total, 120, "Doit prioriser stats.planned_rows")


if __name__ == "__main__":
    unittest.main()
