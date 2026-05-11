"""Tests V1-M13 — mecanisme update auto via GitHub Releases."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

from cinesort.app import updater
from cinesort.app.updater import (
    UpdateInfo,
    _build_update_info,
    _compare_versions,
    _parse_version,
    check_for_updates,
)


def _fake_payload(
    tag: str = "7.7.0",
    body: str = "Notes de release",
    html_url: str = "https://github.com/foo/cinesort/releases/tag/v7.7.0",
    published_at: str = "2026-06-01T12:00:00Z",
    assets: list | None = None,
) -> dict:
    return {
        "tag_name": tag,
        "body": body,
        "html_url": html_url,
        "published_at": published_at,
        "assets": assets
        if assets is not None
        else [
            {"name": "CineSort.exe", "browser_download_url": "https://example.com/CineSort.exe"},
        ],
    }


class _FakeResponse:
    def __init__(self, payload: dict):
        self._data = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args) -> None:
        return None


class CompareVersionsTests(unittest.TestCase):
    def test_newer_returns_true(self) -> None:
        self.assertTrue(_compare_versions("7.6.0", "7.7.0"))
        self.assertTrue(_compare_versions("7.6.0", "8.0.0"))
        self.assertTrue(_compare_versions("7.6.0", "7.6.1"))

    def test_same_returns_false(self) -> None:
        self.assertFalse(_compare_versions("7.6.0", "7.6.0"))

    def test_older_returns_false(self) -> None:
        self.assertFalse(_compare_versions("7.7.0", "7.6.0"))
        self.assertFalse(_compare_versions("8.0.0", "7.9.9"))

    def test_dev_suffix_stripped(self) -> None:
        # '7.6.0-dev' parse en (7,6,0) — meme base, donc pas plus recent que '7.6.0'
        self.assertFalse(_compare_versions("7.6.0-dev", "7.6.0"))
        # Une vraie nouvelle release reste detectee meme depuis un dev
        self.assertTrue(_compare_versions("7.6.0-dev", "7.7.0"))

    def test_v_prefix_stripped(self) -> None:
        self.assertTrue(_compare_versions("7.6.0", "v7.7.0"))
        self.assertFalse(_compare_versions("v7.7.0", "v7.6.0"))

    def test_parse_version_handles_garbage(self) -> None:
        self.assertEqual(_parse_version("1.2.3"), (1, 2, 3))
        self.assertEqual(_parse_version("v1.2.3-rc1"), (1, 2, 3))
        self.assertEqual(_parse_version(""), (0,))
        self.assertEqual(_parse_version("not-a-version"), (0,))


class CheckForUpdatesTests(unittest.TestCase):
    def test_new_version_returns_update_info(self) -> None:
        payload = _fake_payload(tag="7.7.0")
        with mock.patch.object(updater, "urlopen", return_value=_FakeResponse(payload)):
            info = check_for_updates("7.6.0", "foo/cinesort")
        self.assertIsInstance(info, UpdateInfo)
        assert info is not None
        self.assertEqual(info.latest_version, "7.7.0")
        self.assertEqual(info.current_version, "7.6.0")
        self.assertEqual(info.download_url, "https://example.com/CineSort.exe")
        self.assertIn("Notes", info.release_notes_excerpt)

    def test_same_version_returns_none(self) -> None:
        payload = _fake_payload(tag="7.6.0")
        with mock.patch.object(updater, "urlopen", return_value=_FakeResponse(payload)):
            info = check_for_updates("7.6.0", "foo/cinesort")
        self.assertIsNone(info)

    def test_older_remote_returns_none(self) -> None:
        payload = _fake_payload(tag="7.5.0")
        with mock.patch.object(updater, "urlopen", return_value=_FakeResponse(payload)):
            info = check_for_updates("7.6.0", "foo/cinesort")
        self.assertIsNone(info)

    def test_network_error_returns_none(self) -> None:
        with mock.patch.object(updater, "urlopen", side_effect=URLError("DNS fail")):
            info = check_for_updates("7.6.0", "foo/cinesort")
        self.assertIsNone(info)

    def test_404_returns_none(self) -> None:
        err = HTTPError(url="x", code=404, msg="Not Found", hdrs=None, fp=None)
        with mock.patch.object(updater, "urlopen", side_effect=err):
            info = check_for_updates("7.6.0", "foo/cinesort")
        self.assertIsNone(info)

    def test_500_returns_none(self) -> None:
        err = HTTPError(url="x", code=500, msg="Server Error", hdrs=None, fp=None)
        with mock.patch.object(updater, "urlopen", side_effect=err):
            info = check_for_updates("7.6.0", "foo/cinesort")
        self.assertIsNone(info)

    def test_cache_respected_within_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "update_cache.json"
            payload = _fake_payload(tag="7.7.0")
            # 1er appel : reseau touche, cache ecrit
            with mock.patch.object(updater, "urlopen", return_value=_FakeResponse(payload)) as m:
                info1 = check_for_updates("7.6.0", "foo/cinesort", cache_path=cache)
                self.assertEqual(m.call_count, 1)
            # 2e appel : sert depuis le cache, pas d'appel reseau
            with mock.patch.object(updater, "urlopen") as m:
                info2 = check_for_updates("7.6.0", "foo/cinesort", cache_path=cache)
                self.assertEqual(m.call_count, 0)
            self.assertEqual(info1, info2)
            self.assertTrue(cache.exists())

    def test_cache_expired_refetches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "update_cache.json"
            cache.write_text(
                json.dumps({"ts": time.time() - 9999, "payload": _fake_payload(tag="7.7.0")}),
                encoding="utf-8",
            )
            payload = _fake_payload(tag="7.8.0")
            with mock.patch.object(updater, "urlopen", return_value=_FakeResponse(payload)) as m:
                info = check_for_updates("7.6.0", "foo/cinesort", cache_path=cache)
                self.assertEqual(m.call_count, 1)
            assert info is not None
            self.assertEqual(info.latest_version, "7.8.0")

    def test_cache_corrupted_falls_back_to_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "update_cache.json"
            cache.write_text("not-json{{{", encoding="utf-8")
            payload = _fake_payload(tag="7.7.0")
            with mock.patch.object(updater, "urlopen", return_value=_FakeResponse(payload)):
                info = check_for_updates("7.6.0", "foo/cinesort", cache_path=cache)
            assert info is not None
            self.assertEqual(info.latest_version, "7.7.0")


class BuildUpdateInfoTests(unittest.TestCase):
    def test_picks_first_exe_asset(self) -> None:
        payload = _fake_payload(
            tag="7.7.0",
            assets=[
                {"name": "checksums.txt", "browser_download_url": "https://example.com/sums"},
                {"name": "CineSort_QA.zip", "browser_download_url": "https://example.com/zip"},
                {"name": "CineSort.exe", "browser_download_url": "https://example.com/exe"},
            ],
        )
        info = _build_update_info(payload, "7.6.0")
        assert info is not None
        self.assertEqual(info.download_url, "https://example.com/exe")

    def test_no_exe_asset_keeps_download_url_none(self) -> None:
        payload = _fake_payload(tag="7.7.0", assets=[{"name": "src.zip", "browser_download_url": "x"}])
        info = _build_update_info(payload, "7.6.0")
        assert info is not None
        self.assertIsNone(info.download_url)

    def test_release_notes_truncated_to_500(self) -> None:
        payload = _fake_payload(tag="7.7.0", body="a" * 1000)
        info = _build_update_info(payload, "7.6.0")
        assert info is not None
        self.assertEqual(len(info.release_notes_excerpt), 500)

    def test_missing_tag_returns_none(self) -> None:
        payload = _fake_payload(tag="")
        self.assertIsNone(_build_update_info(payload, "7.6.0"))


if __name__ == "__main__":
    unittest.main()
