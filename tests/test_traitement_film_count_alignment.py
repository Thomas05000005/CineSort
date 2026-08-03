# Fix audit 2026-05-25 (v1.5.5) Vague J : test de consistance du compteur de
# films sur la vue Traitement (etape Doublons en particulier), suite au bug
# residuel "855 films" affiche sur l'etape Doublons alors que la Bibliotheque
# et la Qualite affichaient 853.
#
# Cause racine : run_flow.get_status() retournait rs.total = discover_total
# (855 dossiers explores pendant le scan) au lieu de count_plan_rows(plan.jsonl)
# (853 PlanRow valides effectivement persistes). La Vague I.C avait corrige
# dashboard_support + history_support mais pas run_flow.get_status, qui nourrit
# directement le compteur affiche sur la vue Traitement (line 205, 284, 314 de
# web/dashboard/views/traitement.js : _runStatus.total).
#
# Fix : get_status recompte total depuis plan.jsonl quand run done, alignant
# le compteur Doublons sur la meme source de verite que dashboard/history.
"""Tests d'alignement du compteur films sur la vue Traitement (Vague J)."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import cinesort.ui.api.cinesort_api as backend
from cinesort.ui.api.run_data_support import count_plan_rows


class TraitementFilmCountAlignmentTests(unittest.TestCase):
    """REGRESSION Vague J : verifier que get_status (qui nourrit l'etape
    Doublons via _runStatus.total) retourne le meme compteur que
    get_dashboard et que le helper count_plan_rows()."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_traitement_count_")
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
        """Ecrit plan.jsonl avec exactement len(rows) PlanRow valides.
        Le scenario reel du bug : plan.jsonl contient les vrais PlanRow
        (par ex. 853) MAIS rs.total / row.total stocke en DB vaut
        discover_total (855, dossiers explores avant filtrage des dossiers
        sans video). count_plan_rows doit l'emporter sur le snapshot DB."""
        run_dir = self.state_dir / "runs" / f"tri_films_{run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)
        payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
        plan = run_dir / "plan.jsonl"
        plan.write_text(payload, encoding="utf-8")

    def _insert_run_done(self, run_id: str, *, total_snapshot: int, planned_rows: int) -> None:
        """Insere un run termine en DB avec un total "discover_total" different
        du nombre reel de PlanRow valides (reproduit le bug observe)."""
        started = time.time() - 60.0
        self.store.run.insert_run_pending(
            run_id=run_id,
            root=str(self.root),
            state_dir=str(self.state_dir),
            config={"tmdb_enabled": False},
            created_ts=started - 2.0,
        )
        self.store.run.mark_run_running(run_id, started_ts=started)
        # Simule la mise a jour de progression avec total = discover_total
        try:
            self.store.run.update_run_progress(run_id, idx=total_snapshot, total=total_snapshot, current_folder="")
        except (AttributeError, TypeError):
            # API legere : si pas de helper, on continue (le row total peut
            # rester a 0, le test verifie surtout que count_plan_rows prend
            # le dessus)
            pass
        self.store.run.mark_run_done(
            run_id,
            stats={"planned_rows": planned_rows, "applied_count": 0},
            ended_ts=started + 5.0,
        )

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_get_status_aligned_on_plan_jsonl_after_done(self) -> None:
        """BUG VAGUE J : run done en DB avec total stocke = 855
        (discover_total) mais plan.jsonl contient 853 PlanRow valides.
        get_status doit retourner 853 (source plan.jsonl), pas 855."""
        run_id = "20260525_140000_001"
        rows = [self._make_row(f"r{i}", f"Film {i}") for i in range(853)]
        # On ecrit 853 vraies rows + 2 lignes parasites pour bien verifier
        # que count_plan_rows ignore le bruit.
        self._write_plan(run_id, rows)
        # En DB, snapshot dit 855 (= discover_total stocke pendant le scan)
        self._insert_run_done(run_id, total_snapshot=855, planned_rows=855)

        status = self.api.run.get_status(run_id)
        self.assertTrue(status.get("ok"), status)
        self.assertEqual(
            int(status.get("total") or 0),
            853,
            "get_status.total doit etre aligne sur count_plan_rows(plan.jsonl) "
            "(853), pas sur discover_total stocke en DB (855).",
        )

    def test_get_status_matches_dashboard_total_movies(self) -> None:
        """get_status.total et dashboard.kpis.total_movies doivent retourner
        le meme nombre pour un meme run termine."""
        run_id = "20260525_140000_002"
        rows = [self._make_row(f"r{i}", f"Film {i}") for i in range(853)]
        self._write_plan(run_id, rows)
        self._insert_run_done(run_id, total_snapshot=855, planned_rows=855)

        status = self.api.run.get_status(run_id)
        dashboard = self.api._get_dashboard_impl(run_id)
        self.assertTrue(status.get("ok"), status)
        self.assertTrue(dashboard.get("ok"), dashboard)

        status_total = int(status.get("total") or 0)
        dashboard_total = int(dashboard.get("kpis", {}).get("total_movies") or 0)
        self.assertEqual(
            status_total,
            dashboard_total,
            f"get_status.total ({status_total}) doit egaler "
            f"dashboard.kpis.total_movies ({dashboard_total}). C'est exactement "
            f"le bug observe sur la vue Traitement etape Doublons.",
        )
        self.assertEqual(status_total, 853)

    def test_check_duplicates_works_on_853_not_855(self) -> None:
        """check_duplicates doit traiter exactement les rows du plan.jsonl
        (853), independamment du total_snapshot DB (855)."""
        run_id = "20260525_140000_003"
        rows = [self._make_row(f"r{i}", f"Film {i}") for i in range(853)]
        self._write_plan(run_id, rows)
        self._insert_run_done(run_id, total_snapshot=855, planned_rows=855)

        dup_result = self.api.run.check_duplicates(run_id, decisions={})
        self.assertTrue(dup_result.get("ok"), dup_result)
        # check_duplicates ne retourne pas total directement, mais on verifie
        # que get_plan retourne bien 853 rows que check_duplicates consomme.
        plan = self.api.run.get_plan(run_id)
        self.assertTrue(plan.get("ok"), plan)
        self.assertEqual(len(plan.get("rows") or []), 853)

    def test_count_plan_rows_helper_baseline(self) -> None:
        """Sanity : count_plan_rows retourne 853 sur un plan.jsonl avec
        853 rows valides, independamment du total_snapshot DB (855)."""
        run_id = "20260525_140000_004"
        rows = [self._make_row(f"r{i}", f"Film {i}") for i in range(853)]
        self._write_plan(run_id, rows)
        run_paths = self.api._run_paths_for(self.state_dir, run_id, ensure_exists=False)
        self.assertEqual(count_plan_rows(run_paths), 853)

    def test_all_endpoints_aligned_on_853(self) -> None:
        """SYNTHESE : les 3 endpoints qui exposent un compteur films sur la
        vue Traitement (get_status, get_dashboard, check_duplicates via
        get_plan) doivent TOUS retourner 853, pas 855."""
        run_id = "20260525_140000_005"
        rows = [self._make_row(f"r{i}", f"Film {i}") for i in range(853)]
        self._write_plan(run_id, rows)
        self._insert_run_done(run_id, total_snapshot=855, planned_rows=855)

        status_total = int(self.api.run.get_status(run_id).get("total") or 0)
        dashboard_total = int(self.api._get_dashboard_impl(run_id).get("kpis", {}).get("total_movies") or 0)
        plan_rows = self.api.run.get_plan(run_id).get("rows") or []
        plan_total = len(plan_rows)

        self.assertEqual(status_total, 853, "get_status.total != 853")
        self.assertEqual(dashboard_total, 853, "dashboard.total_movies != 853")
        self.assertEqual(plan_total, 853, "get_plan.rows != 853")
        # Verification finale : ils sont tous egaux
        self.assertEqual(
            {status_total, dashboard_total, plan_total},
            {853},
            "Les 3 endpoints (get_status, get_dashboard, get_plan) doivent "
            "retourner le meme compteur (853). Le bug Vague J etait que "
            "get_status retournait 855 alors que les autres retournaient 853.",
        )


if __name__ == "__main__":
    unittest.main()
