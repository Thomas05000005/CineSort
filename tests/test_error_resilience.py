from __future__ import annotations

import os
import shutil
import sqlite3
import stat
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import cinesort.domain.core as core
import cinesort.app.cleanup as core_cleanup
import cinesort.app.plan_support as core_plan_support


class ParseMovieNfoResilienceTests(unittest.TestCase):
    """Test that parse_movie_nfo handles corrupt / inaccessible files gracefully."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_err_")

    def tearDown(self) -> None:
        # Restore permissions before cleanup.
        for dirpath, dirnames, filenames in os.walk(self._tmp):
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_corrupt_xml_returns_none(self) -> None:
        nfo = Path(self._tmp) / "movie.nfo"
        nfo.write_text("<<<NOT VALID XML>>>", encoding="utf-8")
        self.assertIsNone(core.parse_movie_nfo(nfo))

    def test_missing_file_returns_none(self) -> None:
        nfo = Path(self._tmp) / "does_not_exist.nfo"
        self.assertIsNone(core.parse_movie_nfo(nfo))

    def test_empty_file_returns_none(self) -> None:
        nfo = Path(self._tmp) / "empty.nfo"
        nfo.write_bytes(b"")
        self.assertIsNone(core.parse_movie_nfo(nfo))

    def test_binary_garbage_returns_none(self) -> None:
        nfo = Path(self._tmp) / "garbage.nfo"
        nfo.write_bytes(os.urandom(512))
        self.assertIsNone(core.parse_movie_nfo(nfo))

    def test_valid_nfo_still_works(self) -> None:
        nfo = Path(self._tmp) / "movie.nfo"
        nfo.write_text(
            '<?xml version="1.0"?><movie><title>Test Film</title><year>2024</year></movie>',
            encoding="utf-8",
        )
        result = core.parse_movie_nfo(nfo)
        self.assertIsNotNone(result)
        self.assertEqual(result.title, "Test Film")
        self.assertEqual(result.year, 2024)


class FindBestNfoResilienceTests(unittest.TestCase):
    """Test that find_best_nfo_for_video handles inaccessible directories."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_err_")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_missing_folder_returns_none(self) -> None:
        gone = Path(self._tmp) / "nonexistent"
        video = gone / "movie.mkv"
        self.assertIsNone(core.find_best_nfo_for_video(gone, video))


class PlanRowFromJsonableResilienceTests(unittest.TestCase):
    """Test that plan_row_from_jsonable handles corrupt data gracefully."""

    def test_none_returns_none(self) -> None:
        self.assertIsNone(core_plan_support.plan_row_from_jsonable(None))

    def test_empty_dict_returns_row_with_defaults(self) -> None:
        result = core_plan_support.plan_row_from_jsonable({})
        self.assertIsNotNone(result)
        self.assertEqual(result.row_id, "")

    def test_wrong_types_returns_none(self) -> None:
        self.assertIsNone(core_plan_support.plan_row_from_jsonable("not a dict"))

    def test_partial_data_returns_row(self) -> None:
        result = core_plan_support.plan_row_from_jsonable({"row_id": 123})
        self.assertIsNotNone(result)
        self.assertEqual(result.row_id, "123")

    def test_valid_data_works(self) -> None:
        data = {
            "row_id": "r1",
            "kind": "single",
            "folder": "/tmp/film",
            "video": "film.mkv",
            "proposed_title": "Film",
            "proposed_year": 2024,
            "proposed_source": "name",
            "confidence": 80,
            "confidence_label": "high",
            "candidates": [],
            "nfo_path": None,
            "notes": "",
            "detected_year": 2024,
            "detected_year_reason": "paren",
            "warning_flags": [],
            "collection_name": None,
        }
        result = core_plan_support.plan_row_from_jsonable(data)
        self.assertIsNotNone(result)
        self.assertEqual(result.proposed_title, "Film")


class ClassifyCleanableResilienceTests(unittest.TestCase):
    """Test that _classify_cleanable_residual_dir handles edge cases."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_err_")
        # Issue #86 : mock.patch.object pour auto-restore safe meme si exception
        _p_min_video = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p_min_video.start()
        self.addCleanup(_p_min_video.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_cfg(self) -> core.Config:
        return core.Config(
            root=Path(self._tmp),
            enable_collection_folder=False,
            collection_root_name="_Collections",
            empty_folders_folder_name="_Vide",
            move_empty_folders_enabled=False,
            empty_folders_scope="root_all",
            cleanup_residual_folders_enabled=True,
            cleanup_residual_folders_scope="root_all",
            cleanup_residual_folders_folder_name="_Dossier Nettoyage",
        ).normalized()

    def test_nonexistent_dir_returns_invalid(self) -> None:
        cfg = self._make_cfg()
        result = core_cleanup._classify_cleanable_residual_dir(cfg, Path(self._tmp) / "gone")
        self.assertEqual(result, "invalid")

    def test_empty_dir_returns_empty(self) -> None:
        cfg = self._make_cfg()
        d = Path(self._tmp) / "empty_dir"
        d.mkdir()
        result = core_cleanup._classify_cleanable_residual_dir(cfg, d)
        self.assertEqual(result, "empty")


class DecodeRowJsonResilienceTests(unittest.TestCase):
    """Test that SQLiteStore._decode_row_json warns on corrupt data."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_err_")
        self._db_path = Path(self._tmp) / "test.sqlite"
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("CREATE TABLE t (id TEXT, data TEXT)")
        conn.execute("INSERT INTO t VALUES ('ok', '{\"a\": 1}')")
        conn.execute("INSERT INTO t VALUES ('corrupt', '<<<NOT JSON>>>')")
        conn.execute("INSERT INTO t VALUES ('wrong_type', '\"just a string\"')")
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_valid_json_decoded(self) -> None:
        from cinesort.infra.db import SQLiteStore

        store = SQLiteStore(db_path=self._db_path)
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM t WHERE id='ok'").fetchone()
        result = store._decode_row_json(row, "data", default={}, expected_type=dict)
        self.assertEqual(result, {"a": 1})
        conn.close()

    def test_corrupt_json_returns_default_with_warning(self) -> None:
        from cinesort.infra.db import SQLiteStore

        store = SQLiteStore(db_path=self._db_path)
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM t WHERE id='corrupt'").fetchone()
        with self.assertLogs("cinesort.infra.db.sqlite_store", level="WARNING") as cm:
            result = store._decode_row_json(row, "data", default={}, expected_type=dict)
        self.assertEqual(result, {})
        self.assertTrue(any("corrupt JSON" in msg for msg in cm.output))
        conn.close()

    def test_wrong_type_returns_default_with_warning(self) -> None:
        from cinesort.infra.db import SQLiteStore

        store = SQLiteStore(db_path=self._db_path)
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM t WHERE id='wrong_type'").fetchone()
        with self.assertLogs("cinesort.infra.db.sqlite_store", level="WARNING") as cm:
            result = store._decode_row_json(row, "data", default={}, expected_type=dict)
        self.assertEqual(result, {})
        self.assertTrue(any("unexpected type" in msg for msg in cm.output))
        conn.close()


if __name__ == "__main__":
    unittest.main()
