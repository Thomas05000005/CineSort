"""Tests §7 v7.5.0 — Fake 4K detection via FFT 2D."""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from cinesort.domain.perceptual.upscale_detection import (
    classify_fake_4k_fft,
    combine_fake_4k_verdicts,
    compute_fft_hf_ratio,
    compute_fft_hf_ratio_median,
    is_frame_usable_for_fft,
)


def _uniform_frame(w: int, h: int, value: int = 128) -> list:
    return [value] * (w * h)


def _white_noise_frame(w: int, h: int, seed: int = 0) -> list:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=w * h, dtype=np.int32).tolist()


def _checkerboard_high_freq(w: int, h: int) -> list:
    """Motif damier haute-frequence : HF riche."""
    arr = np.indices((h, w)).sum(axis=0) % 2
    return (arr * 255).astype(np.int32).flatten().tolist()


def _smooth_gradient_frame(w: int, h: int, amplitude: float = 34.6, base: float = 110.0, scale: float = 1.0) -> list:
    """Degrade vertical lisse : peu de HF, variance faible mais non nulle.

    Represente un aplat reel (ciel, fondu, carton) : `is_valid_frame` l'accepte
    (variance ~100 en 8 bits, au-dessus de FRAME_MIN_VARIANCE_8BIT=50) alors que
    l'analyse FFT devrait l'ecarter (< FAKE_4K_FFT_MIN_VARIANCE=200).
    `scale=4.0` transpose la meme image sur l'echelle 10 bits.
    """
    ramp = np.linspace(base, base + amplitude, h, dtype=np.float64)
    arr = np.repeat(ramp[:, None], w, axis=1) * scale
    return arr.astype(np.int32).flatten().tolist()


def _bicubic_upscale_simulation(w: int, h: int, seed: int = 0) -> list:
    """Simule un upscale bicubique : faible HF.

    Genere du bruit en basse resolution puis 'upscale' par interpolation
    bilineaire -> les HF ne sont pas ajoutees artificiellement.
    """
    low_w, low_h = w // 4, h // 4
    rng = np.random.default_rng(seed)
    low = rng.integers(0, 256, size=(low_h, low_w), dtype=np.int32).astype(np.float64)
    # Interpolation bilineaire (naif : repeat puis lissage)
    high = np.repeat(np.repeat(low, 4, axis=0), 4, axis=1)[:h, :w]
    # Lissage moyen 3x3 (reduit encore les HF)
    kernel = np.ones((3, 3)) / 9.0
    # Convolution manuelle via FFT (pour eviter scipy)
    from numpy.fft import fft2, ifft2

    k_padded = np.zeros_like(high)
    k_padded[:3, :3] = kernel
    smoothed = np.real(ifft2(fft2(high) * fft2(k_padded)))
    return smoothed.astype(np.int32).flatten().tolist()


# ---------------------------------------------------------------------------
# compute_fft_hf_ratio
# ---------------------------------------------------------------------------


class TestComputeFftHfRatio(unittest.TestCase):
    def test_uniform_returns_zero(self):
        frame = _uniform_frame(64, 64)
        ratio = compute_fft_hf_ratio(frame, 64, 64)
        self.assertLess(ratio, 0.01)

    def test_white_noise_moderate_hf(self):
        frame = _white_noise_frame(64, 64, seed=1)
        ratio = compute_fft_hf_ratio(frame, 64, 64)
        # Bruit blanc : spectre ~plat -> ratio HF/total ~ 0.4-0.6 (surface anneau)
        self.assertGreater(ratio, 0.2)
        self.assertLess(ratio, 0.9)

    def test_high_freq_pattern_high_ratio(self):
        frame = _checkerboard_high_freq(64, 64)
        ratio = compute_fft_hf_ratio(frame, 64, 64)
        # Damier : HF maximum
        self.assertGreater(ratio, 0.3)

    def test_bicubic_upscale_low_hf(self):
        frame = _bicubic_upscale_simulation(64, 64)
        ratio = compute_fft_hf_ratio(frame, 64, 64)
        # Upscale = HF reduite
        self.assertLess(ratio, 0.35)

    def test_invalid_dimensions(self):
        self.assertEqual(compute_fft_hf_ratio([], 0, 0), 0.0)
        self.assertEqual(compute_fft_hf_ratio([1, 2, 3], 10, 10), 0.0)  # tronque

    def test_empty_pixels(self):
        self.assertEqual(compute_fft_hf_ratio([], 64, 64), 0.0)


# ---------------------------------------------------------------------------
# is_frame_usable_for_fft
# ---------------------------------------------------------------------------


class TestIsFrameUsable(unittest.TestCase):
    def test_dark_rejected(self):
        frame = _white_noise_frame(64, 64)
        self.assertFalse(is_frame_usable_for_fft(frame, 64, 64, y_avg=5.0, variance=500.0))

    def test_uniform_rejected_low_variance(self):
        frame = _uniform_frame(64, 64)
        self.assertFalse(is_frame_usable_for_fft(frame, 64, 64, y_avg=128.0, variance=10.0))

    def test_normal_frame_accepted(self):
        frame = _white_noise_frame(64, 64)
        self.assertTrue(is_frame_usable_for_fft(frame, 64, 64, y_avg=128.0, variance=5000.0))

    def test_truncated_rejected(self):
        frame = [128] * 100  # beaucoup moins que 64*64
        self.assertFalse(is_frame_usable_for_fft(frame, 64, 64, y_avg=128.0, variance=5000.0))

    def test_variance_none_is_measured_not_ignored(self):
        """#823 : sans variance fournie, elle est MESUREE (la garde etait morte).

        Aucun producteur de frame ne pose la cle `variance` (frame_extraction
        rend {timestamp, pixels, width, height, y_avg}), donc l'ancien
        `if variance is not None` ne s'appliquait jamais en production.
        """
        noisy = _white_noise_frame(64, 64)
        flat = _smooth_gradient_frame(64, 64)
        self.assertTrue(is_frame_usable_for_fft(noisy, 64, 64, y_avg=128.0, variance=None))
        self.assertFalse(is_frame_usable_for_fft(flat, 64, 64, y_avg=128.0, variance=None))

    def test_thresholds_follow_bit_depth(self):
        """Les seuils sont exprimes en 8 bits ; le 10 bits doit etre remis a l'echelle.

        Un Y 10 bits vaut 4x le Y 8 bits, donc la variance vaut 16x : sans
        remise a l'echelle, la garde « frame uniforme » ne mordait plus sur du
        10 bits, c'est-a-dire sur la quasi-totalite des UHD.
        """
        flat_10bit = _smooth_gradient_frame(64, 64, scale=4.0)
        # variance ~1600 : au-dessus du seuil 8 bits (200), en dessous du seuil
        # 10 bits (3200). Le meme tableau change donc de verdict selon bit_depth.
        self.assertTrue(is_frame_usable_for_fft(flat_10bit, 64, 64, y_avg=512.0, bit_depth=8))
        self.assertFalse(is_frame_usable_for_fft(flat_10bit, 64, 64, y_avg=512.0, bit_depth=10))
        # Meme logique pour la garde « trop sombre » : y_avg=50 en 10 bits vaut
        # 12.5 en 8 bits, donc bien en dessous du plancher.
        noisy = _white_noise_frame(64, 64)
        self.assertTrue(is_frame_usable_for_fft(noisy, 64, 64, y_avg=50.0, bit_depth=8))
        self.assertFalse(is_frame_usable_for_fft(noisy, 64, 64, y_avg=50.0, bit_depth=10))

    def test_zero_dimensions_rejected(self):
        self.assertFalse(is_frame_usable_for_fft([], 0, 0, y_avg=128.0))


# ---------------------------------------------------------------------------
# compute_fft_hf_ratio_median
# ---------------------------------------------------------------------------


class TestComputeFftHfRatioMedian(unittest.TestCase):
    def _mk_frame(self, pixels: list, w: int, h: int, y_avg: float = 128.0, variance: float = 5000.0) -> dict:
        return {"pixels": pixels, "width": w, "height": h, "y_avg": y_avg, "variance": variance}

    def test_median_of_3_frames(self):
        frames = [
            self._mk_frame(_white_noise_frame(64, 64, seed=1), 64, 64),
            self._mk_frame(_white_noise_frame(64, 64, seed=2), 64, 64),
            self._mk_frame(_white_noise_frame(64, 64, seed=3), 64, 64),
        ]
        m = compute_fft_hf_ratio_median(frames, 64, 64)
        self.assertIsNotNone(m)
        self.assertGreater(m, 0.0)
        self.assertLess(m, 1.0)

    def test_filters_dark_frames(self):
        # Une seule frame usable -> None (< 2)
        frames = [
            self._mk_frame(_white_noise_frame(64, 64, seed=1), 64, 64, y_avg=5.0),  # dark
            self._mk_frame(_white_noise_frame(64, 64, seed=2), 64, 64, y_avg=5.0),  # dark
            self._mk_frame(_white_noise_frame(64, 64, seed=3), 64, 64, y_avg=128.0),  # usable
        ]
        m = compute_fft_hf_ratio_median(frames, 64, 64)
        self.assertIsNone(m)

    def test_filters_uniform_frames(self):
        frames = [
            self._mk_frame(_uniform_frame(64, 64), 64, 64, variance=10.0),
            self._mk_frame(_uniform_frame(64, 64), 64, 64, variance=10.0),
            self._mk_frame(_white_noise_frame(64, 64, seed=1), 64, 64),
        ]
        m = compute_fft_hf_ratio_median(frames, 64, 64)
        self.assertIsNone(m)

    def test_flat_frames_excluded_without_variance_key(self):
        """#823, sur la forme REELLE des frames : aucune cle `variance`.

        3 aplats + 2 frames texturees. Sans le filtrage, la mediane des 5 ratios
        tombe sur un aplat (HF ~ 0) et le film est declare `fake_4k_bicubic` a
        tort ; avec le filtrage, seules les 2 frames texturees comptent.
        On verifie le VERDICT, pas seulement le nombre de frames retenues.
        """
        frames = [
            {"pixels": _smooth_gradient_frame(64, 64), "width": 64, "height": 64, "y_avg": 127.0},
            {"pixels": _smooth_gradient_frame(64, 64, base=100.0), "width": 64, "height": 64, "y_avg": 117.0},
            {"pixels": _smooth_gradient_frame(64, 64, base=120.0), "width": 64, "height": 64, "y_avg": 137.0},
            {"pixels": _white_noise_frame(64, 64, seed=1), "width": 64, "height": 64, "y_avg": 128.0},
            {"pixels": _white_noise_frame(64, 64, seed=2), "width": 64, "height": 64, "y_avg": 128.0},
        ]
        m = compute_fft_hf_ratio_median(frames, 64, 64)
        self.assertIsNotNone(m, "2 frames texturees restent utilisables")
        verdict, _ = classify_fake_4k_fft(m, video_height=2160, is_animation=False)
        self.assertEqual(verdict, "4k_native")

    def test_empty_list_none(self):
        self.assertIsNone(compute_fft_hf_ratio_median([], 64, 64))

    def test_all_unusable_none(self):
        frames = [
            self._mk_frame([], 64, 64),  # pixels vides
            self._mk_frame([], 64, 64),
        ]
        self.assertIsNone(compute_fft_hf_ratio_median(frames, 64, 64))


# ---------------------------------------------------------------------------
# classify_fake_4k_fft
# ---------------------------------------------------------------------------


class TestClassifyFake4kFft(unittest.TestCase):
    def test_not_applicable_1080p(self):
        v, c = classify_fake_4k_fft(0.20, video_height=1080, is_animation=False)
        self.assertEqual(v, "not_applicable_resolution")
        self.assertEqual(c, 0.0)

    def test_not_applicable_animation(self):
        v, _ = classify_fake_4k_fft(0.20, video_height=2160, is_animation=True)
        self.assertEqual(v, "not_applicable_animation")

    def test_insufficient_frames_none(self):
        v, _ = classify_fake_4k_fft(None, video_height=2160, is_animation=False)
        self.assertEqual(v, "insufficient_frames")

    def test_ratio_020_native(self):
        v, c = classify_fake_4k_fft(0.20, video_height=2160, is_animation=False)
        self.assertEqual(v, "4k_native")
        self.assertAlmostEqual(c, 0.85)

    def test_ratio_018_native_boundary(self):
        v, _ = classify_fake_4k_fft(0.18, video_height=2160, is_animation=False)
        self.assertEqual(v, "4k_native")

    def test_ratio_010_ambiguous(self):
        v, c = classify_fake_4k_fft(0.10, video_height=2160, is_animation=False)
        self.assertEqual(v, "ambiguous_2k_di")
        self.assertAlmostEqual(c, 0.60)

    def test_ratio_005_fake_bicubic(self):
        v, c = classify_fake_4k_fft(0.05, video_height=2160, is_animation=False)
        self.assertEqual(v, "fake_4k_bicubic")
        self.assertAlmostEqual(c, 0.90)

    def test_ratio_0_fake_bicubic(self):
        v, _ = classify_fake_4k_fft(0.0, video_height=2160, is_animation=False)
        self.assertEqual(v, "fake_4k_bicubic")


# ---------------------------------------------------------------------------
# combine_fake_4k_verdicts
# ---------------------------------------------------------------------------


class TestCombineVerdicts(unittest.TestCase):
    def test_both_fake_confirmed(self):
        v, c = combine_fake_4k_verdicts(fft_ratio=0.05, ssim_self_ref=0.96)
        self.assertEqual(v, "fake_4k_confirmed")
        self.assertAlmostEqual(c, 0.95)

    def test_only_fft_fake_probable(self):
        v, c = combine_fake_4k_verdicts(fft_ratio=0.05, ssim_self_ref=0.87)
        self.assertEqual(v, "fake_4k_probable")
        self.assertAlmostEqual(c, 0.70)

    def test_only_ssim_fake_probable(self):
        v, c = combine_fake_4k_verdicts(fft_ratio=0.20, ssim_self_ref=0.97)
        self.assertEqual(v, "fake_4k_probable")

    def test_neither_fake_native(self):
        v, c = combine_fake_4k_verdicts(fft_ratio=0.22, ssim_self_ref=0.85)
        self.assertEqual(v, "4k_native")
        self.assertAlmostEqual(c, 0.90)

    def test_both_none_ambiguous(self):
        v, c = combine_fake_4k_verdicts(fft_ratio=None, ssim_self_ref=None)
        self.assertEqual(v, "ambiguous")

    def test_ssim_minus_one_treated_as_none(self):
        # SSIM = -1 signifie "non calcule" : on traite comme None
        v, _ = combine_fake_4k_verdicts(fft_ratio=0.05, ssim_self_ref=-1.0)
        self.assertEqual(v, "fake_4k_probable")

    def test_fft_none_ssim_fake(self):
        v, _ = combine_fake_4k_verdicts(fft_ratio=None, ssim_self_ref=0.97)
        self.assertEqual(v, "fake_4k_probable")

    def test_fft_none_ssim_native(self):
        v, _ = combine_fake_4k_verdicts(fft_ratio=None, ssim_self_ref=0.80)
        self.assertEqual(v, "4k_native")

    def test_single_signal_native_has_lower_confidence(self):
        # audit-bot:2026-07-25-A1 : un seul signal disponible et negatif ne peut
        # pas etre aussi sur qu'un consensus a deux signaux.
        _, c_single_fft = combine_fake_4k_verdicts(fft_ratio=0.30, ssim_self_ref=None)
        _, c_single_ssim = combine_fake_4k_verdicts(fft_ratio=None, ssim_self_ref=0.80)
        _, c_both = combine_fake_4k_verdicts(fft_ratio=0.22, ssim_self_ref=0.85)
        self.assertAlmostEqual(c_single_fft, 0.60)
        self.assertAlmostEqual(c_single_ssim, 0.60)
        self.assertAlmostEqual(c_both, 0.90)
        self.assertLess(c_single_fft, c_both)


# ---------------------------------------------------------------------------
# VideoPerceptual sérialisation
# ---------------------------------------------------------------------------


class TestVideoPerceptualSerialization(unittest.TestCase):
    def test_to_dict_contains_fake_4k_block(self):
        from cinesort.domain.perceptual.models import VideoPerceptual

        vp = VideoPerceptual()
        vp.fft_hf_ratio_median = 0.15
        vp.fake_4k_verdict_fft = "ambiguous_2k_di"
        vp.fake_4k_verdict_combined = "ambiguous"
        vp.fake_4k_combined_confidence = 0.30
        d = vp.to_dict()
        self.assertIn("fake_4k", d)
        self.assertAlmostEqual(d["fake_4k"]["fft_hf_ratio_median"], 0.15, places=3)
        self.assertEqual(d["fake_4k"]["verdict_fft"], "ambiguous_2k_di")
        self.assertEqual(d["fake_4k"]["verdict_combined"], "ambiguous")
        self.assertAlmostEqual(d["fake_4k"]["confidence"], 0.30)

    def test_to_dict_none_ratio_stays_none(self):
        from cinesort.domain.perceptual.models import VideoPerceptual

        vp = VideoPerceptual()
        # fft_hf_ratio_median reste None par defaut
        d = vp.to_dict()
        self.assertIsNone(d["fake_4k"]["fft_hf_ratio_median"])


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


class TestSpecContainsUpscaleDetection(unittest.TestCase):
    def test_hiddenimport(self):
        spec = (Path(__file__).resolve().parents[1] / "CineSort.spec").read_text(encoding="utf-8")
        self.assertIn("cinesort.domain.perceptual.upscale_detection", spec)


if __name__ == "__main__":
    unittest.main()
