"""Tests pour le tail check V4 (detection fichiers tronques)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from cinesort.domain.integrity_check import check_header, check_tail


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


class TsHeaderCheckTests(unittest.TestCase):
    """Tests pour check_header() sur les conteneurs MPEG-TS et M2TS/MTS."""

    def _write_file(self, ext: str, content: bytes) -> Path:
        fd, path = tempfile.mkstemp(suffix=ext)
        os.write(fd, content)
        os.close(fd)
        return Path(path)

    @staticmethod
    def _build_ts(base_offset: int, packet_size: int) -> bytes:
        """Construit un flux avec sync 0x47 a `base_offset` puis tous les `packet_size` o."""
        buf = bytearray(b"\x00" * 1024)
        for i in range(5):
            buf[base_offset + i * packet_size] = 0x47
        return bytes(buf)

    def test_classic_ts_valid(self):
        content = self._build_ts(0, 188)
        path = self._write_file(".ts", content)
        try:
            ok, detail = check_header(path)
            self.assertTrue(ok)
            self.assertEqual(detail, "ok")
        finally:
            os.unlink(path)

    def test_m2ts_192_packet_valid(self):
        """M2TS (paquets 192 o, sync a l'offset 4) ne doit PAS etre flag corrompu."""
        content = self._build_ts(4, 192)
        path = self._write_file(".m2ts", content)
        try:
            ok, detail = check_header(path)
            self.assertTrue(ok, "M2TS valide faussement classe header_mismatch")
            self.assertEqual(detail, "ok")
        finally:
            os.unlink(path)

    def test_mts_192_packet_valid(self):
        """MTS (AVCHD camescope, meme layout 192 o) valide."""
        content = self._build_ts(4, 192)
        path = self._write_file(".mts", content)
        try:
            ok, detail = check_header(path)
            self.assertTrue(ok)
        finally:
            os.unlink(path)

    def test_ts_garbage_still_mismatch(self):
        """Un vrai flux corrompu (aucun sync a aucun layout) reste header_mismatch."""
        content = bytes([0x00] * 1024)
        path = self._write_file(".ts", content)
        try:
            ok, detail = check_header(path)
            self.assertFalse(ok)
            self.assertEqual(detail, "header_mismatch")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
