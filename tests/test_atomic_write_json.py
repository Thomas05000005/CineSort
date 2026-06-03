"""Tests audit 2026-06-03 A7 — durabilite atomic_write_json.

Le pattern atomic_write_json doit fsync les pages ecrites AVANT os.replace
pour garantir la durabilite sur crash (sinon le fichier renomme peut etre
0 byte ou tronque sur ext4 sans data=ordered, NTFS, ZFS).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cinesort.infra.state import atomic_write_json


class TestAtomicWriteJsonFsync(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_atomic_")
        self.target = Path(self._tmp) / "config.json"

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_content_written_correctly(self) -> None:
        payload = {"hello": "world", "count": 42, "list": [1, 2, 3]}
        atomic_write_json(self.target, payload)
        self.assertEqual(json.loads(self.target.read_text(encoding="utf-8")), payload)

    def test_fsync_called_before_replace(self) -> None:
        """fsync doit etre appele avant os.replace pour garantir la durabilite."""
        calls: list[str] = []
        real_fsync = os.fsync
        real_replace = os.replace

        def tracked_fsync(fd: int) -> None:
            calls.append("fsync")
            real_fsync(fd)

        def tracked_replace(src: object, dst: object) -> None:
            calls.append("replace")
            real_replace(src, dst)  # type: ignore[arg-type]

        with patch("cinesort.infra.state.os.fsync", side_effect=tracked_fsync) as _:
            with patch("cinesort.infra.state.os.replace", side_effect=tracked_replace):
                atomic_write_json(self.target, {"k": "v"})

        # fsync DOIT etre appele AVANT replace
        self.assertIn("fsync", calls)
        self.assertIn("replace", calls)
        self.assertLess(calls.index("fsync"), calls.index("replace"))

    def test_fsync_oserror_does_not_propagate(self) -> None:
        """fsync OSError (fs reseau read-only) doit etre tolere best-effort."""

        def failing_fsync(fd: int) -> None:
            raise OSError("read-only fs")

        with patch("cinesort.infra.state.os.fsync", side_effect=failing_fsync):
            # Doit ne PAS lever : best-effort
            atomic_write_json(self.target, {"k": "v"})

        self.assertTrue(self.target.exists())
        self.assertEqual(json.loads(self.target.read_text(encoding="utf-8")), {"k": "v"})


if __name__ == "__main__":
    unittest.main()
