"""Tests verification integrite fichiers — cinesort/domain/integrity_check.py.

Couvre :
- check_header : MKV, MP4, AVI, TS (3 sync bytes), WMV valides
- Header invalide : mauvais magic bytes
- Fichier vide, fichier trop petit
- Extension inconnue → skip silencieux
- IOError / fichier inexistant
- UI : badges presents, CSS classes
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cinesort.domain.integrity_check import check_header


def _write_tmp(data: bytes, suffix: str) -> Path:
    """Ecrit des donnees dans un fichier temporaire et retourne le Path."""
    f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    f.write(data)
    f.close()
    return Path(f.name)


# --- Magic bytes de reference pour les tests ---
_MKV_HEADER = bytes([0x1A, 0x45, 0xDF, 0xA3]) + b"\x00" * 100
_MP4_HEADER = b"\x00\x00\x00\x20" + b"ftypisom" + b"\x00" * 100
_AVI_HEADER = b"RIFF" + b"\x00\x00\x00\x00" + b"AVI " + b"\x00" * 100
_TS_HEADER = bytes([0x47]) + b"\x00" * 187 + bytes([0x47]) + b"\x00" * 187 + bytes([0x47]) + b"\x00" * 100
_WMV_HEADER = bytes([0x30, 0x26, 0xB2, 0x75, 0x8E, 0x66, 0xCF, 0x11]) + b"\x00" * 100


class MkvHeaderTests(unittest.TestCase):
    """MKV : EBML header valide."""

    def test_valid_mkv(self) -> None:
        p = _write_tmp(_MKV_HEADER, ".mkv")
        try:
            valid, detail = check_header(p)
            self.assertTrue(valid)
            self.assertEqual(detail, "ok")
        finally:
            p.unlink(missing_ok=True)

    def test_valid_webm(self) -> None:
        p = _write_tmp(_MKV_HEADER, ".webm")
        try:
            valid, detail = check_header(p)
            self.assertTrue(valid)
        finally:
            p.unlink(missing_ok=True)

    def test_invalid_mkv(self) -> None:
        p = _write_tmp(b"\x00\x00\x00\x00" + b"\x00" * 100, ".mkv")
        try:
            valid, detail = check_header(p)
            self.assertFalse(valid)
            self.assertEqual(detail, "header_mismatch")
        finally:
            p.unlink(missing_ok=True)


class Mp4HeaderTests(unittest.TestCase):
    """MP4/MOV : ftyp a l'offset 4."""

    def test_valid_mp4(self) -> None:
        p = _write_tmp(_MP4_HEADER, ".mp4")
        try:
            valid, detail = check_header(p)
            self.assertTrue(valid)
            self.assertEqual(detail, "ok")
        finally:
            p.unlink(missing_ok=True)

    def test_valid_mov(self) -> None:
        p = _write_tmp(_MP4_HEADER, ".mov")
        try:
            valid, detail = check_header(p)
            self.assertTrue(valid)
        finally:
            p.unlink(missing_ok=True)

    def test_invalid_mp4(self) -> None:
        p = _write_tmp(b"\x00" * 100, ".mp4")
        try:
            valid, detail = check_header(p)
            self.assertFalse(valid)
            self.assertEqual(detail, "header_mismatch")
        finally:
            p.unlink(missing_ok=True)


class AviHeaderTests(unittest.TestCase):
    """AVI : RIFF + AVI."""

    def test_valid_avi(self) -> None:
        p = _write_tmp(_AVI_HEADER, ".avi")
        try:
            valid, detail = check_header(p)
            self.assertTrue(valid)
            self.assertEqual(detail, "ok")
        finally:
            p.unlink(missing_ok=True)

    def test_invalid_avi_bad_riff(self) -> None:
        data = b"XXXX" + b"\x00\x00\x00\x00" + b"AVI " + b"\x00" * 100
        p = _write_tmp(data, ".avi")
        try:
            valid, detail = check_header(p)
            self.assertFalse(valid)
        finally:
            p.unlink(missing_ok=True)


class TsHeaderTests(unittest.TestCase):
    """MPEG-TS : 3 sync bytes 0x47 a intervalles de 188 octets."""

    def test_valid_ts(self) -> None:
        p = _write_tmp(_TS_HEADER, ".ts")
        try:
            valid, detail = check_header(p)
            self.assertTrue(valid)
            self.assertEqual(detail, "ok")
        finally:
            p.unlink(missing_ok=True)

    def test_valid_m2ts(self) -> None:
        p = _write_tmp(_TS_HEADER, ".m2ts")
        try:
            valid, detail = check_header(p)
            self.assertTrue(valid)
        finally:
            p.unlink(missing_ok=True)

    def test_invalid_ts_wrong_sync(self) -> None:
        bad = bytes([0x47]) + b"\x00" * 187 + bytes([0x00]) + b"\x00" * 187 + bytes([0x47]) + b"\x00" * 100
        p = _write_tmp(bad, ".ts")
        try:
            valid, detail = check_header(p)
            self.assertFalse(valid)
            self.assertEqual(detail, "header_mismatch")
        finally:
            p.unlink(missing_ok=True)


class WmvHeaderTests(unittest.TestCase):
    """WMV/ASF."""

    def test_valid_wmv(self) -> None:
        p = _write_tmp(_WMV_HEADER, ".wmv")
        try:
            valid, detail = check_header(p)
            self.assertTrue(valid)
            self.assertEqual(detail, "ok")
        finally:
            p.unlink(missing_ok=True)


class EdgeCaseTests(unittest.TestCase):
    """Fichier vide, trop petit, extension inconnue, inexistant."""

    def test_empty_file(self) -> None:
        p = _write_tmp(b"", ".mkv")
        try:
            valid, detail = check_header(p)
            self.assertFalse(valid)
            self.assertEqual(detail, "empty_file")
        finally:
            p.unlink(missing_ok=True)

    def test_file_too_small_mkv(self) -> None:
        p = _write_tmp(b"\x1a\x45", ".mkv")
        try:
            valid, detail = check_header(p)
            self.assertFalse(valid)
            self.assertEqual(detail, "file_too_small")
        finally:
            p.unlink(missing_ok=True)

    def test_file_too_small_ts(self) -> None:
        """TS necessite au moins 377 octets (3 × 188 - 187)."""
        p = _write_tmp(bytes([0x47]) + b"\x00" * 100, ".ts")
        try:
            valid, detail = check_header(p)
            self.assertFalse(valid)
            self.assertEqual(detail, "file_too_small")
        finally:
            p.unlink(missing_ok=True)

    def test_unknown_extension_skip(self) -> None:
        p = _write_tmp(b"\x00" * 100, ".ogv")
        try:
            valid, detail = check_header(p)
            self.assertTrue(valid)
            self.assertEqual(detail, "skipped")
        finally:
            p.unlink(missing_ok=True)

    def test_flv_extension_skip(self) -> None:
        p = _write_tmp(b"\x00" * 100, ".flv")
        try:
            valid, detail = check_header(p)
            self.assertTrue(valid)
            self.assertEqual(detail, "skipped")
        finally:
            p.unlink(missing_ok=True)

    def test_nonexistent_file(self) -> None:
        p = Path(tempfile.gettempdir()) / "nonexistent_video_test.mkv"
        valid, detail = check_header(p)
        self.assertFalse(valid)
        self.assertEqual(detail, "read_error")


@unittest.skip("V5C-01: dashboard/views/review.js supprime — adaptation v5 deferee a V5C-03")
class UiBadgeTests(unittest.TestCase):
    """Badges integrite dans les fichiers UI."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.validation_js = (root / "web" / "views" / "validation.js").read_text(encoding="utf-8")
        cls.review_js = (root / "web" / "dashboard" / "views" / "review.js").read_text(encoding="utf-8")
        cls.app_css = (root / "web" / "styles.css").read_text(encoding="utf-8")
        cls.dash_css = (root / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")

    def test_desktop_badge(self) -> None:
        self.assertIn("integrity_header_invalid", self.validation_js)
        self.assertIn("Corrompu", self.validation_js)

    def test_dashboard_badge(self) -> None:
        self.assertIn("integrity_header_invalid", self.review_js)
        self.assertIn("Corrompu", self.review_js)

    def test_desktop_css(self) -> None:
        self.assertIn("integrity", self.app_css)

    def test_dashboard_css(self) -> None:
        self.assertIn("integrity", self.dash_css)

    def test_badge_tooltip(self) -> None:
        self.assertIn("title=", self.validation_js)
        self.assertIn("corrompu", self.validation_js.lower())


if __name__ == "__main__":
    unittest.main()
