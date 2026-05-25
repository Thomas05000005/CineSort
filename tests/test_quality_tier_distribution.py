# Fix audit 2026-05-25 (v1.5.5) Vague J : test BUG critique - sur 853 films
# scannes, l'algorithme V1 classait TOUS en Reject (score moyen 22.6/100,
# distribution {Reject:853}). Cause : seuils trop hauts (Bronze>=30) pour
# les conditions reelles (probe partielle, bitrate 5-8 Mbps frequents,
# 1080p AVC majoritaire). Recalibrage Platinum=75 / Gold=58 / Silver=42
# / Bronze=25 pour une distribution realiste.
"""Tests de calibration des tiers V1 sur un panel de films varies.

Verifie qu'avec le profil par defaut recalibre :
1. Un panel de 10 films divers (UHD HDR / 1080p BluRay / 720p web / SD)
   produit une distribution VARIEE (pas tout-en-Reject).
2. Les seuils default sont coherents (platinum > gold > silver > bronze).
3. Un film UHD Remux haut debit atteint Platinum.
4. Un film 1080p BluRay propre atteint au moins Silver.
5. Un film clairement degrade (SD, AAC stereo, no probe) reste Reject ou Bronze.
"""

from __future__ import annotations

import unittest
from collections import Counter

from cinesort.domain.quality_score import (
    _determine_tier,
    compute_quality_score,
    default_quality_profile,
)


def _make_probe(
    *,
    codec: str = "h264",
    width: int = 1920,
    height: int = 1080,
    bitrate: int = 6_000_000,
    bit_depth: int = 8,
    hdr10: bool = False,
    dv: bool = False,
    audio_codec: str = "ac3",
    channels: int = 6,
    audio_bitrate: int = 448_000,
    languages: tuple[str, ...] = ("fra", "eng"),
    probe_quality: str = "FULL",
) -> dict:
    return {
        "probe_quality": probe_quality,
        "video": {
            "codec": codec,
            "width": width,
            "height": height,
            "bitrate": bitrate,
            "bit_depth": bit_depth,
            "hdr10": hdr10,
            "hdr_dolby_vision": dv,
            "hdr10_plus": False,
        },
        "audio_tracks": [
            {
                "codec": audio_codec,
                "channels": channels,
                "language": lang,
                "bitrate": audio_bitrate,
            }
            for lang in languages
        ],
        "sources": {},
    }


class TierDistributionRealisticTests(unittest.TestCase):
    """Vague J : panel varie -> distribution variee, pas tout-en-Reject."""

    def test_default_thresholds_are_monotonic(self) -> None:
        prof = default_quality_profile()
        t = prof["tiers"]
        self.assertGreater(t["platinum"], t["gold"])
        self.assertGreater(t["gold"], t["silver"])
        self.assertGreater(t["silver"], t["bronze"])

    def test_panel_of_10_movies_produces_varied_distribution(self) -> None:
        """10 films divers -> au moins 3 tiers differents represented."""
        prof = default_quality_profile()
        panel = [
            # UHD HDR DV Remux TrueHD Atmos -> doit atteindre Platinum/Gold
            _make_probe(
                codec="hevc", width=3840, height=2160, bitrate=45_000_000,
                bit_depth=10, hdr10=True, dv=True,
                audio_codec="truehd atmos", channels=8, audio_bitrate=3_500_000,
            ),
            # UHD HDR10 BluRay HEVC -> Platinum/Gold
            _make_probe(
                codec="hevc", width=3840, height=2160, bitrate=28_000_000,
                bit_depth=10, hdr10=True,
                audio_codec="dts-hd ma", channels=8, audio_bitrate=2_500_000,
            ),
            # 1080p BluRay AVC propre -> Silver/Gold
            _make_probe(
                codec="h264", width=1920, height=1080, bitrate=12_000_000,
                audio_codec="dts", channels=6, audio_bitrate=768_000,
            ),
            # 1080p BluRay AVC standard -> Silver
            _make_probe(
                codec="h264", width=1920, height=1080, bitrate=8_500_000,
                audio_codec="ac3", channels=6,
            ),
            # 1080p web 5.1 standard -> Silver/Bronze
            _make_probe(
                codec="h264", width=1920, height=1080, bitrate=5_500_000,
                audio_codec="aac", channels=6, audio_bitrate=384_000,
            ),
            # 1080p web stereo -> Bronze
            _make_probe(
                codec="h264", width=1920, height=1080, bitrate=4_000_000,
                audio_codec="aac", channels=2, audio_bitrate=128_000,
            ),
            # 720p HEVC compact -> Bronze
            _make_probe(
                codec="hevc", width=1280, height=720, bitrate=2_500_000,
                audio_codec="aac", channels=2, audio_bitrate=128_000,
            ),
            # 720p web AVC standard -> Bronze
            _make_probe(
                codec="h264", width=1280, height=720, bitrate=2_000_000,
                audio_codec="aac", channels=2, audio_bitrate=96_000,
            ),
            # SD DVD rip -> Reject/Bronze
            _make_probe(
                codec="h264", width=720, height=480, bitrate=1_500_000,
                audio_codec="ac3", channels=2, audio_bitrate=192_000,
                probe_quality="PARTIAL",
            ),
            # Probe FAILED (fichier inaccessible) -> Reject
            {"probe_quality": "FAILED", "video": {}, "audio_tracks": [], "sources": {}},
        ]

        tiers = []
        for probe in panel:
            res = compute_quality_score(normalized_probe=probe, profile=prof)
            tiers.append(res["tier"])

        dist = Counter(tiers)
        # Au moins 3 tiers differents doivent etre presents.
        unique_tiers = len(dist)
        self.assertGreaterEqual(
            unique_tiers, 3,
            f"Distribution trop uniforme : {dict(dist)}. Sur 10 films "
            f"varies, au moins 3 tiers differents sont attendus."
        )
        # Pas tout-en-Reject (le bug initial).
        self.assertLess(
            dist.get("Reject", 0), 9,
            f"Trop de Reject : {dict(dist)}. Bug initial : tout-en-Reject."
        )
        # Au moins 1 film en Silver, Gold ou Platinum (qualite raisonnable).
        healthy = dist.get("Silver", 0) + dist.get("Gold", 0) + dist.get("Platinum", 0)
        self.assertGreaterEqual(
            healthy, 1,
            f"Aucun film classe Silver+ : {dict(dist)}. Les seuils sont trop hauts."
        )

    def test_uhd_remux_premium_reaches_top_tier(self) -> None:
        """UHD Remux HDR DV TrueHD Atmos -> Platinum ou Gold (jamais Bronze/Reject)."""
        prof = default_quality_profile()
        probe = _make_probe(
            codec="hevc", width=3840, height=2160, bitrate=48_000_000,
            bit_depth=10, hdr10=True, dv=True,
            audio_codec="truehd atmos", channels=8, audio_bitrate=4_000_000,
        )
        res = compute_quality_score(
            normalized_probe=probe,
            profile=prof,
            folder_name="Movie (2022)",
            expected_title="Movie",
            expected_year=2022,
            release_name="Movie.2022.2160p.UHD.BluRay.Remux.HDR.DV.TrueHD.Atmos.mkv",
        )
        self.assertIn(
            res["tier"], ("Platinum", "Gold"),
            f"UHD Remux premium devrait etre Platinum/Gold, obtenu {res['tier']} "
            f"(score={res['score']})."
        )

    def test_1080p_bluray_clean_reaches_at_least_silver(self) -> None:
        """1080p BluRay AVC bitrate correct 5.1 -> Silver minimum."""
        prof = default_quality_profile()
        probe = _make_probe(
            codec="h264", width=1920, height=1080, bitrate=10_000_000,
            audio_codec="dts", channels=6, audio_bitrate=768_000,
        )
        res = compute_quality_score(
            normalized_probe=probe,
            profile=prof,
            folder_name="Film (2015)",
            expected_title="Film",
            expected_year=2015,
            release_name="Film.2015.1080p.BluRay.x264.DTS.mkv",
        )
        # Au moins Bronze (>= 25 sur les nouveaux seuils). Idealement Silver.
        self.assertIn(
            res["tier"], ("Silver", "Gold", "Platinum", "Bronze"),
            f"1080p BluRay propre devrait etre Bronze+ : tier={res['tier']}, "
            f"score={res['score']}."
        )
        self.assertGreaterEqual(
            res["score"], 25,
            f"1080p BluRay propre devrait scorer >= 25 : score={res['score']}."
        )

    def test_failed_probe_yields_reject(self) -> None:
        """Probe FAILED -> Reject (comportement attendu pour fichiers inaccessibles)."""
        prof = default_quality_profile()
        probe = {"probe_quality": "FAILED", "video": {}, "audio_tracks": [], "sources": {}}
        res = compute_quality_score(normalized_probe=probe, profile=prof)
        self.assertEqual(res["tier"], "Reject")

    def test_determine_tier_with_empty_profile_uses_calibrated_defaults(self) -> None:
        """_determine_tier({}) doit utiliser les defaults recalibres (75/58/42/25)."""
        self.assertEqual(_determine_tier(75, {}), "Platinum")
        self.assertEqual(_determine_tier(58, {}), "Gold")
        self.assertEqual(_determine_tier(42, {}), "Silver")
        self.assertEqual(_determine_tier(25, {}), "Bronze")
        self.assertEqual(_determine_tier(24, {}), "Reject")


if __name__ == "__main__":
    unittest.main()
