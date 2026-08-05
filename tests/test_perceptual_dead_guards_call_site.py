"""Gardes §7/§13 : le SITE D'APPEL transmet bien la geometrie et la profondeur.

Deux correctifs de ce lot vivent dans `cinesort/domain/perceptual/`, mais leur
effet depend entierement de ce que `perceptual_support._video_task` leur passe :

* #525 — `compute_ssim_self_ref` doit recevoir la LARGEUR native, sinon le
  graphe ffmpeg re-upscale vers 3840x2160 et le filtre ssim refuse une source
  DCI 4K / 2:1 (verdict "error" silencieux) ;
* #823 — `compute_fft_hf_ratio_median` doit recevoir le `bit_depth`, sinon les
  seuils « frame sombre / uniforme » restent calibres 8 bits et ne filtrent
  presque rien sur du 10 bits (donc sur la quasi-totalite des UHD).

Tester seulement les fonctions du domaine laisserait ces tests VERTS si l'on
remettait l'ancien appel : on exerce donc `_execute_perceptual_analysis`.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

from cinesort.domain.perceptual.ssim_self_ref import SsimSelfRefResult


def _ctx(width: int, height: int, bit_depth: int) -> tuple:
    """Contexte minimal accepte par `_execute_perceptual_analysis`."""
    settings = {
        "perceptual_parallelism_mode": "serial",
        "perceptual_ssim_self_ref_enabled": True,
        # Tout le reste des sondes ffmpeg est coupe : ce test ne parle que du
        # cablage des deux appels ci-dessus.
        "perceptual_interlacing_detection_enabled": False,
        "perceptual_crop_detection_enabled": False,
        "perceptual_judder_detection_enabled": False,
        "perceptual_hdr10_plus_detection_enabled": False,
        "perceptual_grain_intelligence_enabled": False,
    }
    store = MagicMock()
    row = MagicMock()
    row.candidates = []
    row.proposed_year = 2015
    media_path = MagicMock(exists=lambda: True, __str__=lambda self: "x.mkv")
    normalized = {"duration_s": 7200.0, "audio_tracks": []}  # pas d'audio : tache video seule
    video_info = {"width": width, "height": height, "bit_depth": bit_depth, "fps": 24.0}
    return (settings, "ffmpeg.exe", store, {}, row, media_path, normalized, video_info)


class TestVideoTaskForwardsGeometryAndBitDepth(unittest.TestCase):
    def _run(self, width: int, height: int, bit_depth: int) -> Dict[str, Any]:
        from cinesort.ui.api import perceptual_support as ps

        ssim_calls: List[Dict[str, Any]] = []
        fft_calls: List[tuple] = []

        def fake_ssim(*args: Any, **kwargs: Any) -> SsimSelfRefResult:
            ssim_calls.append(dict(kwargs))
            return SsimSelfRefResult(0.87, 0.88, "native", 0.90)

        def fake_fft(*args: Any, **kwargs: Any) -> float:
            fft_calls.append((args, dict(kwargs)))
            return 0.25

        video_local = MagicMock()
        video_local.blur_mean = 0.02
        grain_local = MagicMock()
        grain_local.is_animation = False

        api = MagicMock()
        api._tmdb_client.return_value = None
        api._perceptual_cancel_event = None

        fake_result = MagicMock()
        fake_result.to_dict.return_value = {"global_score": 78}

        with (
            patch.object(ps, "extract_representative_frames", lambda *a, **k: []),
            patch.object(ps, "run_filter_graph", lambda *a, **k: {}),
            patch.object(ps, "analyze_video_frames", lambda *a, **k: video_local),
            patch.object(ps, "analyze_grain", lambda *a, **k: grain_local),
            patch.object(ps, "_load_tmdb_metadata", lambda *a, **k: None),
            patch.object(ps, "compute_ssim_self_ref", fake_ssim),
            patch.object(ps, "compute_fft_hf_ratio_median", fake_fft),
            patch.object(ps, "build_perceptual_result", return_value=fake_result),
        ):
            out = ps._execute_perceptual_analysis(api, "run1", "row1", _ctx(width, height, bit_depth))

        self.assertTrue(out.get("ok"), out)
        self.assertEqual(len(ssim_calls), 1, "compute_ssim_self_ref doit etre appele une fois")
        self.assertEqual(len(fft_calls), 1, "compute_fft_hf_ratio_median doit etre appele une fois")
        return {"ssim": ssim_calls[0], "fft": fft_calls[0]}

    def test_ssim_receives_native_width_not_a_constant(self):
        """#525 : DCI 4K 4096x2160 — la largeur transmise est celle de la source."""
        calls = self._run(4096, 2160, 8)
        self.assertEqual(calls["ssim"].get("video_width"), 4096)
        self.assertEqual(calls["ssim"].get("video_height"), 2160)

    def test_fft_receives_bit_depth(self):
        """#823 : le 10 bits doit etre annonce au filtrage de frames."""
        calls = self._run(3840, 2160, 10)
        args, kwargs = calls["fft"]
        # bit_depth passe en 4e position (ou en mot-cle) : on accepte les deux.
        got = kwargs.get("bit_depth", args[3] if len(args) > 3 else None)
        self.assertEqual(got, 10)
        # La resolution native reste transmise telle quelle.
        self.assertEqual(args[1], 3840)
        self.assertEqual(args[2], 2160)


if __name__ == "__main__":
    unittest.main()
