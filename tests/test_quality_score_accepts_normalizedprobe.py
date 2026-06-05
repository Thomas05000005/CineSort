"""Test non-vacuous : compute_quality_score doit accepter un VRAI NormalizedProbe
(dataclass), pas seulement un dict simule.

Bug detecte par test manuel post-Vague L : isinstance(dataclass_instance, dict)
est False -> probe={} -> probe_quality='FAILED' meme avec un probe FULL reel.
Tier=Silver max sur TOUS les films, scoring lit le nom uniquement.

Mutation testing : si on retire la branche is_dataclass dans compute_quality_score
(retour direct au isinstance(...,dict) only), CE test casse (verifie ci-dessous).
"""
from __future__ import annotations

import unittest
from pathlib import Path

from cinesort.domain.probe_models import PROBE_QUALITY_FULL, NormalizedProbe
from cinesort.domain.quality_score import compute_quality_score, default_quality_profile
from cinesort.infra.probe.normalize import normalize_probe


class NormalizedProbeDataclassAcceptedTests(unittest.TestCase):
    """Garde-fou contre le bug d'origine isinstance(dataclass, dict) == False."""

    def _build_real_normalized_probe_uhd_dv(self) -> NormalizedProbe:
        ff = {
            "format": {"duration": "7200.000", "bit_rate": "65000000", "size": "58500000000"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 3840,
                    "height": 2160,
                    "bit_rate": "58000000",
                    "pix_fmt": "yuv420p10le",
                    "color_primaries": "bt2020",
                    "color_transfer": "smpte2084",
                    "side_data_list": [
                        {"side_data_type": "DOVI configuration record", "dv_profile": 7}
                    ],
                },
                {
                    "codec_type": "audio",
                    "codec_name": "truehd",
                    "channels": 8,
                    "channel_layout": "7.1",
                    "sample_rate": "48000",
                    "tags": {"language": "fra"},
                },
            ],
        }
        return normalize_probe(
            media_path=Path("test.mkv"),
            raw_mediainfo=None,
            raw_ffprobe=ff,
            backend="ffprobe",
            messages=[],
        )

    def test_dataclass_uhd_full_probe_reads_real_metrics_not_name(self) -> None:
        """Un NormalizedProbe FULL reel doit donner des reasons 'mesuree' pas 'deduite du nom'."""
        probe = self._build_real_normalized_probe_uhd_dv()
        self.assertEqual(probe.probe_quality, PROBE_QUALITY_FULL)
        self.assertEqual(probe.video["width"], 3840)
        self.assertEqual(probe.video["bitrate"], 58_000_000)

        result = compute_quality_score(
            normalized_probe=probe,
            release_name="Movie.2160p.UHD.BluRay.REMUX.DV.HDR10.TrueHD.Atmos.7.1.x265-FraMeSToR.mkv",
            profile=default_quality_profile(),
        )

        # 1) Le scoring DOIT marquer la resolution comme MESUREE (probe), pas deduite du nom.
        reasons_joined = " | ".join(result["reasons"])
        self.assertIn("2160p mesuree", reasons_joined,
                      f"Le scoring ignore le probe FULL et deduit du nom. reasons={result['reasons']}")
        self.assertNotIn("2160p deduite du nom", reasons_joined,
                         f"Le scoring deduit du nom alors que le probe est FULL. reasons={result['reasons']}")

        # 2) Le bitrate REEL doit etre detecte (pas '-8 Debit video non detecte')
        self.assertNotIn("Debit video non detecte", reasons_joined,
                         f"Le bitrate video=58000kbps reel n'est pas detecte. reasons={result['reasons']}")

        # 3) Le tier brut doit etre Gold ou Platinum (pas cape Silver).
        self.assertIn(result["tier"], ("Gold", "Platinum"),
                      f"UHD REMUX DV TrueHD probe FULL devrait etre Gold/Platinum, recu {result['tier']}")

    def test_dataclass_failed_probe_caps_to_silver(self) -> None:
        """Cap probe FAILED reste applique sur un VRAI dataclass aussi."""
        probe = NormalizedProbe(
            path="/x",
            probe_quality="FAILED",
            video={},
            audio_tracks=[],
            subtitles=[],
        )
        result = compute_quality_score(
            normalized_probe=probe,
            release_name="Movie.2160p.UHD.BluRay.REMUX.DV.HDR10.TrueHD.Atmos.7.1.x265-FraMeSToR.mkv",
            profile=default_quality_profile(),
        )
        # Cap Silver maximum
        self.assertEqual(result["tier"], "Silver",
                         f"probe FAILED + nom premium doit etre cape Silver, recu {result['tier']}")

    def test_dict_input_still_works_backward_compat(self) -> None:
        """Retro-compat : un dict simule continue de fonctionner."""
        probe_dict = {
            "probe_quality": "FULL",
            "video": {"width": 3840, "height": 2160, "codec": "hevc", "bitrate": 58_000_000,
                      "bit_depth": 10, "hdr_dolby_vision": True, "hdr10": True},
            "audio_tracks": [{"codec": "truehd", "channels": 8, "language": "fra", "is_atmos": True}],
            "subtitles": [],
        }
        result = compute_quality_score(
            normalized_probe=probe_dict,
            release_name="Movie.2160p.UHD.BluRay.REMUX.DV.HDR10.TrueHD.Atmos.7.1.x265-FraMeSToR.mkv",
            profile=default_quality_profile(),
        )
        reasons_joined = " | ".join(result["reasons"])
        self.assertIn("2160p mesuree", reasons_joined,
                      f"dict input mode mesure casse. reasons={result['reasons']}")


if __name__ == "__main__":
    unittest.main()
