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

    `rendezvous` (optionnel) transforme l'espion en **preuve** de simultaneite
    plutot qu'en indice : les `rendezvous` premiers probes se bloquent sur une
    barriere et ne peuvent repartir que lorsque tous sont arrives. Si le service
    probe en sequentiel, le premier arrive attend seul jusqu'au timeout et
    `rendezvous_timed_out` passe a True. Aucune horloge murale n'intervient dans
    le verdict : c'est la seule facon d'observer « N probes tournent VRAIMENT en
    meme temps » sans dependre de la vitesse de la machine.

    L'exception de barriere est capturee ici et convertie en drapeau parce que
    `probe_files` tolere les erreurs de probe (un probe qui plante ne tue pas le
    batch) : laisser remonter `BrokenBarrierError` la ferait avaler en silence,
    et le test verrait un batch un peu plus court au lieu d'un echec explicite.
    """

    def __init__(
        self, sleep_s: float = 0.05, rendezvous: int | None = None, rendezvous_timeout_s: float = 60.0
    ) -> None:
        self.sleep_s = sleep_s
        self.calls = 0
        self.version_calls = 0
        self.thread_ids: set = set()
        self.max_concurrent = 0
        self.rendezvous_timed_out = False
        self._in_flight = 0
        self._rendezvous_left = rendezvous or 0
        self._rendezvous_timeout_s = rendezvous_timeout_s
        self._barrier = threading.Barrier(rendezvous) if rendezvous else None
        self._lock = threading.Lock()
        self._payload = (
            '{"format": {"format_name": "matroska,webm", "duration": "60.0"}, '
            '"streams": [{"codec_type": "video", "codec_name": "h264", '
            '"width": 1920, "height": 1080}]}'
        )

    def _await_rendezvous(self) -> None:
        """Bloque sur la barriere si ce probe fait partie des N premiers."""
        with self._lock:
            if self._barrier is None or self._rendezvous_left <= 0:
                return
            self._rendezvous_left -= 1
        try:
            self._barrier.wait(timeout=self._rendezvous_timeout_s)
        except threading.BrokenBarrierError:
            # Timeout OU barriere deja cassee par un autre thread : dans les deux
            # cas la simultaneite demandee n'a pas ete atteinte.
            self.rendezvous_timed_out = True

    def __call__(self, cmd, timeout_s):
        # Les checks de version sont [tool, --Version|-version] — pas de fichier media.
        is_version_check = len(cmd) == 2 and str(cmd[1]).lower() in ("--version", "-version")
        with self._lock:
            if is_version_check:
                self.version_calls += 1
            else:
                self.calls += 1
                self.thread_ids.add(threading.get_ident())
                self._in_flight += 1
                self.max_concurrent = max(self.max_concurrent, self._in_flight)
        if is_version_check:
            # Version checks ne dorment pas (rapides en realite).
            return 0, "ffprobe version 6.0", ""
        try:
            self._await_rendezvous()
            time.sleep(self.sleep_s)
            return 0, self._payload, ""
        finally:
            with self._lock:
                self._in_flight -= 1


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

    def test_parallel_uses_multiple_threads(self) -> None:
        """Verifie que parallel a effectivement utilise plusieurs threads.

        Cf issue #88 : l'ancien test test_parallel_faster_than_sequential
        comparait des durees wall-clock (par < seq * 0.75), tres flaky sur CI
        Windows (preemption, AV, threadpool init >50ms). Remplace par une
        verification structurelle : runner.thread_ids contient > 1 ident
        distincts quand parallelism_enabled=True + probe_workers=4. C'est la
        VRAIE definition de "parallel" et c'est deterministe.

        2026-08-29 : le check timing soft (par_dur < seq_dur * 1.5) est RETIRE.
        Il a echoue en CI a par=1.211s / seq=0.713s, c'est-a-dire pour la raison
        exacte que la docstring ci-dessus annonce depuis l'issue #88 :
        preemption Windows, AV, init du threadpool. Un ratio wall-clock sur 5
        fichiers de 100 ms n'a pas assez de signal pour dominer ce bruit — il ne
        mesurait plus la parallelisation, seulement la charge du runner.

        Il n'est pas remplace par une marge plus large mais par la BARRIERE de
        rendez-vous, deja portee par `_SlowRunnerSpy` et deja utilisee par
        `test_100_files_probe_simultaneously`. Ce test-la dit d'ailleurs que « la
        conversion avait simplement oublie ce test-ci » : on la termine.

        La barriere est STRICTEMENT plus forte que le ratio : elle ne se debloque
        que si N probes sont reellement en vol au meme instant, et aucune horloge
        n'entre dans le verdict. Elle attrape meme le cas qu'un ratio ne voyait
        pas — plusieurs threads dont le travail serait serialise par un verrou.
        """
        # 5 films, 100ms chacun.
        runner_seq = _SlowRunnerSpy(sleep_s=0.10)
        service_seq = ProbeService(self.store, runner=runner_seq, which_fn=lambda n: str(n))
        service_seq.probe_files(
            media_paths=self.media_paths,
            settings=self._settings(probe_parallelism_enabled=False),
        )

        # Reset cache pour le run parallel.
        for mp in self.media_paths:
            mp.touch()  # change mtime -> cache miss

        # rendezvous=4 : les 4 premiers probes se bloquent mutuellement jusqu'a ce
        # que les 4 soient arrives. 5 fichiers pour 4 workers, donc les 4 partent
        # ensemble. En sequentiel, le premier attendrait seul et le drapeau de
        # timeout se leverait.
        runner_par = _SlowRunnerSpy(sleep_s=0.10, rendezvous=4, rendezvous_timeout_s=60.0)
        service_par = ProbeService(self.store, runner=runner_par, which_fn=lambda n: str(n))
        service_par.probe_files(
            media_paths=self.media_paths,
            settings=self._settings(probe_parallelism_enabled=True, probe_workers=4),
        )

        # Assertion principale : parallelism observable via les thread idents
        # uniques utilises par le runner. Avec 5 fichiers et 4 workers, on
        # s'attend a >= 2 threads (souvent 4, mais 2 suffit pour valider).
        self.assertGreater(
            len(runner_par.thread_ids),
            1,
            f"Parallel doit utiliser plusieurs threads, vu seulement {len(runner_par.thread_ids)}",
        )
        # Sequential doit utiliser exactement 1 thread.
        self.assertEqual(len(runner_seq.thread_ids), 1)

        # PREUVE de simultaneite, sans horloge : la barriere ne s'est pas debloquee
        # par timeout, donc 4 probes tournaient VRAIMENT au meme instant.
        self.assertFalse(
            runner_par.rendezvous_timed_out,
            "la barriere a expire : les probes ne tournent pas simultanement, ils sont serialises malgre plusieurs threads",
        )

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

    def test_100_files_probe_simultaneously(self) -> None:
        """100 films / 8 workers : prouve que 8 probes tournent VRAIMENT ensemble.

        Ce test comparait auparavant deux durees wall-clock
        (`par_dur < seq_dur * 0.7`) et s'appelait
        `test_100_files_completes_under_reasonable_time`. Il etait connu flaky
        depuis le 2026-06-08 (`docs/internal/BILAN_PREP_BOUCLE_2026-06-08.md` le
        classe « flaky / seuil temporel », et `BILAN_ITER8_2026-06-08.md`
        documente un run ou il a du etre deselectionne) et il a fini par bloquer
        la totalite du backlog : sur `main` le 2026-08-04 il est tombe a
        `par=18.950s seq=26.541s`, soit un ratio de 0.714 contre 0.700 exiges —
        rate de 2 % — ce qui a mis le check requis `Lint, Tests, Build` au rouge
        sur main, donc sur les ~50 PR armees, qui fusionnent avec main.

        Pourquoi ce ratio n'etait pas mesurable de facon fiable : le sleep simule
        ne pese que 2 s des ~12 s d'un run sequentiel (mesure locale) ; tout le
        reste est du travail Python **tenu par le GIL** (parsing JSON, ecritures
        SQLite, hachage). Le gain observable depend donc du nombre de cœurs du
        runner. En local (machine large) le ratio tombe a 0.49 ; le job
        `Lint, Tests, Build` tourne sur `windows-latest`, qui a 4 cœurs, et il y
        stagne autour de 0.71. Le seuil etait pose exactement sur le plancher de
        bruit du runner de CI.

        Le remplacement suit le precedent deja etabli DANS CE FICHIER par
        l'issue #88, qui avait converti `test_parallel_faster_than_sequential` en
        verification structurelle pour exactement la meme raison — la conversion
        avait simplement oublie ce test-ci.

        La nouvelle assertion est **strictement plus forte** que l'ancienne : un
        ratio pouvait passer par chance avec 2 workers actifs sur 8, alors qu'une
        barriere a 8 participants ne se debloque que si 8 probes sont reellement
        en vol au meme instant. Et elle est deterministe : aucune horloge n'entre
        dans le verdict, seulement l'arrivee effective des threads.
        """
        # Cree 100 fichiers vides.
        many = []
        for i in range(100):
            mp = Path(self._tmp.name) / f"big_{i:04d}.mkv"
            mp.write_bytes(b"\x00" * 64)
            many.append(mp)

        workers = 8
        # rendezvous=workers : les 8 premiers probes se bloquent mutuellement
        # jusqu'a ce que les 8 soient arrives. En sequentiel, le premier attend
        # seul et le drapeau de timeout se leve.
        runner_par = _SlowRunnerSpy(sleep_s=0.02, rendezvous=workers, rendezvous_timeout_s=60.0)
        service_par = ProbeService(self.store, runner=runner_par, which_fn=lambda n: str(n))
        out_par = service_par.probe_files(
            media_paths=many,
            settings=self._settings(probe_parallelism_enabled=True, probe_workers=workers),
        )

        self.assertFalse(
            runner_par.rendezvous_timed_out,
            f"Les {workers} probes ne se sont jamais retrouves simultanement : la "
            f"parallelisation est cassee (concurrence max observee "
            f"{runner_par.max_concurrent}, threads distincts "
            f"{len(runner_par.thread_ids)}).",
        )
        self.assertEqual(len(out_par), 100)
        self.assertEqual(runner_par.calls, 100)
        # La barriere garantit deja >= workers simultanes ; on l'affirme pour que
        # l'echec reste lisible si le mecanisme de rendez-vous evoluait.
        self.assertGreaterEqual(runner_par.max_concurrent, workers)

        # Reset cache via touch (mtime changes -> cache miss)
        for mp in many:
            mp.touch()

        # Le chemin sequentiel doit rester strictement mono-thread. Pas de
        # rendez-vous ici : il bloquerait par construction, ce qui est justement
        # ce que la branche parallele prouve.
        runner_seq = _SlowRunnerSpy(sleep_s=0.0)
        service_seq = ProbeService(self.store, runner=runner_seq, which_fn=lambda n: str(n))
        out_seq = service_seq.probe_files(
            media_paths=many,
            settings=self._settings(probe_parallelism_enabled=False),
        )
        self.assertEqual(len(out_seq), 100)
        # `len(out_seq)` compte AUSSI les resultats servis par le cache : sans
        # l'assertion suivante, `max_concurrent == 1` passerait trivialement si
        # le `touch()` n'avait invalide qu'un seul fichier. Autrement dit, le
        # test aurait pu etre vert parce que le travail n'a pas eu lieu.
        # (releve par CodeRabbit sur la PR #892 ; remarque fondee)
        self.assertEqual(runner_seq.calls, len(many))
        self.assertEqual(runner_seq.max_concurrent, 1)
        self.assertEqual(len(runner_seq.thread_ids), 1)

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
