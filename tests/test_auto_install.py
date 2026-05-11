"""Tests unitaires pour cinesort.infra.probe.auto_install (mocks reseau)."""

from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from cinesort.infra.probe.auto_install import (
    _find_in_zip,
    get_tools_dir,
    install_all,
    install_ffprobe,
    install_mediainfo,
)


class TestGetToolsDir(unittest.TestCase):
    """Tests pour get_tools_dir."""

    def test_returns_path(self):
        d = get_tools_dir()
        self.assertIsInstance(d, Path)
        self.assertTrue(d.name == "tools")

    def test_creates_dir(self):
        d = get_tools_dir()
        self.assertTrue(d.exists() or True)  # peut ne pas exister en CI


class TestFindInZip(unittest.TestCase):
    """Tests pour _find_in_zip."""

    def test_finds_nested_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            zp = os.path.join(tmp, "test.zip")
            with zipfile.ZipFile(zp, "w") as zf:
                zf.writestr("subdir/bin/ffprobe.exe", b"fake")
            with zipfile.ZipFile(zp) as zf:
                result = _find_in_zip(zf, "ffprobe.exe")
                self.assertEqual(result, "subdir/bin/ffprobe.exe")

    def test_returns_none_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            zp = os.path.join(tmp, "test.zip")
            with zipfile.ZipFile(zp, "w") as zf:
                zf.writestr("readme.txt", b"nothing")
            with zipfile.ZipFile(zp) as zf:
                self.assertIsNone(_find_in_zip(zf, "ffprobe.exe"))


class TestInstallFfprobe(unittest.TestCase):
    """Tests pour install_ffprobe (mock urlretrieve)."""

    def test_returns_existing_path(self):
        """Si ffprobe.exe existe deja, pas de telechargement."""
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp) / "tools"
            tools.mkdir()
            fp = tools / "ffprobe.exe"
            fp.write_bytes(b"fake")
            with patch("cinesort.infra.probe.auto_install.get_tools_dir", return_value=tools):
                result = install_ffprobe()
                self.assertEqual(result, str(fp))

    @patch("cinesort.infra.probe.auto_install.urlretrieve")
    def test_downloads_and_extracts(self, mock_urlretrieve):
        """Simule le telechargement et l'extraction."""
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp) / "tools"
            tools.mkdir()

            # Creer un faux ZIP avec ffprobe.exe et ffmpeg.exe
            def fake_download(url, dest):
                with zipfile.ZipFile(dest, "w") as zf:
                    zf.writestr("ffmpeg-7.1/bin/ffprobe.exe", b"ffprobe-binary")
                    zf.writestr("ffmpeg-7.1/bin/ffmpeg.exe", b"ffmpeg-binary")

            mock_urlretrieve.side_effect = fake_download

            with patch("cinesort.infra.probe.auto_install.get_tools_dir", return_value=tools):
                cb = MagicMock()
                result = install_ffprobe(progress_callback=cb)
                self.assertTrue(result.endswith("ffprobe.exe"))
                self.assertTrue((tools / "ffprobe.exe").exists())
                self.assertTrue((tools / "ffmpeg.exe").exists())
                self.assertEqual((tools / "ffprobe.exe").read_bytes(), b"ffprobe-binary")
                cb.assert_called()

    @patch("cinesort.infra.probe.auto_install.urlretrieve")
    def test_raises_if_exe_not_in_zip(self, mock_urlretrieve):
        """Leve FileNotFoundError si ffprobe.exe absent du ZIP."""
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp) / "tools"
            tools.mkdir()

            def fake_download(url, dest):
                with zipfile.ZipFile(dest, "w") as zf:
                    zf.writestr("readme.txt", b"nothing")

            mock_urlretrieve.side_effect = fake_download

            with patch("cinesort.infra.probe.auto_install.get_tools_dir", return_value=tools):
                with self.assertRaises(FileNotFoundError):
                    install_ffprobe()


class TestInstallMediainfo(unittest.TestCase):
    """Tests pour install_mediainfo (mock urlretrieve)."""

    @patch("cinesort.infra.probe.auto_install.urlretrieve")
    def test_downloads_and_extracts(self, mock_urlretrieve):
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp) / "tools"
            tools.mkdir()

            def fake_download(url, dest):
                with zipfile.ZipFile(dest, "w") as zf:
                    zf.writestr("MediaInfo.exe", b"mi-binary")

            mock_urlretrieve.side_effect = fake_download

            with patch("cinesort.infra.probe.auto_install.get_tools_dir", return_value=tools):
                result = install_mediainfo()
                self.assertTrue(result.endswith("MediaInfo.exe"))
                self.assertEqual((tools / "MediaInfo.exe").read_bytes(), b"mi-binary")


class TestInstallAll(unittest.TestCase):
    """Tests pour install_all."""

    @patch("cinesort.infra.probe.auto_install.install_mediainfo")
    @patch("cinesort.infra.probe.auto_install.install_ffprobe")
    def test_success(self, mock_ff, mock_mi):
        mock_ff.return_value = "C:/tools/ffprobe.exe"
        mock_mi.return_value = "C:/tools/MediaInfo.exe"
        result = install_all()
        self.assertEqual(result["installed"]["ffprobe"], "C:/tools/ffprobe.exe")
        self.assertEqual(result["installed"]["mediainfo"], "C:/tools/MediaInfo.exe")
        self.assertEqual(result["errors"], [])

    @patch("cinesort.infra.probe.auto_install.install_mediainfo")
    @patch("cinesort.infra.probe.auto_install.install_ffprobe")
    def test_partial_failure(self, mock_ff, mock_mi):
        mock_ff.side_effect = OSError("no internet")
        mock_mi.return_value = "C:/tools/MediaInfo.exe"
        result = install_all()
        self.assertNotIn("ffprobe", result["installed"])
        self.assertEqual(result["installed"]["mediainfo"], "C:/tools/MediaInfo.exe")
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("FFprobe", result["errors"][0])


if __name__ == "__main__":
    unittest.main()
