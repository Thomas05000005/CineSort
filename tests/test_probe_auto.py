from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.infra.db import SQLiteStore, db_path_for_state_dir
from cinesort.infra.probe.service import ProbeService
from cinesort.infra.probe import tooling


class _RunnerSpy:
    def __init__(self) -> None:
        self.calls = []

        self._mediainfo_payload = {
            "media": {
                "track": [
                    {
                        "@type": "General",
                        "Format": "Matroska",
                        "Duration": "7382.123",
                        "OverallBitRate": "12000000",
                    },
                    {
                        "@type": "Video",
                        "Format": "HEVC",
                        "Width": "3 840",
                        "Height": "2 160",
                        "FrameRate": "23.976",
                        "BitDepth": "10",
                        "HDR_Format": "Dolby Vision, HDR10",
                        "BitRate": "10000000",
                    },
                    {
                        "@type": "Audio",
                        "Format": "TrueHD",
                        "Channel(s)": "8",
                        "Language": "fra",
                        "BitRate": "4000000",
                    },
                    {
                        "@type": "Text",
                        "Language": "fre",
                        "Forced": "No",
                    },
                ]
            }
        }
        self._ffprobe_payload = {
            "format": {
                "format_name": "matroska,webm",
                "duration": "7382.120",
                "bit_rate": "12500000",
            },
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 3840,
                    "height": 2160,
                    "avg_frame_rate": "24000/1001",
                    "pix_fmt": "yuv420p10le",
                    "bit_rate": "10100000",
                    "color_transfer": "smpte2084",
                    "side_data_list": [{"side_data_type": "Dolby Vision RPU Metadata"}],
                },
                {
                    "index": 1,
                    "codec_type": "audio",
                    "codec_name": "eac3",
                    "channels": 6,
                    "bit_rate": "768000",
                    "tags": {"language": "fra"},
                },
                {
                    "index": 2,
                    "codec_type": "subtitle",
                    "codec_name": "subrip",
                    "tags": {"language": "fre", "forced": "1"},
                },
            ],
        }

    def __call__(self, cmd, _timeout_s):
        self.calls.append(list(cmd))
        joined = " ".join(str(x) for x in cmd)
        if "--Version" in joined:
            return 0, "MediaInfoLib - v24.01", ""
        if "-version" in joined:
            return 0, "ffprobe version 6.0", ""
        if "--Output=JSON" in joined:
            return 0, json.dumps(self._mediainfo_payload), ""
        if "-show_format" in joined and "-show_streams" in joined:
            return 0, json.dumps(self._ffprobe_payload), ""
        return 1, "", "commande inattendue"


class ProbeAutoTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="probe_auto_")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path_for_state_dir(self.state_dir)
        self.store = SQLiteStore(self.db_path, busy_timeout_ms=8000)
        self.store.initialize()
        self.media = Path(self._tmp.name) / "movie.mkv"
        self.media.write_bytes(b"\x00" * 1024)

    def test_probe_without_tools_returns_partial_with_missing_tool_message(self) -> None:
        spy = _RunnerSpy()
        service = ProbeService(self.store, runner=spy, which_fn=lambda _name: None)
        out = service.probe_file(
            media_path=self.media,
            settings={
                "probe_backend": "auto",
                "mediainfo_path": "",
                "ffprobe_path": "",
            },
        )

        self.assertTrue(out.get("ok"), out)
        self.assertFalse(out.get("cache_hit"), out)
        normalized = out.get("normalized", {})
        self.assertEqual(normalized.get("probe_quality"), "PARTIAL")
        reasons = normalized.get("probe_quality_reasons", [])
        self.assertTrue(any("outil manquant" in str(r).lower() for r in reasons), reasons)
        self.assertEqual(out.get("raw_json", {}).get("mediainfo"), None)
        self.assertEqual(out.get("raw_json", {}).get("ffprobe"), None)
        self.assertEqual(spy.calls, [])

    def test_probe_auto_parses_and_traces_sources(self) -> None:
        spy = _RunnerSpy()
        service = ProbeService(self.store, runner=spy, which_fn=lambda name: str(name))
        out = service.probe_file(
            media_path=self.media,
            settings={
                "probe_backend": "auto",
                "mediainfo_path": "mediainfo",
                "ffprobe_path": "ffprobe",
            },
        )

        self.assertTrue(out.get("ok"), out)
        normalized = out.get("normalized", {})
        self.assertEqual(normalized.get("probe_quality"), "FULL")
        self.assertTrue(any("complete" in str(r).lower() for r in normalized.get("probe_quality_reasons", [])))

        video = normalized.get("video", {})
        self.assertEqual(video.get("codec"), "hevc")
        self.assertEqual(int(video.get("width") or 0), 3840)
        self.assertTrue(bool(video.get("hdr_dolby_vision")))

        sources = normalized.get("sources", {})
        self.assertEqual(sources.get("duration_s"), "ffprobe")
        self.assertEqual(sources.get("video", {}).get("codec"), "ffprobe")
        self.assertEqual(sources.get("container"), "mediainfo")

        raw_json = out.get("raw_json", {})
        self.assertIsInstance(raw_json.get("mediainfo"), dict)
        self.assertIsInstance(raw_json.get("ffprobe"), dict)

    def test_probe_auto_handles_invalid_ffprobe_json_as_partial(self) -> None:
        spy = _RunnerSpy()
        spy._ffprobe_payload = "{bad json"  # type: ignore[assignment]
        service = ProbeService(self.store, runner=spy, which_fn=lambda name: str(name))
        out = service.probe_file(
            media_path=self.media,
            settings={
                "probe_backend": "auto",
                "mediainfo_path": "mediainfo",
                "ffprobe_path": "ffprobe",
            },
        )

        self.assertTrue(out.get("ok"), out)
        normalized = out.get("normalized", {})
        self.assertIn(normalized.get("probe_quality"), {"FULL", "PARTIAL"})
        messages = [str(item).lower() for item in normalized.get("messages", [])]
        self.assertTrue(
            any("ffprobe" in item and ("json invalide" in item or "json non exploitable" in item) for item in messages),
            messages,
        )
        self.assertIsInstance(out.get("raw_json", {}).get("mediainfo"), dict)
        self.assertIsNone(out.get("raw_json", {}).get("ffprobe"))

    def test_probe_auto_handles_runner_timeout_as_partial(self) -> None:
        def timeout_runner(cmd, _timeout_s):
            joined = " ".join(str(x) for x in cmd)
            if "--Version" in joined:
                return 0, "MediaInfoLib - v24.01", ""
            if "-version" in joined:
                return 0, "ffprobe version 6.0", ""
            if "--Output=JSON" in joined:
                return 0, json.dumps(_RunnerSpy()._mediainfo_payload), ""
            if "-show_format" in joined and "-show_streams" in joined:
                raise TimeoutError("ffprobe timeout")
            return 1, "", "commande inattendue"

        service = ProbeService(self.store, runner=timeout_runner, which_fn=lambda name: str(name))
        out = service.probe_file(
            media_path=self.media,
            settings={
                "probe_backend": "auto",
                "mediainfo_path": "mediainfo",
                "ffprobe_path": "ffprobe",
            },
        )

        self.assertTrue(out.get("ok"), out)
        normalized = out.get("normalized", {})
        self.assertIn(normalized.get("probe_quality"), {"FULL", "PARTIAL"})
        messages = [str(item).lower() for item in normalized.get("messages", [])]
        self.assertTrue(any("execution" in item and "ffprobe" in item for item in messages), messages)
        self.assertIsInstance(out.get("raw_json", {}).get("mediainfo"), dict)
        self.assertIsNone(out.get("raw_json", {}).get("ffprobe"))

    def test_probe_cache_hit_skips_subprocess(self) -> None:
        spy = _RunnerSpy()
        service = ProbeService(self.store, runner=spy, which_fn=lambda name: str(name))
        settings = {
            "probe_backend": "auto",
            "mediainfo_path": "mediainfo",
            "ffprobe_path": "ffprobe",
        }
        first = service.probe_file(media_path=self.media, settings=settings)
        self.assertTrue(first.get("ok"), first)
        self.assertFalse(first.get("cache_hit"), first)
        first_calls = len(spy.calls)
        self.assertGreater(first_calls, 0)

        second = service.probe_file(media_path=self.media, settings=settings)
        self.assertTrue(second.get("ok"), second)
        self.assertTrue(second.get("cache_hit"), second)
        self.assertEqual(len(spy.calls), first_calls)

    def test_runner_platform_kwargs_windows_has_no_window_flags(self) -> None:
        with mock.patch.object(tooling.os, "name", "nt"):
            kwargs = tooling._runner_platform_kwargs()
        self.assertIn("creationflags", kwargs)
        self.assertIn("startupinfo", kwargs)

    def test_default_runner_passes_platform_kwargs(self) -> None:
        # Note V1-03 : tooling.default_runner utilise maintenant `tracked_run`
        # (cf cinesort.infra.subprocess_safety) pour garantir le cleanup
        # des subprocess en cas d'exception.
        fake_cp = mock.Mock(returncode=0, stdout="ok", stderr="")
        with (
            mock.patch.object(tooling.os, "name", "nt"),
            mock.patch.object(tooling, "tracked_run", return_value=fake_cp) as mocked_run,
        ):
            rc, out, err = tooling.default_runner(["cmd", "/c", "echo", "ok"], 3.0)
        self.assertEqual((rc, out, err), (0, "ok", ""))
        called_kwargs = mocked_run.call_args.kwargs
        self.assertIn("creationflags", called_kwargs)
        self.assertIn("startupinfo", called_kwargs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
