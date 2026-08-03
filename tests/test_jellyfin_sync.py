"""Tests unitaires pour cinesort/app/jellyfin_sync.py (Phase 2 — sync watched)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from cinesort.app.jellyfin_sync import (
    _MAX_RETRIES,
    _MAX_RETRY_DELAY_S,
    RestoreResult,
    WatchedInfo,
    _build_move_sequence,
    _compute_retry_delay,
    _normalize_path,
    _remap_path,
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


# ── _build_move_sequence ─────────────────────────────────────────────


class TestBuildMoveSequence(unittest.TestCase):
    """Tests pour _build_move_sequence (ex-_build_path_mapping)."""

    def test_move_operation(self):
        ops = [
            {
                "op_type": "MOVE",
                "src_path": r"C:\Films\inception\inception.mkv",
                "dst_path": r"C:\Films\Inception (2010)\Inception (2010).mkv",
                "undo_status": "PENDING",
            }
        ]
        sequence = _build_move_sequence(ops)
        self.assertEqual(len(sequence), 1)
        self.assertFalse(sequence[0].is_dir)
        self.assertEqual(sequence[0].src, _normalize_path(r"C:\Films\inception\inception.mkv"))
        self.assertEqual(sequence[0].dst, _normalize_path(r"C:\Films\Inception (2010)\Inception (2010).mkv"))

    def test_ignores_non_move_ops(self):
        ops = [
            {"op_type": "DELETE", "src_path": "a", "dst_path": "b", "undo_status": "PENDING"},
            {"op_type": "CREATE_DIR", "src_path": "", "dst_path": "c", "undo_status": "PENDING"},
            {"op_type": "MKDIR", "src_path": "", "dst_path": "d", "undo_status": "PENDING"},
        ]
        self.assertEqual(_build_move_sequence(ops), [])

    def test_ignores_already_undone(self):
        ops = [
            {"op_type": "MOVE", "src_path": "a.mkv", "dst_path": "b.mkv", "undo_status": "DONE"},
            {"op_type": "MOVE_DIR", "src_path": "a", "dst_path": "b", "undo_status": "DONE"},
        ]
        self.assertEqual(_build_move_sequence(ops), [])

    def test_rename_operation(self):
        ops = [
            {"op_type": "RENAME", "src_path": "old.mkv", "dst_path": "new.mkv", "undo_status": "PENDING"},
        ]
        sequence = _build_move_sequence(ops)
        self.assertEqual(len(sequence), 1)
        self.assertFalse(sequence[0].is_dir)

    def test_empty_operations(self):
        self.assertEqual(_build_move_sequence([]), [])

    def test_move_dir_is_collected_and_flagged_as_dir(self):
        """#680 : MOVE_DIR est la voie NOMINALE du tri de films (apply_single
        renomme le DOSSIER, jamais le fichier video). Le filtre l'excluait."""
        ops = [
            {
                "op_type": "MOVE_DIR",
                "src_path": r"C:\Films\inception",
                "dst_path": r"C:\Films\Inception (2010)",
                "undo_status": "PENDING",
            }
        ]
        sequence = _build_move_sequence(ops)
        self.assertEqual(len(sequence), 1)
        self.assertTrue(sequence[0].is_dir)

    def test_execution_order_is_preserved(self):
        ops = [
            {"op_type": "MOVE_DIR", "src_path": "a", "dst_path": "b", "undo_status": "PENDING"},
            {"op_type": "MOVE_FILE", "src_path": "b/x.mkv", "dst_path": "b/y.mkv", "undo_status": "PENDING"},
        ]
        sequence = _build_move_sequence(ops)
        self.assertEqual([m.src for m in sequence], ["a", "b/x.mkv"])


# ── _remap_path (#680) ───────────────────────────────────────────────


class TestRemapPath(unittest.TestCase):
    """#680 : Jellyfin indexe les films par chemin de FICHIER, le journal apply
    ne cite que des DOSSIERS pour un MOVE_DIR. Sans re-prefixation, aucune cle
    du snapshot ne matche et le statut « vu » est perdu apres chaque apply."""

    def test_file_move_is_exact_match(self):
        seq = _build_move_sequence(
            [{"op_type": "MOVE_FILE", "src_path": "c:/f/a.mkv", "dst_path": "c:/f/b.mkv", "undo_status": "PENDING"}]
        )
        self.assertEqual(_remap_path("c:/f/a.mkv", seq), "c:/f/b.mkv")

    def test_dir_move_reprefixes_the_video_inside(self):
        seq = _build_move_sequence(
            [
                {
                    "op_type": "MOVE_DIR",
                    "src_path": r"C:\Films\inception",
                    "dst_path": r"C:\Films\Inception (2010)",
                    "undo_status": "PENDING",
                }
            ]
        )
        old = _normalize_path(r"C:\Films\inception\Inception.BluRay.mkv")
        self.assertEqual(_remap_path(old, seq), _normalize_path(r"C:\Films\Inception (2010)\Inception.BluRay.mkv"))

    def test_dir_move_does_not_capture_a_sibling_with_same_prefix(self):
        seq = _build_move_sequence(
            [
                {
                    "op_type": "MOVE_DIR",
                    "src_path": "c:/films/dune",
                    "dst_path": "c:/films/Dune (2021)",
                    "undo_status": "PENDING",
                }
            ]
        )
        # "dune 2" n'est PAS sous "dune" : le chemin doit rester intact.
        self.assertEqual(_remap_path("c:/films/dune 2/dune2.mkv", seq), "c:/films/dune 2/dune2.mkv")

    def test_dir_move_matching_the_media_path_itself(self):
        """Jellyfin peut indexer un rip BDMV par son DOSSIER."""
        seq = _build_move_sequence(
            [
                {
                    "op_type": "MOVE_DIR",
                    "src_path": "c:/films/heat",
                    "dst_path": "c:/films/Heat (1995)",
                    "undo_status": "PENDING",
                }
            ]
        )
        self.assertEqual(_remap_path("c:/films/heat", seq), "c:/films/heat (1995)")

    def test_chained_dir_moves_compose(self):
        """Renommage du dossier PUIS deplacement sous la racine Collection : un
        simple dict ancien->nouveau perdrait la composition."""
        seq = _build_move_sequence(
            [
                {
                    "op_type": "MOVE_DIR",
                    "src_path": "c:/films/matrix",
                    "dst_path": "c:/films/Matrix (1999)",
                    "undo_status": "PENDING",
                },
                {
                    "op_type": "MOVE_DIR",
                    "src_path": "c:/films/Matrix (1999)",
                    "dst_path": "c:/films/_Collection/Matrix (1999)",
                    "undo_status": "PENDING",
                },
            ]
        )
        self.assertEqual(
            _remap_path("c:/films/matrix/matrix.mkv", seq),
            "c:/films/_collection/matrix (1999)/matrix.mkv",
        )

    def test_untouched_path_is_returned_unchanged(self):
        seq = _build_move_sequence(
            [{"op_type": "MOVE_DIR", "src_path": "c:/films/a", "dst_path": "c:/films/b", "undo_status": "PENDING"}]
        )
        self.assertEqual(_remap_path("c:/autre/film.mkv", seq), "c:/autre/film.mkv")


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
    def test_move_dir_restores_watched_status(self, mock_sleep):
        """#680 — le cas NOMINAL du tri de films : apply_single renomme le
        DOSSIER (MOVE_DIR), le fichier video garde son nom. Avant le correctif,
        aucun film vu n'etait retrouve (skipped) et l'utilisateur retrouvait ses
        films marques NON VUS.
        """
        old_dir = r"C:\Films\inception"
        new_dir = r"C:\Films\Inception (2010)"
        video_name = "Inception.2010.1080p.BluRay.mkv"
        old_path = rf"{old_dir}\{video_name}"
        new_path = rf"{new_dir}\{video_name}"

        snapshot = {_normalize_path(old_path): WatchedInfo(True, 3, "2025-12-01")}
        operations = [
            {"op_type": "MKDIR", "src_path": "", "dst_path": new_dir, "undo_status": "PENDING"},
            {"op_type": "MOVE_DIR", "src_path": old_dir, "dst_path": new_dir, "undo_status": "PENDING"},
        ]

        client = MagicMock()
        client.get_all_movies_from_all_libraries.return_value = [
            {"id": "jf-inception", "path": new_path, "played": False, "play_count": 0, "last_played_date": ""},
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
        self.assertEqual(result.skipped, 0)
        self.assertEqual(result.not_found, 0)
        client.mark_played.assert_called_once_with("uid", "jf-inception")

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
