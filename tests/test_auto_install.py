"""Tests unitaires pour cinesort.infra.probe.auto_install (mocks reseau)."""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from cinesort.infra.probe.auto_install import (
    IntegrityError,
    _assert_https,
    _find_in_zip,
    _resolve_expected_sha256,
    _sha256_file,
    _verify_archive,
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
        # get_tools_dir() fait tools_dir.mkdir(exist_ok=True) puis retourne :
        # le dossier DOIT exister apres l'appel (cf auto_install.py:169).
        self.assertTrue(d.exists(), "get_tools_dir() doit creer le dossier tools/")


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

    @patch("cinesort.infra.probe.auto_install._MAX_UNCOMPRESSED_BYTES", 4)
    @patch("cinesort.infra.probe.auto_install.urlretrieve")
    def test_rejects_oversized_entry(self, mock_urlretrieve):
        """Une entree dont la taille decompressee depasse le cap -> IntegrityError (anti zip-bomb)."""

        def fake_download(url, dest):
            with zipfile.ZipFile(dest, "w") as zf:
                zf.writestr("ffmpeg-7.1/bin/ffprobe.exe", b"way-too-large-payload")

        mock_urlretrieve.side_effect = fake_download

        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp) / "tools"
            tools.mkdir()
            with patch("cinesort.infra.probe.auto_install.get_tools_dir", return_value=tools):
                with self.assertRaises(IntegrityError):
                    install_ffprobe()
                self.assertFalse((tools / "ffprobe.exe").exists())


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


class TestSha256Verification(unittest.TestCase):
    """Tests VN-A.4 : verification SHA256 fail-closed des archives downloadees."""

    def test_sha256_file_known_vector(self):
        """_sha256_file calcule un hash conforme a hashlib.sha256."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            path = f.name
        try:
            expected = hashlib.sha256(b"hello world").hexdigest()
            self.assertEqual(_sha256_file(path), expected)
        finally:
            os.unlink(path)

    def test_assert_https_rejects_http(self):
        """_assert_https refuse les URLs en clair (defense en profondeur)."""
        with self.assertRaises(IntegrityError):
            _assert_https("http://evil.example.com/ffmpeg.zip")

    def test_assert_https_accepts_https(self):
        """HTTPS passe sans exception."""
        _assert_https("https://example.com/x.zip")  # no raise

    def test_verify_archive_no_pin_logs_warning(self):
        """Sans hash pin (None), _verify_archive ne leve PAS mais loggue un warning."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"some bytes")
            path = f.name
        try:
            # Pas d'exception attendue : retour silencieux + warning logge.
            _verify_archive(path, None, label="test.zip")
            self.assertTrue(os.path.exists(path))  # fichier intact
        finally:
            os.unlink(path)

    def test_verify_archive_match_ok(self):
        """SHA256 attendu == reel : pas d'exception, fichier preserve."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"payload")
            path = f.name
        try:
            expected = hashlib.sha256(b"payload").hexdigest()
            _verify_archive(path, expected, label="test.zip")
            self.assertTrue(os.path.exists(path))
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_resolve_expected_sha256_priority(self):
        """GATE AUDIT 2026-06-10 : permet d'epingler le SHA256 via variable d'env
        pour forcer le fail-closed sans modifier le code. Ordre : override kwarg
        > env var > constante module."""
        env = "CINESORT_TEST_SHA256_XYZ"
        # 1. override kwarg gagne sur tout
        with patch.dict(os.environ, {env: "from_env"}):
            self.assertEqual(_resolve_expected_sha256(env, "from_override", "from_const"), "from_override")
        # 2. sans override, la variable d'env gagne sur la constante
        with patch.dict(os.environ, {env: "from_env"}):
            self.assertEqual(_resolve_expected_sha256(env, None, "from_const"), "from_env")
        # 3. sans override ni env : constante module (None par defaut = unverified)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(env, None)
            self.assertEqual(_resolve_expected_sha256(env, None, "from_const"), "from_const")
            self.assertIsNone(_resolve_expected_sha256(env, None, None))
        # 4. env vide (espaces) ignore -> constante
        with patch.dict(os.environ, {env: "   "}):
            self.assertEqual(_resolve_expected_sha256(env, None, "from_const"), "from_const")

    def test_verify_archive_mismatch_fails_closed(self):
        """SHA256 mismatch : IntegrityError + suppression du fichier suspect (fail-closed)."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"payload-modified-by-mitm")
            path = f.name
        try:
            wrong = "0" * 64
            with self.assertRaises(IntegrityError) as ctx:
                _verify_archive(path, wrong, label="test.zip")
            self.assertIn("SHA256 mismatch", str(ctx.exception))
            # Fail-closed : fichier supprime pour empecher reuse accidentel.
            self.assertFalse(os.path.exists(path))
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_verify_archive_case_insensitive_hash(self):
        """Le hash attendu est normalise (lowercase + strip) avant comparaison."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x")
            path = f.name
        try:
            expected_upper = hashlib.sha256(b"x").hexdigest().upper()
            # Doit pas lever : normalisation case-insensitive.
            _verify_archive(path, "  " + expected_upper + "  ", label="test.zip")
        finally:
            if os.path.exists(path):
                os.unlink(path)

    @patch("cinesort.infra.probe.auto_install.urlretrieve")
    def test_install_ffprobe_rejects_bad_hash(self, mock_urlretrieve):
        """install_ffprobe(expected_sha256=...) avec mismatch -> IntegrityError."""
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp) / "tools"
            tools.mkdir()

            def fake_download(url, dest):
                with zipfile.ZipFile(dest, "w") as zf:
                    zf.writestr("ffmpeg-7.1/bin/ffprobe.exe", b"tampered")

            mock_urlretrieve.side_effect = fake_download

            with patch("cinesort.infra.probe.auto_install.get_tools_dir", return_value=tools):
                with self.assertRaises(IntegrityError):
                    install_ffprobe(expected_sha256="0" * 64)
                # Aucun binaire ne doit avoir ete extrait apres mismatch.
                self.assertFalse((tools / "ffprobe.exe").exists())


if __name__ == "__main__":
    unittest.main()
