"""Lot perceptuel 2026-08-03 — verdicts faux (issues #559, #660, #752, #804, #813, #836).

Chaque classe correspond a une issue. Les tests portent sur le COMPORTEMENT
observable (contenu de frame, ratio mesure, verdict, confiance, timeout reel) et
jamais sur une chaine de code source.
"""

from __future__ import annotations

import threading
import time
import unittest
from typing import Dict, List, Optional, Tuple
from unittest import mock

import numpy as np

from cinesort.domain.perceptual.audio_perceptual import classify_drc
from cinesort.domain.perceptual.comparison import compute_pixel_diff, extract_aligned_frames
from cinesort.domain.perceptual.composite_score import detect_cross_verdicts
from cinesort.domain.perceptual.composite_score_v2 import build_audio_subscores
from cinesort.domain.perceptual.constants import (
    DRC_CONFIDENCE_SINGLE_METRIC,
    FAKE_4K_CONFIDENCE_SINGLE_SIGNAL,
    MEL_AAC_HOLE_RATIO_SEVERE,
    MEL_AAC_HOLE_THRESHOLD_DB,
    MEL_TOP_DB,
    PERCEPTUAL_ENGINE_VERSION,
)
from cinesort.domain.perceptual.frame_extraction import extract_representative_frames
from cinesort.domain.perceptual.mel_analysis import analyze_mel
from cinesort.domain.perceptual.models import AudioPerceptual, VideoPerceptual
from cinesort.domain.perceptual.parallelism import run_parallel_tasks
from cinesort.domain.perceptual.upscale_detection import combine_fake_4k_verdicts

# ---------------------------------------------------------------------------
# Faux ffmpeg : rend une frame Y a la resolution que la COMMANDE demande
# ---------------------------------------------------------------------------


def _gradient_bytes(width: int, height: int) -> bytes:
    """Degrade vertical 0 -> 255 : la valeur d'un pixel encode sa ligne.

    Une frame correctement redimensionnee garde donc la MEME moyenne (~127)
    quelle que soit la resolution ; une frame mal cadree (octets d'une autre
    geometrie relus comme WxH) a une moyenne franchement differente.
    """
    rows = np.linspace(0.0, 255.0, num=max(1, height), dtype=np.float64)
    frame = np.repeat(np.round(rows).astype(np.uint8), max(1, width))
    return frame.tobytes()


class _FakeFfmpeg:
    """Emule ffmpeg : applique `-vf scale=W:H` si present, sinon sort en natif."""

    def __init__(self, native: Dict[str, Tuple[int, int]]) -> None:
        self.native = native
        self.commands: List[List[str]] = []

    def __call__(self, cmd: List[str], timeout_s: float) -> Tuple[int, bytes, str]:
        self.commands.append(list(cmd))
        media = cmd[cmd.index("-i") + 1]
        w, h = self.native[str(media)]
        if "-vf" in cmd:
            vf = cmd[cmd.index("-vf") + 1]
            self.assert_scale_filter(vf)
            scale_w, scale_h = vf.split("=", 1)[1].split(":")
            w, h = int(scale_w), int(scale_h)
        return (0, _gradient_bytes(w, h), "")

    @staticmethod
    def assert_scale_filter(vf: str) -> None:
        if not vf.startswith("scale=") or ":" not in vf:
            raise AssertionError(f"filtre ffmpeg inattendu: {vf}")


class ExtractSingleFrameForcesResolutionTests(unittest.TestCase):
    """#559 — la frame extraite doit avoir EXACTEMENT la geometrie demandee."""

    def test_aligned_frames_1080p_vs_720p_have_identical_content(self) -> None:
        """Deux editions de la meme image, resolutions differentes -> diff nulle.

        C'est le cas d'usage central du deep-compare. Sans mise a l'echelle
        forcee, ffmpeg sort la resolution native et `parse_raw_frame` relit les
        premiers octets d'une autre geometrie : les pixels compares n'ont plus
        rien a voir.
        """
        fake = _FakeFfmpeg({"A.mkv": (1920, 1080), "B.mkv": (1280, 720)})
        with mock.patch("cinesort.domain.perceptual.frame_extraction.run_ffmpeg_binary", fake):
            aligned = extract_aligned_frames(
                "/usr/bin/ffmpeg",
                "A.mkv",
                "B.mkv",
                duration_a=7200.0,
                duration_b=7200.0,
                width_a=1920,
                height_a=1080,
                width_b=1280,
                height_b=720,
                frames_count=5,
            )

        self.assertGreaterEqual(len(aligned), 5)
        for frame in aligned:
            self.assertEqual((frame["width"], frame["height"]), (1280, 720))
            diff = compute_pixel_diff(frame["pixels_a"], frame["pixels_b"])
            self.assertIsNotNone(diff)
            assert diff is not None
            self.assertLessEqual(
                diff["mean_diff"],
                1.0,
                f"les deux frames devraient montrer la meme image, diff={diff}",
            )

    def test_aligned_frames_keep_the_whole_image(self) -> None:
        """La frame doit couvrir toute l'image, pas seulement sa moitie haute."""
        fake = _FakeFfmpeg({"A.mkv": (1920, 1080), "B.mkv": (1280, 720)})
        with mock.patch("cinesort.domain.perceptual.frame_extraction.run_ffmpeg_binary", fake):
            aligned = extract_aligned_frames(
                "/usr/bin/ffmpeg",
                "A.mkv",
                "B.mkv",
                duration_a=7200.0,
                duration_b=7200.0,
                width_a=1920,
                height_a=1080,
                width_b=1280,
                height_b=720,
                frames_count=5,
            )

        self.assertTrue(aligned)
        for frame in aligned:
            for key in ("pixels_a", "pixels_b"):
                mean = float(np.asarray(frame[key], dtype=np.float64).mean())
                self.assertAlmostEqual(
                    mean,
                    127.5,
                    delta=3.0,
                    msg=f"{key}: moyenne {mean:.1f}, la frame n'est pas l'image complete",
                )

    def test_extract_command_targets_the_requested_geometry(self) -> None:
        """Chaque commande ffmpeg demande explicitement la geometrie commune."""
        fake = _FakeFfmpeg({"A.mkv": (1920, 1080), "B.mkv": (1280, 720)})
        with mock.patch("cinesort.domain.perceptual.frame_extraction.run_ffmpeg_binary", fake):
            extract_aligned_frames(
                "/usr/bin/ffmpeg",
                "A.mkv",
                "B.mkv",
                duration_a=7200.0,
                duration_b=7200.0,
                width_a=1920,
                height_a=1080,
                width_b=1280,
                height_b=720,
                frames_count=5,
            )

        self.assertTrue(fake.commands)
        for cmd in fake.commands:
            self.assertIn("-vf", cmd)
            self.assertEqual(cmd[cmd.index("-vf") + 1], "scale=1280:720")

    def test_uhd_source_is_still_downscaled_to_1920(self) -> None:
        """Non-regression : la politique de downscale 4K+ reste appliquee."""
        fake = _FakeFfmpeg({"UHD.mkv": (3840, 2160)})
        with mock.patch("cinesort.domain.perceptual.frame_extraction.run_ffmpeg_binary", fake):
            frames = extract_representative_frames(
                "/usr/bin/ffmpeg",
                "UHD.mkv",
                7200.0,
                3840,
                2160,
                8,
                frames_count=5,
                scene_detection_enabled=False,
            )

        self.assertTrue(frames)
        for frame in frames:
            self.assertEqual((frame["width"], frame["height"]), (1920, 1080))
        for cmd in fake.commands:
            self.assertEqual(cmd[cmd.index("-vf") + 1], "scale=1920:1080")


class CombineFake4kConfidenceTests(unittest.TestCase):
    """#804 — un verdict rendu sur un seul signal ne porte pas la confiance d'un consensus."""

    def test_native_on_fft_alone_is_not_full_confidence(self) -> None:
        verdict, conf = combine_fake_4k_verdicts(fft_ratio=0.25, ssim_self_ref=None)
        self.assertEqual(verdict, "4k_native")
        self.assertAlmostEqual(conf, FAKE_4K_CONFIDENCE_SINGLE_SIGNAL)
        self.assertLess(conf, 0.90)

    def test_native_on_ssim_alone_is_not_full_confidence(self) -> None:
        verdict, conf = combine_fake_4k_verdicts(fft_ratio=None, ssim_self_ref=0.80)
        self.assertEqual(verdict, "4k_native")
        self.assertAlmostEqual(conf, FAKE_4K_CONFIDENCE_SINGLE_SIGNAL)

    def test_ssim_minus_one_counts_as_missing_signal(self) -> None:
        """-1 = "non calcule" : c'est un signal absent, pas un signal negatif."""
        verdict, conf = combine_fake_4k_verdicts(fft_ratio=0.25, ssim_self_ref=-1.0)
        self.assertEqual(verdict, "4k_native")
        self.assertAlmostEqual(conf, FAKE_4K_CONFIDENCE_SINGLE_SIGNAL)

    def test_fake_on_a_single_signal_is_not_full_confidence(self) -> None:
        verdict, conf = combine_fake_4k_verdicts(fft_ratio=0.02, ssim_self_ref=None)
        self.assertEqual(verdict, "fake_4k_probable")
        self.assertAlmostEqual(conf, FAKE_4K_CONFIDENCE_SINGLE_SIGNAL)
        self.assertLess(conf, 0.70)

    def test_single_signal_confidence_sits_above_no_signal_at_all(self) -> None:
        _, none_conf = combine_fake_4k_verdicts(fft_ratio=None, ssim_self_ref=None)
        self.assertGreater(FAKE_4K_CONFIDENCE_SINGLE_SIGNAL, none_conf)

    def test_two_signals_keep_their_confidences(self) -> None:
        """Non-regression : rien ne change quand les deux signaux ont parle."""
        self.assertEqual(combine_fake_4k_verdicts(0.22, 0.85), ("4k_native", 0.90))
        self.assertEqual(combine_fake_4k_verdicts(0.05, 0.96), ("fake_4k_confirmed", 0.95))
        self.assertEqual(combine_fake_4k_verdicts(0.05, 0.87), ("fake_4k_probable", 0.70))


class ClassifyDrcPartialDataTests(unittest.TestCase):
    """#752 — une seule metrique mesuree ne peut pas donner un verdict ferme."""

    def test_low_crest_alone_does_not_give_firm_broadcast_verdict(self) -> None:
        verdict, conf = classify_drc(crest_factor=6.0, lra=None)
        self.assertEqual(verdict, "broadcast_compressed")
        self.assertAlmostEqual(conf, DRC_CONFIDENCE_SINGLE_METRIC)
        self.assertLess(conf, 0.85)

    def test_low_lra_alone_does_not_give_firm_broadcast_verdict(self) -> None:
        verdict, conf = classify_drc(crest_factor=None, lra=4.0)
        self.assertEqual(verdict, "broadcast_compressed")
        self.assertAlmostEqual(conf, DRC_CONFIDENCE_SINGLE_METRIC)

    def test_high_crest_alone_stays_low_confidence(self) -> None:
        verdict, conf = classify_drc(crest_factor=18.0, lra=None)
        self.assertEqual(verdict, "cinema")
        self.assertAlmostEqual(conf, DRC_CONFIDENCE_SINGLE_METRIC)
        self.assertLess(conf, 0.75)

    def test_mid_lra_alone_stays_low_confidence(self) -> None:
        verdict, conf = classify_drc(crest_factor=None, lra=12.0)
        self.assertEqual(verdict, "standard")
        self.assertAlmostEqual(conf, DRC_CONFIDENCE_SINGLE_METRIC)
        self.assertLess(conf, 0.80)

    def test_two_metrics_keep_their_confidences(self) -> None:
        """Non-regression : deux mesures reelles gardent la table d'origine."""
        self.assertEqual(classify_drc(20.0, 22.0), ("cinema", 0.95))
        self.assertEqual(classify_drc(16.0, 8.0), ("cinema", 0.75))
        self.assertEqual(classify_drc(12.0, 8.0), ("standard", 0.80))
        self.assertEqual(classify_drc(6.0, 5.0), ("broadcast_compressed", 0.85))
        self.assertEqual(classify_drc(None, None), ("unknown", 0.0))

    def test_composite_v2_relays_the_low_confidence(self) -> None:
        """La confiance basse doit ARRIVER au sous-score, sinon le fix est inerte."""
        audio = AudioPerceptual()
        audio.drc_category = "broadcast_compressed"
        audio.drc_confidence = DRC_CONFIDENCE_SINGLE_METRIC
        drc = next(s for s in build_audio_subscores(audio) if s.name == "drc_category")
        self.assertAlmostEqual(drc.confidence, DRC_CONFIDENCE_SINGLE_METRIC)
        self.assertLess(drc.confidence, 0.7)

    def test_composite_v2_keeps_default_when_producer_said_nothing(self) -> None:
        """Non-regression : confiance absente (0.0) -> valeur par defaut du sous-score."""
        audio = AudioPerceptual()
        audio.drc_category = "broadcast_compressed"
        audio.drc_confidence = 0.0
        drc = next(s for s in build_audio_subscores(audio) if s.name == "drc_category")
        self.assertAlmostEqual(drc.confidence, 0.7)


class MelAacHolesDetectionTests(unittest.TestCase):
    """#660 — le seuil de trou doit etre au-dessus du plancher dB, sinon rien ne se detecte."""

    SR = 48000

    def _pink(self, n: int, seed: int = 7) -> np.ndarray:
        rng = np.random.default_rng(seed)
        spec = np.fft.rfft(rng.normal(0.0, 1.0, n))
        freqs = np.fft.rfftfreq(n, 1.0 / self.SR)
        scale = np.ones_like(freqs)
        scale[1:] = 1.0 / np.sqrt(freqs[1:])
        out = np.fft.irfft(spec * scale, n=n)
        return (out / (np.abs(out).max() + 1e-12)).astype(np.float32)

    def _lowpass(self, samples: np.ndarray, cutoff_hz: float) -> np.ndarray:
        spec = np.fft.rfft(samples)
        freqs = np.fft.rfftfreq(samples.size, 1.0 / self.SR)
        spec[freqs > cutoff_hz] = 0.0
        return np.fft.irfft(spec, n=samples.size).astype(np.float32)

    def test_threshold_is_strictly_above_the_db_floor(self) -> None:
        """Invariant : un seuil <= -MEL_TOP_DB rend la detection impossible."""
        self.assertGreater(MEL_AAC_HOLE_THRESHOLD_DB, -MEL_TOP_DB)

    def test_low_bitrate_cut_at_11k_is_detected(self) -> None:
        samples = self._lowpass(self._pink(self.SR * 4), 11000.0)
        result = analyze_mel(samples, sample_rate=self.SR)
        self.assertGreaterEqual(result.mel_aac_holes_ratio, MEL_AAC_HOLE_RATIO_SEVERE)

    def test_full_band_signal_has_no_hole(self) -> None:
        """Non-regression : un signal pleine bande ne doit RIEN declencher."""
        result = analyze_mel(self._pink(self.SR * 4), sample_rate=self.SR)
        self.assertEqual(result.mel_aac_holes_ratio, 0.0)

    def test_hole_ratio_grows_when_the_cutoff_drops(self) -> None:
        """La mesure doit etre monotone : plus la coupure est basse, plus il y a de trous."""
        base = self._pink(self.SR * 4)
        ratios = [
            analyze_mel(self._lowpass(base, cut), sample_rate=self.SR).mel_aac_holes_ratio
            for cut in (18000.0, 16000.0, 14000.0, 11000.0)
        ]
        self.assertEqual(ratios, sorted(ratios), f"ratios non monotones: {ratios}")
        self.assertGreater(ratios[-1], ratios[0])


class FakeFourKCrossVerdictTests(unittest.TestCase):
    """#813 — pas de verdict "Faux 4K" quand le bit depth effectif n'a pas ete mesure."""

    @staticmethod
    def _video(bits: float) -> VideoPerceptual:
        video = VideoPerceptual()
        video.resolution_height = 2160
        video.blur_mean = 0.09
        video.effective_bits_mean = bits
        video.bit_depth_nominal = 10
        return video

    @staticmethod
    def _ids(video: VideoPerceptual) -> List[str]:
        return [v["id"] for v in detect_cross_verdicts(video, None, None)]

    def test_unmeasured_bits_do_not_raise_fake_4k(self) -> None:
        """0.0 = sentinelle "passe pixel sans frame exploitable", pas une mesure."""
        self.assertNotIn("fake_4k", self._ids(self._video(0.0)))

    def test_measured_low_bits_still_raise_fake_4k(self) -> None:
        """Non-regression : une vraie mesure basse leve toujours le verdict."""
        self.assertIn("fake_4k", self._ids(self._video(7.5)))

    def test_measured_high_bits_do_not_raise_fake_4k(self) -> None:
        self.assertNotIn("fake_4k", self._ids(self._video(9.6)))


class RunParallelTasksTimeoutTests(unittest.TestCase):
    """#836 — `timeout_per_task_s` doit etre honore aussi hors du chemin poole."""

    def setUp(self) -> None:
        self._release = threading.Event()

    def tearDown(self) -> None:
        # Libere systematiquement le worker bloque : un thread non-daemon
        # laisse en attente ferait trainer l'arret de l'interpreteur.
        self._release.set()

    def _blocker(self) -> str:
        self._release.wait(30.0)
        return "fini"

    def test_timeout_enforced_on_a_single_task(self) -> None:
        results = run_parallel_tasks({"solo": self._blocker}, max_workers=4, timeout_per_task_s=0.15)
        ok, payload = results["solo"]
        self.assertFalse(ok)
        self.assertIsInstance(payload, TimeoutError)

    def test_timeout_enforced_with_a_single_worker(self) -> None:
        results = run_parallel_tasks(
            {"bloquee": self._blocker, "rapide": lambda: "vite"},
            max_workers=1,
            timeout_per_task_s=0.15,
        )
        self.assertFalse(results["bloquee"][0])
        self.assertIsInstance(results["bloquee"][1], TimeoutError)

    def test_timeout_returns_quickly(self) -> None:
        started = time.monotonic()
        run_parallel_tasks({"solo": self._blocker}, max_workers=1, timeout_per_task_s=0.15)
        self.assertLess(time.monotonic() - started, 5.0)

    def test_single_task_without_timeout_keeps_the_inline_fast_path(self) -> None:
        """Non-regression : sans timeout, pas de pool (execution dans le thread appelant)."""
        seen: Dict[str, Optional[int]] = {}

        def probe() -> str:
            seen["thread"] = threading.get_ident()
            return "ok"

        results = run_parallel_tasks({"solo": probe}, max_workers=4)
        self.assertEqual(results["solo"], (True, "ok"))
        self.assertEqual(seen["thread"], threading.get_ident())

    def test_serial_without_timeout_still_runs_in_order(self) -> None:
        order: List[str] = []
        tasks = {name: (lambda n=name: order.append(n) or n) for name in ("a", "b", "c")}
        results = run_parallel_tasks(tasks, max_workers=1)
        self.assertEqual(order, ["a", "b", "c"])
        self.assertTrue(all(ok for ok, _ in results.values()))


class PerceptualEngineVersionTests(unittest.TestCase):
    """Estampille des regles : un rapport calcule avant ce lot doit rester identifiable."""

    def test_engine_version_bumped_for_this_rules_change(self) -> None:
        """Le sujet de ce test est LE LOT DU 2026-08-03, pas la version courante.

        Il epinglait `== "1.1"`. Le bump suivant (1.2, le 2026-08-31, sans
        aucun rapport avec ce lot-ci) l'a donc fait rougir : un test date qui
        exige la valeur COURANTE devient une taxe d'entretien sur tous les lots
        suivants, et le reflexe est alors de recopier le nouveau numero sans
        relire ce qu'il garde.

        Ce qu'il doit garder, c'est que le bump de ce lot a bien eu lieu et n'a
        jamais ete annule — donc un PLANCHER. La comparaison se fait sur les
        composants entiers : `"1.10" < "1.2"` en ordre lexical, et cette
        version-la finira par exister.
        """
        composants = tuple(int(p) for p in PERCEPTUAL_ENGINE_VERSION.split("."))

        self.assertGreaterEqual(
            composants,
            (1, 1),
            "le bump du lot verdicts 2026-08-03 (#660) a ete annule",
        )


if __name__ == "__main__":
    unittest.main()
