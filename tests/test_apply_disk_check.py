"""H-2 audit QA 20260428 — tests du pre-check espace disque avant apply.

Verifie que :
- check_disk_space_for_apply autorise quand assez d'espace.
- Refuse quand moins que somme + marge 10%.
- Refuse quand moins que minimum absolu (100 MB) meme avec rows vides.
- Tolere shutil.disk_usage qui echoue (laisse passer plutot que blocage).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cinesort.app.disk_space_check import (
    _MIN_FREE_BYTES,
    check_disk_space_for_apply,
    estimate_apply_size,
)


def _make_row(folder: str, video: str, row_id: str = "r1") -> SimpleNamespace:
    return SimpleNamespace(folder=folder, video=video, row_id=row_id)


def _make_cfg(root: Path) -> SimpleNamespace:
    return SimpleNamespace(root=root)


class EstimateApplySizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_disk_est_")
        self.tmp = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_size_video_only(self) -> None:
        folder = self.tmp / "Film1"
        folder.mkdir()
        video = folder / "movie.mkv"
        video.write_bytes(b"x" * 12345)
        row = _make_row(str(folder), "movie.mkv")
        size = estimate_apply_size([row], approved_keys={"r1"})
        self.assertEqual(size, 12345)

    def test_size_skipped_if_not_approved(self) -> None:
        folder = self.tmp / "Film1"
        folder.mkdir()
        video = folder / "movie.mkv"
        video.write_bytes(b"x" * 999)
        row = _make_row(str(folder), "movie.mkv")
        size = estimate_apply_size([row], approved_keys=set())  # rien d'approuve
        self.assertEqual(size, 0)

    def test_size_collection_sum_files(self) -> None:
        folder = self.tmp / "Trilogy"
        folder.mkdir()
        (folder / "f1.mkv").write_bytes(b"a" * 1000)
        (folder / "f2.mkv").write_bytes(b"b" * 2000)
        (folder / "notes.txt").write_bytes(b"c" * 10)
        row = _make_row(str(folder), "")  # collection : video vide
        size = estimate_apply_size([row], approved_keys={"r1"})
        self.assertEqual(size, 3010)

    def test_size_missing_file_returns_zero(self) -> None:
        row = _make_row(str(self.tmp / "ghost"), "ghost.mkv")
        size = estimate_apply_size([row], approved_keys={"r1"})
        self.assertEqual(size, 0)


class CheckDiskSpaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_disk_chk_")
        self.tmp = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_ok_when_plenty_of_space(self) -> None:
        cfg = _make_cfg(self.tmp)
        # disk_usage normal → on a beaucoup d'espace en realite
        ok, info = check_disk_space_for_apply(cfg, rows=[], approved_keys=set())
        self.assertTrue(ok)
        self.assertGreater(info["free_bytes"], 0)
        self.assertEqual(info["estimated_bytes"], 0)

    def test_refuses_when_below_min_absolute(self) -> None:
        cfg = _make_cfg(self.tmp)
        fake_usage = SimpleNamespace(total=10**9, used=10**9 - 1024, free=1024)  # 1 KB libre
        with patch("cinesort.app.disk_space_check.shutil.disk_usage", return_value=fake_usage):
            ok, info = check_disk_space_for_apply(cfg, rows=[], approved_keys=set())
        self.assertFalse(ok)
        self.assertEqual(info["needed_bytes"], _MIN_FREE_BYTES)
        self.assertIn("Espace disque insuffisant", info["message"])

    def test_refuses_when_estimated_plus_margin_exceeds_free(self) -> None:
        # 1 fichier de 1 GB, 1.05 GB libres → besoin = 1.1 GB → refuse
        folder = self.tmp / "Film"
        folder.mkdir()
        big = folder / "big.mkv"
        big.write_bytes(b"\0" * 1024)  # contenu test
        # On va mocker stat pour faire croire a 1 GB
        cfg = _make_cfg(self.tmp)
        row = _make_row(str(folder), "big.mkv")
        fake_usage = SimpleNamespace(total=10**12, used=10**12 - int(1.05 * 1024**3), free=int(1.05 * 1024**3))
        with patch("cinesort.app.disk_space_check._row_estimated_size", return_value=1024**3):  # 1 GB
            with patch("cinesort.app.disk_space_check.shutil.disk_usage", return_value=fake_usage):
                ok, info = check_disk_space_for_apply(cfg, rows=[row], approved_keys={"r1"})
        self.assertFalse(ok)
        self.assertEqual(info["estimated_bytes"], 1024**3)
        # needed = 1 GB * 1.10 = 1.1 GB > 1.05 GB libres
        self.assertGreater(info["needed_bytes"], info["free_bytes"])

    def test_disk_usage_failure_lets_apply_proceed(self) -> None:
        cfg = _make_cfg(self.tmp)
        with patch(
            "cinesort.app.disk_space_check.shutil.disk_usage",
            side_effect=OSError("WinError 5: Access denied"),
        ):
            ok, info = check_disk_space_for_apply(cfg, rows=[], approved_keys=set())
        self.assertTrue(ok)  # tolerance : on laisse passer
        self.assertEqual(info["free_bytes"], -1)
        self.assertIn("pre-check ignore", info["message"])


if __name__ == "__main__":
    unittest.main()
