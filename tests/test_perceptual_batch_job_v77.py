"""GATE AUDIT 2026-06-13 (R5-C) — analyse perceptuelle batch SINGLE-film async.

Avant : le bouton biblio "Analyser perceptuel" appelait analyze_perceptual_batch
en BLOQUANT (requete suspendue plusieurs minutes, aucune progression, toast
"lancee" trompeur). On ajoute queue_perceptual_batch -> job_id pollable via
get_perceptual_job_status (meme registre que les paires de doublons), avec
progression done/total par film.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.ui.api import perceptual_support
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import wait_run_done as _wait_done


class PerceptualBatchJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_perc_job_")
        self.root = Path(self._tmp) / "root"
        self.sd = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.sd.mkdir(parents=True, exist_ok=True)
        _p = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p.start()
        self.addCleanup(_p.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _scan(self, n=3):
        for i in range(n):
            (self.root / f"Film {2010 + i}.mkv").write_bytes(b"x" * 4096)
        api = CineSortApi()
        st = api.run.start_plan({"root": str(self.root), "state_dir": str(self.sd), "tmdb_enabled": False})
        self.assertTrue(st.get("ok"), st)
        run_id = str(st["run_id"])
        _wait_done(api, run_id)
        ids = [r["row_id"] for r in api.run.get_plan(run_id).get("rows", [])]
        return api, run_id, ids

    def _drain(self, api, job_id, timeout_s=30.0):
        deadline = time.monotonic() + timeout_s
        snap = {}
        while time.monotonic() < deadline:
            snap = api.quality.get_perceptual_job_status(job_id)
            if str(snap.get("status")) in ("done", "error", "cancelled"):
                return snap
            time.sleep(0.05)
        raise AssertionError(f"job {job_id} jamais termine, dernier={snap}")

    def test_queue_returns_jobid_and_total(self) -> None:
        api, run_id, ids = self._scan(3)
        res = api.quality.queue_perceptual_batch(run_id, ids)
        self.assertTrue(res.get("ok"), res)
        self.assertTrue(res.get("job_id"))
        self.assertEqual(res.get("total"), len(ids))

    def test_job_reaches_terminal_with_done_equals_total(self) -> None:
        api, run_id, ids = self._scan(3)
        res = api.quality.queue_perceptual_batch(run_id, ids)
        snap = self._drain(api, res["job_id"])
        self.assertIn(snap.get("status"), ("done", "error"))
        self.assertEqual(int(snap.get("done") or 0), len(ids), f"progression done!=total : {snap}")
        self.assertEqual(int(snap.get("total") or 0), len(ids))

    def test_empty_rowids_is_validation_error(self) -> None:
        api, run_id, _ids = self._scan(1)
        res = api.quality.queue_perceptual_batch(run_id, [])
        self.assertFalse(res.get("ok"))

    def test_missing_runid_is_validation_error(self) -> None:
        api, _run_id, ids = self._scan(1)
        res = api.quality.queue_perceptual_batch("", ids)
        self.assertFalse(res.get("ok"))

    def test_progress_cb_called_per_film(self) -> None:
        # analyze_perceptual_batch doit appeler progress_cb une fois par film.
        api, run_id, ids = self._scan(3)
        seen = []
        perceptual_support.analyze_perceptual_batch(
            api, run_id, ids, None, progress_cb=lambda d, t: seen.append((d, t)),
        )
        self.assertEqual(len(seen), len(ids), f"progress_cb appele {len(seen)}x pour {len(ids)} films")
        # le dernier tick doit etre (total, total)
        self.assertEqual(seen[-1][0], len(ids))
        self.assertEqual(seen[-1][1], len(ids))

    def test_legacy_batch_without_cb_still_works(self) -> None:
        # Non-regression : appel historique sans progress_cb inchange.
        api, run_id, ids = self._scan(2)
        res = perceptual_support.analyze_perceptual_batch(api, run_id, ids)
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("total"), len(ids))


if __name__ == "__main__":
    unittest.main()
