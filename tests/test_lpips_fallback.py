"""Tests V1-04 v7.7.0 — Fallback gracieux LPIPS si modele ONNX absent.

Resout R5-PERC-3 / R4-PERC-3 : si l'utilisateur a une installation sans le
modele lpips_alexnet.onnx (cas rare mais possible : .exe corrompu, build
incomplet, modele supprime manuellement), l'analyse perceptuelle ne doit pas
crasher avec FileNotFoundError visible dans l'UI mais retourner un resultat
degrade (LpipsResult avec verdict="insufficient_data") et logger un WARNING.

Couvre :
    - Modele absent -> LpipsResult(verdict="insufficient_data") via orchestrateur.
    - Modele absent -> log WARNING emis (avec instructions de reinstall).
    - Modele absent -> WARNING emis UNE SEULE FOIS (pas de spam logs).
    - Modele absent -> compute_lpips_distance_pair retourne None gracieusement.
    - Modele absent -> _get_session leve FileNotFoundError (interne, geree).
    - Modele present mais ort absent -> WARNING different + None.
    - Le pipeline perceptuel (build_comparison_report) gere LPIPS None.
"""

from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

import numpy as np

from cinesort.domain.perceptual.lpips_compare import (
    LpipsResult,
    _get_session,
    compute_lpips_comparison,
    compute_lpips_distance_pair,
    reset_session_cache,
)


# ---------------------------------------------------------------------------
# Fallback gracieux dans l'orchestrateur compute_lpips_comparison
# ---------------------------------------------------------------------------


class TestModelMissingGracefulOrchestrator(unittest.TestCase):
    """Le modele ONNX absent doit produire un LpipsResult degrade, pas un crash."""

    def setUp(self):
        reset_session_cache()

    @patch("cinesort.domain.perceptual.lpips_compare._resolve_model_path", return_value=None)
    @patch("cinesort.domain.perceptual.lpips_compare._is_ort_available", return_value=True)
    def test_returns_insufficient_data_when_model_missing(self, _mock_ort, _mock_path):
        """Modele absent -> LpipsResult(verdict='insufficient_data', distance=None)."""
        aligned = [{"pixels_a": [50] * 64, "pixels_b": [50] * 64, "width": 8, "height": 8}]
        result = compute_lpips_comparison(aligned)
        self.assertIsInstance(result, LpipsResult)
        self.assertIsNone(result.distance_median)
        self.assertEqual(result.verdict, "insufficient_data")
        self.assertEqual(result.n_pairs_evaluated, 0)
        self.assertEqual(result.distances_per_pair, [])

    @patch("cinesort.domain.perceptual.lpips_compare._resolve_model_path", return_value=None)
    @patch("cinesort.domain.perceptual.lpips_compare._is_ort_available", return_value=True)
    def test_warning_logged_with_reinstall_hint(self, _mock_ort, _mock_path):
        """Modele absent -> WARNING emis avec instructions de reinstall."""
        aligned = [{"pixels_a": [50] * 64, "pixels_b": [50] * 64, "width": 8, "height": 8}]
        with self.assertLogs("cinesort.domain.perceptual.lpips_compare", level="WARNING") as cm:
            compute_lpips_comparison(aligned)
        joined = "\n".join(cm.output)
        # Verifie le contenu actionable du message (pas juste sa presence)
        self.assertIn("LPIPS", joined)
        self.assertIn("reinstaller", joined.lower())

    @patch("cinesort.domain.perceptual.lpips_compare._resolve_model_path", return_value=None)
    @patch("cinesort.domain.perceptual.lpips_compare._is_ort_available", return_value=True)
    def test_warning_emitted_once_not_spammed(self, _mock_ort, _mock_path):
        """5 appels successifs avec modele absent -> 1 seul WARNING (pas de spam)."""
        aligned = [{"pixels_a": [50] * 64, "pixels_b": [50] * 64, "width": 8, "height": 8}]
        with self.assertLogs("cinesort.domain.perceptual.lpips_compare", level="WARNING") as cm:
            for _ in range(5):
                compute_lpips_comparison(aligned)
        # 1 seul message WARNING (idempotence du flag _missing_model_warned)
        warning_lines = [line for line in cm.output if "WARNING" in line and "LPIPS" in line]
        self.assertEqual(len(warning_lines), 1, f"Attendu 1 WARNING, trouve : {cm.output}")

    @patch("cinesort.domain.perceptual.lpips_compare._resolve_model_path", return_value=None)
    @patch("cinesort.domain.perceptual.lpips_compare._is_ort_available", return_value=True)
    def test_reset_cache_re_enables_warning(self, _mock_ort, _mock_path):
        """reset_session_cache() doit reinitialiser le flag (utile pour tests)."""
        aligned = [{"pixels_a": [50] * 64, "pixels_b": [50] * 64, "width": 8, "height": 8}]
        # 1er warning
        with self.assertLogs("cinesort.domain.perceptual.lpips_compare", level="WARNING"):
            compute_lpips_comparison(aligned)
        # Apres reset, un nouveau warning doit pouvoir etre emis
        reset_session_cache()
        with self.assertLogs("cinesort.domain.perceptual.lpips_compare", level="WARNING") as cm2:
            compute_lpips_comparison(aligned)
        self.assertTrue(any("LPIPS" in line for line in cm2.output))


# ---------------------------------------------------------------------------
# Fallback gracieux au niveau bas : compute_lpips_distance_pair / _get_session
# ---------------------------------------------------------------------------


class TestModelMissingGracefulLowLevel(unittest.TestCase):
    """Les fonctions bas niveau ne doivent jamais propager FileNotFoundError."""

    def setUp(self):
        reset_session_cache()

    @patch("cinesort.domain.perceptual.lpips_compare._resolve_model_path", return_value=None)
    @patch("cinesort.domain.perceptual.lpips_compare._is_ort_available", return_value=True)
    def test_distance_pair_returns_none_when_model_missing(self, _mock_ort, _mock_path):
        """compute_lpips_distance_pair -> None si modele absent (pas de crash)."""
        a = np.zeros((1, 3, 256, 256), dtype=np.float32)
        b = np.zeros((1, 3, 256, 256), dtype=np.float32)
        result = compute_lpips_distance_pair(a, b)
        self.assertIsNone(result)

    @patch("cinesort.domain.perceptual.lpips_compare._resolve_model_path", return_value=None)
    @patch("cinesort.domain.perceptual.lpips_compare._is_ort_available", return_value=True)
    def test_get_session_raises_file_not_found(self, _mock_ort, _mock_path):
        """_get_session leve FileNotFoundError (geree par les appelants)."""
        # API privee mais on documente le contrat : l'exception remonte
        # uniquement jusqu'aux appelants directs (compute_lpips_distance_pair)
        # qui la transforment en None.
        with self.assertRaises(FileNotFoundError):
            _get_session()

    @patch("cinesort.domain.perceptual.lpips_compare._is_ort_available", return_value=False)
    def test_distance_pair_returns_none_when_ort_missing(self, _mock_ort):
        """onnxruntime absent -> None gracieux (chemin separe du modele absent)."""
        a = np.zeros((1, 3, 256, 256), dtype=np.float32)
        b = np.zeros((1, 3, 256, 256), dtype=np.float32)
        self.assertIsNone(compute_lpips_distance_pair(a, b))


# ---------------------------------------------------------------------------
# Coexistence avec le pipeline perceptuel : autres analyses doivent continuer
# ---------------------------------------------------------------------------


class TestPipelineContinuesWithoutLpips(unittest.TestCase):
    """L'absence du modele LPIPS ne doit pas casser l'analyse perceptuelle."""

    def setUp(self):
        reset_session_cache()

    def _min_perceptual(self) -> dict:
        return {
            "video_perceptual": {
                "blockiness": {"mean": 0},
                "blur": {"mean": 0},
                "banding": {"mean_score": 0},
                "effective_bit_depth": {"mean_bits": 8},
                "local_variance": {"mean_variance": 0},
            },
            "audio_perceptual": {
                "ebu_r128": {"loudness_range": 0},
                "astats": {"noise_floor": 0},
                "clipping": {"clipping_pct": 0},
            },
            "global_score": 50,
        }

    @patch("cinesort.domain.perceptual.lpips_compare._resolve_model_path", return_value=None)
    @patch("cinesort.domain.perceptual.lpips_compare._is_ort_available", return_value=True)
    def test_build_comparison_report_works_with_degraded_lpips(self, _mock_ort, _mock_path):
        """build_comparison_report ne crashe pas avec LpipsResult degrade."""
        from cinesort.domain.perceptual.comparison import build_comparison_report

        # On simule l'orchestrateur sur un cas reel : modele absent
        aligned = [{"pixels_a": [50] * 64, "pixels_b": [50] * 64, "width": 8, "height": 8}]
        lpips_result = compute_lpips_comparison(aligned)
        # Le rapport doit se construire sans erreur, en omettant le critere LPIPS
        report = build_comparison_report(
            self._min_perceptual(),
            self._min_perceptual(),
            [],
            "a.mkv",
            "b.mkv",
            lpips_result=lpips_result,
        )
        self.assertIn("criteria", report)
        # Aucun critere LPIPS car distance_median is None (omis par _build_lpips_criterion)
        lpips_criteria = [c for c in report["criteria"] if "LPIPS" in c["criterion"]]
        self.assertEqual(lpips_criteria, [])

    def test_composite_score_v2_handles_lpips_none(self):
        """build_video_subscores ne crashe pas avec lpips_result=None."""
        from cinesort.domain.perceptual.composite_score_v2 import build_video_subscores

        # Stub minimal pour video et grain (frozen dataclasses non importees ici)
        class _Stub:
            visual_tier = "moyen"
            resolution_width = 1920
            resolution_height = 1080
            visual_score = 60.0

        video = _Stub()
        grain = _Stub()
        # lpips_result=None -> la sub-score LPIPS est simplement omise
        subs, _flags = build_video_subscores(video, grain, normalized_probe=None, lpips_result=None)
        self.assertGreater(len(subs), 0)
        lpips_subs = [s for s in subs if s.name == "lpips_distance"]
        self.assertEqual(lpips_subs, [], "lpips_distance ne doit pas etre present si lpips_result=None")

    def test_composite_score_v2_handles_lpips_insufficient(self):
        """build_video_subscores omet LPIPS si LpipsResult.distance_median is None."""
        from cinesort.domain.perceptual.composite_score_v2 import build_video_subscores

        class _Stub:
            visual_tier = "moyen"
            resolution_width = 1920
            resolution_height = 1080
            visual_score = 60.0

        # LpipsResult degrade (modele absent)
        degraded = LpipsResult(
            distance_median=None,
            distances_per_pair=[],
            verdict="insufficient_data",
            n_pairs_evaluated=0,
        )
        subs, _flags = build_video_subscores(_Stub(), _Stub(), normalized_probe=None, lpips_result=degraded)
        self.assertGreater(len(subs), 0)
        # Aucune sub-score LPIPS quand distance_median is None
        lpips_subs = [s for s in subs if s.name == "lpips_distance"]
        self.assertEqual(lpips_subs, [])


# ---------------------------------------------------------------------------
# Compatibilite : signature publique LpipsResult inchangee
# ---------------------------------------------------------------------------


class TestPublicSignatureUnchanged(unittest.TestCase):
    """V1-04 ne doit casser aucune signature publique."""

    def setUp(self):
        reset_session_cache()

    def test_lpips_result_fields(self):
        """LpipsResult expose toujours 4 champs : distance_median, distances_per_pair, verdict, n_pairs_evaluated."""
        r = LpipsResult(
            distance_median=0.1,
            distances_per_pair=[0.1],
            verdict="very_similar",
            n_pairs_evaluated=1,
        )
        self.assertEqual(r.distance_median, 0.1)
        self.assertEqual(r.distances_per_pair, [0.1])
        self.assertEqual(r.verdict, "very_similar")
        self.assertEqual(r.n_pairs_evaluated, 1)

    def test_compute_lpips_comparison_returns_lpips_result(self):
        """compute_lpips_comparison retourne toujours un LpipsResult (jamais None)."""
        result = compute_lpips_comparison([])
        self.assertIsInstance(result, LpipsResult)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    unittest.main()
