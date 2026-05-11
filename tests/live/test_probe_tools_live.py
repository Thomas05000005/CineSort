from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import live_env
from cinesort.infra.db import SQLiteStore, db_path_for_state_dir
from cinesort.infra.probe.service import ProbeService


class ProbeToolsLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.capability = live_env.require_probe_live()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_probe_live_")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.state_dir = self.root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.store = SQLiteStore(db_path_for_state_dir(self.state_dir), busy_timeout_ms=8000)
        self.store.initialize()
        self.service = ProbeService(self.store)

    def _settings(self, backend: str) -> dict[str, str]:
        ffprobe = self.capability["ffprobe"] if isinstance(self.capability.get("ffprobe"), dict) else {}
        mediainfo = self.capability["mediainfo"] if isinstance(self.capability.get("mediainfo"), dict) else {}
        return {
            "probe_backend": backend,
            "ffprobe_path": str(ffprobe.get("path") or ""),
            "mediainfo_path": str(mediainfo.get("path") or ""),
        }

    def _sample_media(self) -> Path:
        return live_env.ensure_sample_media(self.root / "media")

    def test_live_probe_environment_has_at_least_one_compatible_tool(self) -> None:
        self.assertGreaterEqual(
            int(self.capability.get("compatible_count") or 0),
            1,
            self.capability,
        )
        self.assertTrue(
            bool(self.capability.get("sample_override_exists")) or bool(self.capability.get("ffmpeg_path")),
            self.capability,
        )

    def test_ffprobe_backend_probes_real_media_when_available(self) -> None:
        ffprobe = self.capability["ffprobe"] if isinstance(self.capability.get("ffprobe"), dict) else {}
        if not (bool(ffprobe.get("available")) and bool(ffprobe.get("compatible"))):
            self.skipTest(f"ffprobe indisponible/incompatible: {ffprobe}")

        output = self.service.probe_file(
            media_path=self._sample_media(),
            settings=self._settings("ffprobe"),
        )

        self.assertTrue(output.get("ok"), output)
        self.assertFalse(output.get("cache_hit"), output)
        raw_json = output.get("raw_json", {})
        self.assertIsInstance(raw_json.get("ffprobe"), dict)
        self.assertIsNone(raw_json.get("mediainfo"))
        normalized = output.get("normalized", {})
        video = normalized.get("video", {})
        self.assertGreater(int(video.get("width") or 0), 0, normalized)
        self.assertGreater(int(video.get("height") or 0), 0, normalized)
        sources = normalized.get("sources", {})
        self.assertEqual((sources.get("video") or {}).get("codec"), "ffprobe")

    def test_mediainfo_backend_probes_real_media_when_available(self) -> None:
        mediainfo = self.capability["mediainfo"] if isinstance(self.capability.get("mediainfo"), dict) else {}
        if not (bool(mediainfo.get("available")) and bool(mediainfo.get("compatible"))):
            self.skipTest(f"MediaInfo indisponible/incompatible: {mediainfo}")

        output = self.service.probe_file(
            media_path=self._sample_media(),
            settings=self._settings("mediainfo"),
        )

        self.assertTrue(output.get("ok"), output)
        self.assertFalse(output.get("cache_hit"), output)
        raw_json = output.get("raw_json", {})
        self.assertIsInstance(raw_json.get("mediainfo"), dict)
        self.assertIsNone(raw_json.get("ffprobe"))
        normalized = output.get("normalized", {})
        video = normalized.get("video", {})
        self.assertGreater(int(video.get("width") or 0), 0, normalized)
        self.assertGreater(int(video.get("height") or 0), 0, normalized)
        self.assertTrue(str(video.get("codec") or "").strip(), normalized)

    def test_auto_backend_uses_real_tools_and_hits_cache_when_both_are_available(self) -> None:
        ffprobe = self.capability["ffprobe"] if isinstance(self.capability.get("ffprobe"), dict) else {}
        mediainfo = self.capability["mediainfo"] if isinstance(self.capability.get("mediainfo"), dict) else {}
        if not (
            bool(ffprobe.get("available"))
            and bool(ffprobe.get("compatible"))
            and bool(mediainfo.get("available"))
            and bool(mediainfo.get("compatible"))
        ):
            self.skipTest("Mode hybride non disponible sur ce poste.")

        sample = self._sample_media()
        settings = self._settings("auto")
        first = self.service.probe_file(media_path=sample, settings=settings)
        second = self.service.probe_file(media_path=sample, settings=settings)

        self.assertTrue(first.get("ok"), first)
        self.assertFalse(first.get("cache_hit"), first)
        self.assertTrue(second.get("ok"), second)
        self.assertTrue(second.get("cache_hit"), second)
        raw_json = first.get("raw_json", {})
        self.assertIsInstance(raw_json.get("mediainfo"), dict)
        self.assertIsInstance(raw_json.get("ffprobe"), dict)
        normalized = first.get("normalized", {})
        video = normalized.get("video", {})
        self.assertGreater(int(video.get("width") or 0), 0, normalized)
        self.assertGreater(int(video.get("height") or 0), 0, normalized)


if __name__ == "__main__":
    unittest.main(verbosity=2)
