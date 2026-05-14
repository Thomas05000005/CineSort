"""Tests pour les fixes securite #69 CORS, #70 SSRF, #71 validate_tool_path."""

from __future__ import annotations

import unittest
from pathlib import Path

from cinesort.infra.jellyfin_client import JellyfinError
from cinesort.infra.network_utils import is_safe_external_url
from cinesort.infra.plex_client import PlexError
from cinesort.infra.radarr_client import RadarrError


class IsSafeExternalUrlTests(unittest.TestCase):
    """Issue #70 : helper is_safe_external_url."""

    def test_http_jellyfin_localhost_ok(self) -> None:
        ok, _reason = is_safe_external_url("http://localhost:8096")
        self.assertTrue(ok)

    def test_http_jellyfin_lan_ok(self) -> None:
        ok, _ = is_safe_external_url("http://192.168.1.50:8096")
        self.assertTrue(ok)

    def test_https_external_ok(self) -> None:
        ok, _ = is_safe_external_url("https://jellyfin.example.com")
        self.assertTrue(ok)

    def test_aws_metadata_blocked(self) -> None:
        ok, reason = is_safe_external_url("http://169.254.169.254/latest/meta-data/")
        self.assertFalse(ok)
        lr = reason.lower()
        self.assertTrue("metadata" in lr or "link-local" in lr, f"reason inattendu: {reason}")

    def test_gcp_metadata_blocked(self) -> None:
        ok, reason = is_safe_external_url("http://metadata.google.internal/computeMetadata/v1/")
        self.assertFalse(ok)
        self.assertIn("metadata", reason.lower())

    def test_link_local_169_254_blocked(self) -> None:
        ok, _ = is_safe_external_url("http://169.254.1.1/")
        self.assertFalse(ok)

    def test_file_scheme_blocked(self) -> None:
        ok, reason = is_safe_external_url("file:///etc/passwd")
        self.assertFalse(ok)
        self.assertIn("scheme", reason.lower())

    def test_ftp_scheme_blocked(self) -> None:
        ok, _ = is_safe_external_url("ftp://internal.corp/files")
        self.assertFalse(ok)

    def test_empty_url_rejected(self) -> None:
        ok, _ = is_safe_external_url("")
        self.assertFalse(ok)


class JellyfinUrlValidationTests(unittest.TestCase):
    """Issue #70 : JellyfinClient refuse les URLs metadata cloud."""

    def test_normalize_blocks_aws_metadata(self) -> None:
        from cinesort.infra.jellyfin_client import _normalize_url

        with self.assertRaises(JellyfinError):
            _normalize_url("http://169.254.169.254/")

    def test_normalize_blocks_file_scheme(self) -> None:
        from cinesort.infra.jellyfin_client import _normalize_url

        with self.assertRaises(JellyfinError):
            _normalize_url("file:///etc/passwd")

    def test_normalize_allows_lan(self) -> None:
        from cinesort.infra.jellyfin_client import _normalize_url

        self.assertEqual(_normalize_url("http://192.168.1.50:8096"), "http://192.168.1.50:8096")


class PlexUrlValidationTests(unittest.TestCase):
    def test_normalize_blocks_metadata(self) -> None:
        from cinesort.infra.plex_client import _normalize_url

        with self.assertRaises(PlexError):
            _normalize_url("http://metadata.google.internal/")

    def test_normalize_allows_localhost(self) -> None:
        from cinesort.infra.plex_client import _normalize_url

        self.assertEqual(_normalize_url("http://localhost:32400"), "http://localhost:32400")


class RadarrUrlValidationTests(unittest.TestCase):
    def test_normalize_blocks_link_local(self) -> None:
        from cinesort.infra.radarr_client import _normalize_url

        with self.assertRaises(RadarrError):
            _normalize_url("http://169.254.1.2:7878")

    def test_normalize_allows_https(self) -> None:
        from cinesort.infra.radarr_client import _normalize_url

        self.assertEqual(_normalize_url("https://radarr.example.com"), "https://radarr.example.com")


class ValidateToolPathBinaryNameTests(unittest.TestCase):
    """Issue #71 : validate_tool_path doit refuser un binaire au mauvais nom."""

    def test_validate_rejects_wrong_binary_name(self) -> None:
        """Si on pointe ffprobe vers calc.exe, validate_tool_path doit refuser."""
        from cinesort.infra.probe.tools_manager import validate_tool_path

        # Cree un faux executable au mauvais nom
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "calc.exe"
            fake.write_bytes(b"\x4dZ")  # fake PE header
            result = validate_tool_path(
                tool_name="ffprobe",
                tool_path=str(fake),
                state_dir=Path(tmp),
            )
            self.assertFalse(result["ok"])
            self.assertIn("invalide", result["message"].lower())

    def test_validate_rejects_arbitrary_exe(self) -> None:
        from cinesort.infra.probe.tools_manager import validate_tool_path

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "malware.exe"
            fake.write_bytes(b"\x4dZ")
            result = validate_tool_path(
                tool_name="ffprobe",
                tool_path=str(fake),
                state_dir=Path(tmp),
            )
            self.assertFalse(result["ok"])


class CorsHeaderTests(unittest.TestCase):
    """Issue #69 : Vary: Origin et pas de Credentials."""

    def test_send_cors_headers_with_specific_origin_adds_vary(self) -> None:
        """Quand cors_origin != *, le handler doit ajouter Vary: Origin."""
        # Inspection statique : verifier que le code source contient Vary
        src = (Path(__file__).resolve().parents[1] / "cinesort" / "infra" / "rest_server.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"Vary"', src)
        # Verifier qu'on n'envoie PAS le header Allow-Credentials (incompatible
        # avec "*"). On cherche l'appel send_header explicite, pas la mention
        # textuelle dans un commentaire de doc.
        self.assertNotIn('send_header("Access-Control-Allow-Credentials"', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
