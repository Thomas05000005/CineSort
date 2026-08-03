"""ITER 6 cluster settings — Re-ancre `perceptual_auto_on_scan` (no-op silencieux).

Avant fix : le toggle UI etait sauvegarde par `_save_section_perceptual` puis
expose par `_build_settings_dict`, mais ZERO lecture dans le chemin start_plan
reel (`run_flow_support` / `_build_plan_job_fn` / `job_fn` / `_start_plan_impl`).
L'utilisateur activait le toggle, scannait, rien ne se passait cote perceptual.

Apres fix : `_build_plan_job_fn` lit `to_bool(settings.get("perceptual_auto_on_scan"))`
apres `_save_plan_artifacts` et lance `perceptual_support.analyze_perceptual_batch`
sur les row_ids du run quand ON (gate sur `perceptual_enabled` aussi True, sinon
log WARN bruyant — contrat ii.b).

Le test traverse la vraie entree publique `api.run.start_plan` avec un mini-
test_library (fichiers .mkv stubs > MIN_VIDEO_BYTES), mocke
`perceptual_support.analyze_perceptual_batch` (reponses deterministes, pas de
ffprobe/ffmpeg necessaire) et observe le differentiel ON vs OFF :

- OFF (defaut) : analyze_perceptual_batch JAMAIS appele.
- ON + perceptual_enabled=False : appel NON fait + log WARN explicite.
- ON + perceptual_enabled=True : appel fait sur les row_ids du run.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.ui.api import perceptual_support
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import create_file as _create_file
from tests._helpers import wait_run_done as _wait_done


class PerceptualAutoOnScanIter6Tests(unittest.TestCase):
    """ITER 6 BUG #1 — `perceptual_auto_on_scan` doit declencher
    `analyze_perceptual_batch` en fin de scan quand ON, ne rien faire quand OFF."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_iter6_perc_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Stubs video minimaux : 2 films pour avoir des row_ids dans le plan.
        _create_file(self.root / "Inception.2010.1080p" / "Inception.2010.1080p.mkv")
        _create_file(self.root / "The.Matrix.1999.1080p" / "The.Matrix.1999.1080p.mkv")

        _p_min_video = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p_min_video.start()
        self.addCleanup(_p_min_video.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _base_settings(self) -> dict:
        return {
            "root": str(self.root),
            "state_dir": str(self.state_dir),
            "tmdb_enabled": False,
            "omdb_enabled": False,
            "auto_recompute_quality_on_scan": False,
            "subtitle_detection_enabled": False,
        }

    def test_off_does_not_call_analyze_perceptual_batch(self) -> None:
        """OFF (defaut) : analyze_perceptual_batch JAMAIS appele."""
        api = CineSortApi()
        settings = self._base_settings()
        settings["perceptual_auto_on_scan"] = False
        settings["perceptual_enabled"] = True  # Moteur dispo mais auto OFF

        with mock.patch.object(
            perceptual_support,
            "analyze_perceptual_batch",
            return_value={"ok": True, "success_count": 0, "error_count": 0},
        ) as mocked:
            start = api.run.start_plan(settings)
            self.assertTrue(start.get("ok"), start)
            _wait_done(api, start["run_id"], timeout_s=20.0)

        self.assertEqual(
            mocked.call_count,
            0,
            "OFF : analyze_perceptual_batch ne doit JAMAIS etre appele",
        )

    def test_on_with_engine_enabled_triggers_batch(self) -> None:
        """ON + perceptual_enabled=True : analyze_perceptual_batch appele
        avec les row_ids du run."""
        api = CineSortApi()
        settings = self._base_settings()
        settings["perceptual_auto_on_scan"] = True
        settings["perceptual_enabled"] = True

        with mock.patch.object(
            perceptual_support,
            "analyze_perceptual_batch",
            return_value={"ok": True, "success_count": 2, "error_count": 0},
        ) as mocked:
            start = api.run.start_plan(settings)
            self.assertTrue(start.get("ok"), start)
            _wait_done(api, start["run_id"], timeout_s=20.0)

        self.assertEqual(
            mocked.call_count,
            1,
            "ON + engine enabled : analyze_perceptual_batch doit etre appele une fois",
        )
        args = mocked.call_args
        # signature: analyze_perceptual_batch(api, run_id, row_ids, options=None)
        called_api, called_run_id, called_row_ids = args.args[0], args.args[1], args.args[2]
        self.assertIs(called_api, api)
        self.assertEqual(called_run_id, start["run_id"])
        self.assertIsInstance(called_row_ids, list)
        self.assertGreaterEqual(len(called_row_ids), 2)
        for rid in called_row_ids:
            self.assertIsInstance(rid, str)
            self.assertTrue(rid.strip(), "row_id ne doit pas etre vide")

    def test_on_without_engine_logs_warn_and_skips(self) -> None:
        """ON + perceptual_enabled=False : pas d'appel mais log WARN bruyant
        (contrat ii.b : echec d'approvisionnement observable)."""
        api = CineSortApi()
        settings = self._base_settings()
        settings["perceptual_auto_on_scan"] = True
        settings["perceptual_enabled"] = False  # Moteur OFF -> warn + skip

        with mock.patch.object(
            perceptual_support,
            "analyze_perceptual_batch",
            return_value={"ok": True},
        ) as mocked:
            start = api.run.start_plan(settings)
            self.assertTrue(start.get("ok"), start)
            status = _wait_done(api, start["run_id"], timeout_s=20.0)

        self.assertEqual(
            mocked.call_count,
            0,
            "ON + engine OFF : analyze_perceptual_batch ne doit PAS etre appele",
        )
        # Le log WARN doit contenir le message bruyant.
        # Format _run_state.RunState.log : items {"ts","level","msg"}.
        logs_status = api.run.get_status(start["run_id"], 0)
        all_logs = logs_status.get("logs") or status.get("logs") or []
        warn_msgs = [str(l.get("msg", "") if isinstance(l, dict) else l) for l in all_logs]
        joined = " | ".join(warn_msgs)
        self.assertIn(
            "perceptual_auto_on_scan",
            joined,
            f"Un log WARN doit signaler le skip d'approvisionnement. logs={joined!r}",
        )


if __name__ == "__main__":
    unittest.main()
