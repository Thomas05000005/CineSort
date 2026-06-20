"""GATE AUDIT 2026-06-13 (R5-H1) — enrichissement TMDb post-scan, gate tmdb_enabled.

Quand TMDb est active, le scan resout en arriere-plan le tmdb_id (+ jaquette)
des films identifies NFO/nom sans tmdb_id (la recherche TMDb etant
court-circuitee au scan quand un NFO matche). Gate strict sur tmdb_enabled :
desactive -> aucune resolution (pas d'appels API surprises).
"""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.ui.api import tmdb_support
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import wait_run_done as _wait_done


class TmdbEnrichOnScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_enrich_scan_")
        self.root = Path(self._tmp) / "root"
        self.sd = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.sd.mkdir(parents=True, exist_ok=True)
        (self.root / "Inception 2010.mkv").write_bytes(b"x" * 4096)
        _p = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p.start()
        self.addCleanup(_p.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _scan(self, tmdb_enabled: bool):
        calls = {"n": 0, "ids": [], "run_id": None}

        def fake_enrich(api, run_id, row_ids):
            calls["n"] += 1
            calls["run_id"] = run_id
            calls["ids"] = list(row_ids)
            return {"ok": True, "resolved": 0, "total": len(row_ids), "posters": {}}

        with mock.patch.object(tmdb_support, "enrich_tmdb_ids_by_title", side_effect=fake_enrich):
            api = CineSortApi()
            st = api.run.start_plan(
                {"root": str(self.root), "state_dir": str(self.sd), "tmdb_enabled": tmdb_enabled}
            )
            self.assertTrue(st.get("ok"), st)
            _wait_done(api, str(st["run_id"]))
            # Le hook tourne en thread daemon : laisser converger.
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and calls["n"] == 0 and tmdb_enabled:
                time.sleep(0.05)
            return calls, str(st["run_id"])

    def test_enrich_called_when_tmdb_enabled(self) -> None:
        calls, run_id = self._scan(tmdb_enabled=True)
        self.assertGreaterEqual(calls["n"], 1, "enrich post-scan doit etre lance si tmdb_enabled")
        self.assertEqual(calls["run_id"], run_id)
        self.assertGreaterEqual(len(calls["ids"]), 1, "doit passer les row_ids du run")

    def test_enrich_not_called_when_tmdb_disabled(self) -> None:
        calls, _run_id = self._scan(tmdb_enabled=False)
        # On laisse un petit delai pour ne pas rater un thread tardif.
        time.sleep(0.4)
        self.assertEqual(calls["n"], 0, "enrich ne doit PAS tourner si TMDb desactive")


if __name__ == "__main__":
    unittest.main()
