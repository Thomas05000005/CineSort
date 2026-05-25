# Fix audit 2026-05-25 (v1.5.5) Vague K : tests du scoring qualite avec fallback
# sur le nom de release quand le probe est PARTIAL/FAILED.
"""Tests : scoring V2 - fallback sur le nom de release quand probe FAILED.

Verifie que le scoring exploite les hints extraits du nom (resolution, codec,
HDR, audio, source) au lieu de tomber a 0 quand le probe ne donne rien.
"""

from __future__ import annotations

import unittest

from cinesort.domain.quality_score import compute_quality_score, default_quality_profile
from cinesort.domain.release_name_parser import parse_release_name


def _failed_probe() -> dict:
    """Probe qui a echoue : aucune info technique exploitable."""
    return {
        "probe_quality": "FAILED",
        "probe_quality_reasons": ["ffprobe a echoue (SMB obsolete)."],
        "video": {},
        "audio_tracks": [],
        "sources": {},
    }


def _partial_probe_only_resolution(width: int, height: int) -> dict:
    """Probe PARTIAL : seulement les dimensions exposees, pas de codec/bitrate."""
    return {
        "probe_quality": "PARTIAL",
        "probe_quality_reasons": ["ffprobe partiel : codec absent."],
        "video": {
            "width": width,
            "height": height,
        },
        "audio_tracks": [],
        "sources": {"video": {"width": "ffprobe", "height": "ffprobe"}},
    }


class ReleaseNameParserTests(unittest.TestCase):
    """Tests unitaires du parser pour s'assurer qu'il extrait bien les specs."""

    def test_parse_uhd_dv_hdr_bluray_dts_hd_x265(self) -> None:
        info = parse_release_name(
            "12 Angry Men (1957) 2160p DV HDR BluRay DTS-HD MA 1.0 x265-GROUP.mkv"
        )
        self.assertEqual(info.resolution_hint, "2160p")
        self.assertEqual(info.width_hint, 3840)
        self.assertEqual(info.height_hint, 2160)
        self.assertEqual(info.codec_hint, "hevc")
        self.assertEqual(info.bit_depth_hint, 10)  # heuristique HEVC 2160p -> 10-bit
        self.assertEqual(info.hdr_hint, "dv")
        self.assertEqual(info.source_hint, "bluray")
        self.assertEqual(info.audio_codec_hint, "dts_hd_ma")
        self.assertTrue(info.audio_is_lossless)
        self.assertEqual(info.audio_channels_hint, "1.0")
        self.assertEqual(info.release_group, "GROUP")

    def test_parse_1080p_bluray_h264_dts_hd_ma(self) -> None:
        info = parse_release_name("Inception (2010) 1080p BluRay x264 DTS-HD MA 5.1-FraMeSToR.mkv")
        self.assertEqual(info.resolution_hint, "1080p")
        self.assertEqual(info.codec_hint, "h264")
        self.assertEqual(info.source_hint, "bluray")
        self.assertEqual(info.audio_codec_hint, "dts_hd_ma")
        self.assertEqual(info.audio_channels_hint, "5.1")
        self.assertTrue(info.audio_is_lossless)
        self.assertEqual(info.release_group, "FraMeSToR")

    def test_parse_720p_webdl_aac(self) -> None:
        info = parse_release_name("Movie (2020) 720p WEB-DL x264 AAC 2.0-RARBG.mkv")
        self.assertEqual(info.resolution_hint, "720p")
        self.assertEqual(info.codec_hint, "h264")
        self.assertEqual(info.source_hint, "webdl")
        self.assertEqual(info.audio_codec_hint, "aac")
        self.assertFalse(info.audio_is_lossless)
        self.assertEqual(info.audio_channels_hint, "2.0")

    def test_parse_atmos_truehd(self) -> None:
        info = parse_release_name(
            "Dune.Part.Two.2024.2160p.UHD.BluRay.x265.10bit.HDR.TrueHD.Atmos.7.1-SWTYBLZ.mkv"
        )
        self.assertEqual(info.resolution_hint, "2160p")
        self.assertEqual(info.codec_hint, "hevc")
        self.assertEqual(info.bit_depth_hint, 10)
        self.assertEqual(info.hdr_hint, "hdr10")  # "HDR" sans suffixe
        self.assertEqual(info.source_hint, "bluray")
        self.assertTrue(info.audio_is_atmos)
        # Atmos est detecte en premier (motif specifique avant TrueHD).
        # On verifie surtout que c'est lossless (TrueHD/Atmos sont lossless).
        self.assertIn(info.audio_codec_hint, {"truehd", "atmos"})
        self.assertTrue(info.audio_is_lossless)

    def test_parse_empty(self) -> None:
        info = parse_release_name("")
        self.assertEqual(info.resolution_hint, "")
        self.assertEqual(info.codec_hint, "")
        self.assertEqual(info.audio_codec_hint, "")


class QualityScoreFallbackToNameTests(unittest.TestCase):
    """Tests : compute_quality_score avec probe FAILED + nom riche."""

    def setUp(self) -> None:
        self.profile = default_quality_profile()

    def test_12_angry_men_4k_dv_bluray_dts_hd_x265_probe_failed(self) -> None:
        """Probe FAILED + nom UHD DV BluRay DTS-HD MA -> Platinum/Gold."""
        name = "12 Angry Men (1957) 2160p DV HDR BluRay DTS-HD MA x265.mkv"
        result = compute_quality_score(
            normalized_probe=_failed_probe(),
            profile=self.profile,
            release_name=name,
            folder_name="12 Angry Men (1957)",
            expected_title="12 Angry Men",
            expected_year=1957,
            film_year=1957,
        )
        self.assertGreaterEqual(
            result["score"], 70, f"score trop faible: {result['score']} ({result['reasons']})"
        )
        self.assertIn(result["tier"], {"Platinum", "Gold"}, f"tier={result['tier']}")

    def test_inception_1080p_bluray_x264_dts_hd_ma_probe_failed(self) -> None:
        """Probe FAILED + nom 1080p BluRay DTS-HD MA -> Gold/Silver."""
        name = "Inception (2010) 1080p BluRay x264 DTS-HD MA 5.1.mkv"
        result = compute_quality_score(
            normalized_probe=_failed_probe(),
            profile=self.profile,
            release_name=name,
            folder_name="Inception (2010)",
            expected_title="Inception",
            expected_year=2010,
            film_year=2010,
        )
        self.assertGreaterEqual(
            result["score"], 55, f"score trop faible: {result['score']} ({result['reasons']})"
        )
        self.assertIn(result["tier"], {"Gold", "Silver"}, f"tier={result['tier']}")

    def test_movie_720p_webdl_aac_probe_failed(self) -> None:
        """Probe FAILED + nom 720p WEB-DL AAC -> Bronze."""
        name = "Movie (2020) 720p WEB-DL x264 AAC 2.0.mkv"
        result = compute_quality_score(
            normalized_probe=_failed_probe(),
            profile=self.profile,
            release_name=name,
            folder_name="Movie (2020)",
            expected_title="Movie",
            expected_year=2020,
            film_year=2020,
        )
        self.assertGreaterEqual(result["score"], 25, f"score trop faible: {result['score']}")
        self.assertLessEqual(result["score"], 55, f"score trop fort: {result['score']}")
        self.assertIn(
            result["tier"],
            {"Bronze", "Silver"},
            f"tier={result['tier']} score={result['score']}",
        )

    def test_empty_name_and_probe_failed_yields_reject(self) -> None:
        """Probe FAILED + nom vide -> score tres faible (Reject)."""
        result = compute_quality_score(
            normalized_probe=_failed_probe(),
            profile=self.profile,
            release_name="",
            folder_name="",
        )
        self.assertLessEqual(result["score"], 25, f"score: {result['score']}")
        self.assertEqual(result["tier"], "Reject")

    def test_partial_probe_completed_by_name(self) -> None:
        """Probe PARTIAL avec resolution seule + nom riche -> bon score."""
        name = "Blade Runner 2049 (2017) 2160p UHD BluRay HDR10 TrueHD Atmos 7.1 x265.mkv"
        partial = _partial_probe_only_resolution(3840, 2160)
        result = compute_quality_score(
            normalized_probe=partial,
            profile=self.profile,
            release_name=name,
            folder_name="Blade Runner 2049 (2017)",
            expected_title="Blade Runner 2049",
            expected_year=2017,
            film_year=2017,
        )
        # Le probe donne la resolution (mesuree, pas de penalite incertitude),
        # le nom comble codec/HDR/audio.
        self.assertGreaterEqual(
            result["score"], 55, f"score trop faible: {result['score']} ({result['reasons']})"
        )

    def test_full_probe_overrides_name_for_codec(self) -> None:
        """Probe FULL avec codec HEVC + nom contradictoire (x264) -> probe gagne."""
        full_probe = {
            "probe_quality": "FULL",
            "video": {
                "codec": "hevc",
                "width": 3840,
                "height": 2160,
                "bitrate": 60000000,
                "bit_depth": 10,
                "hdr10": True,
            },
            "audio_tracks": [
                {"codec": "truehd", "channels": 8, "language": "eng", "bitrate": 4000000}
            ],
            "sources": {},
        }
        # Le nom dit x264 mais le probe dit HEVC : le probe doit gagner.
        name = "Film (2020) 2160p BluRay x264 AAC 2.0.mkv"
        result = compute_quality_score(
            normalized_probe=full_probe,
            profile=self.profile,
            release_name=name,
            film_year=2020,
        )
        detected = result["metrics"]["detected"]
        self.assertEqual(detected["video_codec"], "hevc")
        self.assertEqual(detected["audio_best_codec"], "truehd")
        self.assertGreaterEqual(result["score"], 70)

    def test_before_after_comparison_12_angry_men(self) -> None:
        """Comparaison avant/apres pour le cas pivot : SMB obsolete + nom riche.

        AVANT (sans Vague K) : probe FAILED -> score ~10-20 -> Reject.
        APRES (Vague K) : nom exploite -> score 70+ -> Platinum/Gold.
        """
        name = "12 Angry Men (1957) 2160p DV HDR BluRay DTS-HD MA x265.mkv"
        # Sans release_name : ce qui se passait avant la Vague K.
        without = compute_quality_score(
            normalized_probe=_failed_probe(),
            profile=self.profile,
            release_name="",
            folder_name="12 Angry Men (1957)",
        )
        # Avec release_name : nouvelle voie Vague K.
        with_name = compute_quality_score(
            normalized_probe=_failed_probe(),
            profile=self.profile,
            release_name=name,
            folder_name="12 Angry Men (1957)",
            film_year=1957,
        )
        self.assertLess(without["score"], with_name["score"])
        self.assertGreaterEqual(
            with_name["score"] - without["score"],
            40,
            f"gap insuffisant: {without['score']} -> {with_name['score']}",
        )


if __name__ == "__main__":
    unittest.main()
