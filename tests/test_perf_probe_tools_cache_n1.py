"""PERF-N1 (2026-08-03) -- la sonde ne doit rien couter quand elle est desactivee.

Trois gardes independantes, mesurees en conditions reelles sur 10 rapports
qualite (bac a sable 12 films, `probe_backend=none`) :

A. `ProbeService._get_tools_cached` s'appuie sur un cache PROCESSUS. Le cache
   porte par `self` ne servait jamais : chaque appelant de production construit
   un `ProbeService` neuf (`quality_report_support.py`, `perceptual_support.py`,
   `probe_support.py`, `quality_support.py`, `runtime_probe_check.py`).
   Mesure avant : 2 `CreateProcess` par rapport.

B. `ProbeService._get_tools_cached` ne sonde AUCUN binaire quand
   `probe_backend == none`. Mesure avant : 2 sous-processus `--version` par
   rapport pour une sonde desactivee.

C. `quality_report_support.probe_settings_for_report` n'appelle
   `_effective_probe_settings_for_runtime` (donc `tools_manager.detect_probe_tools`,
   qui balaye le PATH) que si la sonde est active. Mesure avant : 31,06 ms par
   rapport contre 0,246 ms pour le raccourci ; `shutil.which` 170 -> 38 appels
   sur 10 rapports.

Plus l'invariant qui autorise C : la version complete ne modifie JAMAIS
`probe_backend`, elle ne remplit que les chemins d'outils.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cinesort.infra.db import SQLiteStore, db_path_for_state_dir
from cinesort.infra.probe import service as probe_service_module
from cinesort.infra.probe.service import ProbeService, reset_tools_status_cache
from cinesort.ui.api import probe_support
from cinesort.ui.api.quality_report_support import probe_settings_for_report


class _VersionRunnerSpy:
    """Runner qui n'accepte que les appels `--version` (aucune vraie probe ici)."""

    def __init__(self) -> None:
        self.calls: List[List[str]] = []

    def __call__(self, cmd: List[str], _timeout_s: float) -> Tuple[int, str, str]:
        self.calls.append([str(x) for x in cmd])
        joined = " ".join(str(x) for x in cmd)
        if "--Version" in joined:
            return 0, "MediaInfoLib - v24.01", ""
        if "-version" in joined:
            return 0, "ffprobe version 6.0", ""
        return 1, "", "commande inattendue"


class _WhichSpy:
    def __init__(self) -> None:
        self.calls: List[str] = []

    def __call__(self, name: str) -> Optional[str]:
        self.calls.append(str(name))
        return str(name)


class _ProbeServiceCacheTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="perf_n1_")
        self.addCleanup(self._tmp.cleanup)
        state_dir = Path(self._tmp.name) / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        self.store = SQLiteStore(db_path_for_state_dir(state_dir), busy_timeout_ms=8000)
        self.store.initialize()
        self.media = Path(self._tmp.name) / "movie.mkv"
        self.media.write_bytes(b"\x00" * 1024)
        reset_tools_status_cache()
        self.addCleanup(reset_tools_status_cache)


class ProcessWideToolsCacheTests(_ProbeServiceCacheTestBase):
    """Garde A : le cache d'outils survit a la destruction du ProbeService."""

    def _settings(self) -> Dict[str, Any]:
        return {
            "probe_backend": "auto",
            "mediainfo_path": "mediainfo",
            "ffprobe_path": "ffprobe",
        }

    def test_second_probe_service_reuses_the_tools_status(self) -> None:
        runner = _VersionRunnerSpy()
        which = _WhichSpy()

        first = ProbeService(self.store, runner=runner, which_fn=which)
        tools_first = first._get_tools_cached(
            probe_service_module._normalize_probe_settings(self._settings()),
        )
        version_calls_after_first = len(runner.calls)
        self.assertEqual(version_calls_after_first, 2, runner.calls)

        # Instance NEUVE : c'est exactement ce que fait chaque rapport qualite.
        second = ProbeService(self.store, runner=runner, which_fn=which)
        tools_second = second._get_tools_cached(
            probe_service_module._normalize_probe_settings(self._settings()),
        )

        self.assertEqual(len(runner.calls), version_calls_after_first, runner.calls)
        self.assertEqual(tools_second["ffprobe"].version, tools_first["ffprobe"].version)
        self.assertTrue(tools_second["ffprobe"].available)

    def test_cache_is_not_shared_across_different_runners(self) -> None:
        """Deux doublures differentes, meme signature de chemins : pas de melange."""
        runner_a = _VersionRunnerSpy()
        ProbeService(self.store, runner=runner_a, which_fn=_WhichSpy())._get_tools_cached(
            probe_service_module._normalize_probe_settings(self._settings()),
        )
        runner_b = _VersionRunnerSpy()
        ProbeService(self.store, runner=runner_b, which_fn=_WhichSpy())._get_tools_cached(
            probe_service_module._normalize_probe_settings(self._settings()),
        )
        self.assertEqual(len(runner_a.calls), 2, runner_a.calls)
        self.assertEqual(len(runner_b.calls), 2, runner_b.calls)

    def test_path_change_forces_a_fresh_detection(self) -> None:
        runner = _VersionRunnerSpy()
        which = _WhichSpy()
        cfg_a = probe_service_module._normalize_probe_settings(self._settings())
        ProbeService(self.store, runner=runner, which_fn=which)._get_tools_cached(cfg_a)
        cfg_b = probe_service_module._normalize_probe_settings(
            {**self._settings(), "ffprobe_path": "C:/autre/ffprobe.exe"},
        )
        ProbeService(self.store, runner=runner, which_fn=which)._get_tools_cached(cfg_b)
        self.assertEqual(len(runner.calls), 4, runner.calls)

    def test_invalidate_clears_the_process_cache_too(self) -> None:
        runner = _VersionRunnerSpy()
        which = _WhichSpy()
        cfg = probe_service_module._normalize_probe_settings(self._settings())
        svc = ProbeService(self.store, runner=runner, which_fn=which)
        svc._get_tools_cached(cfg)
        self.assertEqual(len(runner.calls), 2, runner.calls)

        svc.invalidate_tools_status_cache()

        ProbeService(self.store, runner=runner, which_fn=which)._get_tools_cached(cfg)
        self.assertEqual(len(runner.calls), 4, runner.calls)

    def test_stale_entry_expires_after_the_ttl(self) -> None:
        """Un ffprobe installe pendant que l'app tourne doit finir par etre vu."""
        runner = _VersionRunnerSpy()
        which = _WhichSpy()
        cfg = probe_service_module._normalize_probe_settings(self._settings())
        clock = {"t": 1000.0}
        original_monotonic = probe_service_module.time.monotonic
        probe_service_module.time.monotonic = lambda: clock["t"]  # type: ignore[assignment]
        try:
            ProbeService(self.store, runner=runner, which_fn=which)._get_tools_cached(cfg)
            self.assertEqual(len(runner.calls), 2, runner.calls)

            clock["t"] += probe_service_module._TOOLS_STATUS_CACHE_TTL_S / 2.0
            ProbeService(self.store, runner=runner, which_fn=which)._get_tools_cached(cfg)
            self.assertEqual(len(runner.calls), 2, runner.calls)

            clock["t"] += probe_service_module._TOOLS_STATUS_CACHE_TTL_S
            ProbeService(self.store, runner=runner, which_fn=which)._get_tools_cached(cfg)
            self.assertEqual(len(runner.calls), 4, runner.calls)
        finally:
            probe_service_module.time.monotonic = original_monotonic  # type: ignore[assignment]


class ProbeDisabledSkipsToolDetectionTests(_ProbeServiceCacheTestBase):
    """Garde B : `probe_backend=none` ne sonde aucun binaire."""

    def _disabled_settings(self) -> Dict[str, Any]:
        return {
            "probe_backend": "none",
            "mediainfo_path": "mediainfo",
            "ffprobe_path": "ffprobe",
        }

    def test_probe_file_with_backend_none_launches_no_subprocess(self) -> None:
        runner = _VersionRunnerSpy()
        which = _WhichSpy()
        service = ProbeService(self.store, runner=runner, which_fn=which)

        out = service.probe_file(media_path=self.media, settings=self._disabled_settings())

        self.assertTrue(out.get("ok"), out)
        self.assertEqual(runner.calls, [], runner.calls)
        self.assertEqual(which.calls, [], which.calls)
        messages = [str(m) for m in (out.get("normalized") or {}).get("messages", [])]
        self.assertTrue(any("desactivee" in m.lower() for m in messages), messages)

    def test_disabled_tool_status_says_not_probed_not_missing(self) -> None:
        """Pas de succes ni d'echec silencieux : le message dit POURQUOI."""
        runner = _VersionRunnerSpy()
        service = ProbeService(self.store, runner=runner, which_fn=_WhichSpy())

        payload = service.get_tools_status(self._disabled_settings())

        self.assertEqual(payload["probe_backend"], "none")
        for name in ("mediainfo", "ffprobe"):
            tool = payload["tools"][name]
            self.assertFalse(tool["available"], tool)
            self.assertIn("probe_backend=none", tool["message"])
            self.assertIn("non sonde", tool["message"])
        self.assertEqual(runner.calls, [], runner.calls)

    def test_active_backend_still_probes_the_binaries(self) -> None:
        """Non-regression : le court-circuit ne doit pas deborder sur `auto`."""
        runner = _VersionRunnerSpy()
        service = ProbeService(self.store, runner=runner, which_fn=_WhichSpy())

        payload = service.get_tools_status({**self._disabled_settings(), "probe_backend": "auto"})

        self.assertEqual(payload["probe_backend"], "auto")
        self.assertTrue(payload["tools"]["ffprobe"]["available"])
        self.assertEqual(len(runner.calls), 2, runner.calls)


class _ApiDouble:
    """Double minimal de CineSortApi pour le seul chemin `probe_settings_for_report`."""

    def __init__(self, settings: Dict[str, Any], effective: Optional[Dict[str, Any]] = None) -> None:
        self._settings = settings
        self._effective = effective or {}
        self.effective_calls = 0
        self.settings = self

    def get_settings(self) -> Dict[str, Any]:
        return dict(self._settings)

    def _effective_probe_settings_for_runtime(self, run_row: Any = None) -> Dict[str, Any]:
        self.effective_calls += 1
        return dict(self._effective)


class ProbeSettingsForReportTests(unittest.TestCase):
    """Garde C : pas de balayage du PATH quand la sonde est desactivee."""

    def test_backend_none_never_calls_the_expensive_resolver(self) -> None:
        api = _ApiDouble({"probe_backend": "none"}, effective={"probe_backend": "none", "ffprobe_path": "X"})

        cfg = probe_settings_for_report(api, {"config_json": "{}"})

        self.assertEqual(api.effective_calls, 0)
        self.assertEqual(cfg["probe_backend"], "none")

    def test_active_backend_still_resolves_the_tool_paths(self) -> None:
        api = _ApiDouble(
            {"probe_backend": "auto"},
            effective={"probe_backend": "auto", "ffprobe_path": "C:/tools/ffprobe.exe"},
        )

        cfg = probe_settings_for_report(api, {"config_json": "{}"})

        self.assertEqual(api.effective_calls, 1)
        self.assertEqual(cfg["ffprobe_path"], "C:/tools/ffprobe.exe")

    def test_backend_falls_back_on_the_run_config_when_settings_are_empty(self) -> None:
        """Meme repli que `effective_probe_settings_for_runtime` : `current` sinon `base`."""
        api = _ApiDouble({}, effective={"probe_backend": "auto"})

        cfg = probe_settings_for_report(api, {"config_json": '{"probe_backend": "none"}'})

        self.assertEqual(api.effective_calls, 0)
        self.assertEqual(cfg["probe_backend"], "none")


class EffectiveProbeSettingsInvariantTests(unittest.TestCase):
    """L'invariant qui autorise la garde C, verrouille contre la derive."""

    def test_full_resolver_never_rewrites_probe_backend(self) -> None:
        seen: Dict[str, Any] = {}

        def fake_detect(**kwargs: Any) -> Dict[str, Any]:
            seen.update(kwargs)
            return {
                "tools": {
                    "ffprobe": {"available": True, "path": "C:/tools/ffprobe.exe"},
                    "mediainfo": {"available": True, "path": "C:/tools/mediainfo.exe"},
                }
            }

        for backend in ("none", "auto", "ffprobe", "mediainfo"):
            api = _ApiDouble({"probe_backend": backend, "state_dir": ""})
            api._state_dir = Path(tempfile.gettempdir())
            api._probe_tools_cache = {}
            cheap = probe_support.probe_settings_from_dict({"probe_backend": backend})
            full = probe_support.effective_probe_settings_for_runtime(
                api,
                None,
                detect_probe_tools_fn=fake_detect,
            )
            self.assertEqual(
                full["probe_backend"],
                cheap["probe_backend"],
                f"backend={backend}: le resolveur complet a reecrit probe_backend",
            )
            # Il ne fait bien QUE remplir les chemins d'outils.
            self.assertEqual(full["ffprobe_path"], "C:/tools/ffprobe.exe")
            self.assertEqual(full["mediainfo_path"], "C:/tools/mediainfo.exe")


if __name__ == "__main__":
    unittest.main()
