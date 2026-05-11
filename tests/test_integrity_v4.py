"""Tests pour le tail check V4 (detection fichiers tronques)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from cinesort.domain.integrity_check import check_tail


class TailCheckTests(unittest.TestCase):
    """Tests pour check_tail()."""

    def _write_file(self, ext: str, content: bytes) -> Path:
        fd, path = tempfile.mkstemp(suffix=ext)
        os.write(fd, content)
        os.close(fd)
        return Path(path)

    def test_mp4_with_moov(self):
        """MP4 avec atome moov dans le header → ok."""
        # Simuler un MP4 minimal avec ftyp + moov
        content = b"\x00\x00\x00\x1c" + b"ftyp" + b"isom" + b"\x00" * 16
        content += b"\x00\x00\x00\x08" + b"moov"
        content += b"\x00" * 5000  # padding pour depasser TAIL_READ_SIZE
        path = self._write_file(".mp4", content)
        try:
            ok, detail = check_tail(path)
            self.assertTrue(ok)
        finally:
            os.unlink(path)

    def test_mp4_no_moov(self):
        """MP4 sans atome moov → echec."""
        # Simuler un MP4 tronque (ftyp OK mais pas de moov)
        content = b"\x00\x00\x00\x1c" + b"ftyp" + b"isom" + b"\x00" * 16
        content += b"\x00" * 70000  # padding suffisant
        path = self._write_file(".mp4", content)
        try:
            ok, detail = check_tail(path)
            self.assertFalse(ok)
            self.assertIn("moov", detail)
        finally:
            os.unlink(path)

    def test_mkv_valid(self):
        """MKV normal (fin non-nulle) → ok."""
        content = bytes([0x1A, 0x45, 0xDF, 0xA3]) + b"\x00" * 100 + b"data" * 1200
        path = self._write_file(".mkv", content)
        try:
            ok, detail = check_tail(path)
            self.assertTrue(ok)
        finally:
            os.unlink(path)

    def test_mkv_null_end(self):
        """MKV avec fin entierement nulle → echec."""
        content = bytes([0x1A, 0x45, 0xDF, 0xA3]) + b"data" * 100 + b"\x00" * 5000
        path = self._write_file(".mkv", content)
        try:
            ok, detail = check_tail(path)
            self.assertFalse(ok)
            self.assertIn("nulle", detail)
        finally:
            os.unlink(path)

    def test_other_format_skip(self):
        """AVI → skip (True)."""
        content = b"RIFF" + b"\x00" * 4 + b"AVI " + b"\x00" * 5000
        path = self._write_file(".avi", content)
        try:
            ok, detail = check_tail(path)
            self.assertTrue(ok)
            self.assertEqual(detail, "skipped")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
