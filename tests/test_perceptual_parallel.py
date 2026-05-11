"""Tests §1 v7.5.0 — parallelisme perceptuel."""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from cinesort.domain.perceptual.parallelism import (
    resolve_max_workers,
    run_parallel_tasks,
)


class TestResolveMaxWorkers(unittest.TestCase):
    """Table de resolution mode x intent x cpu_count."""

    def test_serial_always_one(self):
        for intent in ("single_film", "deep_compare"):
            for cpu in (1, 2, 4, 8, 16, 32):
                self.assertEqual(resolve_max_workers("serial", intent, cpu_count=cpu), 1)

    def test_safe_caps_at_two(self):
        # cpu suffisant -> 2, sinon 1
        self.assertEqual(resolve_max_workers("safe", "single_film", cpu_count=8), 2)
        self.assertEqual(resolve_max_workers("safe", "deep_compare", cpu_count=16), 2)
        self.assertEqual(resolve_max_workers("safe", "single_film", cpu_count=2), 1)

    def test_auto_single_film_uses_half_cpu_capped(self):
        self.assertEqual(resolve_max_workers("auto", "single_film", cpu_count=4), 2)
        self.assertEqual(resolve_max_workers("auto", "single_film", cpu_count=8), 2)  # cap 2
        self.assertEqual(resolve_max_workers("auto", "single_film", cpu_count=16), 2)  # cap 2

    def test_auto_deep_compare_scales_up_to_four(self):
        self.assertEqual(resolve_max_workers("auto", "deep_compare", cpu_count=4), 2)
        self.assertEqual(resolve_max_workers("auto", "deep_compare", cpu_count=8), 4)
        self.assertEqual(resolve_max_workers("auto", "deep_compare", cpu_count=16), 4)  # cap 4

    def test_low_cpu_fallback_to_one(self):
        self.assertEqual(resolve_max_workers("auto", "single_film", cpu_count=2), 1)
        self.assertEqual(resolve_max_workers("auto", "deep_compare", cpu_count=3), 1)

    def test_max_mode_uses_cap_regardless_of_cpu(self):
        self.assertEqual(resolve_max_workers("max", "single_film", cpu_count=1), 2)
        self.assertEqual(resolve_max_workers("max", "deep_compare", cpu_count=1), 4)

    def test_invalid_mode_fallbacks_to_auto(self):
        self.assertEqual(resolve_max_workers("bogus", "single_film", cpu_count=8), 2)
        self.assertEqual(resolve_max_workers("", "deep_compare", cpu_count=8), 4)

    def test_invalid_intent_fallbacks_to_single_film(self):
        self.assertEqual(resolve_max_workers("auto", "bogus", cpu_count=8), 2)

    def test_os_cpu_count_returning_none_fallbacks_to_one(self):
        """Systemes virtualises peuvent voir os.cpu_count() retourner None."""
        with patch("cinesort.domain.perceptual.parallelism.os.cpu_count", return_value=None):
            self.assertEqual(resolve_max_workers("auto", "single_film", cpu_count=None), 1)
            self.assertEqual(resolve_max_workers("auto", "deep_compare", cpu_count=None), 1)


class TestRunParallelTasks(unittest.TestCase):
    def test_empty_tasks_returns_empty(self):
        self.assertEqual(run_parallel_tasks({}, max_workers=4), {})

    def test_all_tasks_succeed(self):
        tasks = {"a": lambda: 1, "b": lambda: 2, "c": lambda: 3}
        results = run_parallel_tasks(tasks, max_workers=2)
        self.assertEqual(len(results), 3)
        for name in ("a", "b", "c"):
            ok, value = results[name]
            self.assertTrue(ok)
            self.assertEqual(value, {"a": 1, "b": 2, "c": 3}[name])

    def test_one_task_raises_others_still_run(self):
        def boom():
            raise ValueError("kaboom")

        tasks = {"ok1": lambda: "x", "bad": boom, "ok2": lambda: "y"}
        results = run_parallel_tasks(tasks, max_workers=3)
        self.assertTrue(results["ok1"][0])
        self.assertEqual(results["ok1"][1], "x")
        self.assertFalse(results["bad"][0])
        self.assertIsInstance(results["bad"][1], ValueError)
        self.assertTrue(results["ok2"][0])
        self.assertEqual(results["ok2"][1], "y")

    def test_cancel_event_aborts_pending(self):
        ev = threading.Event()
        ev.set()
        tasks = {"a": lambda: 1, "b": lambda: 2}
        results = run_parallel_tasks(tasks, max_workers=2, cancel_event=ev)
        self.assertEqual(len(results), 2)
        # Les deux taches doivent etre marquees echec (cancelled)
        for name in ("a", "b"):
            ok, _ = results[name]
            self.assertFalse(ok)

    def test_serial_fallback_with_max_workers_one(self):
        call_order = []

        def task(name):
            def _fn():
                call_order.append(name)
                return name

            return _fn

        tasks = {"a": task("a"), "b": task("b"), "c": task("c")}
        results = run_parallel_tasks(tasks, max_workers=1)
        self.assertEqual(len(results), 3)
        # Execution sequentielle
        self.assertEqual(call_order, ["a", "b", "c"])

    def test_tasks_run_in_parallel(self):
        """Si 2 taches bloquent 0.2s chacune et pool=2, total < 0.4s."""

        def slow():
            time.sleep(0.15)
            return "ok"

        tasks = {"a": slow, "b": slow}
        t0 = time.time()
        results = run_parallel_tasks(tasks, max_workers=2)
        elapsed = time.time() - t0
        self.assertLess(elapsed, 0.28, f"parallelisme casse, elapsed={elapsed:.3f}s")
        self.assertTrue(all(ok for ok, _ in results.values()))


class TestPerceptualSettingDefaults(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile
        from pathlib import Path

        import cinesort.ui.api.cinesort_api as backend

        self._tmp = tempfile.mkdtemp(prefix="cinesort_parallel_")
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

    def test_default_mode_is_auto(self):
        s = self.api.get_settings()
        self.assertEqual(s.get("perceptual_parallelism_mode"), "auto")

    def test_roundtrip_valid_modes(self):
        for mode in ("auto", "max", "safe", "serial"):
            self._save({"perceptual_parallelism_mode": mode})
            s = self.api.get_settings()
            self.assertEqual(s.get("perceptual_parallelism_mode"), mode)

    def test_invalid_mode_fallbacks_to_auto(self):
        self._save({"perceptual_parallelism_mode": "bogus"})
        s = self.api.get_settings()
        self.assertEqual(s.get("perceptual_parallelism_mode"), "auto")

    def test_case_insensitive(self):
        self._save({"perceptual_parallelism_mode": "SERIAL"})
        s = self.api.get_settings()
        self.assertEqual(s.get("perceptual_parallelism_mode"), "serial")


class TestPerceptualOrchestrationParallel(unittest.TestCase):
    """Tests d'integration : _execute_perceptual_analysis utilise bien le pool."""

    def test_video_and_audio_tasks_run_via_pool(self):
        """video et audio s'executent en parallele si mode=max et has_video+has_audio."""
        from cinesort.ui.api import perceptual_support as ps

        ffmpeg_calls: list[str] = []

        def fake_extract(*args, **kwargs):
            time.sleep(0.1)
            ffmpeg_calls.append("video")
            return []

        def fake_filter(*args, **kwargs):
            return {}

        def fake_analyze_video(*args, **kwargs):
            vr = MagicMock()
            vr.blur_mean = 0.02
            return vr

        def fake_grain(*args, **kwargs):
            return MagicMock()

        def fake_audio(*args, **kwargs):
            time.sleep(0.1)
            ffmpeg_calls.append("audio")
            return MagicMock()

        fake_result = MagicMock()
        fake_result.visual_score = 80
        fake_result.audio_score = 75
        fake_result.global_score = 78
        fake_result.global_tier = "excellent"
        fake_result.to_dict.return_value = {"global_score": 78}

        api = MagicMock()
        api._tmdb_client.return_value = None
        api._perceptual_cancel_event = None  # pas de cancel (MagicMock en creerait un truthy)
        store = MagicMock()
        store.upsert_perceptual_report = MagicMock()

        row = MagicMock()
        row.candidates = []
        row.proposed_year = 2015

        ctx = (
            {"perceptual_parallelism_mode": "max"},
            "ffmpeg.exe",
            store,
            {"state_dir": None},
            row,
            MagicMock(exists=lambda: True, __str__=lambda self: "x.mkv"),
            {"duration_s": 7200, "audio_tracks": [{"codec": "eac3"}]},
            {"width": 1920, "height": 1080, "bit_depth": 8, "fps": 24.0},
        )

        with (
            patch.object(ps, "extract_representative_frames", fake_extract),
            patch.object(ps, "run_filter_graph", fake_filter),
            patch.object(ps, "analyze_video_frames", fake_analyze_video),
            patch.object(ps, "analyze_grain", fake_grain),
            patch.object(ps, "analyze_audio_perceptual", fake_audio),
            patch.object(ps, "build_perceptual_result", return_value=fake_result),
        ):
            t0 = time.time()
            out = ps._execute_perceptual_analysis(api, "run1", "row1", ctx)
            elapsed = time.time() - t0

        self.assertTrue(out.get("ok"))
        # Les 2 taches sommees feraient 0.2s en serial, parallele attendu ~0.1s.
        # Marge 0.35s pour absorber le bruit CI (threadpool startup + ffmpeg mock
        # overhead). Si parallelisme casse, elapsed >= 0.2s + overhead ~0.5s+.
        self.assertLess(elapsed, 0.35, f"parallelisme casse, elapsed={elapsed:.3f}s")
        self.assertIn("video", ffmpeg_calls)
        self.assertIn("audio", ffmpeg_calls)


if __name__ == "__main__":
    unittest.main()
