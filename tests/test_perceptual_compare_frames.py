"""Tests pour get_perceptual_compare_frames (#94).

Verifications visees :
- Validation des inputs (run_id, row_ids requis).
- Erreur explicite si perceptual_enabled=False.
- Erreur explicite si ffmpeg introuvable.
- Erreur explicite si run / row introuvable.
- Encodage PNG base64 valide quand frames extraites.
- Cap a max_frames (1-5).
"""

from __future__ import annotations

import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from cinesort.ui.api.cinesort_api import CineSortApi


def _write_settings(state_dir: Path, **fields) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "settings.json").write_text(json.dumps(fields), encoding="utf-8")


class CompareFramesValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cs_compare_frames_"))
        self.api = CineSortApi()
        self.api._state_dir = self._tmp

    def test_requires_run_id_and_row_ids(self) -> None:
        r = self.api.quality.get_perceptual_compare_frames("", "a", "b")
        self.assertFalse(r["ok"])

    def test_perceptual_disabled_returns_error(self) -> None:
        _write_settings(self._tmp, perceptual_enabled=False)
        r = self.api.quality.get_perceptual_compare_frames("run1", "a", "b")
        self.assertFalse(r["ok"])
        self.assertIn("desactivee", r["message"].lower())

    def test_no_ffmpeg_returns_missing_tool(self) -> None:
        _write_settings(self._tmp, perceptual_enabled=True, ffprobe_path="")
        with mock.patch("cinesort.ui.api.perceptual_support.resolve_ffmpeg_path", return_value=""):
            r = self.api.quality.get_perceptual_compare_frames("run1", "a", "b")
        self.assertFalse(r["ok"])
        self.assertEqual(r.get("missing_tool"), "ffmpeg")

    def test_unknown_run_returns_error(self) -> None:
        _write_settings(self._tmp, perceptual_enabled=True, ffprobe_path="/fake")
        with mock.patch(
            "cinesort.ui.api.perceptual_support.resolve_ffmpeg_path",
            return_value="/fake/ffmpeg",
        ):
            with mock.patch.object(self.api, "_find_run_row", return_value=None):
                r = self.api.quality.get_perceptual_compare_frames("ghost", "a", "b")
        self.assertFalse(r["ok"])
        self.assertIn("introuvable", r["message"].lower())


class CompareFramesEncodingTests(unittest.TestCase):
    """Verifie l'encodage PNG base64 quand l'extraction reussit (mock complet)."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cs_compare_frames_enc_"))
        self.api = CineSortApi()
        self.api._state_dir = self._tmp
        _write_settings(self._tmp, perceptual_enabled=True, ffprobe_path="/fake/ffprobe")

    def _patch_pipeline(self, aligned_frames: list) -> Any:
        """Mock toute la chaine en amont de extract_aligned_frames pour
        permettre le test de l'encodage PNG sans avoir de fichier media reel.
        """
        # row simule : .row_id + .proposed_year (utilise par classify_film_era)
        row_a = mock.MagicMock(row_id="a", proposed_year=2020)
        row_b = mock.MagicMock(row_id="b", proposed_year=2020)

        cfg = mock.MagicMock()
        run_row = {"state_dir": str(self._tmp)}
        store = mock.MagicMock()
        rs = mock.MagicMock(rows=[row_a, row_b], cfg=cfg)

        patches = [
            mock.patch.object(self.api, "_find_run_row", return_value=(run_row, store)),
            mock.patch.object(self.api, "_get_run", return_value=rs),
            mock.patch.object(self.api, "_run_paths_for", return_value=mock.MagicMock()),
            mock.patch.object(self.api, "_load_rows_from_plan_jsonl", return_value=[row_a, row_b]),
            mock.patch.object(
                self.api, "_resolve_media_path_for_row", side_effect=[Path("/m/a.mkv"), Path("/m/b.mkv")]
            ),
            mock.patch(
                "cinesort.ui.api.perceptual_support.resolve_ffmpeg_path",
                return_value="/fake/ffmpeg",
            ),
            mock.patch(
                "cinesort.ui.api.perceptual_support._load_probe",
                return_value={"normalized": {"duration_s": 100.0, "video": {"width": 4, "height": 4}}},
            ),
            mock.patch(
                "cinesort.domain.perceptual.comparison.extract_aligned_frames",
                return_value=aligned_frames,
            ),
        ]
        for p in patches:
            p.start()
        for p in patches:
            self.addCleanup(p.stop)

    def test_returns_base64_png_when_frames_extracted(self) -> None:
        # 2 frames 4x4 luminance, valeurs differentes pour produire un diff.
        aligned = [
            {
                "timestamp": 10.0,
                "pixels_a": [0, 64, 128, 192] * 4,
                "pixels_b": [255, 192, 128, 64] * 4,
                "width": 4,
                "height": 4,
            },
            {
                "timestamp": 20.0,
                "pixels_a": [50] * 16,
                "pixels_b": [50] * 16,  # identique : mean_diff=0
                "width": 4,
                "height": 4,
            },
        ]
        self._patch_pipeline(aligned)
        r = self.api.quality.get_perceptual_compare_frames("run1", "a", "b", {"max_frames": 3})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["width"], 4)
        self.assertEqual(r["height"], 4)
        self.assertGreaterEqual(r["frame_count"], 1)
        # La frame avec le plus gros mean_diff doit etre en premier
        first = r["frames"][0]
        self.assertIn("frame_a_b64", first)
        self.assertIn("frame_b_b64", first)
        self.assertGreater(first["mean_diff"], 0)
        # Verifie qu'on peut decoder le base64 et que c'est bien un PNG.
        png_a = base64.b64decode(first["frame_a_b64"])
        self.assertTrue(png_a.startswith(b"\x89PNG\r\n\x1a\n"))
        # Decode via Pillow pour confirmer dimensions
        from PIL import Image

        img = Image.open(io.BytesIO(png_a))
        self.assertEqual(img.size, (4, 4))
        self.assertEqual(img.mode, "L")

    def test_max_frames_capped_to_5(self) -> None:
        aligned = [
            {"timestamp": float(i), "pixels_a": [i] * 16, "pixels_b": [255 - i] * 16, "width": 4, "height": 4}
            for i in range(10)
        ]
        self._patch_pipeline(aligned)
        r = self.api.quality.get_perceptual_compare_frames(
            "run1",
            "a",
            "b",
            {"max_frames": 100},  # demande absurdement haut
        )
        self.assertTrue(r["ok"])
        self.assertLessEqual(r["frame_count"], 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
