"""Tests comparaison perceptuelle profonde — Phase VII (item 9.24).

Couvre :
- compute_pixel_diff : frames identiques, differentes
- compare_histograms : identiques, differents, detail winner
- compare_criterion : higher/lower is better, tie
- compare_per_frame : structure retournee
- build_comparison_report : gagnant, recommendation, criteria_summary
- extract_aligned_frames : resolution commune forcee (issue #559)
- endpoint compare_perceptual expose
"""

from __future__ import annotations

import unittest
from unittest import mock

import numpy as np

from cinesort.domain.perceptual.comparison import (
    build_comparison_report,
    compare_criterion,
    compare_histograms,
    compare_per_frame,
    compute_pixel_diff,
    extract_aligned_frames,
)

# ---------------------------------------------------------------------------
# compute_pixel_diff (2 tests)
# ---------------------------------------------------------------------------


class PixelDiffTests(unittest.TestCase):
    """Tests de la difference pixel-a-pixel."""

    def test_identical_frames_zero(self) -> None:
        """Frames identiques → mean_diff = 0."""
        pixels = [100, 150, 200, 50]
        result = compute_pixel_diff(pixels, pixels)
        self.assertIsNotNone(result)
        self.assertEqual(result["mean_diff"], 0.0)
        self.assertEqual(result["max_diff"], 0)

    def test_different_frames_positive(self) -> None:
        """Frames differentes → mean_diff > 0."""
        a = [0, 0, 0, 0]
        b = [50, 100, 150, 200]
        result = compute_pixel_diff(a, b)
        self.assertIsNotNone(result)
        self.assertEqual(result["mean_diff"], 125.0)
        self.assertEqual(result["max_diff"], 200)


# ---------------------------------------------------------------------------
# compare_histograms (2 tests)
# ---------------------------------------------------------------------------


class CompareHistogramsTests(unittest.TestCase):
    """Tests de la comparaison d'histogrammes."""

    def test_identical_histograms_zero_divergence(self) -> None:
        """Histogrammes identiques → divergence = 0."""
        hist = [100] * 256
        result = compare_histograms(hist, hist)
        self.assertAlmostEqual(result["divergence"], 0.0, places=3)

    def test_different_histograms_positive_divergence(self) -> None:
        """Histogrammes differents → divergence > 0."""
        hist_a = [0] * 256
        hist_a[100] = 1000  # Un seul pic
        hist_b = [10] * 256  # Distribution uniforme
        result = compare_histograms(hist_a, hist_b)
        self.assertGreater(result["divergence"], 0.0)

    def test_detail_winner_more_levels(self) -> None:
        """Plus de niveaux distincts = plus de detail."""
        hist_a = [100] * 256  # 256 niveaux
        hist_b = [0] * 256
        for i in range(0, 256, 4):
            hist_b[i] = 400  # 64 niveaux
        result = compare_histograms(hist_a, hist_b)
        self.assertEqual(result["detail_winner"], "a")
        self.assertGreater(result["levels_a"], result["levels_b"])


# ---------------------------------------------------------------------------
# compare_criterion (3 tests)
# ---------------------------------------------------------------------------


class CompareCriterionTests(unittest.TestCase):
    """Tests de la comparaison de criteres."""

    def test_higher_is_better_a_wins(self) -> None:
        """A > B avec higher_is_better → A gagne."""
        result = compare_criterion(80.0, 60.0, "LRA", higher_is_better=True)
        self.assertEqual(result["winner"], "a")
        self.assertAlmostEqual(result["delta"], 20.0)

    def test_lower_is_better_a_wins(self) -> None:
        """A < B avec higher_is_better=False → A gagne."""
        result = compare_criterion(10.0, 30.0, "Blockiness", higher_is_better=False)
        self.assertEqual(result["winner"], "a")

    def test_tie_when_delta_small(self) -> None:
        """Delta < 5% du max → tie."""
        result = compare_criterion(100.0, 98.0, "Score", higher_is_better=True)
        self.assertEqual(result["winner"], "tie")
        self.assertLess(result["delta_pct"], 5.0)


# ---------------------------------------------------------------------------
# compare_per_frame (1 test)
# ---------------------------------------------------------------------------


class ComparePerFrameTests(unittest.TestCase):
    """Tests de la comparaison per-frame."""

    def test_structure(self) -> None:
        """Chaque frame retournee a la bonne structure."""
        w, h = 32, 32
        pa = [(i * 37) % 256 for i in range(w * h)]
        pb = [(i * 41 + 10) % 256 for i in range(w * h)]
        frames = [{"timestamp": 10.0, "pixels_a": pa, "pixels_b": pb, "width": w, "height": h}]
        results = compare_per_frame(frames, bit_depth=8)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["timestamp"], 10.0)
        self.assertIn("pixel_diff", r)
        self.assertIn("histogram", r)
        self.assertIn("variance_a", r)
        self.assertIn("banding_a", r)


# ---------------------------------------------------------------------------
# build_comparison_report (3 tests)
# ---------------------------------------------------------------------------


class BuildComparisonReportTests(unittest.TestCase):
    """Tests du rapport de comparaison complet."""

    def _make_perceptual_dict(
        self,
        global_score: int,
        block: float = 15.0,
        blur: float = 0.02,
        banding: float = 5.0,
        bits: float = 8.5,
        variance: float = 500.0,
        lra: float = 14.0,
        noise: float = -65.0,
        clip: float = 0.0,
    ) -> dict:
        return {
            "global_score": global_score,
            "video_perceptual": {
                "blockiness": {"mean": block},
                "blur": {"mean": blur},
                "banding": {"mean_score": banding},
                "effective_bit_depth": {"mean_bits": bits},
                "local_variance": {"mean_variance": variance},
            },
            "audio_perceptual": {
                "ebu_r128": {"loudness_range": lra},
                "astats": {"noise_floor": noise},
                "clipping": {"clipping_pct": clip},
            },
        }

    def test_a_wins(self) -> None:
        """Fichier A nettement meilleur → winner='a', recommendation non vide."""
        pa = self._make_perceptual_dict(85, block=8, blur=0.01, bits=9.8, lra=18)
        pb = self._make_perceptual_dict(60, block=40, blur=0.06, bits=7.5, lra=6)
        report = build_comparison_report(pa, pb, [], "remux.mkv", "encode.mkv")
        self.assertEqual(report["winner"], "a")
        self.assertIn("superieur", report["recommendation"])
        self.assertGreater(report["score_delta"], 0)
        self.assertGreater(len(report["criteria_summary"]), 0)

    def test_tie(self) -> None:
        """Fichiers quasi-identiques → tie."""
        pa = self._make_perceptual_dict(80)
        pb = self._make_perceptual_dict(78)
        report = build_comparison_report(pa, pb, [], "a.mkv", "b.mkv")
        self.assertEqual(report["winner"], "tie")
        self.assertIn("equivalente", report["recommendation"])

    def test_criteria_summary_complete(self) -> None:
        """Tous les criteres sont presents dans le summary."""
        pa = self._make_perceptual_dict(80)
        pb = self._make_perceptual_dict(70)
        report = build_comparison_report(pa, pb, [], "a.mkv", "b.mkv")
        criteria_names = [c["criterion"] for c in report["criteria_summary"]]
        self.assertIn("Artefacts (blockiness)", criteria_names)
        self.assertIn("Nettete (blur)", criteria_names)
        self.assertIn("Banding", criteria_names)
        self.assertIn("Profondeur effective", criteria_names)
        self.assertIn("Dynamique audio (LRA)", criteria_names)
        self.assertIn("Clipping", criteria_names)
        self.assertEqual(len(criteria_names), 8)  # 5 video + 3 audio


# ---------------------------------------------------------------------------
# extract_aligned_frames — resolution commune forcee (issue #559, 3 tests)
# ---------------------------------------------------------------------------


class ExtractAlignedFramesTests(unittest.TestCase):
    """Issue #559 : deux fichiers de resolutions differentes doivent etre
    ramenes a la MEME grille de pixels avant toute comparaison."""

    NATIVE = {"A_1080p.mkv": (1920, 1080), "B_720p.mkv": (1280, 720)}

    @staticmethod
    def _render(width: int, height: int) -> bytes:
        """Rend une mire 8-bit dont la valeur ne depend que de la position
        NORMALISEE : la meme scene rendue a deux resolutions differentes donne
        des octets identiques une fois ramenee a la meme grille."""
        if width <= 0 or height <= 0:
            return b""
        xs = (np.arange(width) * 256) // width
        ys = (np.arange(height) * 256) // height
        return ((xs[None, :] + ys[:, None]) % 256).astype(np.uint8).tobytes()

    def setUp(self) -> None:
        self.commands: list[list[str]] = []

    def _fake_ffmpeg(self, cmd: list[str], timeout: float) -> tuple[int, bytes, str]:
        """Faux ffmpeg fidele : sort la frame a la resolution demandee par
        ``-vf scale=W:H``, et a la resolution NATIVE du fichier sans filtre."""
        self.commands.append(list(cmd))
        width, height = self.NATIVE[cmd[cmd.index("-i") + 1]]
        if "-vf" in cmd:
            spec = cmd[cmd.index("-vf") + 1]
            parts = spec.split("scale=")[1].split(":")
            width, height = int(parts[0]), int(parts[1])
        return (0, self._render(width, height), "")

    def _run(self, **kwargs) -> list:
        with mock.patch(
            "cinesort.domain.perceptual.frame_extraction.run_ffmpeg_binary",
            side_effect=self._fake_ffmpeg,
        ):
            return extract_aligned_frames(
                "/usr/bin/ffmpeg",
                "A_1080p.mkv",
                "B_720p.mkv",
                100.0,
                100.0,
                1920,
                1080,
                1280,
                720,
                frames_count=3,
                **kwargs,
            )

    def test_1080p_vs_720p_frames_are_pixel_aligned(self) -> None:
        """1080p vs 720p : les 2 frames sont sur la meme grille 1280x720."""
        aligned = self._run()

        # Non-regression : les 3 paires demandees sont bien produites.
        self.assertEqual(len(aligned), 3)
        for frame in aligned:
            self.assertEqual(frame["width"], 1280)
            self.assertEqual(frame["height"], 720)
            self.assertEqual(frame["pixels_a"].size, 1280 * 720)
            self.assertEqual(frame["pixels_b"].size, 1280 * 720)
            # Coeur du bug : sans mise a l'echelle forcee, la frame A est sortie
            # en 1920x1080 et tronquee a l'aveugle -> pixels decales.
            self.assertTrue(np.array_equal(frame["pixels_a"], frame["pixels_b"]))
            diff = compute_pixel_diff(frame["pixels_a"], frame["pixels_b"])
            self.assertEqual(diff["mean_diff"], 0.0)
            self.assertEqual(diff["max_diff"], 0)

    def test_scale_filter_applied_to_both_inputs(self) -> None:
        """Chaque commande ffmpeg force explicitement la resolution commune."""
        self._run()

        self.assertEqual(len(self.commands), 6)  # 3 timestamps x 2 fichiers
        for cmd in self.commands:
            self.assertIn("-vf", cmd)
            self.assertEqual(cmd[cmd.index("-vf") + 1], "scale=1280:720")

    def test_missing_probe_width_returns_empty(self) -> None:
        """Largeur inconnue (probe incomplet) → aucune extraction tentee."""
        with mock.patch(
            "cinesort.domain.perceptual.frame_extraction.run_ffmpeg_binary",
            side_effect=self._fake_ffmpeg,
        ):
            aligned = extract_aligned_frames(
                "/usr/bin/ffmpeg", "A_1080p.mkv", "B_720p.mkv", 100.0, 100.0, 0, 0, 1280, 720, frames_count=3
            )
        self.assertEqual(aligned, [])
        self.assertEqual(self.commands, [])


# ---------------------------------------------------------------------------
# Endpoint expose (1 test)
# ---------------------------------------------------------------------------


class EndpointTests(unittest.TestCase):
    """Tests que l'endpoint est dans CineSortApi."""

    def test_compare_perceptual_exists(self) -> None:
        """Issue #84 PR 10 : compare_perceptual est sur QualityFacade."""
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        self.assertTrue(hasattr(api.quality, "compare_perceptual"))


if __name__ == "__main__":
    unittest.main()
