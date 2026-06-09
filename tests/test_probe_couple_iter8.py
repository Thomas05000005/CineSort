"""ITER 8 cluster settings — Re-ancre couple `probe_workers` + `probe_parallelism_enabled`.

Avant fix : `probe_settings_from_dict` (probe_support.py L19-25) retournait un dict
filtrant SILENCIEUSEMENT les deux cles. Consequence sur le chemin reel
`_prewarm_probe_cache -> _effective_probe_settings_for_runtime ->
probe_settings_from_dict` :
- `probe_parallelism_enabled=False` cote settings.json -> dict transmis SANS la cle
  -> `_prewarm_probe_cache` lit `probe_settings.get("probe_parallelism_enabled", True)`
  -> default True -> toggle utilisateur AVALE.
- `probe_workers=2` cote settings.json -> dict transmis SANS la cle -> service.py
  `_resolve_probe_workers(None)` -> `min(cpu_count(), 8)` -> valeur utilisateur IGNOREE.

Apres fix : `probe_settings_from_dict` traverse `raw.get("probe_workers")` et
`raw.get("probe_parallelism_enabled")` brut. `_normalize_probe_settings` (service.py
L44-70) clamp/normalise deja en aval — pas de duplication ici. Pattern identique a
12b3721 (`perceptual_auto_on_scan`).

Le scenario `start_plan` est INSENSIBLE par construction : le couple est consomme
UNIQUEMENT par `analyze_quality_batch -> _prewarm_probe_cache` (chemin Qualite), pas
par le pipeline scan/plan. Le test cible donc le chemin reel via :
1. `probe_settings_from_dict` (test unitaire approvisionnement) : assert couple PRESENT.
2. `_prewarm_probe_cache` court-circuit OFF : assert retour 0 et `probe_files` NON appelee.
3. `_prewarm_probe_cache` ON : assert `probe_files` appelee + settings transmis contient
   bien `probe_workers=N` user (clampe en aval), `probe_parallelism_enabled=True`.

Ce test FAIL AVANT le fix (couple absent du dict transmis -> tous les asserts
de propagation echouent) et PASS APRES.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.ui.api import quality_support
from cinesort.ui.api.cinesort_api import CineSortApi
from cinesort.ui.api.probe_support import probe_settings_from_dict
from tests._helpers import create_file as _create_file
from tests._helpers import wait_run_done as _wait_done


class ProbeSettingsFromDictPropagationTests(unittest.TestCase):
    """Approvisionnement direct : `probe_settings_from_dict` doit traverser le couple.

    Test le point de drop exact (probe_support.py L19-25). FAIL avant fix car les
    cles sont filtrees ; PASS apres fix.
    """

    def test_couple_present_in_returned_dict_when_user_off(self) -> None:
        out = probe_settings_from_dict(
            {
                "probe_backend": "auto",
                "probe_workers": 2,
                "probe_parallelism_enabled": False,
            }
        )
        # FAIL AVANT FIX : KeyError ou AssertionError (cles absentes).
        self.assertIn("probe_workers", out)
        self.assertIn("probe_parallelism_enabled", out)
        self.assertEqual(out["probe_workers"], 2)
        self.assertEqual(out["probe_parallelism_enabled"], False)

    def test_couple_present_in_returned_dict_when_user_on(self) -> None:
        out = probe_settings_from_dict(
            {
                "probe_backend": "ffprobe",
                "probe_workers": 4,
                "probe_parallelism_enabled": True,
            }
        )
        self.assertEqual(out["probe_workers"], 4)
        self.assertEqual(out["probe_parallelism_enabled"], True)

    def test_couple_absent_in_input_passes_through_none(self) -> None:
        """Input sans le couple -> traverse None (clamp en aval `_normalize_probe_settings`)."""
        out = probe_settings_from_dict({"probe_backend": "auto"})
        # Toujours les cles dans la sortie (preserve traversee).
        self.assertIn("probe_workers", out)
        self.assertIn("probe_parallelism_enabled", out)
        # Valeur None traversee brut (defauts appliques par service._normalize_probe_settings).
        self.assertIsNone(out["probe_workers"])
        self.assertIsNone(out["probe_parallelism_enabled"])


class PrewarmProbeCacheCoupleTests(unittest.TestCase):
    """Differentiel ON vs OFF sur le chemin reel `_prewarm_probe_cache`.

    OFF : retourne 0 (court-circuit L184 quality_support.py) -> probe_files PAS appelee.
    ON  : probe_files appelee avec settings contenant le couple user.

    Le test traverse `start_plan` pour produire un vrai run + plan.jsonl avec
    >=2 row_ids, puis observe `_prewarm_probe_cache` directement (le chemin
    interne de `analyze_quality_batch`).
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_iter8_probe_couple_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Stubs video : 2 films pour avoir >=2 row_ids dans le plan.
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
            "perceptual_auto_on_scan": False,
            "perceptual_enabled": False,
        }

    def _make_run(self, api: CineSortApi, settings: dict) -> tuple[str, list[str]]:
        """Lance start_plan + attend completion + recupere row_ids."""
        start = api.run.start_plan(settings)
        self.assertTrue(start.get("ok"), start)
        run_id = start["run_id"]
        _wait_done(api, run_id, timeout_s=20.0)
        # Recupere les row_ids du plan via la facade run.
        status = api.run.get_status(run_id, 0) or {}
        # Le plan.jsonl est accessible via rs.rows ou via le helper de la facade.
        rs = api._get_run(run_id)
        if rs and rs.rows:
            row_ids = [str(r.row_id) for r in rs.rows]
        else:
            row_ids = []
        self.assertGreaterEqual(
            len(row_ids), 2, f"Plan doit avoir >=2 rows, status={status}, rs={rs}"
        )
        return run_id, row_ids

    def test_off_returns_zero_and_probe_files_not_called(self) -> None:
        """OFF : `_prewarm_probe_cache` court-circuite (return 0), probe_files PAS appelee.

        FAIL AVANT FIX : la cle `probe_parallelism_enabled` est filtree par
        `probe_settings_from_dict`. Le default True applique en aval -> return
        non-zero + probe_files appelee. Test fail au `self.assertEqual(returned, 0)`.
        """
        api = CineSortApi()
        settings = self._base_settings()
        settings["probe_parallelism_enabled"] = False
        settings["probe_workers"] = 2

        # Configure settings persistes (utilises par _effective_probe_settings_for_runtime).
        save_res = api.settings.save_settings(settings)
        self.assertTrue(save_res.get("ok"), save_res)

        run_id, row_ids = self._make_run(api, settings)

        # Mock probe_files au niveau ProbeService (le call site reel L187).
        with mock.patch(
            "cinesort.ui.api.quality_support.ProbeService"
        ) as mock_service_cls:
            mock_probe = mock_service_cls.return_value
            mock_probe.probe_files.return_value = {}
            returned = quality_support._prewarm_probe_cache(api, run_id, row_ids)

        # OFF court-circuit : retourne 0 (L184-185 quality_support.py).
        self.assertEqual(
            returned,
            0,
            "OFF : _prewarm_probe_cache doit retourner 0 (court-circuit)",
        )
        # probe_files NON appelee (court-circuite avant L187).
        mock_probe.probe_files.assert_not_called()

    def test_on_calls_probe_files_with_user_couple_propagated(self) -> None:
        """ON + workers=4 : `probe_files` appelee + settings transmis contient couple user.

        FAIL AVANT FIX : settings transmis NE CONTIENT PAS `probe_workers` ni
        `probe_parallelism_enabled` (filtrees) -> assert sur kwargs settings echoue.
        """
        api = CineSortApi()
        settings = self._base_settings()
        settings["probe_parallelism_enabled"] = True
        settings["probe_workers"] = 4

        save_res = api.settings.save_settings(settings)
        self.assertTrue(save_res.get("ok"), save_res)

        run_id, row_ids = self._make_run(api, settings)

        with mock.patch(
            "cinesort.ui.api.quality_support.ProbeService"
        ) as mock_service_cls:
            mock_probe = mock_service_cls.return_value
            # Simule succes probe sur 2 films.
            mock_probe.probe_files.return_value = {
                "/dummy1": {"ok": True},
                "/dummy2": {"ok": True},
            }
            returned = quality_support._prewarm_probe_cache(api, run_id, row_ids)

        # ON + media_paths >=2 : probe_files DOIT etre appelee une fois.
        self.assertEqual(
            mock_probe.probe_files.call_count,
            1,
            f"ON : probe_files doit etre appelee 1x, vu {mock_probe.probe_files.call_count}",
        )
        # Verifie que le couple user est PROPAGE jusqu'a probe_files via settings kwargs.
        call_kwargs = mock_probe.probe_files.call_args.kwargs
        propagated_settings = call_kwargs.get("settings", {})
        self.assertEqual(
            propagated_settings.get("probe_parallelism_enabled"),
            True,
            f"ON : probe_parallelism_enabled doit etre True dans settings, vu {propagated_settings!r}",
        )
        self.assertEqual(
            propagated_settings.get("probe_workers"),
            4,
            f"ON : probe_workers user=4 doit etre propage, vu {propagated_settings!r}",
        )
        # Confirme return > 0 (resultats simules).
        self.assertGreaterEqual(returned, 2)


if __name__ == "__main__":
    unittest.main()
