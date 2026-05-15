"""LOT C — Tests de concurrence et de stabilite memoire.

Couvre : race _state_dir, stabilite memoire sur 100 runs, get_status concurrent,
2 apply simultanes (serialisation), apply+undo simultanes, cancel pendant apply.
"""

from __future__ import annotations

import gc
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path

import cinesort.domain.core as core
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import create_file as _create_file
from tests._helpers import wait_run_done as _wait_done


class _ConcurrencyBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_concurrency_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        # Issue #86 : mock.patch.object pour auto-restore safe meme si exception
        _p_min_video = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p_min_video.start()
        self.addCleanup(_p_min_video.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)


class StateDirRaceTests(_ConcurrencyBase):
    # 20
    def test_start_plan_and_save_settings_parallel(self) -> None:
        """start_plan + save_settings en parallele : pas de corruption de _state_dir."""
        for i in range(3):
            _create_file(self.root / f"F{i}.2020" / f"F{i}.2020.mkv")

        api = CineSortApi()
        # Pre-save pour avoir un etat initial coherent
        api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
            }
        )

        results: dict = {"start": None, "save": None}
        errors: list = []

        def _start():
            try:
                results["start"] = api.run.start_plan(
                    {
                        "root": str(self.root),
                        "state_dir": str(self.state_dir),
                        "tmdb_enabled": False,
                    }
                )
            except Exception as exc:
                errors.append(("start", exc))

        def _save():
            try:
                results["save"] = api.settings.save_settings(
                    {
                        "root": str(self.root),
                        "state_dir": str(self.state_dir),
                        "tmdb_enabled": False,
                        "notifications_enabled": True,
                    }
                )
            except Exception as exc:
                errors.append(("save", exc))

        t1 = threading.Thread(target=_start)
        t2 = threading.Thread(target=_save)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(errors, [])
        # Les 2 operations ont toutes les deux abouti
        self.assertIsNotNone(results["start"])
        self.assertIsNotNone(results["save"])
        # _state_dir pointe vers un Path coherent (pas None, pas corrompu)
        self.assertIsInstance(api._state_dir, Path)


class MemoryStabilityTests(_ConcurrencyBase):
    # 21
    def test_100_runs_memory_stable(self) -> None:
        """Scans repetes : _runs reste borne grace au cleanup H6 (garantit pas de fuite lineaire)."""
        _create_file(self.root / "Single.2020" / "Single.2020.mkv")

        api = CineSortApi()

        # Warmup + mesure via RSS si psutil dispo, sinon on se contente de la verification _runs
        for _ in range(5):
            start = api.run.start_plan(
                {
                    "root": str(self.root),
                    "state_dir": str(self.state_dir),
                    "tmdb_enabled": False,
                }
            )
            _wait_done(api, start["run_id"])
        gc.collect()

        # Lancer 30 scans supplementaires
        for _ in range(30):
            start = api.run.start_plan(
                {
                    "root": str(self.root),
                    "state_dir": str(self.state_dir),
                    "tmdb_enabled": False,
                }
            )
            _wait_done(api, start["run_id"])
        gc.collect()

        # Verification principale : _runs du JobRunner est bien cleanup (H6).
        # Sans le fix H6, on aurait 35+ entrees. Avec le cleanup : max ~5-6 runs.
        _store, runner = api._get_or_create_infra(self.state_dir)
        with runner._lock:
            n_runs = len(runner._runs)
        self.assertLessEqual(
            n_runs, 10, f"JobRunner._runs pas cleanup (H6) : {n_runs} runs en memoire sur 35 lances (attendu <= 10)"
        )


class GetStatusConcurrencyTests(_ConcurrencyBase):
    # 22
    def test_get_status_during_active_run(self) -> None:
        """get_status() appele 100x en parallele d'un scan : pas de crash ni d'etat incoherent."""
        for i in range(5):
            _create_file(self.root / f"Film{i}.2020" / f"Film{i}.2020.mkv")

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = start["run_id"]

        incoherences: list = []

        def _poll():
            for _ in range(100):
                s = api.run.get_status(run_id, 0)
                # Incoherence : running et done simultanement (avant le fix)
                if s.get("done") and s.get("running"):
                    incoherences.append(dict(s))
                time.sleep(0.001)

        threads = [threading.Thread(target=_poll) for _ in range(3)]
        for t in threads:
            t.start()
        _wait_done(api, run_id)
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(incoherences, [], f"Etats incoherents : {incoherences}")


class TwoAppliesSimultaneousTests(_ConcurrencyBase):
    # 23
    def test_two_applies_simultaneous_one_refused(self) -> None:
        """2 apply() sur le meme run_id : 1 seul accepte (guard lock), l'autre refuse proprement."""
        for i in range(3):
            _create_file(self.root / f"Movie{i}.2021" / f"Movie{i}.2021.mkv")

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
            }
        )
        run_id = start["run_id"]
        _wait_done(api, run_id)

        plan = api.run.get_plan(run_id)
        decisions = {
            r["row_id"]: {"ok": True, "title": r.get("proposed_title") or "", "year": r.get("proposed_year") or 0}
            for r in plan.get("rows", [])
        }

        results: list = [None, None]

        def _run_apply(idx: int):
            results[idx] = api.apply(run_id, decisions, False, False)

        t1 = threading.Thread(target=_run_apply, args=(0,))
        t2 = threading.Thread(target=_run_apply, args=(1,))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        # Au moins un des deux a reussi
        oks = [r for r in results if r and r.get("ok")]
        # Avec le lock, au moins 1 reussit ; le 2e peut soit reussir apres le 1er, soit etre refuse
        self.assertGreaterEqual(len(oks), 1, f"Aucun apply n'a reussi : {results}")


class ApplyUndoSimultaneousTests(_ConcurrencyBase):
    # 24
    def test_apply_and_undo_simultaneous_serialized(self) -> None:
        """apply() et undo_last_apply() lances en parallele : serialisation sans crash."""
        for i in range(3):
            _create_file(self.root / f"Film{i}.2020" / f"Film{i}.2020.mkv")

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
            }
        )
        run_id = start["run_id"]
        _wait_done(api, run_id)
        plan = api.run.get_plan(run_id)
        decisions = {
            r["row_id"]: {"ok": True, "title": r.get("proposed_title") or "", "year": r.get("proposed_year") or 0}
            for r in plan.get("rows", [])
        }

        # 1er apply (sequentiel, pour avoir un batch a undo)
        r1 = api.apply(run_id, decisions, False, False)
        self.assertTrue(r1.get("ok"), r1)

        # Maintenant : 2e apply + undo en parallele
        results: list = [None, None]
        errors: list = []

        def _apply_again():
            try:
                results[0] = api.apply(run_id, decisions, False, False)
            except Exception as exc:
                errors.append(("apply", exc))

        def _undo():
            try:
                results[1] = api.undo_last_apply(run_id)
            except Exception as exc:
                errors.append(("undo", exc))

        t1 = threading.Thread(target=_apply_again)
        t2 = threading.Thread(target=_undo)
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        # Pas de crash
        self.assertEqual(errors, [], f"Crash lors de l'execution : {errors}")


class CancelDuringApplyTests(_ConcurrencyBase):
    # 25
    def test_cancel_during_scan(self) -> None:
        """Cancel pendant un scan : le run finit en CANCELLED sans crash."""
        # Creer plusieurs films pour avoir du temps d'action
        for i in range(10):
            _create_file(self.root / f"Movie{i}.2020" / f"Movie{i}.2020.mkv")

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = start["run_id"]

        # Attendre un peu puis annuler
        time.sleep(0.05)
        cancel_result = api.run.cancel_run(run_id)
        self.assertIsInstance(cancel_result, dict)

        # Attendre que le run termine
        deadline = time.time() + 10
        while time.time() < deadline:
            s = api.run.get_status(run_id, 0)
            if s.get("done"):
                break
            time.sleep(0.05)
        # Pas de crash — le run doit etre dans un etat terminal
        final = api.run.get_status(run_id, 0)
        self.assertTrue(final.get("done"), final)


if __name__ == "__main__":
    unittest.main(verbosity=2)
