"""Tests d'extraction "NFO complet" depuis ffprobe.

Fix audit 2026-05-25 (v1.5.5) Vague K : verifie que normalize_probe extrait
TOUS les champs utiles depuis un payload ffprobe realiste (4K HDR Dolby Vision
Atmos avec chapitres). Garantit la retro-compat des anciens champs et l'apparition
des nouveaux (container_*, profile, level, color_*, channel_layout, sample_rate,
is_atmos, is_dts_x, chapters, etc.).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from cinesort.infra.probe.normalize import (
    _detect_atmos_dtsx,
    _extract_bit_depth,
    normalize_probe,
)


def _make_ffprobe_payload_full() -> dict:
    """Payload ffprobe representatif d'un .mkv 4K HDR10/DV Atmos avec chapitres."""
    return {
        "format": {
            "format_name": "matroska,webm",
            "duration": "7382.123",
            "size": "25000000000",
            "bit_rate": "27000000",
            "tags": {
                "title": "Mad Max Fury Road",
                "encoder": "libmakemkv v1.17.5",
                "creation_time": "2024-03-15T10:00:00.000000Z",
            },
        },
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "hevc",
                "profile": "Main 10",
                "level": 153,
                "width": 3840,
                "height": 2160,
                "display_aspect_ratio": "16:9",
                "sample_aspect_ratio": "1:1",
                "pix_fmt": "yuv420p10le",
                "bits_per_raw_sample": "10",
                "r_frame_rate": "24000/1001",
                "avg_frame_rate": "24000/1001",
                "bit_rate": "20000000",
                "color_primaries": "bt2020",
                "color_transfer": "smpte2084",
                "color_space": "bt2020nc",
                "color_range": "tv",
                "chroma_location": "topleft",
                "side_data_list": [
                    {
                        "side_data_type": "Mastering display metadata",
                        "min_luminance": "50/10000",
                        "max_luminance": "10000000/10000",
                    },
                    {
                        "side_data_type": "Content light level metadata",
                        "max_content": 1000,
                        "max_average": 400,
                    },
                    {
                        "side_data_type": "DOVI configuration record",
                        "dv_profile": 7,
                        "dv_bl_signal_compatibility_id": 0,
                        "rpu_present_flag": 1,
                        "el_present_flag": 1,
                        "bl_present_flag": 1,
                    },
                ],
                "tags": {"language": "eng", "title": "Main video"},
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "truehd",
                "profile": "Dolby TrueHD",
                "channels": 8,
                "channel_layout": "7.1",
                "sample_rate": "48000",
                "bits_per_raw_sample": "24",
                "bit_rate": "4000000",
                "disposition": {"default": 1, "forced": 0, "comment": 0},
                "tags": {"language": "eng", "title": "Dolby Atmos 7.1"},
            },
            {
                "index": 2,
                "codec_type": "audio",
                "codec_name": "dts",
                "profile": "DTS-HD MA",
                "channels": 6,
                "channel_layout": "5.1",
                "sample_rate": "48000",
                "bits_per_raw_sample": "24",
                "bit_rate": "1500000",
                "disposition": {"default": 0, "forced": 0, "comment": 0},
                "tags": {"language": "fre", "title": "DTS:X French"},
            },
            {
                "index": 3,
                "codec_type": "audio",
                "codec_name": "ac3",
                "channels": 2,
                "channel_layout": "stereo",
                "sample_rate": "48000",
                "bit_rate": "192000",
                "disposition": {"default": 0, "forced": 0, "comment": 1},
                "tags": {"language": "eng", "title": "Director commentary"},
            },
            {
                "index": 4,
                "codec_type": "subtitle",
                "codec_name": "subrip",
                "disposition": {"default": 1, "forced": 0, "hearing_impaired": 0},
                "tags": {"language": "eng", "title": "English SRT"},
            },
            {
                "index": 5,
                "codec_type": "subtitle",
                "codec_name": "hdmv_pgs_subtitle",
                "disposition": {"default": 0, "forced": 1, "hearing_impaired": 0},
                "tags": {"language": "fre", "title": "French PGS Forced"},
            },
            {
                "index": 6,
                "codec_type": "subtitle",
                "codec_name": "subrip",
                "disposition": {"default": 0, "forced": 0, "hearing_impaired": 1},
                "tags": {"language": "eng", "title": "SDH"},
            },
        ],
        "chapters": [
            {
                "id": 0,
                "start_time": "0.000000",
                "end_time": "300.000000",
                "tags": {"title": "Chapter 01"},
            },
            {
                "id": 1,
                "start_time": "300.000000",
                "end_time": "600.000000",
                "tags": {"title": "Chapter 02"},
            },
        ],
    }


class ProbeNormalizeCompleteTests(unittest.TestCase):
    """Vague K : extraction exhaustive ffprobe (NFO complet)."""

    def test_container_complete(self) -> None:
        raw = _make_ffprobe_payload_full()
        n = normalize_probe(
            media_path=Path("/movies/mad_max.mkv"),
            raw_mediainfo=None,
            raw_ffprobe=raw,
            backend="ffprobe",
            messages=[],
        )
        d = n.to_dict()
        self.assertEqual(d["container"], "matroska")
        self.assertEqual(d["container_title"], "Mad Max Fury Road")
        self.assertEqual(d["container_format_long"], "matroska,webm")
        self.assertEqual(d["container_size_bytes"], 25_000_000_000)
        self.assertEqual(d["container_bit_rate"], 27_000_000)
        self.assertEqual(d["container_encoder"], "libmakemkv v1.17.5")
        self.assertEqual(d["container_creation_time"], "2024-03-15T10:00:00.000000Z")
        self.assertAlmostEqual(d["duration_s"], 7382.123, places=2)

    def test_video_stream_complete(self) -> None:
        raw = _make_ffprobe_payload_full()
        n = normalize_probe(
            media_path=Path("/movies/mad_max.mkv"),
            raw_mediainfo=None,
            raw_ffprobe=raw,
            backend="ffprobe",
            messages=[],
        )
        v = n.to_dict()["video"]
        # Champs historiques (retro-compat)
        self.assertEqual(v["codec"], "hevc")
        self.assertEqual(v["width"], 3840)
        self.assertEqual(v["height"], 2160)
        self.assertEqual(v["bit_depth"], 10)
        self.assertEqual(v["pixel_format"], "yuv420p10le")
        self.assertEqual(v["bitrate"], 20_000_000)
        # Champs HDR existants
        self.assertEqual(v["hdr_type"], "dolby_vision")
        self.assertTrue(v["dv_present"])
        self.assertEqual(v["dv_profile"], "7")
        # Champs Vague K (NFO complet)
        self.assertEqual(v["profile"], "Main 10")
        self.assertEqual(v["level"], 153)
        self.assertEqual(v["display_aspect_ratio"], "16:9")
        self.assertEqual(v["sample_aspect_ratio"], "1:1")
        self.assertEqual(v["color_primaries"], "bt2020")
        self.assertEqual(v["color_transfer"], "smpte2084")
        self.assertEqual(v["color_space"], "bt2020nc")
        self.assertEqual(v["color_range"], "tv")
        self.assertEqual(v["chroma_location"], "topleft")
        self.assertEqual(v["language"], "eng")
        self.assertEqual(v["title"], "Main video")
        self.assertIsNotNone(v["r_frame_rate"])

    def test_audio_streams_complete(self) -> None:
        raw = _make_ffprobe_payload_full()
        n = normalize_probe(
            media_path=Path("/movies/mad_max.mkv"),
            raw_mediainfo=None,
            raw_ffprobe=raw,
            backend="ffprobe",
            messages=[],
        )
        tracks = n.to_dict()["audio_tracks"]
        self.assertEqual(len(tracks), 3)

        truehd = tracks[0]
        self.assertEqual(truehd["codec"], "truehd")
        self.assertEqual(truehd["profile"], "Dolby TrueHD")
        self.assertEqual(truehd["channels"], 8)
        self.assertEqual(truehd["channel_layout"], "7.1")
        self.assertEqual(truehd["sample_rate"], 48000)
        self.assertEqual(truehd["bit_depth"], 24)
        self.assertEqual(truehd["bitrate"], 4_000_000)
        self.assertEqual(truehd["language"], "eng")
        self.assertTrue(truehd["is_default"])
        self.assertFalse(truehd["is_forced"])
        # Atmos detecte depuis le titre
        self.assertTrue(truehd["is_atmos"])
        self.assertFalse(truehd["is_dts_x"])

        dts = tracks[1]
        self.assertEqual(dts["codec"], "dts")
        self.assertEqual(dts["profile"], "DTS-HD MA")
        self.assertEqual(dts["channels"], 6)
        self.assertEqual(dts["channel_layout"], "5.1")
        # DTS:X detecte depuis le titre
        self.assertTrue(dts["is_dts_x"])
        self.assertFalse(dts["is_atmos"])

        commentary = tracks[2]
        self.assertEqual(commentary["codec"], "ac3")
        self.assertTrue(commentary["is_commentary"])
        self.assertFalse(commentary["is_atmos"])
        self.assertFalse(commentary["is_dts_x"])

    def test_subtitle_streams_complete(self) -> None:
        raw = _make_ffprobe_payload_full()
        n = normalize_probe(
            media_path=Path("/movies/mad_max.mkv"),
            raw_mediainfo=None,
            raw_ffprobe=raw,
            backend="ffprobe",
            messages=[],
        )
        subs = n.to_dict()["subtitles"]
        self.assertEqual(len(subs), 3)

        eng_srt = subs[0]
        self.assertEqual(eng_srt["codec"], "subrip")
        self.assertEqual(eng_srt["language"], "eng")
        self.assertEqual(eng_srt["title"], "English SRT")
        self.assertTrue(eng_srt["is_default"])
        self.assertFalse(eng_srt["forced"])
        self.assertFalse(eng_srt["is_hearing_impaired"])

        fre_pgs = subs[1]
        self.assertEqual(fre_pgs["codec"], "hdmv_pgs_subtitle")
        self.assertTrue(fre_pgs["forced"])
        self.assertFalse(fre_pgs["is_default"])

        sdh = subs[2]
        self.assertTrue(sdh["is_hearing_impaired"])

    def test_chapters_extracted(self) -> None:
        raw = _make_ffprobe_payload_full()
        n = normalize_probe(
            media_path=Path("/movies/mad_max.mkv"),
            raw_mediainfo=None,
            raw_ffprobe=raw,
            backend="ffprobe",
            messages=[],
        )
        chapters = n.to_dict()["chapters"]
        self.assertEqual(len(chapters), 2)
        self.assertEqual(chapters[0]["title"], "Chapter 01")
        self.assertEqual(chapters[0]["start_time"], 0.0)
        self.assertEqual(chapters[0]["end_time"], 300.0)
        self.assertEqual(chapters[1]["title"], "Chapter 02")

    def test_probe_quality_full_on_complete_payload(self) -> None:
        raw = _make_ffprobe_payload_full()
        n = normalize_probe(
            media_path=Path("/movies/mad_max.mkv"),
            raw_mediainfo=None,
            raw_ffprobe=raw,
            backend="ffprobe",
            messages=[],
        )
        self.assertEqual(n.probe_quality, "FULL")


class BitDepthHelperTests(unittest.TestCase):
    """Vague K : helper _extract_bit_depth (pix_fmt fallback)."""

    def test_explicit_bits_per_raw_sample_wins(self) -> None:
        self.assertEqual(_extract_bit_depth("yuv420p10le", "12"), 12)

    def test_pix_fmt_10bit(self) -> None:
        self.assertEqual(_extract_bit_depth("yuv420p10le", None), 10)
        self.assertEqual(_extract_bit_depth("yuv422p10le", ""), 10)

    def test_pix_fmt_12bit(self) -> None:
        self.assertEqual(_extract_bit_depth("yuv420p12le", None), 12)

    def test_pix_fmt_16bit(self) -> None:
        self.assertEqual(_extract_bit_depth("yuv420p16le", None), 16)

    def test_pix_fmt_8bit_default(self) -> None:
        self.assertEqual(_extract_bit_depth("yuv420p", None), 8)
        self.assertEqual(_extract_bit_depth("yuvj420p", None), 8)

    def test_pix_fmt_empty_returns_none(self) -> None:
        self.assertIsNone(_extract_bit_depth("", None))


class AtmosDtsXDetectionTests(unittest.TestCase):
    """Vague K : helper _detect_atmos_dtsx."""

    def test_atmos_truehd_from_title(self) -> None:
        is_atmos, is_dts_x = _detect_atmos_dtsx("truehd", "", "Dolby Atmos 7.1", {})
        self.assertTrue(is_atmos)
        self.assertFalse(is_dts_x)

    def test_atmos_eac3_joc_profile(self) -> None:
        is_atmos, is_dts_x = _detect_atmos_dtsx("eac3", "JOC", "", {})
        self.assertTrue(is_atmos)

    def test_dts_x_from_title(self) -> None:
        is_atmos, is_dts_x = _detect_atmos_dtsx("dts", "DTS-HD MA", "DTS:X French", {})
        self.assertFalse(is_atmos)
        self.assertTrue(is_dts_x)

    def test_plain_stereo_neither(self) -> None:
        is_atmos, is_dts_x = _detect_atmos_dtsx("ac3", "", "English 2.0", {})
        self.assertFalse(is_atmos)
        self.assertFalse(is_dts_x)

    def test_aac_neither(self) -> None:
        is_atmos, is_dts_x = _detect_atmos_dtsx("aac", "LC", "stereo", {})
        self.assertFalse(is_atmos)
        self.assertFalse(is_dts_x)


class RetroCompatTests(unittest.TestCase):
    """Vague K : verifie qu'aucun ancien champ n'a disparu."""

    def test_minimal_payload_still_works(self) -> None:
        raw = {
            "format": {"format_name": "matroska,webm", "duration": "100.0"},
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "pix_fmt": "yuv420p",
                },
            ],
        }
        n = normalize_probe(
            media_path=Path("/movies/test.mp4"),
            raw_mediainfo=None,
            raw_ffprobe=raw,
            backend="ffprobe",
            messages=[],
        )
        d = n.to_dict()
        # Anciens champs preserves
        self.assertEqual(d["container"], "matroska")
        self.assertEqual(d["video"]["codec"], "h264")
        self.assertEqual(d["video"]["width"], 1920)
        # Nouveaux champs absents ou None mais presents
        self.assertIn("container_size_bytes", d)
        self.assertIn("chapters", d)
        self.assertEqual(d["chapters"], [])


if __name__ == "__main__":
    unittest.main()
