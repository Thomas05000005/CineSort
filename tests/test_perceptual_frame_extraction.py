"""Tests extraction de frames representatives — Phase II-A (item 9.24).

Couvre :
- compute_timestamps : determinisme, skip, films courts, clamping
- parse_raw_frame : 8-bit, 10-bit, donnees tronquees
- is_valid_frame : variance haute/basse, donnees tronquees
- compute_inter_frame_diff : frames identiques, differentes
- extract_single_frame : commande ffmpeg, downscale, pix_fmt
- extract_representative_frames : orchestration, diversite, remplacement
"""

from __future__ import annotations

import struct
import unittest
from unittest import mock

from cinesort.domain.perceptual.frame_extraction import (
    compute_inter_frame_diff,
    compute_timestamps,
    extract_representative_frames,
    extract_single_frame,
    is_valid_frame,
    parse_raw_frame,
)


# ---------------------------------------------------------------------------
# compute_timestamps (7 tests)
# ---------------------------------------------------------------------------


class ComputeTimestampsTests(unittest.TestCase):
    """Tests du calcul de timestamps deterministes."""

    def test_deterministic_same_input_same_output(self) -> None:
        """Meme input = meme output — reproductibilite."""
        a = compute_timestamps(7200.0, 10, 5)
        b = compute_timestamps(7200.0, 10, 5)
        self.assertEqual(a, b)

    def test_skip_5_percent(self) -> None:
        """Les timestamps respectent le skip de 5 %."""
        ts = compute_timestamps(1000.0, 10, 5)
        # skip_s = 50, useful = 900, premiers/derniers 5 % ignores
        self.assertTrue(all(t >= 50.0 for t in ts))
        self.assertTrue(all(t < 950.0 for t in ts))
        self.assertEqual(len(ts), 10)

    def test_skip_0_includes_all(self) -> None:
        """Skip 0 % = tout inclus, y compris debut et fin."""
        ts = compute_timestamps(1000.0, 10, 0)
        self.assertTrue(ts[0] < 100.0)  # premiere frame proche du debut
        self.assertTrue(ts[-1] > 900.0)  # derniere frame proche de la fin

    def test_short_film_minimum_3_frames(self) -> None:
        """Film tres court (< 2 min) → au moins 3 frames."""
        ts = compute_timestamps(60.0, 2, 5)  # 2 demande mais minimum 3
        self.assertGreaterEqual(len(ts), 3)

    def test_frames_count_clamped_5_to_50(self) -> None:
        """Le nombre de frames est clampe entre 5 et 50."""
        # Trop bas → 5 minimum (film normal)
        ts_low = compute_timestamps(7200.0, 1, 5)
        self.assertEqual(len(ts_low), 5)
        # Trop haut → 50 maximum
        ts_high = compute_timestamps(7200.0, 999, 5)
        self.assertEqual(len(ts_high), 50)

    def test_precision_3_decimals(self) -> None:
        """Les timestamps ont 3 decimales de precision."""
        ts = compute_timestamps(7200.0, 10, 5)
        for t in ts:
            # round(x, 3) doit etre egal a x
            self.assertAlmostEqual(t, round(t, 3), places=3)

    def test_zero_duration_empty(self) -> None:
        """Duree <= 0 → aucun timestamp."""
        self.assertEqual(compute_timestamps(0.0, 10, 5), [])
        self.assertEqual(compute_timestamps(-1.0, 10, 5), [])


# ---------------------------------------------------------------------------
# parse_raw_frame (3 tests)
# ---------------------------------------------------------------------------


class ParseRawFrameTests(unittest.TestCase):
    """Tests du parsing de frames brutes."""

    def test_8bit_correct(self) -> None:
        """Parsing 8-bit : bytes directs → valeurs 0-255."""
        width, height = 4, 3
        data = bytes(range(12))  # 0, 1, 2, ..., 11
        pixels = parse_raw_frame(data, width, height, 8)
        self.assertEqual(len(pixels), 12)
        self.assertEqual(pixels[0], 0)
        self.assertEqual(pixels[11], 11)

    def test_10bit_correct(self) -> None:
        """Parsing 10-bit (gray16le) : uint16 LE >> 6 → valeurs 0-1023."""
        width, height = 2, 2
        # Valeurs raw 16-bit : 64, 128, 256, 512 → apres >> 6 : 1, 2, 4, 8
        raw_values = [64, 128, 256, 512]
        data = struct.pack(f"<{len(raw_values)}H", *raw_values)
        pixels = parse_raw_frame(data, width, height, 10)
        self.assertEqual(len(pixels), 4)
        self.assertEqual(pixels[0], 1)  # 64 >> 6 = 1
        self.assertEqual(pixels[1], 2)  # 128 >> 6 = 2
        self.assertEqual(pixels[2], 4)  # 256 >> 6 = 4
        self.assertEqual(pixels[3], 8)  # 512 >> 6 = 8

    def test_truncated_data_returns_empty(self) -> None:
        """Donnees trop courtes → liste vide."""
        pixels = parse_raw_frame(b"\x00\x01", 4, 3, 8)  # 2 bytes, attendu 12
        self.assertEqual(pixels, [])


# ---------------------------------------------------------------------------
# is_valid_frame (3 tests)
# ---------------------------------------------------------------------------


class IsValidFrameTests(unittest.TestCase):
    """Tests de validation de frame."""

    def test_high_variance_valid(self) -> None:
        """Frame avec haute variance → valide."""
        # Alternance de valeurs tres differentes
        pixels = [0, 255] * 500
        self.assertTrue(is_valid_frame(pixels, 25, 40, 8))

    def test_low_variance_invalid(self) -> None:
        """Frame quasi-uniforme (variance < seuil) → invalide."""
        # Tous les pixels a la meme valeur → variance = 0
        pixels = [128] * 1000
        self.assertFalse(is_valid_frame(pixels, 25, 40, 8))

    def test_truncated_data_invalid(self) -> None:
        """Donnees trop courtes (< 90 % attendu) → invalide."""
        pixels = [100] * 5  # attendu 1000 (25*40)
        self.assertFalse(is_valid_frame(pixels, 25, 40, 8))


# ---------------------------------------------------------------------------
# compute_inter_frame_diff (2 tests)
# ---------------------------------------------------------------------------


class InterFrameDiffTests(unittest.TestCase):
    """Tests de la difference inter-frame."""

    def test_identical_frames_zero_diff(self) -> None:
        """Frames identiques → diff = 0."""
        pixels = [100, 200, 50, 150]
        self.assertEqual(compute_inter_frame_diff(pixels, pixels), 0.0)

    def test_different_frames_positive_diff(self) -> None:
        """Frames differentes → diff > 0."""
        a = [0, 0, 0, 0]
        b = [100, 100, 100, 100]
        diff = compute_inter_frame_diff(a, b)
        self.assertEqual(diff, 100.0)


# ---------------------------------------------------------------------------
# extract_single_frame (3 tests)
# ---------------------------------------------------------------------------


class ExtractSingleFrameTests(unittest.TestCase):
    """Tests de l'extraction d'une frame unique via ffmpeg."""

    @mock.patch("cinesort.domain.perceptual.frame_extraction.run_ffmpeg_binary")
    def test_downscale_4k(self, mock_run) -> None:
        """Width > 1920 → commande contient scale=1920:-1."""
        mock_run.return_value = (0, b"\x80" * 100, "")
        extract_single_frame("/usr/bin/ffmpeg", "film.mkv", 10.0, 3840, 2160, 8)
        cmd = mock_run.call_args[0][0]
        # Chercher le filtre scale
        self.assertIn("-vf", cmd)
        vf_idx = cmd.index("-vf")
        self.assertIn("scale=1920:-1", cmd[vf_idx + 1])

    @mock.patch("cinesort.domain.perceptual.frame_extraction.run_ffmpeg_binary")
    def test_no_downscale_1080p(self, mock_run) -> None:
        """Width <= 1920 → pas de filtre scale."""
        mock_run.return_value = (0, b"\x80" * 100, "")
        extract_single_frame("/usr/bin/ffmpeg", "film.mkv", 10.0, 1920, 1080, 8)
        cmd = mock_run.call_args[0][0]
        self.assertNotIn("-vf", cmd)

    @mock.patch("cinesort.domain.perceptual.frame_extraction.run_ffmpeg_binary")
    def test_pix_fmt_by_bit_depth(self, mock_run) -> None:
        """8-bit → gray, 10-bit → gray16le."""
        mock_run.return_value = (0, b"", "")
        # 8-bit
        extract_single_frame("/usr/bin/ffmpeg", "film.mkv", 10.0, 1920, 1080, 8)
        cmd_8 = mock_run.call_args[0][0]
        self.assertIn("gray", cmd_8)

        # 10-bit
        extract_single_frame("/usr/bin/ffmpeg", "film.mkv", 10.0, 1920, 1080, 10)
        cmd_10 = mock_run.call_args[0][0]
        self.assertIn("gray16le", cmd_10)


# ---------------------------------------------------------------------------
# extract_representative_frames (5 tests)
# ---------------------------------------------------------------------------


class ExtractRepresentativeFramesTests(unittest.TestCase):
    """Tests de l'orchestrateur principal."""

    def _make_frame_bytes(self, width: int, height: int, value: int = 128) -> bytes:
        """Fabrique des bytes bruts pour une frame 8-bit uniforme."""
        return bytes([value] * (width * height))

    def _make_varied_frame_bytes(self, width: int, height: int, seed: int = 0) -> bytes:
        """Fabrique des bytes avec variation (valide, diverse)."""
        return bytes([(seed + i * 37 + i * i) % 256 for i in range(width * height)])

    @mock.patch("cinesort.domain.perceptual.frame_extraction.run_ffmpeg_binary")
    def test_returns_correct_structure(self, mock_run) -> None:
        """Chaque frame retournee a la bonne structure."""
        w, h = 32, 24
        frame_data = self._make_varied_frame_bytes(w, h, seed=42)
        mock_run.return_value = (0, frame_data, "")

        frames = extract_representative_frames(
            "/usr/bin/ffmpeg",
            "film.mkv",
            7200.0,
            w,
            h,
            8,
            frames_count=5,
            skip_percent=5,
        )
        self.assertGreater(len(frames), 0)
        for f in frames:
            self.assertIn("timestamp", f)
            self.assertIn("pixels", f)
            self.assertIn("width", f)
            self.assertIn("height", f)
            self.assertIn("y_avg", f)
            self.assertIsInstance(f["pixels"], list)
            self.assertEqual(f["width"], w)
            self.assertEqual(f["height"], h)

    @mock.patch("cinesort.domain.perceptual.frame_extraction.run_ffmpeg_binary")
    def test_black_frames_skipped_and_replaced(self, mock_run) -> None:
        """Les frames noires sont skipees ; les remplacements sont tentes."""
        w, h = 32, 24
        black = bytes([0] * (w * h))  # variance = 0
        varied = self._make_varied_frame_bytes(w, h, seed=99)

        call_count = [0]

        def side_effect(cmd, timeout):
            call_count[0] += 1
            # Les 2 premiers appels retournent du noir, les suivants du vrai contenu
            if call_count[0] <= 2:
                return (0, black, "")
            return (0, varied, "")

        mock_run.side_effect = side_effect

        frames = extract_representative_frames(
            "/usr/bin/ffmpeg",
            "film.mkv",
            7200.0,
            w,
            h,
            8,
            frames_count=5,
            skip_percent=0,
        )
        # Au moins quelques frames reel extraites (les remplacements ont marche)
        self.assertGreater(len(frames), 0)

    @mock.patch("cinesort.domain.perceptual.frame_extraction.run_ffmpeg_binary")
    def test_replacement_exhausted_graceful(self, mock_run) -> None:
        """Si tous les remplacements echouent → frame simplement omise."""
        w, h = 32, 24
        black = bytes([0] * (w * h))
        mock_run.return_value = (0, black, "")  # Toujours noir

        frames = extract_representative_frames(
            "/usr/bin/ffmpeg",
            "film.mkv",
            7200.0,
            w,
            h,
            8,
            frames_count=5,
            skip_percent=5,
        )
        # Aucune frame valide, mais pas de crash
        self.assertEqual(len(frames), 0)

    @mock.patch("cinesort.domain.perceptual.frame_extraction.run_ffmpeg_binary")
    def test_diversity_similar_frames_replaced(self, mock_run) -> None:
        """Frames trop similaires → la deuxieme est decalee via remplacement."""
        w, h = 32, 24
        # Premiere frame variee
        frame_a = self._make_varied_frame_bytes(w, h, seed=10)
        # Deuxieme frame identique (sera rejetee pour manque de diversite)
        # Troisieme frame differente (remplacement)
        frame_c = self._make_varied_frame_bytes(w, h, seed=200)

        call_count = [0]

        def side_effect(cmd, timeout):
            call_count[0] += 1
            # Alterner : frame_a (identique), puis frame_c (differente)
            if call_count[0] % 3 == 0:
                return (0, frame_c, "")
            return (0, frame_a, "")

        mock_run.side_effect = side_effect

        frames = extract_representative_frames(
            "/usr/bin/ffmpeg",
            "film.mkv",
            7200.0,
            w,
            h,
            8,
            frames_count=5,
            skip_percent=0,
        )
        # Au moins 1 frame extraite
        self.assertGreater(len(frames), 0)

    def test_empty_file_no_crash(self) -> None:
        """Parametres invalides → liste vide, pas de crash."""
        frames = extract_representative_frames("", "", 0, 0, 0, 8)
        self.assertEqual(frames, [])

    @mock.patch("cinesort.domain.perceptual.frame_extraction.run_ffmpeg_binary")
    def test_ffmpeg_failure_returns_empty(self, mock_run) -> None:
        """ffmpeg retourne rc != 0 → frame omise."""
        mock_run.return_value = (1, b"", "error")
        frames = extract_representative_frames(
            "/usr/bin/ffmpeg",
            "film.mkv",
            7200.0,
            1920,
            1080,
            8,
            frames_count=5,
            skip_percent=5,
        )
        self.assertEqual(len(frames), 0)

    @mock.patch("cinesort.domain.perceptual.frame_extraction.run_ffmpeg_binary")
    def test_timeout_passed_to_runner(self, mock_run) -> None:
        """Le timeout est propage au runner ffmpeg."""
        mock_run.return_value = (0, b"", "")
        extract_single_frame("/usr/bin/ffmpeg", "film.mkv", 10.0, 1920, 1080, 8, timeout_s=42.0)
        _, timeout_arg = mock_run.call_args[0]
        self.assertEqual(timeout_arg, 42.0)


if __name__ == "__main__":
    unittest.main()
