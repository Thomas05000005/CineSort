"""ITER 8 cluster settings — Re-ancre `perceptual_auto_on_quality` (no-op silencieux).

Avant fix : le toggle UI etait sauvegarde par `_save_section_perceptual`
(settings_support L1523, defaut True L847) puis expose par `_build_settings_dict`
(perceptual_support L1433 alias `auto_on_quality`), mais ZERO lecture dans le
chemin reel (`_recompute_worker` / `run_flow_support` apres
`recompute_all_scores`).
L'utilisateur activait le toggle, scannait, la recompute quality finissait,
rien ne se passait cote perceptual.

Apres fix : `_recompute_worker` lit
`to_bool(settings.get("perceptual_auto_on_quality"), True)` apres la boucle
row_ids et lance `perceptual_support.analyze_perceptual_batch` sur les row_ids
du run quand ON (gate sur `perceptual_enabled` aussi True, sinon log WARN
bruyant — contrat ii.b).

Le test traverse la vraie entree publique `api.run.start_plan` avec un mini-
test_library (fichiers .mkv stubs > MIN_VIDEO_BYTES), active
`auto_recompute_quality_on_scan=True` pour declencher la recompute background,
isole le declencheur quality avec `perceptual_auto_on_scan=False` (sinon
12b3721 confondrait les deux signaux), mocke
`perceptual_support.analyze_perceptual_batch` et attend la fin du job
recompute via `get_recompute_job_status`. Observe le differentiel ON vs OFF :

- OFF : analyze_perceptual_batch JAMAIS appele.
- ON + perceptual_enabled=False : appel NON fait + log WARN explicite.
- ON + perceptual_enabled=True : appel fait sur les row_ids du run.

Modele direct clone de tests/test_perceptual_auto_on_scan_iter6.py (12b3721).
"""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.ui.api import perceptual_support, quality_audit_support
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import create_file as _create_file
from tests._helpers import wait_run_done as _wait_done


def _wait_recompute_done(api: object, timeout_s: float = 20.0) -> dict:
    """Attendre qu'un job _recompute_worker soit termine.

    Le job est lance par run_flow apres scan (auto_recompute_quality_on_scan=True),
    mais l'API n'expose pas directement le job_id. On poll le registry
    global de quality_audit_support pour trouver le dernier job actif.
    """
    deadline = time.monotonic() + float(timeout_s)
    last: dict = {}
    while time.monotonic() < deadline:
        with quality_audit_support._RECOMPUTE_JOBS_LOCK:
            if quality_audit_support._RECOMPUTE_JOBS:
                # Le dernier job ajoute (started_ts max).
                jid = max(
                    quality_audit_support._RECOMPUTE_JOBS.items(),
                    key=lambda kv: float(kv[1].get("started_ts") or 0.0),
                )[0]
                last = dict(quality_audit_support._RECOMPUTE_JOBS[jid])
        if last.get("status") in {"done", "failed", "cancelled"}:
            return last
        time.sleep(0.03)
    raise AssertionError(
        f"Timeout {timeout_s}s en attendant un job recompute. Dernier status={last}"
    )


class PerceptualAutoOnQualityIter8Tests(unittest.TestCase):
    """ITER 8 CASSE #Z — `perceptual_auto_on_quality` doit declencher
    `analyze_perceptual_batch` en fin de recompute quality quand ON, ne rien
    faire quand OFF."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_iter8_perc_q_")
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

        # Vider le registry global entre tests pour ne pas detecter le job
        # d'un test precedent (registry partage en module-level).
        with quality_audit_support._RECOMPUTE_JOBS_LOCK:
            quality_audit_support._RECOMPUTE_JOBS.clear()

    def tearDown(self) -> None:
        # Vider apres test aussi.
        with quality_audit_support._RECOMPUTE_JOBS_LOCK:
            quality_audit_support._RECOMPUTE_JOBS.clear()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _base_settings(self) -> dict:
        return {
            "root": str(self.root),
            "state_dir": str(self.state_dir),
            "tmdb_enabled": False,
            "omdb_enabled": False,
            # Cle : on veut declencher la recompute quality background.
            "auto_recompute_quality_on_scan": True,
            # On isole le declencheur quality (sinon 12b3721 confondrait
            # les deux signaux perceptual).
            "perceptual_auto_on_scan": False,
            "subtitle_detection_enabled": False,
        }

    def _run_scan_with(self, api: object, settings: dict) -> str:
        """Lance start_plan + attend la fin du scan + attend la fin du job
        recompute. Retourne le run_id."""
        start = api.run.start_plan(settings)
        self.assertTrue(start.get("ok"), start)
        _wait_done(api, start["run_id"], timeout_s=20.0)
        _wait_recompute_done(api, timeout_s=20.0)
        return start["run_id"]

    def _patched_get_settings(self, original: object, overrides: dict) -> object:
        """Wrappe api.settings.get_settings pour injecter perceptual_*
        sans persister settings.json.

        AUDIT 2026-06-11 (R3) : get_settings() retourne un dict PLAT et
        _recompute_worker lit desormais settings.get(...) directement (le
        .get("settings") qui rendait settings={} a ete supprime). On injecte donc
        les overrides au TOP-level. Avant, l'injection nestee {"settings": {...}}
        encodait le bug (le test passait en exercant le chemin casse).
        """

        def _patched():
            base = original() or {}
            base.update(overrides)
            return base

        return _patched

    def test_off_does_not_call_analyze_perceptual_batch(self) -> None:
        """OFF : analyze_perceptual_batch JAMAIS appele apres recompute."""
        api = CineSortApi()
        settings = self._base_settings()
        settings["perceptual_auto_on_quality"] = False
        settings["perceptual_enabled"] = True  # Moteur dispo mais auto OFF

        overrides = {
            "perceptual_enabled": True,
            "perceptual_auto_on_quality": False,
            "perceptual_auto_on_scan": False,
        }
        original = api.settings.get_settings

        with mock.patch.object(
            api.settings,
            "get_settings",
            side_effect=self._patched_get_settings(original, overrides),
        ), mock.patch.object(
            perceptual_support,
            "analyze_perceptual_batch",
            return_value={"ok": True, "success_count": 0, "error_count": 0},
        ) as mocked:
            self._run_scan_with(api, settings)

        self.assertEqual(
            mocked.call_count,
            0,
            "OFF : analyze_perceptual_batch ne doit JAMAIS etre appele",
        )

    def test_on_with_engine_enabled_triggers_batch(self) -> None:
        """ON + perceptual_enabled=True : analyze_perceptual_batch appele
        avec les row_ids du run apres la boucle recompute."""
        api = CineSortApi()
        settings = self._base_settings()
        settings["perceptual_auto_on_quality"] = True
        settings["perceptual_enabled"] = True

        overrides = {
            "perceptual_enabled": True,
            "perceptual_auto_on_quality": True,
            "perceptual_auto_on_scan": False,
        }
        original = api.settings.get_settings

        with mock.patch.object(
            api.settings,
            "get_settings",
            side_effect=self._patched_get_settings(original, overrides),
        ), mock.patch.object(
            perceptual_support,
            "analyze_perceptual_batch",
            return_value={"ok": True, "success_count": 2, "error_count": 0},
        ) as mocked:
            run_id = self._run_scan_with(api, settings)

        self.assertEqual(
            mocked.call_count,
            1,
            "ON + engine enabled : analyze_perceptual_batch doit etre appele une fois",
        )
        args = mocked.call_args
        # signature: analyze_perceptual_batch(api, run_id, row_ids, options=None)
        called_api, called_run_id, called_row_ids = (
            args.args[0],
            args.args[1],
            args.args[2],
        )
        self.assertIs(called_api, api)
        # run_id est celui du dernier run (resolve_latest_run_id)
        self.assertEqual(called_run_id, run_id)
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
        settings["perceptual_auto_on_quality"] = True
        settings["perceptual_enabled"] = False

        overrides = {
            "perceptual_enabled": False,
            "perceptual_auto_on_quality": True,
            "perceptual_auto_on_scan": False,
        }
        original = api.settings.get_settings

        with mock.patch.object(
            api.settings,
            "get_settings",
            side_effect=self._patched_get_settings(original, overrides),
        ), mock.patch.object(
            perceptual_support,
            "analyze_perceptual_batch",
            return_value={"ok": True},
        ) as mocked, self.assertLogs(
            "cinesort.ui.api.quality_audit_support", level="WARNING"
        ) as cm:
            self._run_scan_with(api, settings)

        self.assertEqual(
            mocked.call_count,
            0,
            "ON + engine OFF : analyze_perceptual_batch ne doit PAS etre appele",
        )
        joined = " | ".join(cm.output)
        self.assertIn(
            "perceptual_auto_on_quality",
            joined,
            f"Un log WARN doit signaler le skip d'approvisionnement. logs={joined!r}",
        )


if __name__ == "__main__":
    unittest.main()
