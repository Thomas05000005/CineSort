"""GATE AUDIT 2026-06-10 (REAL 2/2) — get_film_timeline trouve le plan.jsonl dans
le vrai dossier de run `runs/tri_films_<run_id>`.

Avant : le chemin etait construit `runs/<run_id>/plan.jsonl` (sans le prefixe
tri_films_) -> plan.jsonl jamais trouve -> get_film_history retournait 0
evenement et list_films_with_history 0 film (timeline du Modal Film vide).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cinesort.domain.film_history import _resolve_run_dir, get_film_timeline
from cinesort.ui.api import film_history_support


class _FakeRunRepo:
    def __init__(self, runs):
        self._runs = runs

    def get_runs_summary(self, *, limit=20):
        return list(self._runs)


class _FakeQualityRepo:
    def get_quality_report(self, *, run_id, row_id):
        return None


class _FakeApplyRepo:
    def list_apply_batches_for_run(self, *, run_id, limit=10):
        return []

    def list_apply_operations_by_row(self, *, batch_id, row_id):
        return []


class _FakeStore:
    def __init__(self, runs):
        self.run = _FakeRunRepo(runs)
        self.quality = _FakeQualityRepo()
        self.apply = _FakeApplyRepo()


class FilmHistoryRunDirTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_histdir_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_prefixed_plan(self, run_id, rows):
        run_dir = self.state_dir / "runs" / f"tri_films_{run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)
        with open(run_dir / "plan.jsonl", "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def test_resolve_run_dir_prefers_prefixed(self) -> None:
        (self.state_dir / "runs" / "tri_films_run1").mkdir(parents=True)
        self.assertEqual(
            _resolve_run_dir(self.state_dir, "run1"),
            self.state_dir / "runs" / "tri_films_run1",
        )

    def test_resolve_run_dir_falls_back_to_bare(self) -> None:
        (self.state_dir / "runs" / "run2").mkdir(parents=True)
        self.assertEqual(
            _resolve_run_dir(self.state_dir, "run2"),
            self.state_dir / "runs" / "run2",
        )

    def test_timeline_found_in_prefixed_dir(self) -> None:
        self._write_prefixed_plan(
            "run1",
            [
                {
                    "row_id": "S|1",
                    "proposed_title": "Inception",
                    "proposed_year": 2010,
                    "candidates": [{"tmdb_id": 27205}],
                    "confidence": 90,
                    "proposed_source": "tmdb",
                }
            ],
        )
        store = _FakeStore(runs=[{"run_id": "run1", "status": "DONE", "start_ts": 1000, "created_ts": 1000}])
        result = get_film_timeline("tmdb:27205", self.state_dir, store)
        self.assertEqual(result["scan_count"], 1, "le plan.jsonl du dossier tri_films_ doit etre trouve")
        self.assertEqual(len(result["events"]), 1)


class FilmHistorySupportErrorHandlingTests(unittest.TestCase):
    """Les endpoints support convertissent RuntimeError / sqlite3.Error en err() structurée."""

    def _api_raising(self, exc):
        def _boom(_state_dir):
            raise exc

        return SimpleNamespace(
            settings=SimpleNamespace(get_settings=lambda: {"state_dir": tempfile.gettempdir()}),
            _get_or_create_infra=_boom,
        )

    def test_get_film_history_wraps_sqlite_error(self) -> None:
        api = self._api_raising(sqlite3.OperationalError("database is locked"))
        res = film_history_support.get_film_history(api, "tmdb:1")
        self.assertFalse(res["ok"])

    def test_get_film_history_wraps_runtime_error(self) -> None:
        api = self._api_raising(RuntimeError("migration rollback"))
        res = film_history_support.get_film_history(api, "tmdb:1")
        self.assertFalse(res["ok"])

    def test_list_films_with_history_wraps_sqlite_error(self) -> None:
        api = self._api_raising(sqlite3.OperationalError("database is locked"))
        res = film_history_support.list_films_with_history(api, limit=10)
        self.assertFalse(res["ok"])


if __name__ == "__main__":
    unittest.main()
