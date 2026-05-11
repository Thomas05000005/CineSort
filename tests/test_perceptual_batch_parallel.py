"""Tests V5-02 Polish Total v7.7.0 (R5-STRESS-5) — parallelisme batch perceptuel.

Couverture :
- resolve_batch_workers : table mode auto / force / clamp / cpu_count.
- run_batch_parallel : ordre preserve, isolation crashs, fast path sequentiel,
  cancel cooperatif, gain de perf observable.
- analyze_perceptual_batch : settings -> mode, kill-switch, < 2 films sequentiel,
  preservation ordre des row_ids dans `results`/`errors`.
- Setting normalization : `perceptual_workers` clamp [0, 16], bool/string tolere.
"""

from __future__ import annotations

import threading
import time
import unittest
from unittest import mock
from unittest.mock import patch

from cinesort.domain.perceptual.constants import (
    BATCH_PARALLELISM_AUTO_CAP,
    BATCH_PARALLELISM_MAX_WORKERS,
)
from cinesort.domain.perceptual.parallelism import (
    resolve_batch_workers,
    run_batch_parallel,
)
from cinesort.ui.api.perceptual_support import analyze_perceptual_batch


# ---------------------------------------------------------------------------
# resolve_batch_workers
# ---------------------------------------------------------------------------


class TestResolveBatchWorkers(unittest.TestCase):
    """Mode auto / force / clamp / cpu_count edge cases."""

    def test_auto_uses_cpu_capped_at_auto_cap(self):
        # 0 = auto. min(cpu, AUTO_CAP=8).
        self.assertEqual(resolve_batch_workers(0, cpu_count=4), 4)
        self.assertEqual(resolve_batch_workers(0, cpu_count=8), 8)
        self.assertEqual(resolve_batch_workers(0, cpu_count=16), BATCH_PARALLELISM_AUTO_CAP)
        self.assertEqual(resolve_batch_workers(0, cpu_count=32), BATCH_PARALLELISM_AUTO_CAP)

    def test_auto_min_one_on_low_cpu(self):
        self.assertEqual(resolve_batch_workers(0, cpu_count=1), 1)
        self.assertEqual(resolve_batch_workers(0, cpu_count=0), 1)

    def test_explicit_workers_clamped_to_max(self):
        self.assertEqual(resolve_batch_workers(4, cpu_count=4), 4)
        self.assertEqual(resolve_batch_workers(16, cpu_count=4), BATCH_PARALLELISM_MAX_WORKERS)
        self.assertEqual(resolve_batch_workers(99, cpu_count=4), BATCH_PARALLELISM_MAX_WORKERS)

    def test_explicit_one_returns_one(self):
        self.assertEqual(resolve_batch_workers(1, cpu_count=8), 1)

    def test_negative_falls_back_to_auto(self):
        self.assertEqual(resolve_batch_workers(-1, cpu_count=4), 4)
        self.assertEqual(resolve_batch_workers(-99, cpu_count=8), 8)

    def test_invalid_type_falls_back_to_auto(self):
        self.assertEqual(resolve_batch_workers("bogus", cpu_count=4), 4)  # type: ignore[arg-type]
        self.assertEqual(resolve_batch_workers(None, cpu_count=4), 4)  # type: ignore[arg-type]

    def test_os_cpu_count_returns_none(self):
        """Systemes virtualises peuvent voir os.cpu_count() retourner None."""
        with patch("cinesort.domain.perceptual.parallelism.os.cpu_count", return_value=None):
            self.assertEqual(resolve_batch_workers(0, cpu_count=None), 1)


# ---------------------------------------------------------------------------
# run_batch_parallel
# ---------------------------------------------------------------------------


class TestRunBatchParallel(unittest.TestCase):
    def test_empty_returns_empty_list(self):
        self.assertEqual(run_batch_parallel([], lambda x: x, max_workers=4), [])

    def test_single_item_fast_path_sequential(self):
        results = run_batch_parallel([42], lambda x: x * 2, max_workers=8)
        self.assertEqual(results, [(True, 84)])

    def test_order_preserved_for_10_items(self):
        items = list(range(10))
        results = run_batch_parallel(items, lambda x: x * x, max_workers=4)
        self.assertEqual(len(results), 10)
        for i, (ok, val) in enumerate(results):
            self.assertTrue(ok)
            self.assertEqual(val, i * i)

    def test_one_item_crashes_others_succeed(self):
        def worker(x):
            if x == 5:
                raise ValueError("kaboom on 5")
            return x

        items = list(range(10))
        results = run_batch_parallel(items, worker, max_workers=4)
        self.assertEqual(len(results), 10)
        for i, (ok, val) in enumerate(results):
            if i == 5:
                self.assertFalse(ok)
                self.assertIsInstance(val, ValueError)
            else:
                self.assertTrue(ok)
                self.assertEqual(val, i)

    def test_serial_fallback_when_max_workers_one(self):
        call_order = []

        def worker(x):
            call_order.append(x)
            return x

        items = ["a", "b", "c", "d"]
        results = run_batch_parallel(items, worker, max_workers=1)
        self.assertEqual(call_order, items)
        self.assertEqual([r[1] for r in results], items)

    def test_cancel_event_pre_set_aborts_all(self):
        ev = threading.Event()
        ev.set()
        items = list(range(5))
        results = run_batch_parallel(items, lambda x: x, max_workers=4, cancel_event=ev)
        self.assertEqual(len(results), 5)
        for ok, _ in results:
            self.assertFalse(ok)

    def test_parallelism_observable_speedup(self):
        """4 taches qui dorment 0.1s chacune en pool=4 -> total < 0.2s."""

        def slow(x):
            time.sleep(0.10)
            return x

        items = [1, 2, 3, 4]
        t0 = time.time()
        results = run_batch_parallel(items, slow, max_workers=4)
        elapsed = time.time() - t0
        # Sequentiel ~0.4s, parallele ~0.10s. Marge confortable a 0.25s.
        self.assertLess(elapsed, 0.25, f"parallelisme casse, elapsed={elapsed:.3f}s")
        self.assertEqual([r[1] for r in results], items)

    def test_results_indexed_correctly_with_jitter(self):
        """Workers terminent dans un ordre arbitraire mais resultats restent ordonnes."""

        def jitter(x):
            # Inverse l'ordre de completion : item 0 dort le plus, item 9 le moins.
            time.sleep((10 - x) * 0.005)
            return x * 100

        items = list(range(10))
        results = run_batch_parallel(items, jitter, max_workers=8)
        for i, (ok, val) in enumerate(results):
            self.assertTrue(ok)
            self.assertEqual(val, i * 100, f"ordre casse a l'index {i}")


# ---------------------------------------------------------------------------
# analyze_perceptual_batch — integration avec settings
# ---------------------------------------------------------------------------


def _make_api_mock(*, parallelism_enabled=True, workers=0):
    api = mock.MagicMock()
    api.get_settings.return_value = {
        "perceptual_parallelism_enabled": parallelism_enabled,
        "perceptual_workers": workers,
    }
    api._perceptual_cancel_event = None  # pas un threading.Event -> ignore
    return api


class TestAnalyzePerceptualBatch(unittest.TestCase):
    """Integration : settings -> mode, ordre preserve, isolation crashs."""

    @mock.patch("cinesort.ui.api.perceptual_support.get_perceptual_report")
    def test_empty_row_ids(self, mock_get):
        api = _make_api_mock()
        result = analyze_perceptual_batch(api, "run1", [])
        self.assertTrue(result["ok"])
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["success_count"], 0)
        self.assertEqual(result["error_count"], 0)
        mock_get.assert_not_called()

    @mock.patch("cinesort.ui.api.perceptual_support.get_perceptual_report")
    def test_single_film_uses_sequential_mode(self, mock_get):
        mock_get.return_value = {"ok": True, "perceptual": {"global_score": 80}}
        api = _make_api_mock(parallelism_enabled=True, workers=8)
        result = analyze_perceptual_batch(api, "run1", ["r1"])
        self.assertEqual(result["workers_used"], 1)
        self.assertEqual(result["success_count"], 1)

    @mock.patch("cinesort.ui.api.perceptual_support.get_perceptual_report")
    def test_kill_switch_disables_parallelism(self, mock_get):
        mock_get.return_value = {"ok": True, "perceptual": {"global_score": 70}}
        api = _make_api_mock(parallelism_enabled=False, workers=8)
        result = analyze_perceptual_batch(api, "run1", ["r1", "r2", "r3"])
        self.assertEqual(result["workers_used"], 1)
        self.assertEqual(result["success_count"], 3)

    @mock.patch("cinesort.ui.api.perceptual_support.get_perceptual_report")
    def test_explicit_workers_respected(self, mock_get):
        mock_get.return_value = {"ok": True, "perceptual": {"global_score": 75}}
        api = _make_api_mock(parallelism_enabled=True, workers=4)
        result = analyze_perceptual_batch(api, "run1", ["r1", "r2", "r3", "r4", "r5"])
        # workers=4 force, < BATCH_PARALLELISM_MAX_WORKERS, donc 4 attendus.
        self.assertEqual(result["workers_used"], 4)
        self.assertEqual(result["success_count"], 5)

    @mock.patch("cinesort.ui.api.perceptual_support.get_perceptual_report")
    def test_mixed_results_preserved_order(self, mock_get):
        """Films dans un ordre random de retour, results suivent l'ordre des row_ids."""

        def fake_report(api, run_id, row_id, options):
            # film r2 echoue, autres reussissent
            if row_id == "r2":
                return {"ok": False, "message": "erreur film 2"}
            return {"ok": True, "perceptual": {"global_score": int(row_id[1:]) * 10}}

        mock_get.side_effect = fake_report
        api = _make_api_mock(parallelism_enabled=True, workers=4)
        result = analyze_perceptual_batch(api, "run1", ["r1", "r2", "r3", "r4"])
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["success_count"], 3)
        self.assertEqual(result["error_count"], 1)
        # Ordre preserve dans results et errors
        success_ids = [r["row_id"] for r in result["results"]]
        self.assertEqual(success_ids, ["r1", "r3", "r4"])
        self.assertEqual(result["errors"][0]["row_id"], "r2")

    @mock.patch("cinesort.ui.api.perceptual_support.get_perceptual_report")
    def test_worker_crash_isolated_does_not_break_batch(self, mock_get):
        """Un worker qui leve une exception ne casse pas les autres."""

        def fake_report(api, run_id, row_id, options):
            if row_id == "r2":
                raise RuntimeError("ffmpeg crash sur r2")
            return {"ok": True, "perceptual": {"global_score": 80}}

        mock_get.side_effect = fake_report
        api = _make_api_mock(parallelism_enabled=True, workers=4)
        result = analyze_perceptual_batch(api, "run1", ["r1", "r2", "r3"])
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["success_count"], 2)
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["errors"][0]["row_id"], "r2")
        self.assertIn("ffmpeg crash", result["errors"][0]["message"])

    @mock.patch("cinesort.ui.api.perceptual_support.get_perceptual_report")
    def test_settings_lookup_failure_fallback(self, mock_get):
        """Si api.get_settings() leve, on retombe sur defauts (auto + enabled)."""
        mock_get.return_value = {"ok": True, "perceptual": {"global_score": 80}}
        api = mock.MagicMock()
        api.get_settings.side_effect = AttributeError("no settings")
        api._perceptual_cancel_event = None
        result = analyze_perceptual_batch(api, "run1", ["r1", "r2"])
        # Pas de crash, tout traite. workers_used >= 1.
        self.assertTrue(result["ok"])
        self.assertEqual(result["success_count"], 2)
        self.assertGreaterEqual(result["workers_used"], 1)

    @mock.patch("cinesort.ui.api.perceptual_support.get_perceptual_report")
    def test_10_films_simulated_perf_observable(self, mock_get):
        """10 films simules avec sleep 50ms : pool 4 doit etre < sequentiel."""
        call_lock = threading.Lock()
        call_count = {"n": 0}

        def fake_report(api, run_id, row_id, options):
            with call_lock:
                call_count["n"] += 1
            time.sleep(0.05)
            return {"ok": True, "perceptual": {"global_score": 80}}

        mock_get.side_effect = fake_report
        api = _make_api_mock(parallelism_enabled=True, workers=4)
        t0 = time.time()
        result = analyze_perceptual_batch(api, "run1", [f"r{i}" for i in range(10)])
        elapsed = time.time() - t0
        # Sequentiel = 10 * 50ms = 500ms. Pool 4 ~ 150ms. Marge 0.40s.
        self.assertLess(elapsed, 0.40, f"parallelisme casse, elapsed={elapsed:.3f}s")
        self.assertEqual(result["success_count"], 10)
        self.assertEqual(call_count["n"], 10)


# ---------------------------------------------------------------------------
# Settings normalization
# ---------------------------------------------------------------------------


class TestPerceptualWorkersSetting(unittest.TestCase):
    """Validation des settings `perceptual_workers` et `perceptual_parallelism_enabled`."""

    def setUp(self):
        import shutil
        import tempfile
        from pathlib import Path

        import cinesort.ui.api.cinesort_api as backend

        self._tmp = tempfile.mkdtemp(prefix="cinesort_v502_")
        self._root = Path(self._tmp) / "root"
        self._sd = Path(self._tmp) / "state"
        self._root.mkdir()
        self._sd.mkdir()
        self.api = backend.CineSortApi()
        self.api._state_dir = self._sd
        self._shutil = shutil

    def tearDown(self):
        self._shutil.rmtree(self._tmp, ignore_errors=True)

    def _save(self, extra):
        base = {"root": str(self._root), "state_dir": str(self._sd)}
        base.update(extra)
        return self.api.save_settings(base)

    def test_default_values(self):
        s = self.api.get_settings()
        self.assertTrue(s.get("perceptual_parallelism_enabled"))
        self.assertEqual(s.get("perceptual_workers"), 0)

    def test_kill_switch_persists(self):
        self._save({"perceptual_parallelism_enabled": False})
        s = self.api.get_settings()
        self.assertFalse(s.get("perceptual_parallelism_enabled"))

    def test_workers_clamped_to_16(self):
        self._save({"perceptual_workers": 99})
        s = self.api.get_settings()
        self.assertEqual(s.get("perceptual_workers"), 16)

    def test_workers_negative_falls_to_zero(self):
        self._save({"perceptual_workers": -5})
        s = self.api.get_settings()
        self.assertEqual(s.get("perceptual_workers"), 0)

    def test_workers_string_auto(self):
        self._save({"perceptual_workers": "auto"})
        s = self.api.get_settings()
        self.assertEqual(s.get("perceptual_workers"), 0)

    def test_workers_string_numeric(self):
        self._save({"perceptual_workers": "4"})
        s = self.api.get_settings()
        self.assertEqual(s.get("perceptual_workers"), 4)

    def test_workers_invalid_string_falls_to_zero(self):
        self._save({"perceptual_workers": "bogus"})
        s = self.api.get_settings()
        self.assertEqual(s.get("perceptual_workers"), 0)

    def test_workers_bool_rejected(self):
        # bool est sous-classe d'int -> on rejette pour eviter True->1 silencieux.
        self._save({"perceptual_workers": True})
        s = self.api.get_settings()
        self.assertEqual(s.get("perceptual_workers"), 0)


if __name__ == "__main__":
    unittest.main()
