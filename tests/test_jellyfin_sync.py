"""Tests unitaires pour cinesort/app/jellyfin_sync.py (Phase 2 — sync watched)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from cinesort.app.jellyfin_sync import (
    _MAX_RETRIES,
    _MAX_RETRY_DELAY_S,
    RestoreResult,
    WatchedInfo,
    _build_path_mapping,
    _compute_retry_delay,
    _normalize_path,
    restore_watched,
    snapshot_watched,
)


# ── _compute_retry_delay (H-11) ──────────────────────────────────────


class TestComputeRetryDelay(unittest.TestCase):
    """H-11 audit QA 20260429 : backoff exponentiel + cap."""

    def test_first_attempt_returns_base(self) -> None:
        self.assertEqual(_compute_retry_delay(1, 5.0), 5.0)

    def test_second_attempt_doubles(self) -> None:
        self.assertEqual(_compute_retry_delay(2, 5.0), 10.0)

    def test_third_attempt_quadruples(self) -> None:
        self.assertEqual(_compute_retry_delay(3, 5.0), 20.0)

    def test_caps_at_max_delay(self) -> None:
        # Avec base=5 et attempt=10, sans cap on aurait 5*512=2560s.
        # Le cap est _MAX_RETRY_DELAY_S (60.0).
        self.assertEqual(_compute_retry_delay(10, 5.0), _MAX_RETRY_DELAY_S)

    def test_zero_attempt_returns_base(self) -> None:
        self.assertEqual(_compute_retry_delay(0, 5.0), 5.0)

    def test_max_retries_increased_to_5(self) -> None:
        """Audit H-11 : on est passes de 2 a 5 retries."""
        self.assertEqual(_MAX_RETRIES, 5)


# ── _normalize_path ──────────────────────────────────────────────────


class TestNormalizePath(unittest.TestCase):
    """Tests pour _normalize_path."""

    def test_empty(self):
        self.assertEqual(_normalize_path(""), "")

    def test_backslashes_to_forward(self):
        result = _normalize_path(r"C:\Films\Inception (2010)\Inception.mkv")
        self.assertNotIn("\\", result)
        self.assertIn("c:/films/inception (2010)/inception.mkv", result)

    def test_lowercase(self):
        result = _normalize_path("C:/Films/MATRIX.MKV")
        self.assertEqual(result, "c:/films/matrix.mkv")

    def test_trailing_slash_removed(self):
        result = _normalize_path("C:\\Films\\Inception\\")
        self.assertFalse(result.endswith("/"))


# ── _build_path_mapping ───���─────────────────────────────────────────


class TestBuildPathMapping(unittest.TestCase):
    """Tests pour _build_path_mapping."""

    def test_move_operation(self):
        ops = [
            {
                "op_type": "MOVE",
                "src_path": r"C:\Films\inception\inception.mkv",
                "dst_path": r"C:\Films\Inception (2010)\Inception (2010).mkv",
                "undo_status": "PENDING",
            }
        ]
        mapping = _build_path_mapping(ops)
        self.assertEqual(len(mapping), 1)
        src_norm = _normalize_path(r"C:\Films\inception\inception.mkv")
        dst_norm = _normalize_path(r"C:\Films\Inception (2010)\Inception (2010).mkv")
        self.assertEqual(mapping[src_norm], dst_norm)

    def test_ignores_non_move_ops(self):
        ops = [
            {"op_type": "DELETE", "src_path": "a", "dst_path": "b", "undo_status": "PENDING"},
            {"op_type": "CREATE_DIR", "src_path": "", "dst_path": "c", "undo_status": "PENDING"},
        ]
        mapping = _build_path_mapping(ops)
        self.assertEqual(len(mapping), 0)

    def test_ignores_already_undone(self):
        ops = [
            {"op_type": "MOVE", "src_path": "a.mkv", "dst_path": "b.mkv", "undo_status": "DONE"},
        ]
        mapping = _build_path_mapping(ops)
        self.assertEqual(len(mapping), 0)

    def test_rename_operation(self):
        ops = [
            {"op_type": "RENAME", "src_path": "old.mkv", "dst_path": "new.mkv", "undo_status": "PENDING"},
        ]
        mapping = _build_path_mapping(ops)
        self.assertEqual(len(mapping), 1)

    def test_empty_operations(self):
        self.assertEqual(_build_path_mapping([]), {})


# ── snapshot_watched ─────────────────────────────────────────────────


class TestSnapshotWatched(unittest.TestCase):
    """Tests pour snapshot_watched."""

    def test_captures_played_movies(self):
        client = MagicMock()
        client.get_all_movies_from_all_libraries.return_value = [
            {"path": r"C:\Films\Inception.mkv", "played": True, "play_count": 2, "last_played_date": "2025-12-01"},
            {"path": r"C:\Films\Matrix.mkv", "played": False, "play_count": 0, "last_played_date": ""},
            {"path": r"C:\Films\Interstellar.mkv", "played": True, "play_count": 1, "last_played_date": "2025-11-15"},
        ]
        result = snapshot_watched(client, "uid")
        # Only 2 played movies
        self.assertEqual(len(result), 2)
        inception_key = _normalize_path(r"C:\Films\Inception.mkv")
        self.assertIn(inception_key, result)
        self.assertTrue(result[inception_key].played)
        self.assertEqual(result[inception_key].play_count, 2)

    def test_empty_library(self):
        client = MagicMock()
        client.get_all_movies_from_all_libraries.return_value = []
        result = snapshot_watched(client, "uid")
        self.assertEqual(len(result), 0)

    def test_client_error_returns_empty(self):
        client = MagicMock()
        client.get_all_movies_from_all_libraries.side_effect = OSError("network error")
        result = snapshot_watched(client, "uid")
        self.assertEqual(len(result), 0)

    def test_no_played_movies(self):
        client = MagicMock()
        client.get_all_movies_from_all_libraries.return_value = [
            {"path": r"C:\Films\Movie.mkv", "played": False, "play_count": 0, "last_played_date": ""},
        ]
        result = snapshot_watched(client, "uid")
        self.assertEqual(len(result), 0)


# ── restore_watched ─────��────────────────────────────────────────────


class TestRestoreWatched(unittest.TestCase):
    """Tests pour restore_watched."""

    def test_empty_snapshot_returns_empty_result(self):
        result = restore_watched(MagicMock(), "uid", {}, [])
        self.assertEqual(result.restored, 0)
        self.assertEqual(result.not_found, 0)

    def test_no_move_operations_skips(self):
        snapshot = {_normalize_path(r"C:\Films\Movie.mkv"): WatchedInfo(True, 1, "")}
        ops = [{"op_type": "CREATE_DIR", "src_path": "", "dst_path": "dir", "undo_status": "PENDING"}]
        result = restore_watched(MagicMock(), "uid", snapshot, ops, initial_delay_s=0, retry_delay_s=0)
        self.assertEqual(result.skipped, 1)

    @patch("cinesort.app.jellyfin_sync.time.sleep")
    def test_successful_restore(self, mock_sleep):
        """Film deplace, retrouve dans Jellyfin, marque comme vu."""
        old_path = r"C:\Films\inception\inception.mkv"
        new_path = r"C:\Films\Inception (2010)\Inception (2010).mkv"

        snapshot = {_normalize_path(old_path): WatchedInfo(True, 3, "2025-12-01")}
        operations = [
            {"op_type": "MOVE", "src_path": old_path, "dst_path": new_path, "undo_status": "PENDING"},
        ]

        client = MagicMock()
        # After refresh, Jellyfin returns the movie at its new path
        client.get_all_movies_from_all_libraries.return_value = [
            {"id": "jf-item-1", "path": new_path, "played": False, "play_count": 0, "last_played_date": ""},
        ]
        client.mark_played.return_value = True

        result = restore_watched(
            client,
            "uid",
            snapshot,
            operations,
            initial_delay_s=0,
            retry_delay_s=0,
            max_retries=1,
        )
        self.assertEqual(result.restored, 1)
        self.assertEqual(result.not_found, 0)
        self.assertEqual(result.errors, 0)
        client.mark_played.assert_called_once_with("uid", "jf-item-1")

    @patch("cinesort.app.jellyfin_sync.time.sleep")
    def test_movie_not_found_after_retries(self, mock_sleep):
        """Film deplace mais pas encore indexe par Jellyfin."""
        old_path = r"C:\Films\movie.mkv"
        new_path = r"C:\Films\Movie (2020)\Movie (2020).mkv"

        snapshot = {_normalize_path(old_path): WatchedInfo(True, 1, "")}
        operations = [
            {"op_type": "MOVE", "src_path": old_path, "dst_path": new_path, "undo_status": "PENDING"},
        ]

        client = MagicMock()
        client.get_all_movies_from_all_libraries.return_value = []  # Jellyfin n'a pas encore indexe

        result = restore_watched(
            client,
            "uid",
            snapshot,
            operations,
            initial_delay_s=0,
            retry_delay_s=0,
            max_retries=2,
        )
        self.assertEqual(result.restored, 0)
        self.assertEqual(result.not_found, 1)

    @patch("cinesort.app.jellyfin_sync.time.sleep")
    def test_mark_played_failure(self, mock_sleep):
        """Film retrouve mais mark_played echoue."""
        old_path = r"C:\Films\old.mkv"
        new_path = r"C:\Films\new.mkv"

        snapshot = {_normalize_path(old_path): WatchedInfo(True, 1, "")}
        operations = [
            {"op_type": "MOVE", "src_path": old_path, "dst_path": new_path, "undo_status": "PENDING"},
        ]

        client = MagicMock()
        client.get_all_movies_from_all_libraries.return_value = [
            {"id": "jf-1", "path": new_path, "played": False, "play_count": 0, "last_played_date": ""},
        ]
        client.mark_played.return_value = False

        result = restore_watched(
            client,
            "uid",
            snapshot,
            operations,
            initial_delay_s=0,
            retry_delay_s=0,
            max_retries=1,
        )
        self.assertEqual(result.errors, 1)
        self.assertEqual(result.restored, 0)

    @patch("cinesort.app.jellyfin_sync.time.sleep")
    def test_unwatched_movie_not_in_snapshot(self, mock_sleep):
        """Film deplace mais pas dans le snapshot (pas vu) — rien a restaurer."""
        operations = [
            {"op_type": "MOVE", "src_path": "a.mkv", "dst_path": "b.mkv", "undo_status": "PENDING"},
        ]
        result = restore_watched(
            MagicMock(),
            "uid",
            {},
            operations,
            initial_delay_s=0,
            retry_delay_s=0,
            max_retries=1,
        )
        self.assertEqual(result.restored, 0)

    @patch("cinesort.app.jellyfin_sync.time.sleep")
    def test_multiple_movies_partial_restore(self, mock_sleep):
        """Plusieurs films deplaces, un seul retrouve."""
        old1, new1 = r"C:\Films\a.mkv", r"C:\Films\A (2020)\A.mkv"
        old2, new2 = r"C:\Films\b.mkv", r"C:\Films\B (2021)\B.mkv"

        snapshot = {
            _normalize_path(old1): WatchedInfo(True, 1, ""),
            _normalize_path(old2): WatchedInfo(True, 2, ""),
        }
        operations = [
            {"op_type": "MOVE", "src_path": old1, "dst_path": new1, "undo_status": "PENDING"},
            {"op_type": "MOVE", "src_path": old2, "dst_path": new2, "undo_status": "PENDING"},
        ]

        client = MagicMock()
        # Seul le premier film est indexe
        client.get_all_movies_from_all_libraries.return_value = [
            {"id": "jf-a", "path": new1, "played": False, "play_count": 0, "last_played_date": ""},
        ]
        client.mark_played.return_value = True

        result = restore_watched(
            client,
            "uid",
            snapshot,
            operations,
            initial_delay_s=0,
            retry_delay_s=0,
            max_retries=1,
        )
        self.assertEqual(result.restored, 1)
        self.assertEqual(result.not_found, 1)


# ── RestoreResult ────────────────────────────────────────────────────


class TestRestoreResult(unittest.TestCase):
    """Tests pour RestoreResult dataclass."""

    def test_to_dict(self):
        r = RestoreResult(restored=3, skipped=1, not_found=2, errors=0)
        d = r.to_dict()
        self.assertEqual(d["restored"], 3)
        self.assertEqual(d["not_found"], 2)
        self.assertIsInstance(d["details"], list)

    def test_defaults(self):
        r = RestoreResult()
        self.assertEqual(r.restored, 0)
        self.assertEqual(r.errors, 0)


# ── WatchedInfo ────��─────────────────────────────────────────────────


class TestWatchedInfo(unittest.TestCase):
    """Tests pour WatchedInfo dataclass."""

    def test_frozen(self):
        w = WatchedInfo(played=True, play_count=5, last_played_date="2025-12-01")
        with self.assertRaises(AttributeError):
            w.played = False  # type: ignore[misc]

    def test_values(self):
        w = WatchedInfo(played=True, play_count=3, last_played_date="2025-12-01")
        self.assertTrue(w.played)
        self.assertEqual(w.play_count, 3)


if __name__ == "__main__":
    unittest.main()
