"""GATE AUDIT 2026-06-10 — get_dashboard expose `status` (par run) et
`active_run_id` (payload).

Avant : runs_history n'avait pas de `status` (le CTA "Reprendre la validation"
de l'accueil et les filtres Statut/Undone de l'historique ne matchaient jamais)
et get_dashboard ne renvoyait pas `active_run_id` (la carte "Scan en cours" de
l'accueil ne s'affichait jamais ; active_run_id n'existait que sur /api/health).
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import cinesort.ui.api.cinesort_api as backend


class DashboardStatusActiveRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_dash_status_")
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
        self.store, _runner = self.api._get_or_create_infra(self.state_dir)  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _insert_run(self, run_id: str, *, status_done: bool = True) -> None:
        started = time.time() - 50.0
        self.store.run.insert_run_pending(
            run_id=run_id,
            root=str(self.root),
            state_dir=str(self.state_dir),
            config={"tmdb_enabled": False},
            created_ts=started - 2.0,
        )
        self.store.run.mark_run_running(run_id, started_ts=started)
        if status_done:
            self.store.run.mark_run_done(run_id, stats={"planned_rows": 1}, ended_ts=started + 10.0)
        run_dir = self.state_dir / "runs" / f"tri_films_{run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "plan.jsonl").write_text(
            json.dumps(
                {
                    "row_id": "r1",
                    "kind": "single",
                    "folder": str(self.root),
                    "video": str(self.root / "x.mkv"),
                    "proposed_title": "X",
                    "proposed_year": 2020,
                    "proposed_source": "tmdb",
                    "confidence": 80,
                    "candidates": [],
                    "notes": "",
                    "collection_name": None,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def test_runs_history_exposes_status(self) -> None:
        run_id = "20260101_000000_001"
        self._insert_run(run_id, status_done=True)
        data = self.api._get_dashboard_impl(run_id)
        self.assertTrue(data.get("ok"), data)
        entry = next((x for x in data["runs_history"] if x.get("run_id") == run_id), None)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.get("status"), "DONE")

    def test_payload_has_active_run_id_key(self) -> None:
        run_id = "20260101_000000_002"
        self._insert_run(run_id, status_done=True)
        data = self.api._get_dashboard_impl(run_id)
        # La cle existe toujours ; aucune run en memoire -> None
        self.assertIn("active_run_id", data)
        self.assertIsNone(data["active_run_id"])

    def test_active_run_id_detects_running_run(self) -> None:
        run_id = "20260101_000000_003"
        self._insert_run(run_id, status_done=True)
        # Simuler un run en cours en memoire (RunState running, pas done)
        self.api._runs = {"live_run_42": SimpleNamespace(running=True, done=False)}  # type: ignore[attr-defined]
        import threading

        self.api._runs_lock = threading.RLock()  # type: ignore[attr-defined]
        data = self.api._get_dashboard_impl(run_id)
        self.assertEqual(data["active_run_id"], "live_run_42")


if __name__ == "__main__":
    unittest.main()
