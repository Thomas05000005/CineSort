"""Tests historique par film — item 9.13.

Couvre :
- film_identity_key : tmdb_id, titre+annee, edition
- get_film_timeline : reconstruction, events, delta score
- list_films_overview : liste films
- _load_plan_rows_from_jsonl : parsing robuste
- API : endpoints existent
- UI : boutons et CSS presentes
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cinesort.domain.film_history import (
    film_identity_key,
    _identity_key_from_dict,
    get_film_timeline,
)


# ---------------------------------------------------------------------------
# Identite film (4 tests)
# ---------------------------------------------------------------------------


class FilmIdentityKeyTests(unittest.TestCase):
    """Tests de la cle d'identite stable d'un film."""

    def test_with_tmdb_id(self) -> None:
        row = SimpleNamespace(
            proposed_title="Inception",
            proposed_year=2010,
            edition=None,
            candidates=[SimpleNamespace(tmdb_id=27205)],
        )
        self.assertEqual(film_identity_key(row), "tmdb:27205")

    def test_without_tmdb_id(self) -> None:
        row = SimpleNamespace(
            proposed_title="Mon Film",
            proposed_year=2020,
            edition=None,
            candidates=[],
        )
        self.assertEqual(film_identity_key(row), "title:mon film|2020")

    def test_with_edition(self) -> None:
        row = SimpleNamespace(
            proposed_title="Blade Runner",
            proposed_year=1982,
            edition="Final Cut",
            candidates=[SimpleNamespace(tmdb_id=78)],
        )
        self.assertEqual(film_identity_key(row), "tmdb:78|final cut")

    def test_same_film_different_runs_same_key(self) -> None:
        """Meme film dans 2 runs → meme cle."""
        row1 = SimpleNamespace(
            proposed_title="Inception",
            proposed_year=2010,
            edition=None,
            candidates=[SimpleNamespace(tmdb_id=27205)],
        )
        row2 = SimpleNamespace(
            proposed_title="Inception",
            proposed_year=2010,
            edition=None,
            candidates=[SimpleNamespace(tmdb_id=27205)],
        )
        self.assertEqual(film_identity_key(row1), film_identity_key(row2))

    def test_dict_identity(self) -> None:
        """_identity_key_from_dict fonctionne sur un dict plan.jsonl."""
        d = {
            "proposed_title": "Inception",
            "proposed_year": 2010,
            "candidates": [{"tmdb_id": 27205}],
        }
        self.assertEqual(_identity_key_from_dict(d), "tmdb:27205")


# ---------------------------------------------------------------------------
# Reconstruction timeline (6 tests)
# ---------------------------------------------------------------------------


class _FakeStore:
    """Fake store minimaliste pour les tests de timeline."""

    def __init__(self, runs=None, quality_reports=None, batches=None, ops_by_row=None):
        self._runs = runs or []
        self._qr = quality_reports or {}
        self._batches = batches or {}
        self._ops = ops_by_row or {}

    def get_runs_summary(self, *, limit=20):
        return list(self._runs)

    def get_quality_report(self, *, run_id, row_id):
        return self._qr.get((run_id, row_id))

    def list_apply_batches_for_run(self, *, run_id, limit=10):
        return self._batches.get(run_id, [])

    def list_apply_operations_by_row(self, *, batch_id, row_id):
        return self._ops.get((batch_id, row_id), [])


class TimelineReconstructionTests(unittest.TestCase):
    """Tests de la reconstruction de timeline depuis les donnees."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_hist_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_plan(self, run_id, rows_data):
        run_dir = self.state_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        plan = run_dir / "plan.jsonl"
        with open(plan, "w", encoding="utf-8") as f:
            for row in rows_data:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def test_one_run_one_scan(self) -> None:
        """1 run, 1 film → 1 evenement scan."""
        self._write_plan(
            "run1",
            [
                {
                    "row_id": "S|1",
                    "proposed_title": "Inception",
                    "proposed_year": 2010,
                    "candidates": [{"tmdb_id": 27205}],
                    "confidence": 90,
                    "proposed_source": "tmdb",
                },
            ],
        )
        store = _FakeStore(runs=[{"run_id": "run1", "status": "DONE", "start_ts": 1000, "created_ts": 1000}])
        result = get_film_timeline("tmdb:27205", self.state_dir, store)
        self.assertEqual(result["film_id"], "tmdb:27205")
        self.assertEqual(result["scan_count"], 1)
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["events"][0]["type"], "scan")

    def test_two_runs_same_film(self) -> None:
        """2 runs, meme film → 2+ evenements."""
        for rid in ("run1", "run2"):
            self._write_plan(
                rid,
                [
                    {
                        "row_id": "S|1",
                        "proposed_title": "Inception",
                        "proposed_year": 2010,
                        "candidates": [{"tmdb_id": 27205}],
                        "confidence": 85,
                        "proposed_source": "tmdb",
                    },
                ],
            )
        store = _FakeStore(
            runs=[
                {"run_id": "run1", "status": "DONE", "start_ts": 1000, "created_ts": 1000},
                {"run_id": "run2", "status": "DONE", "start_ts": 2000, "created_ts": 2000},
            ]
        )
        result = get_film_timeline("tmdb:27205", self.state_dir, store)
        self.assertEqual(result["scan_count"], 2)
        self.assertGreaterEqual(len(result["events"]), 2)

    def test_quality_report_creates_score_event(self) -> None:
        """Run avec quality report → evenement score avec delta."""
        self._write_plan(
            "run1",
            [
                {
                    "row_id": "S|1",
                    "proposed_title": "Inception",
                    "proposed_year": 2010,
                    "candidates": [{"tmdb_id": 27205}],
                    "confidence": 90,
                    "proposed_source": "tmdb",
                },
            ],
        )
        self._write_plan(
            "run2",
            [
                {
                    "row_id": "S|1",
                    "proposed_title": "Inception",
                    "proposed_year": 2010,
                    "candidates": [{"tmdb_id": 27205}],
                    "confidence": 92,
                    "proposed_source": "tmdb",
                },
            ],
        )
        store = _FakeStore(
            runs=[
                {"run_id": "run1", "status": "DONE", "start_ts": 1000, "created_ts": 1000},
                {"run_id": "run2", "status": "DONE", "start_ts": 2000, "created_ts": 2000},
            ],
            quality_reports={
                ("run1", "S|1"): {"score": 62, "tier": "Moyen", "ts": 1001},
                ("run2", "S|1"): {"score": 87, "tier": "Premium", "ts": 2001},
            },
        )
        result = get_film_timeline("tmdb:27205", self.state_dir, store)
        score_events = [e for e in result["events"] if e["type"] == "score"]
        self.assertEqual(len(score_events), 2)
        self.assertEqual(score_events[0]["delta"], 0)  # Premier score, pas de precedent
        self.assertEqual(score_events[1]["delta"], 25)  # 87 - 62
        self.assertEqual(result["current_score"], 87)

    def test_apply_creates_apply_event(self) -> None:
        """Run avec apply → evenement apply avec operations."""
        self._write_plan(
            "run1",
            [
                {
                    "row_id": "S|1",
                    "proposed_title": "Inception",
                    "proposed_year": 2010,
                    "candidates": [{"tmdb_id": 27205}],
                    "confidence": 90,
                    "proposed_source": "tmdb",
                },
            ],
        )
        store = _FakeStore(
            runs=[{"run_id": "run1", "status": "DONE", "start_ts": 1000, "created_ts": 1000}],
            batches={"run1": [{"batch_id": "b1", "dry_run": False, "started_ts": 1100, "ended_ts": 1200}]},
            ops_by_row={
                ("b1", "S|1"): [
                    {
                        "op_type": "RENAME",
                        "src_path": "/old/Inception",
                        "dst_path": "/new/Inception (2010)",
                        "undo_status": "PENDING",
                    },
                ]
            },
        )
        result = get_film_timeline("tmdb:27205", self.state_dir, store)
        apply_events = [e for e in result["events"] if e["type"] == "apply"]
        self.assertEqual(len(apply_events), 1)
        self.assertEqual(result["apply_count"], 1)
        self.assertEqual(apply_events[0]["operations"][0]["op"], "RENAME")

    def test_events_sorted_by_timestamp(self) -> None:
        """Les evenements sont tries par timestamp."""
        self._write_plan(
            "run1",
            [
                {
                    "row_id": "S|1",
                    "proposed_title": "Inception",
                    "proposed_year": 2010,
                    "candidates": [{"tmdb_id": 27205}],
                    "confidence": 90,
                    "proposed_source": "tmdb",
                },
            ],
        )
        store = _FakeStore(
            runs=[{"run_id": "run1", "status": "DONE", "start_ts": 1000, "created_ts": 1000}],
            quality_reports={("run1", "S|1"): {"score": 75, "tier": "Bon", "ts": 1500}},
        )
        result = get_film_timeline("tmdb:27205", self.state_dir, store)
        timestamps = [e.get("ts", 0) for e in result["events"]]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_incompatible_plan_jsonl_skipped(self) -> None:
        """plan.jsonl avec lignes invalides → skip gracieux, pas de crash."""
        run_dir = self.state_dir / "runs" / "run1"
        run_dir.mkdir(parents=True)
        (run_dir / "plan.jsonl").write_text("not json\n{bad\n", encoding="utf-8")
        store = _FakeStore(runs=[{"run_id": "run1", "status": "DONE", "start_ts": 1000, "created_ts": 1000}])
        result = get_film_timeline("tmdb:27205", self.state_dir, store)
        self.assertEqual(result["scan_count"], 0)
        self.assertEqual(result["events"], [])


# ---------------------------------------------------------------------------
# API (4 tests)
# ---------------------------------------------------------------------------


class ApiEndpointTests(unittest.TestCase):
    """Tests que les endpoints sont enregistres dans CineSortApi."""

    def test_get_film_history_exists(self) -> None:
        """Issue #84 PR 10 : get_film_history est sur la LibraryFacade."""
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        self.assertTrue(hasattr(api.library, "get_film_history"))
        self.assertTrue(callable(api.library.get_film_history))

    def test_list_films_with_history_exists(self) -> None:
        """Issue #84 PR 10 : list_films_with_history est sur la LibraryFacade."""
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        self.assertTrue(hasattr(api.library, "list_films_with_history"))

    def test_get_film_history_empty_id(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        result = api.library.get_film_history("")
        self.assertFalse(result.get("ok"))

    def test_list_films_default(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        result = api.library.list_films_with_history()
        # Peut retourner ok=True avec films=[] ou ok=False si pas de state
        self.assertIn("ok", result)


# ---------------------------------------------------------------------------
# UI (4 tests)
# ---------------------------------------------------------------------------


class UiFilmHistoryTests(unittest.TestCase):
    """Tests presence UI boutons et CSS timeline."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.validation_js = (root / "web" / "views" / "validation.js").read_text(encoding="utf-8")
        cls.library_js = (root / "web" / "dashboard" / "views" / "library.js").read_text(encoding="utf-8")
        cls.app_css = (root / "web" / "styles.css").read_text(encoding="utf-8")
        cls.dash_css = (root / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")

    def test_desktop_history_button(self) -> None:
        self.assertIn("btnShowHistory", self.validation_js)
        self.assertIn("_showFilmHistory", self.validation_js)

    def test_dashboard_history_button(self) -> None:
        self.assertIn("btnFilmHistory", self.library_js)
        self.assertIn("_loadFilmHistory", self.library_js)

    def test_app_css_timeline_classes(self) -> None:
        self.assertIn(".timeline-container", self.app_css)
        self.assertIn(".timeline-event", self.app_css)
        self.assertIn(".timeline-delta-up", self.app_css)
        self.assertIn(".timeline-delta-down", self.app_css)

    def test_dash_css_timeline_classes(self) -> None:
        self.assertIn(".timeline-container", self.dash_css)
        self.assertIn(".timeline-event", self.dash_css)
        self.assertIn(".timeline-delta-up", self.dash_css)


# ---------------------------------------------------------------------------
# Edge cases (2 tests)
# ---------------------------------------------------------------------------


class EdgeCaseTests(unittest.TestCase):
    """Tests cas limites."""

    def test_film_renamed_still_linked_by_tmdb(self) -> None:
        """Film renomme entre 2 runs → lie par tmdb_id, pas par dossier."""
        d1 = {"proposed_title": "Inception", "proposed_year": 2010, "candidates": [{"tmdb_id": 27205}]}
        d2 = {"proposed_title": "Inception Renamed", "proposed_year": 2010, "candidates": [{"tmdb_id": 27205}]}
        self.assertEqual(_identity_key_from_dict(d1), _identity_key_from_dict(d2))

    def test_zero_runs_empty_result(self) -> None:
        """0 runs → timeline vide."""
        tmp = tempfile.mkdtemp(prefix="cinesort_hist_empty_")
        try:
            store = _FakeStore(runs=[])
            result = get_film_timeline("tmdb:27205", Path(tmp), store)
            self.assertEqual(result["events"], [])
            self.assertEqual(result["scan_count"], 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
