"""Tests unitaires pour cinesort.infra.probe.auto_install (mocks reseau).

Couvre le contrat du module : empreinte SHA256 obligatoire (#466, CWE-494) et
bornes de decompression (#734, CWE-409). Le comportement de bout en bout, via
la facade de production, est verifie dans
`tests/test_probe_auto_install_supply_chain.py`.
"""

from __future__ import annotations

import hashlib
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Callable, Dict, Optional
from unittest.mock import MagicMock, patch

import cinesort.infra.probe.auto_install as auto_install
from cinesort.infra.probe.auto_install import (
    EXPECTED_SHA256_FFMPEG,
    EXPECTED_SHA256_MEDIAINFO,
    FFMPEG_URL,
    MEDIAINFO_URL,
    IntegrityError,
    _assert_https,
    _bounded_reporthook,
    _check_archive_shape,
    _download_bounded,
    _extract_member,
    _ExtractBudget,
    _find_in_zip,
    _resolve_expected_sha256,
    _sha256_file,
    _verify_archive,
    get_tools_dir,
    install_all,
    install_ffprobe,
    install_mediainfo,
)


def _zip_bytes(entries: Dict[str, bytes]) -> bytes:
    """Construit une archive ZIP en memoire et retourne ses octets exacts."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries.items():
            zf.writestr(name, payload)
    return buf.getvalue()


def _zip_with_lying_uncompressed_size(name: str, payload: bytes, declared: int) -> bytes:
    """ZIP dont l'en-tete ANNONCE `declared` octets alors que le flux en contient bien plus.

    `ZipInfo.file_size` est une valeur d'en-tete, donc controlee par
    l'attaquant : ce cas sert a verifier que la borne tient meme quand elle
    ment.
    """
    raw = bytearray(_zip_bytes({name: payload}))
    true_size = len(payload).to_bytes(4, "little")
    fake_size = int(declared).to_bytes(4, "little")
    # Local file header (PK\x03\x04) : taille non compressee a l'offset +22.
    lfh = raw.find(b"PK\x03\x04")
    if raw[lfh + 22 : lfh + 26] != true_size:
        raise AssertionError("structure ZIP inattendue (local file header)")
    raw[lfh + 22 : lfh + 26] = fake_size
    # Central directory (PK\x01\x02) : taille non compressee a l'offset +24.
    cd = raw.find(b"PK\x01\x02")
    if raw[cd + 24 : cd + 28] != true_size:
        raise AssertionError("structure ZIP inattendue (central directory)")
    raw[cd + 24 : cd + 28] = fake_size
    return bytes(raw)


def _transport(payload: bytes) -> Callable[..., None]:
    """Faux urlretrieve respectant le contrat urllib (reporthook inclus)."""

    def _download(url: str, dest: str, reporthook: Optional[Callable[[int, int, int], None]] = None) -> None:
        block = 8192
        if reporthook is not None:
            reporthook(0, block, len(payload))
        with open(dest, "wb") as out:
            written = 0
            blocknum = 0
            while written < len(payload):
                chunk = payload[written : written + block]
                out.write(chunk)
                written += len(chunk)
                blocknum += 1
                if reporthook is not None:
                    reporthook(blocknum, block, len(payload))

    return _download


class TestGetToolsDir(unittest.TestCase):
    """Tests pour get_tools_dir."""

    def test_returns_path(self):
        d = get_tools_dir()
        self.assertIsInstance(d, Path)
        self.assertTrue(d.name == "tools")

    def test_creates_dir(self):
        d = get_tools_dir()
        # get_tools_dir() fait tools_dir.mkdir(exist_ok=True) puis retourne :
        # le dossier DOIT exister apres l'appel.
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
        """Simule le telechargement et l'extraction d'une archive conforme a l'empreinte attendue."""
        archive = _zip_bytes(
            {
                "ffmpeg-7.1/bin/ffprobe.exe": b"ffprobe-binary",
                "ffmpeg-7.1/bin/ffmpeg.exe": b"ffmpeg-binary",
            }
        )
        mock_urlretrieve.side_effect = _transport(archive)
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp) / "tools"
            tools.mkdir()
            with patch("cinesort.infra.probe.auto_install.get_tools_dir", return_value=tools):
                cb = MagicMock()
                result = install_ffprobe(progress_callback=cb, expected_sha256=hashlib.sha256(archive).hexdigest())
                self.assertTrue(result.endswith("ffprobe.exe"))
                self.assertTrue((tools / "ffprobe.exe").exists())
                self.assertTrue((tools / "ffmpeg.exe").exists())
                self.assertEqual((tools / "ffprobe.exe").read_bytes(), b"ffprobe-binary")
                self.assertEqual((tools / "ffmpeg.exe").read_bytes(), b"ffmpeg-binary")
                cb.assert_called()

    @patch("cinesort.infra.probe.auto_install.urlretrieve")
    def test_raises_if_exe_not_in_zip(self, mock_urlretrieve):
        """Leve FileNotFoundError si ffprobe.exe absent du ZIP (archive pourtant conforme)."""
        archive = _zip_bytes({"readme.txt": b"nothing"})
        mock_urlretrieve.side_effect = _transport(archive)
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp) / "tools"
            tools.mkdir()
            with patch("cinesort.infra.probe.auto_install.get_tools_dir", return_value=tools):
                with self.assertRaises(FileNotFoundError):
                    install_ffprobe(expected_sha256=hashlib.sha256(archive).hexdigest())


class TestInstallMediainfo(unittest.TestCase):
    """Tests pour install_mediainfo (mock urlretrieve)."""

    @patch("cinesort.infra.probe.auto_install.urlretrieve")
    def test_downloads_and_extracts(self, mock_urlretrieve):
        archive = _zip_bytes({"MediaInfo.exe": b"mi-binary"})
        mock_urlretrieve.side_effect = _transport(archive)
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp) / "tools"
            tools.mkdir()
            with patch("cinesort.infra.probe.auto_install.get_tools_dir", return_value=tools):
                result = install_mediainfo(expected_sha256=hashlib.sha256(archive).hexdigest())
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

    @patch("cinesort.infra.probe.auto_install.install_mediainfo")
    @patch("cinesort.infra.probe.auto_install.install_ffprobe")
    def test_integrity_error_is_reported_not_swallowed(self, mock_ff, mock_mi):
        """Un refus d'integrite doit remonter dans errors, jamais devenir un succes silencieux."""
        mock_ff.side_effect = IntegrityError("SHA256 mismatch pour ffmpeg.zip")
        mock_mi.side_effect = IntegrityError("SHA256 mismatch pour mediainfo.zip")
        result = install_all()
        self.assertEqual(result["installed"], {})
        self.assertEqual(len(result["errors"]), 2)
        self.assertIn("SHA256 mismatch", result["errors"][0])


class TestSha256Verification(unittest.TestCase):
    """Verification SHA256 fail-closed des archives telechargees (#466)."""

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

    def test_verify_archive_without_pin_fails_closed(self):
        """#466 — sans empreinte de reference, _verify_archive REFUSE et efface l'archive.

        Comportement anterieur (le defaut) : un simple `logger.warning` puis
        `return`. La verification existait mais ne verifiait rien.
        """
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"some bytes")
            path = f.name
        try:
            with self.assertRaises(IntegrityError) as ctx:
                _verify_archive(path, None, label="test.zip")
            self.assertFalse(os.path.exists(path), "l'archive non verifiable doit etre effacee")
            message = str(ctx.exception)
            self.assertIn("refusee", message.lower())
            # Le message doit rester actionnable : degradation + alternatives.
            self.assertIn("winget", message)
            self.assertIn("Parametres > Outils externes", message)
        finally:
            if os.path.exists(path):
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
        """Ordre de resolution : override kwarg > variable d'env > constante module."""
        env = "CINESORT_TEST_SHA256_XYZ"
        from_env = "a" * 64
        from_override = "b" * 64
        from_const = "c" * 64
        # 1. override kwarg gagne sur tout
        with patch.dict(os.environ, {env: from_env}):
            self.assertEqual(_resolve_expected_sha256(env, from_override, from_const), from_override)
        # 2. sans override, la variable d'env gagne sur la constante
        with patch.dict(os.environ, {env: from_env}):
            self.assertEqual(_resolve_expected_sha256(env, None, from_const), from_env)
        # 3. sans override ni env : constante module
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(env, None)
            self.assertEqual(_resolve_expected_sha256(env, None, from_const), from_const)
            self.assertIsNone(_resolve_expected_sha256(env, None, None))
        # 4. env vide (espaces) ignore -> constante
        with patch.dict(os.environ, {env: "   "}):
            self.assertEqual(_resolve_expected_sha256(env, None, from_const), from_const)
        # 5. normalisation : majuscules et espaces autour
        with patch.dict(os.environ, {env: "  " + ("A" * 64) + "  "}):
            self.assertEqual(_resolve_expected_sha256(env, None, from_const), "a" * 64)

    def test_resolve_expected_sha256_rejects_malformed_value(self):
        """Une empreinte mal formee est REFUSEE, jamais ignoree au profit d'une autre source.

        Sinon une coquille dans la variable d'environnement retomberait
        silencieusement sur la constante que l'operateur croyait remplacer.
        """
        env = "CINESORT_TEST_SHA256_BADFMT"
        good = "d" * 64
        for bad in ("pas-un-hash", "z" * 64, "abc123", "a" * 63, "a" * 65):
            with patch.dict(os.environ, {env: bad}):
                with self.assertRaises(IntegrityError, msg=f"valeur acceptee a tort : {bad!r}"):
                    _resolve_expected_sha256(env, None, good)

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
        mock_urlretrieve.side_effect = _transport(_zip_bytes({"ffmpeg-7.1/bin/ffprobe.exe": b"tampered"}))
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp) / "tools"
            tools.mkdir()
            with patch("cinesort.infra.probe.auto_install.get_tools_dir", return_value=tools):
                with self.assertRaises(IntegrityError):
                    install_ffprobe(expected_sha256="0" * 64)
                # Aucun binaire ne doit avoir ete extrait apres mismatch.
                self.assertFalse((tools / "ffprobe.exe").exists())

    @patch("cinesort.infra.probe.auto_install.urlretrieve")
    def test_install_without_any_pin_refuses_before_download(self, mock_urlretrieve):
        """#466 — sans empreinte disponible, on refuse AVANT de tirer l'archive."""
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp) / "tools"
            tools.mkdir()
            with (
                patch("cinesort.infra.probe.auto_install.get_tools_dir", return_value=tools),
                patch.object(auto_install, "EXPECTED_SHA256_FFMPEG", None),
                patch.object(auto_install, "EXPECTED_SHA256_MEDIAINFO", None),
                patch.dict(os.environ, {}, clear=False),
            ):
                os.environ.pop(auto_install._ENV_SHA256_FFMPEG, None)
                os.environ.pop(auto_install._ENV_SHA256_MEDIAINFO, None)
                with self.assertRaises(IntegrityError):
                    install_ffprobe()
                with self.assertRaises(IntegrityError):
                    install_mediainfo()
            self.assertEqual(mock_urlretrieve.call_count, 0)
            self.assertEqual(sorted(p.name for p in tools.iterdir()), [])


class TestPinnedConstants(unittest.TestCase):
    """Invariant structurel : toute source telechargee est epinglee et en HTTPS.

    Empeche la regression exacte de #466 : ajouter (ou reactiver) une URL sans
    empreinte, ce qui remettrait l'installation en fail-open.
    """

    def test_every_download_url_is_https_and_versioned(self):
        for url in (FFMPEG_URL, MEDIAINFO_URL):
            self.assertTrue(url.startswith("https://"), url)
        self.assertIn(auto_install.FFMPEG_VERSION, FFMPEG_URL)
        self.assertIn(auto_install.MEDIAINFO_VERSION, MEDIAINFO_URL)

    def test_every_expected_sha256_is_pinned_and_well_formed(self):
        for name, value in (
            ("EXPECTED_SHA256_FFMPEG", EXPECTED_SHA256_FFMPEG),
            ("EXPECTED_SHA256_MEDIAINFO", EXPECTED_SHA256_MEDIAINFO),
        ):
            self.assertIsNotNone(value, f"{name} doit etre epinglee (sinon install fail-closed permanent)")
            self.assertRegex(str(value), r"^[0-9a-f]{64}$", name)

    def test_caps_are_ordered_and_plausible(self):
        """Les plafonds gardent une marge sur le reel mesure sans permettre un OOM."""
        self.assertLessEqual(auto_install._MAX_ARCHIVE_BYTES, 512 * 1024 * 1024)
        self.assertLessEqual(auto_install._MAX_MEMBER_UNCOMPRESSED_BYTES, 512 * 1024 * 1024)
        self.assertLessEqual(auto_install._MAX_EXTRACTED_BYTES_PER_INSTALL, 1024 * 1024 * 1024)
        self.assertLessEqual(auto_install._MAX_TOTAL_UNCOMPRESSED_BYTES, 2 * 1024 * 1024 * 1024)
        # ffmpeg essentials 8.1.2 : 104.6 Mio telecharges, 194.2 Mio extraits.
        self.assertGreater(auto_install._MAX_ARCHIVE_BYTES, 110_000_000)
        self.assertGreater(auto_install._MAX_EXTRACTED_BYTES_PER_INSTALL, 204_000_000)
        # La borne cumulee doit rester ATTEIGNABLE : l'installation extrait au
        # plus deux membres, donc un plafond >= 2 x le plafond par membre ne se
        # declencherait jamais et ne serait qu'un decor.
        self.assertLess(
            auto_install._MAX_EXTRACTED_BYTES_PER_INSTALL,
            2 * auto_install._MAX_MEMBER_UNCOMPRESSED_BYTES,
        )


class TestDownloadBounds(unittest.TestCase):
    """Bornage du telechargement (#734, volet reseau)."""

    def test_reporthook_refuses_announced_oversize(self):
        hook = _bounded_reporthook("ffmpeg.zip")
        with self.assertRaises(IntegrityError) as ctx:
            hook(0, 8192, auto_install._MAX_ARCHIVE_BYTES + 1)
        self.assertIn("taille annoncee", str(ctx.exception))

    def test_reporthook_aborts_when_received_exceeds_cap(self):
        """Taille non annoncee (-1) : la coupure vient du volume reellement recu."""
        hook = _bounded_reporthook("ffmpeg.zip")
        hook(1, 8192, -1)  # sous le plafond : ne leve pas
        blocks = auto_install._MAX_ARCHIVE_BYTES // 8192 + 2
        with self.assertRaises(IntegrityError) as ctx:
            hook(blocks, 8192, -1)
        self.assertIn("interrompu", str(ctx.exception))

    @patch("cinesort.infra.probe.auto_install.urlretrieve")
    def test_download_bounded_rejects_oversize_file_even_without_reporthook(self, mock_urlretrieve):
        """Second verrou : un transport qui n'appelle pas le hook est rattrape apres coup."""

        def _silent_transport(url, dest, reporthook=None):
            with open(dest, "wb") as out:
                out.write(b"\0" * (auto_install._MAX_ARCHIVE_BYTES + 1))

        mock_urlretrieve.side_effect = _silent_transport
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "big.zip")
            with patch.object(auto_install, "_MAX_ARCHIVE_BYTES", 4096):
                with self.assertRaises(IntegrityError) as ctx:
                    _download_bounded("https://example.com/x.zip", dest, label="x.zip")
            self.assertIn("trop volumineuse", str(ctx.exception))
            self.assertFalse(os.path.exists(dest), "l'archive hors plafond doit etre effacee")

    @patch("cinesort.infra.probe.auto_install.urlretrieve")
    def test_download_bounded_refuses_non_https(self, mock_urlretrieve):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(IntegrityError):
                _download_bounded("http://example.com/x.zip", os.path.join(tmp, "x.zip"), label="x.zip")
        self.assertEqual(mock_urlretrieve.call_count, 0)


class TestArchiveShapeBounds(unittest.TestCase):
    """Bornes structurelles de l'archive (#734)."""

    def test_rejects_too_many_entries(self):
        payload = _zip_bytes({f"f{i}.txt": b"x" for i in range(40)})
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            with patch.object(auto_install, "_MAX_ZIP_ENTRIES", 10):
                with self.assertRaises(IntegrityError) as ctx:
                    _check_archive_shape(zf, label="x.zip")
            self.assertIn("entrees", str(ctx.exception))

    def test_rejects_cumulative_uncompressed_size(self):
        """La borne porte sur le CUMUL, pas sur la plus grosse entree."""
        payload = _zip_bytes({f"f{i}.bin": b"\0" * 100_000 for i in range(10)})
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            with patch.object(auto_install, "_MAX_TOTAL_UNCOMPRESSED_BYTES", 250_000):
                with self.assertRaises(IntegrityError) as ctx:
                    _check_archive_shape(zf, label="x.zip")
            self.assertIn("cumulee", str(ctx.exception))
            # Chaque entree prise isolement passe largement sous le plafond.
            with patch.object(auto_install, "_MAX_TOTAL_UNCOMPRESSED_BYTES", 2_000_000):
                _check_archive_shape(zf, label="x.zip")

    def test_accepts_realistic_shape(self):
        payload = _zip_bytes({"bin/ffprobe.exe": b"\0" * 1024, "doc/readme.txt": b"hi"})
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            _check_archive_shape(zf, label="x.zip")  # no raise


class TestExtractBounds(unittest.TestCase):
    """Extraction bornee, streaming, sans binaire tronque (#734)."""

    def test_rejects_member_declared_over_cap(self):
        payload = _zip_bytes({"bin/ffprobe.exe": b"\0" * 200_000})
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "ffprobe.exe"
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                with patch.object(auto_install, "_MAX_MEMBER_UNCOMPRESSED_BYTES", 50_000):
                    with self.assertRaises(IntegrityError) as ctx:
                        _extract_member(
                            zf,
                            "bin/ffprobe.exe",
                            dest,
                            budget=_ExtractBudget(10**9),
                            label="x.zip",
                        )
            self.assertIn("taille declaree", str(ctx.exception))
            self.assertFalse(dest.exists())
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), [])

    def test_cumulative_budget_aborts_during_copy(self):
        """Chaque membre passe seul, mais leur CUMUL depasse : abandon en cours de copie."""
        payload = _zip_bytes({"a.exe": b"\0" * 1_000_000, "b.exe": b"\0" * 1_000_000})
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "a.exe"
            second = Path(tmp) / "b.exe"
            budget = _ExtractBudget(1_500_000)
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                _extract_member(zf, "a.exe", first, budget=budget, label="x.zip")
                self.assertEqual(first.stat().st_size, 1_000_000)
                with self.assertRaises(IntegrityError) as ctx:
                    _extract_member(zf, "b.exe", second, budget=budget, label="x.zip")
            self.assertIn("Decompression abandonnee", str(ctx.exception))
            self.assertFalse(second.exists(), "aucun binaire tronque au chemin final")
            self.assertFalse((Path(tmp) / "b.exe.part").exists(), "aucun residu .part")

    def test_aborts_when_zip_header_lies_about_size(self):
        """En-tete mensonger (annonce 1 Ko, flux de 8 Mio) : rien n'est ecrit.

        `ZipInfo.file_size` est ecrit par l'attaquant. Le contrat verifie ici est
        celui qui compte pour l'utilisateur : l'extraction echoue et ne laisse ni
        binaire au chemin final, ni residu `.part` qui pourrait etre pris pour un
        outil installe puis EXECUTE.
        """
        payload = _zip_with_lying_uncompressed_size("bin/ffprobe.exe", b"\0" * (8 * 1024 * 1024), declared=1024)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "ffprobe.exe"
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                self.assertEqual(zf.getinfo("bin/ffprobe.exe").file_size, 1024)
                with self.assertRaises((IntegrityError, zipfile.BadZipFile)):
                    _extract_member(
                        zf,
                        "bin/ffprobe.exe",
                        dest,
                        budget=_ExtractBudget(10**9),
                        label="x.zip",
                    )
            self.assertFalse(dest.exists())
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), [])

    def test_extract_member_writes_exact_content(self):
        payload = _zip_bytes({"bin/ffprobe.exe": b"exact-bytes"})
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "ffprobe.exe"
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                _extract_member(zf, "bin/ffprobe.exe", dest, budget=_ExtractBudget(10**9), label="x.zip")
            self.assertEqual(dest.read_bytes(), b"exact-bytes")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["ffprobe.exe"])

    def test_budget_raises_exactly_at_overflow(self):
        budget = _ExtractBudget(10)
        budget.consume(10, label="x.zip")  # pile au plafond : accepte
        with self.assertRaises(IntegrityError):
            budget.consume(1, label="x.zip")


if __name__ == "__main__":
    unittest.main()
