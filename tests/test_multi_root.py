"""Tests unitaires pour le support multi-root."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from cinesort.domain.core import Config, PlanRow, Stats
from cinesort.app.plan_support import (
    _detect_cross_root_duplicates,
    _merge_stats,
    plan_multi_roots,
)
from cinesort.ui.api.settings_support import (
    _migrate_root_to_roots,
    resolve_roots_from_payload,
    validate_roots,
)


# ── PlanRow.source_root ──────────────────────────────────────────────


class TestPlanRowSourceRoot(unittest.TestCase):
    """Verifie que PlanRow a le champ source_root."""

    def test_default_is_none(self):
        row = PlanRow(
            row_id="r1",
            kind="single",
            folder="f",
            video="v.mkv",
            proposed_title="T",
            proposed_year=2020,
            proposed_source="name",
            confidence=80,
            confidence_label="high",
            candidates=[],
        )
        self.assertIsNone(row.source_root)

    def test_can_set_source_root(self):
        row = PlanRow(
            row_id="r1",
            kind="single",
            folder="f",
            video="v.mkv",
            proposed_title="T",
            proposed_year=2020,
            proposed_source="name",
            confidence=80,
            confidence_label="high",
            candidates=[],
        )
        row.source_root = r"C:\Films"
        self.assertEqual(row.source_root, r"C:\Films")


# ── _merge_stats ─────────────────────────────────────────────────────


class TestMergeStats(unittest.TestCase):
    """Tests pour _merge_stats."""

    def test_merges_int_fields(self):
        a = Stats(folders_scanned=10, collections_seen=2, planned_rows=5)
        b = Stats(folders_scanned=7, collections_seen=1, planned_rows=3)
        _merge_stats(a, b)
        self.assertEqual(a.folders_scanned, 17)
        self.assertEqual(a.collections_seen, 3)
        self.assertEqual(a.planned_rows, 8)

    def test_merges_dict_fields(self):
        a = Stats()
        a.analyse_ignores_par_raison = {"ignore_tv_like": 3}
        b = Stats()
        b.analyse_ignores_par_raison = {"ignore_tv_like": 2, "ignore_autre": 1}
        _merge_stats(a, b)
        self.assertEqual(a.analyse_ignores_par_raison["ignore_tv_like"], 5)
        self.assertEqual(a.analyse_ignores_par_raison["ignore_autre"], 1)

    def test_merges_incremental_cache_stats(self):
        a = Stats(incremental_cache_hits=5, incremental_cache_row_hits=10)
        b = Stats(incremental_cache_hits=3, incremental_cache_row_hits=7)
        _merge_stats(a, b)
        self.assertEqual(a.incremental_cache_hits, 8)
        self.assertEqual(a.incremental_cache_row_hits, 17)


# ── _detect_cross_root_duplicates ────────────────────────────────────


class TestDetectCrossRootDuplicates(unittest.TestCase):
    """Tests pour _detect_cross_root_duplicates."""

    def _make_row(self, title, year, source_root):
        row = PlanRow(
            row_id=f"{title}_{year}_{source_root}",
            kind="single",
            folder="f",
            video="v.mkv",
            proposed_title=title,
            proposed_year=year,
            proposed_source="name",
            confidence=80,
            confidence_label="high",
            candidates=[],
        )
        row.source_root = source_root
        return row

    def test_no_duplicates(self):
        rows = [
            self._make_row("Inception", 2010, r"C:\Films"),
            self._make_row("Matrix", 1999, r"D:\Films"),
        ]
        count = _detect_cross_root_duplicates(rows)
        self.assertEqual(count, 0)

    def test_detects_cross_root_duplicate(self):
        rows = [
            self._make_row("Inception", 2010, r"C:\Films"),
            self._make_row("Inception", 2010, r"D:\Films"),
        ]
        count = _detect_cross_root_duplicates(rows)
        self.assertEqual(count, 2)
        for row in rows:
            self.assertIn("duplicate_cross_root", row.warning_flags)

    def test_same_root_not_flagged(self):
        rows = [
            self._make_row("Inception", 2010, r"C:\Films"),
            self._make_row("Inception", 2010, r"C:\Films"),
        ]
        count = _detect_cross_root_duplicates(rows)
        self.assertEqual(count, 0)

    def test_case_insensitive_title(self):
        rows = [
            self._make_row("inception", 2010, r"C:\Films"),
            self._make_row("INCEPTION", 2010, r"D:\Films"),
        ]
        count = _detect_cross_root_duplicates(rows)
        self.assertEqual(count, 2)


# ── plan_multi_roots ─────────────────────────────────────────────────


class TestPlanMultiRoots(unittest.TestCase):
    """Tests pour plan_multi_roots."""

    def test_single_root_backward_compat(self):
        """Un seul root se comporte comme plan_library."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "films"
            root.mkdir()
            # Create a fake video
            (root / "movie").mkdir()
            (root / "movie" / "movie.mkv").write_bytes(b"\x00" * 1024)

            def build_cfg(r):
                return Config(root=r)

            log_calls = []

            rows, stats = plan_multi_roots(
                [root],
                build_cfg=build_cfg,
                tmdb=None,
                log=lambda level, msg: log_calls.append((level, msg)),
                progress=lambda i, t, c: None,
            )
            # Should run without error, rows may be 0 if no valid video
            self.assertIsInstance(rows, list)
            self.assertIsInstance(stats, Stats)

    def test_inaccessible_root_skipped(self):
        """Un root inaccessible est skip sans erreur."""
        with tempfile.TemporaryDirectory() as tmp:
            root_ok = Path(tmp) / "films"
            root_ok.mkdir()
            root_bad = Path(tmp) / "nonexistent"

            log_calls = []

            def build_cfg(r):
                return Config(root=r)

            rows, stats = plan_multi_roots(
                [root_bad, root_ok],
                build_cfg=build_cfg,
                tmdb=None,
                log=lambda level, msg: log_calls.append((level, msg)),
                progress=lambda i, t, c: None,
            )
            # Should have a warning about inaccessible root
            warn_msgs = [msg for level, msg in log_calls if level == "WARN"]
            self.assertTrue(any("inaccessible" in m for m in warn_msgs))

    def test_source_root_is_set_on_rows(self):
        """Chaque row recoit source_root = str(root)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "films"
            root.mkdir()
            (root / "movie").mkdir()
            (root / "movie" / "movie.mkv").write_bytes(b"\x00" * 1024)

            def build_cfg(r):
                return Config(root=r)

            rows, _ = plan_multi_roots(
                [root],
                build_cfg=build_cfg,
                tmdb=None,
                log=lambda l, m: None,
                progress=lambda i, t, c: None,
            )
            for row in rows:
                self.assertEqual(row.source_root, str(root))


# ── Settings migration ───────────────────────────────────────────────


class TestMigrateRootToRoots(unittest.TestCase):
    """Tests pour _migrate_root_to_roots."""

    def test_legacy_root_migrated(self):
        data = {"root": r"C:\Films"}
        _migrate_root_to_roots(data)
        self.assertEqual(data["roots"], [r"C:\Films"])
        self.assertEqual(data["root"], r"C:\Films")

    def test_roots_already_present(self):
        data = {"root": r"C:\Films", "roots": [r"C:\Films", r"D:\Films"]}
        _migrate_root_to_roots(data)
        self.assertEqual(data["roots"], [r"C:\Films", r"D:\Films"])

    def test_empty_root(self):
        data = {"root": ""}
        _migrate_root_to_roots(data)
        self.assertEqual(data["roots"], [])

    def test_no_root_at_all(self):
        data = {}
        _migrate_root_to_roots(data)
        self.assertEqual(data["roots"], [])

    def test_roots_not_list(self):
        data = {"roots": r"C:\Films"}
        _migrate_root_to_roots(data)
        self.assertEqual(data["roots"], [r"C:\Films"])


# ── validate_roots ───────────────────────────────────────────────────


class TestValidateRoots(unittest.TestCase):
    """Tests pour validate_roots."""

    def test_empty_list(self):
        result = validate_roots([])
        self.assertEqual(result["roots"], [])
        self.assertEqual(result["warnings"], [])

    def test_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = validate_roots([tmp, tmp])
            self.assertEqual(len(result["roots"]), 1)
            self.assertTrue(any("Doublon" in w for w in result["warnings"]))

    def test_detects_nested_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            child = os.path.join(tmp, "sub")
            os.makedirs(child)
            result = validate_roots([tmp, child])
            self.assertTrue(any("Imbrication" in w for w in result["warnings"]))

    def test_detects_inaccessible(self):
        result = validate_roots([r"Z:\nonexistent_root_12345"])
        self.assertTrue(any("inaccessible" in w for w in result["warnings"]))
        self.assertEqual(result["disconnected"], [r"Z:\nonexistent_root_12345"])

    def test_strips_empty(self):
        result = validate_roots(["", "  ", None])
        self.assertEqual(result["roots"], [])


# ── resolve_roots_from_payload ───────────────────────────────────────


class TestResolveRootsFromPayload(unittest.TestCase):
    """Tests pour resolve_roots_from_payload."""

    def test_roots_from_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots, err = resolve_roots_from_payload(
                {"roots": [tmp]},
                state_dir=Path(tmp),
                state_dir_present=True,
                current_state_dir=Path(tmp),
                default_root=tmp,
                missing_message="Missing",
            )
            self.assertIsNone(err)
            self.assertEqual(len(roots), 1)
            self.assertEqual(str(roots[0]), os.path.normpath(tmp))

    def test_fallback_to_root_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots, err = resolve_roots_from_payload(
                {"root": tmp},
                state_dir=Path(tmp),
                state_dir_present=True,
                current_state_dir=Path(tmp),
                default_root=tmp,
                missing_message="Missing",
            )
            self.assertIsNone(err)
            self.assertEqual(len(roots), 1)

    def test_empty_root_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots, err = resolve_roots_from_payload(
                {"root": ""},
                state_dir=Path(tmp),
                state_dir_present=True,
                current_state_dir=Path(tmp),
                default_root=tmp,
                missing_message="Missing",
            )
            self.assertIsNotNone(err)


if __name__ == "__main__":
    unittest.main()
