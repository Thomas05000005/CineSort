"""Tests analyse d'encodage — cinesort/domain/encode_analysis.py.

Couvre :
- Upscale : 4K HEVC/H264, 1080p HEVC/H264, 720p
- Pas upscale : bitrate normal
- 4K light : 4K HEVC entre 3500 et 25000 kbps
- Re-encode degrade : bitrate extremement bas
- Guards : bitrate None/0, resolution inconnue, codec vide
- Mutuelle exclusivite : 4K < 3500 → upscale PAS 4k_light
- UI : badges presents, CSS classes
"""

from __future__ import annotations

import unittest
from pathlib import Path

from cinesort.domain.encode_analysis import analyze_encode_quality


def _det(*, height=0, bitrate_kbps=0, video_codec=""):
    """Helper pour creer un dict detected minimal."""
    return {"height": height, "bitrate_kbps": bitrate_kbps, "video_codec": video_codec}


# ---------------------------------------------------------------------------
# Upscale suspect
# ---------------------------------------------------------------------------


class UpscaleTests(unittest.TestCase):
    """Detection upscale suspect."""

    def test_4k_hevc_low_bitrate(self) -> None:
        """4K HEVC 2000 kbps → upscale."""
        flags = analyze_encode_quality(_det(height=2160, bitrate_kbps=2000, video_codec="hevc"))
        self.assertIn("upscale_suspect", flags)
        self.assertNotIn("4k_light", flags)

    def test_4k_h264_any_bitrate(self) -> None:
        """4K H264 n'importe quel bitrate → upscale."""
        flags = analyze_encode_quality(_det(height=2160, bitrate_kbps=30000, video_codec="h264"))
        self.assertIn("upscale_suspect", flags)

    def test_4k_av1_low_bitrate(self) -> None:
        """4K AV1 2500 kbps → upscale (AV1 traite comme HEVC)."""
        flags = analyze_encode_quality(_det(height=2160, bitrate_kbps=2500, video_codec="av1"))
        self.assertIn("upscale_suspect", flags)

    def test_1080p_hevc_low(self) -> None:
        """1080p HEVC 1000 kbps → upscale."""
        flags = analyze_encode_quality(_det(height=1080, bitrate_kbps=1000, video_codec="hevc"))
        self.assertIn("upscale_suspect", flags)

    def test_1080p_h264_low(self) -> None:
        """1080p H264 1500 kbps → upscale."""
        flags = analyze_encode_quality(_det(height=1080, bitrate_kbps=1500, video_codec="h264"))
        self.assertIn("upscale_suspect", flags)

    def test_720p_low(self) -> None:
        """720p 800 kbps → upscale."""
        flags = analyze_encode_quality(_det(height=720, bitrate_kbps=800, video_codec="hevc"))
        self.assertIn("upscale_suspect", flags)


class NotUpscaleTests(unittest.TestCase):
    """Pas d'upscale — bitrate normal."""

    def test_4k_hevc_high(self) -> None:
        """4K HEVC 30000 kbps → pas de flag upscale."""
        flags = analyze_encode_quality(_det(height=2160, bitrate_kbps=30000, video_codec="hevc"))
        self.assertNotIn("upscale_suspect", flags)

    def test_1080p_hevc_normal(self) -> None:
        """1080p HEVC 5000 kbps → pas de flag."""
        flags = analyze_encode_quality(_det(height=1080, bitrate_kbps=5000, video_codec="hevc"))
        self.assertNotIn("upscale_suspect", flags)

    def test_1080p_h264_normal(self) -> None:
        """1080p H264 4000 kbps → pas de flag."""
        flags = analyze_encode_quality(_det(height=1080, bitrate_kbps=4000, video_codec="h264"))
        self.assertNotIn("upscale_suspect", flags)

    def test_720p_normal(self) -> None:
        """720p 2000 kbps → pas de flag."""
        flags = analyze_encode_quality(_det(height=720, bitrate_kbps=2000, video_codec="hevc"))
        self.assertNotIn("upscale_suspect", flags)


# ---------------------------------------------------------------------------
# 4K light
# ---------------------------------------------------------------------------


class FourKLightTests(unittest.TestCase):
    """Detection 4K light (web/streaming)."""

    def test_4k_hevc_15mbps(self) -> None:
        """4K HEVC 15000 kbps → 4k_light (pas upscale)."""
        flags = analyze_encode_quality(_det(height=2160, bitrate_kbps=15000, video_codec="hevc"))
        self.assertIn("4k_light", flags)
        self.assertNotIn("upscale_suspect", flags)

    def test_4k_hevc_5mbps(self) -> None:
        """4K HEVC 5000 kbps → 4k_light (juste au-dessus du seuil upscale)."""
        flags = analyze_encode_quality(_det(height=2160, bitrate_kbps=5000, video_codec="hevc"))
        self.assertIn("4k_light", flags)

    def test_4k_hevc_above_25mbps(self) -> None:
        """4K HEVC 30000 kbps → pas de flag (vrai 4K)."""
        flags = analyze_encode_quality(_det(height=2160, bitrate_kbps=30000, video_codec="hevc"))
        self.assertNotIn("4k_light", flags)

    def test_mutual_exclusion_upscale_vs_light(self) -> None:
        """4K < 3500 → upscale PAS 4k_light."""
        flags = analyze_encode_quality(_det(height=2160, bitrate_kbps=3000, video_codec="hevc"))
        self.assertIn("upscale_suspect", flags)
        self.assertNotIn("4k_light", flags)


# ---------------------------------------------------------------------------
# Re-encode degrade
# ---------------------------------------------------------------------------


class ReencodeTests(unittest.TestCase):
    """Detection re-encode destructif."""

    def test_1080p_hevc_very_low(self) -> None:
        """1080p HEVC 500 kbps → reencode (+ upscale)."""
        flags = analyze_encode_quality(_det(height=1080, bitrate_kbps=500, video_codec="hevc"))
        self.assertIn("reencode_degraded", flags)
        self.assertIn("upscale_suspect", flags)

    def test_1080p_h264_very_low(self) -> None:
        """1080p H264 700 kbps → reencode (+ upscale)."""
        flags = analyze_encode_quality(_det(height=1080, bitrate_kbps=700, video_codec="h264"))
        self.assertIn("reencode_degraded", flags)

    def test_720p_very_low(self) -> None:
        """720p 400 kbps → reencode."""
        flags = analyze_encode_quality(_det(height=720, bitrate_kbps=400, video_codec="hevc"))
        self.assertIn("reencode_degraded", flags)

    def test_sd_very_low(self) -> None:
        """SD 200 kbps → reencode."""
        flags = analyze_encode_quality(_det(height=480, bitrate_kbps=200, video_codec="h264"))
        self.assertIn("reencode_degraded", flags)

    def test_1080p_hevc_above_threshold(self) -> None:
        """1080p HEVC 900 kbps → upscale mais PAS reencode (au-dessus de 800)."""
        flags = analyze_encode_quality(_det(height=1080, bitrate_kbps=900, video_codec="hevc"))
        self.assertIn("upscale_suspect", flags)
        self.assertNotIn("reencode_degraded", flags)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


class GuardTests(unittest.TestCase):
    """Guards : donnees manquantes → pas de flag."""

    def test_bitrate_none(self) -> None:
        flags = analyze_encode_quality({"height": 1080, "bitrate_kbps": None, "video_codec": "hevc"})
        self.assertEqual(flags, [])

    def test_bitrate_zero(self) -> None:
        flags = analyze_encode_quality(_det(height=1080, bitrate_kbps=0, video_codec="hevc"))
        self.assertEqual(flags, [])

    def test_height_zero(self) -> None:
        flags = analyze_encode_quality(_det(height=0, bitrate_kbps=5000, video_codec="hevc"))
        self.assertEqual(flags, [])

    def test_codec_empty(self) -> None:
        flags = analyze_encode_quality(_det(height=1080, bitrate_kbps=5000, video_codec=""))
        self.assertEqual(flags, [])

    def test_none_dict(self) -> None:
        flags = analyze_encode_quality(None)
        self.assertEqual(flags, [])

    def test_empty_dict(self) -> None:
        flags = analyze_encode_quality({})
        self.assertEqual(flags, [])


# ---------------------------------------------------------------------------
# UI badges
# ---------------------------------------------------------------------------


@unittest.skip("V5C-01: dashboard/views/review.js supprime — adaptation v5 deferee a V5C-03")
class UiBadgeTests(unittest.TestCase):
    """Badges encode dans les fichiers UI."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.validation_js = (root / "web" / "views" / "validation.js").read_text(encoding="utf-8")
        cls.review_js = (root / "web" / "dashboard" / "views" / "review.js").read_text(encoding="utf-8")
        cls.app_css = (root / "web" / "styles.css").read_text(encoding="utf-8")

    def test_desktop_upscale_badge(self) -> None:
        self.assertIn("upscale_suspect", self.validation_js)
        self.assertIn("Upscale", self.validation_js)

    def test_desktop_4k_light_badge(self) -> None:
        self.assertIn("4k_light", self.validation_js)
        self.assertIn("4K light", self.validation_js)

    def test_desktop_reencode_badge(self) -> None:
        self.assertIn("reencode_degraded", self.validation_js)
        self.assertIn("Re-encode", self.validation_js)

    def test_dashboard_upscale_badge(self) -> None:
        self.assertIn("upscale_suspect", self.review_js)

    def test_dashboard_4k_light_badge(self) -> None:
        self.assertIn("4k_light", self.review_js)

    def test_desktop_css_upscale(self) -> None:
        self.assertIn(".badge--upscale", self.app_css)

    def test_desktop_css_4k_light(self) -> None:
        self.assertIn(".badge--4k-light", self.app_css)

    def test_desktop_css_reencode(self) -> None:
        self.assertIn(".badge--reencode", self.app_css)


if __name__ == "__main__":
    unittest.main()
