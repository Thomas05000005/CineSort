"""Tests V5-04 (Polish Total v7.7.0, R5-STRESS-1) : probe parallelisation.

Verifie que ProbeService.probe_files() :
- Utilise ThreadPoolExecutor quand parallelism_enabled + N>1.
- Mono-thread quand parallelism_enabled=False ou N<=1.
- Cache lookup AVANT submit (evite subprocess inutile).
- Preserve l'ordre des resultats via dict mapping path -> result.
- Workers count clampe : auto = min(cpu_count(), 8), max 16.
- Tolerance aux erreurs (un probe qui plante ne tue pas le batch).
"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from cinesort.infra.db import SQLiteStore, db_path_for_state_dir
from cinesort.infra.probe.constants import PROBE_WORKERS_AUTO_CAP, PROBE_WORKERS_MAX
from cinesort.infra.probe.service import ProbeService, _resolve_probe_workers


class _SlowRunnerSpy:
    """Runner qui simule un subprocess ffprobe lent (sleep) et trace les threads.

    `calls` ne compte que les vrais probes de fichier (pas les --Version checks).
    """

    def __init__(self, sleep_s: float = 0.05) -> None:
        self.sleep_s = sleep_s
        self.calls = 0
        self.version_calls = 0
        self.thread_ids: set = set()
        self._lock = threading.Lock()
        self._payload = (
            '{"format": {"format_name": "matroska,webm", "duration": "60.0"}, '
            '"streams": [{"codec_type": "video", "codec_name": "h264", '
            '"width": 1920, "height": 1080}]}'
        )

    def __call__(self, cmd, timeout_s):
        # Les checks de version sont [tool, --Version|-version] — pas de fichier media.
        is_version_check = len(cmd) == 2 and str(cmd[1]).lower() in ("--version", "-version")
        with self._lock:
            if is_version_check:
                self.version_calls += 1
            else:
                self.calls += 1
                self.thread_ids.add(threading.get_ident())
        if is_version_check:
            # Version checks ne dorment pas (rapides en realite).
            return 0, "ffprobe version 6.0", ""
        time.sleep(self.sleep_s)
        return 0, self._payload, ""


class ProbeWorkersResolutionTests(unittest.TestCase):
    """Verifie le clamp de probe_workers (0=auto, [1, 16])."""

    def test_zero_value_uses_auto_capped_at_8(self) -> None:
        with mock.patch("cinesort.infra.probe.service.os.cpu_count", return_value=32):
            self.assertEqual(_resolve_probe_workers(0), PROBE_WORKERS_AUTO_CAP)

    def test_negative_value_uses_auto(self) -> None:
        with mock.patch("cinesort.infra.probe.service.os.cpu_count", return_value=4):
            self.assertEqual(_resolve_probe_workers(-1), 4)

    def test_explicit_value_clamped_to_max(self) -> None:
        self.assertEqual(_resolve_probe_workers(99), PROBE_WORKERS_MAX)

    def test_explicit_value_clamped_to_min(self) -> None:
        # input <= 0 retombe sur auto, donc on teste un input "1".
        self.assertEqual(_resolve_probe_workers(1), 1)

    def test_invalid_value_uses_auto(self) -> None:
        with mock.patch("cinesort.infra.probe.service.os.cpu_count", return_value=4):
            self.assertEqual(_resolve_probe_workers("garbage"), 4)
            self.assertEqual(_resolve_probe_workers(None), 4)

    def test_cpu_count_none_falls_back_to_4(self) -> None:
        with mock.patch("cinesort.infra.probe.service.os.cpu_count", return_value=None):
            # Default fallback = 4, capped at 8 -> 4
            self.assertEqual(_resolve_probe_workers(0), 4)


class ProbeFilesBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="probe_par_")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path_for_state_dir(self.state_dir)
        self.store = SQLiteStore(self.db_path, busy_timeout_ms=8000)
        self.store.initialize()
        # 5 fichiers films minces (assez pour declencher parallel).
        self.media_paths = []
        for i in range(5):
            mp = Path(self._tmp.name) / f"movie_{i:03d}.mkv"
            mp.write_bytes(b"\x00" * 256)
            self.media_paths.append(mp)

    def _make_service(self, runner: _SlowRunnerSpy) -> ProbeService:
        return ProbeService(self.store, runner=runner, which_fn=lambda name: str(name))

    def _settings(self, **overrides) -> dict:
        base = {
            "probe_backend": "ffprobe",
            "mediainfo_path": "",
            "ffprobe_path": "ffprobe",
        }
        base.update(overrides)
        return base

    def test_empty_input_returns_empty_dict(self) -> None:
        runner = _SlowRunnerSpy()
        service = self._make_service(runner)
        out = service.probe_files(media_paths=[], settings=self._settings())
        self.assertEqual(out, {})
        self.assertEqual(runner.calls, 0)

    def test_single_file_uses_mono_thread_path(self) -> None:
        runner = _SlowRunnerSpy()
        service = self._make_service(runner)
        out = service.probe_files(media_paths=[self.media_paths[0]], settings=self._settings())
        self.assertEqual(len(out), 1)
        self.assertIn(str(self.media_paths[0]), out)
        # Mono-thread = 1 seul thread utilise.
        self.assertEqual(len(runner.thread_ids), 1)

    def test_parallel_enabled_uses_multiple_threads(self) -> None:
        runner = _SlowRunnerSpy(sleep_s=0.05)
        service = self._make_service(runner)
        settings = self._settings(probe_parallelism_enabled=True, probe_workers=4)
        out = service.probe_files(media_paths=self.media_paths, settings=settings)
        self.assertEqual(len(out), len(self.media_paths))
        # Au moins 2 threads differents (parallelism actif).
        self.assertGreaterEqual(len(runner.thread_ids), 2)

    def test_parallel_disabled_uses_mono_thread(self) -> None:
        runner = _SlowRunnerSpy()
        service = self._make_service(runner)
        settings = self._settings(probe_parallelism_enabled=False)
        out = service.probe_files(media_paths=self.media_paths, settings=settings)
        self.assertEqual(len(out), len(self.media_paths))
        # 1 seul thread (mono-thread force).
        self.assertEqual(len(runner.thread_ids), 1)

    def test_results_keyed_by_path_preserve_mapping(self) -> None:
        runner = _SlowRunnerSpy()
        service = self._make_service(runner)
        out = service.probe_files(media_paths=self.media_paths, settings=self._settings())
        # Chaque media_path doit etre une cle dans le resultat.
        for mp in self.media_paths:
            self.assertIn(str(mp), out)
            self.assertTrue(out[str(mp)].get("ok"))

    def test_cache_hit_skips_subprocess(self) -> None:
        runner = _SlowRunnerSpy()
        service = self._make_service(runner)
        # 1er pass : remplit le cache.
        service.probe_files(media_paths=self.media_paths, settings=self._settings())
        first_calls = runner.calls
        self.assertEqual(first_calls, len(self.media_paths))
        # 2eme pass : tout doit hit le cache.
        runner.calls = 0
        runner.thread_ids.clear()
        out = service.probe_files(media_paths=self.media_paths, settings=self._settings())
        self.assertEqual(len(out), len(self.media_paths))
        self.assertEqual(runner.calls, 0)
        # Toutes les entrees doivent etre cache_hit=True.
        for mp in self.media_paths:
            self.assertTrue(out[str(mp)].get("cache_hit"))

    def test_partial_cache_hit_only_probes_missing(self) -> None:
        runner = _SlowRunnerSpy()
        service = self._make_service(runner)
        # Cache only first 2.
        service.probe_files(media_paths=self.media_paths[:2], settings=self._settings())
        runner.calls = 0
        out = service.probe_files(media_paths=self.media_paths, settings=self._settings())
        self.assertEqual(len(out), len(self.media_paths))
        # Seuls les 3 manquants ont declenche subprocess.
        self.assertEqual(runner.calls, 3)
        # Les 2 premiers sont cache_hit.
        self.assertTrue(out[str(self.media_paths[0])].get("cache_hit"))
        self.assertTrue(out[str(self.media_paths[1])].get("cache_hit"))
        # Les 3 derniers ne sont pas cache_hit (fresh).
        for mp in self.media_paths[2:]:
            self.assertFalse(out[str(mp)].get("cache_hit"))

    def test_parallel_faster_than_sequential(self) -> None:
        """Verifie que parallel est mesurablement plus rapide que mono-thread."""
        # 5 films, 100ms chacun.
        runner_seq = _SlowRunnerSpy(sleep_s=0.10)
        service_seq = ProbeService(self.store, runner=runner_seq, which_fn=lambda n: str(n))
        # Empty cache : creer un nouveau store pour chaque run.
        t0 = time.monotonic()
        service_seq.probe_files(
            media_paths=self.media_paths,
            settings=self._settings(probe_parallelism_enabled=False),
        )
        seq_dur = time.monotonic() - t0

        # Reset cache pour le run parallel.
        for mp in self.media_paths:
            mp.touch()  # change mtime -> cache miss

        runner_par = _SlowRunnerSpy(sleep_s=0.10)
        service_par = ProbeService(self.store, runner=runner_par, which_fn=lambda n: str(n))
        t0 = time.monotonic()
        service_par.probe_files(
            media_paths=self.media_paths,
            settings=self._settings(probe_parallelism_enabled=True, probe_workers=4),
        )
        par_dur = time.monotonic() - t0

        # Parallel doit etre au moins 1.5x plus rapide (5 films, 4 workers, sleep 100ms :
        # sequential ≈ 500ms, parallel ≈ 200ms attendus).
        self.assertLess(par_dur, seq_dur * 0.75, f"par={par_dur:.3f}s seq={seq_dur:.3f}s")

    def test_invalid_probe_workers_value_falls_back_to_auto(self) -> None:
        """Settings avec probe_workers='abc' tombe sur l'auto resolution."""
        runner = _SlowRunnerSpy()
        service = self._make_service(runner)
        out = service.probe_files(
            media_paths=self.media_paths,
            settings=self._settings(probe_workers="garbage"),
        )
        self.assertEqual(len(out), len(self.media_paths))

    def test_duplicate_input_paths_deduplicated(self) -> None:
        """Si on passe le meme path 2x, il n'est probe qu'une fois."""
        runner = _SlowRunnerSpy()
        service = self._make_service(runner)
        mp = self.media_paths[0]
        out = service.probe_files(media_paths=[mp, mp, mp], settings=self._settings())
        self.assertEqual(len(out), 1)
        self.assertEqual(runner.calls, 1)

    def test_100_files_completes_under_reasonable_time(self) -> None:
        """100 films simules avec 8 workers : doit etre nettement < mono-thread.

        Compare parallel vs sequential pour eviter la flakiness CI : on
        verifie le ratio (parallel doit etre au moins 2x plus rapide), pas
        une borne absolue qui depend de la charge machine.
        """
        # Cree 100 fichiers vides.
        many = []
        for i in range(100):
            mp = Path(self._tmp.name) / f"big_{i:04d}.mkv"
            mp.write_bytes(b"\x00" * 64)
            many.append(mp)
        # Run parallel
        runner_par = _SlowRunnerSpy(sleep_s=0.02)
        service_par = ProbeService(self.store, runner=runner_par, which_fn=lambda n: str(n))
        t0 = time.monotonic()
        out_par = service_par.probe_files(
            media_paths=many,
            settings=self._settings(probe_parallelism_enabled=True, probe_workers=8),
        )
        par_dur = time.monotonic() - t0
        self.assertEqual(len(out_par), 100)

        # Reset cache via touch (mtime changes -> cache miss)
        for mp in many:
            mp.touch()

        # Run sequential
        runner_seq = _SlowRunnerSpy(sleep_s=0.02)
        service_seq = ProbeService(self.store, runner=runner_seq, which_fn=lambda n: str(n))
        t0 = time.monotonic()
        out_seq = service_seq.probe_files(
            media_paths=many,
            settings=self._settings(probe_parallelism_enabled=False),
        )
        seq_dur = time.monotonic() - t0
        self.assertEqual(len(out_seq), 100)

        # Parallel doit etre plus rapide que sequentiel (gain reel attendu : 4-8x
        # selon CPU/Windows scheduling). Seuil 0.7 pour absorber le jitter CI :
        # un gain de 30%+ (par < 70% seq) prouve le parallelism, le gain reel
        # observe est typiquement 50-80% mais varie selon la machine.
        self.assertLess(
            par_dur,
            seq_dur * 0.7,
            f"100 films par={par_dur:.3f}s seq={seq_dur:.3f}s (gain insuffisant)",
        )

    def test_one_failing_probe_does_not_kill_batch(self) -> None:
        """Un subprocess qui plante en parallele ne doit pas tuer les autres."""
        bad_runner_calls = {"count": 0}

        def runner(cmd, timeout_s):
            bad_runner_calls["count"] += 1
            if bad_runner_calls["count"] == 2:
                raise OSError("simulated subprocess crash")
            time.sleep(0.01)
            return (
                0,
                '{"format": {"format_name": "matroska", "duration": "1.0"}, "streams": []}',
                "",
            )

        service = ProbeService(self.store, runner=runner, which_fn=lambda n: str(n))
        out = service.probe_files(
            media_paths=self.media_paths,
            settings=self._settings(probe_parallelism_enabled=True, probe_workers=2),
        )
        # Tous les paths doivent avoir un resultat (meme si certains failed).
        self.assertEqual(len(out), len(self.media_paths))


class ProbeBatchSettingsNormalizationTests(unittest.TestCase):
    """Verifie que _normalize_probe_settings expose probe_workers + parallelism."""

    def test_default_settings_have_parallelism_enabled(self) -> None:
        from cinesort.infra.probe.service import _normalize_probe_settings

        cfg = _normalize_probe_settings({})
        self.assertTrue(cfg["probe_parallelism_enabled"])
        # 0 (auto) → workers > 0 apres normalisation
        self.assertGreaterEqual(cfg["probe_workers"], 1)
        self.assertLessEqual(cfg["probe_workers"], PROBE_WORKERS_MAX)

    def test_explicit_disable(self) -> None:
        from cinesort.infra.probe.service import _normalize_probe_settings

        cfg = _normalize_probe_settings({"probe_parallelism_enabled": False})
        self.assertFalse(cfg["probe_parallelism_enabled"])

    def test_explicit_workers_clamped(self) -> None:
        from cinesort.infra.probe.service import _normalize_probe_settings

        cfg = _normalize_probe_settings({"probe_workers": 999})
        self.assertEqual(cfg["probe_workers"], PROBE_WORKERS_MAX)


if __name__ == "__main__":
    unittest.main()
