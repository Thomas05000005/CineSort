"""Smoke regression tests for plan_support decoupe (VP-E refactor).

Verifie qu'apres decoupe en sous-modules (`plan_support_core`,
`plan_support_replan`, `plan_support_dedup`) :
- les sous-modules s'importent independamment ;
- les fonctions publiques principales restent appelables ;
- une mini-bibliotheque scan + multi-roots fonctionne bout-en-bout (smoke
  proxy 853 films : on valide la pipeline sur fixture controlee).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cinesort.domain.core as core


class PlanSupportModulesImportTests(unittest.TestCase):
    """Chaque sous-module se charge independamment et expose son API."""

    def test_core_module_imports_and_exposes_plan_library(self) -> None:
        from cinesort.app import plan_support_core

        self.assertTrue(hasattr(plan_support_core, "plan_library"))
        self.assertTrue(hasattr(plan_support_core, "_PlanLibraryContext"))
        self.assertTrue(hasattr(plan_support_core, "plan_row_to_jsonable"))
        self.assertTrue(hasattr(plan_support_core, "plan_row_from_jsonable"))
        self.assertTrue(hasattr(plan_support_core, "cfg_signature_for_incremental"))
        self.assertTrue(hasattr(plan_support_core, "folder_signature"))
        self.assertTrue(hasattr(plan_support_core, "resolve_incremental_quick_hash"))
        self.assertTrue(hasattr(plan_support_core, "stats_snapshot_for_cache"))

    def test_replan_module_imports_and_exposes_pipeline(self) -> None:
        from cinesort.app import plan_support_replan

        self.assertTrue(hasattr(plan_support_replan, "replan_single_row"))
        self.assertTrue(hasattr(plan_support_replan, "_plan_item"))
        self.assertTrue(hasattr(plan_support_replan, "_plan_single"))
        self.assertTrue(hasattr(plan_support_replan, "_plan_collection_item"))
        self.assertTrue(hasattr(plan_support_replan, "_plan_tv_episode"))
        self.assertTrue(hasattr(plan_support_replan, "_build_resolved_row"))
        self.assertTrue(hasattr(plan_support_replan, "_build_unresolved_row"))

    def test_dedup_module_imports_and_exposes_scoring_and_dup(self) -> None:
        from cinesort.app import plan_support_dedup

        self.assertTrue(hasattr(plan_support_dedup, "find_duplicate_targets"))
        self.assertTrue(hasattr(plan_support_dedup, "plan_multi_roots"))
        self.assertTrue(hasattr(plan_support_dedup, "_build_nfo_candidates"))
        self.assertTrue(hasattr(plan_support_dedup, "_augment_candidates_from_nfo_imdb"))
        self.assertTrue(hasattr(plan_support_dedup, "_augment_candidates_from_nfo_tmdb_id"))
        self.assertTrue(hasattr(plan_support_dedup, "_build_tmdb_fallback_candidates"))
        self.assertTrue(hasattr(plan_support_dedup, "_apply_runtime_hard_filter_to_tmdb_cands"))
        self.assertTrue(hasattr(plan_support_dedup, "_detect_cross_root_duplicates"))


class PlanSupportSmokeTests(unittest.TestCase):
    """Smoke proxy : plan_library + find_duplicate_targets + plan_multi_roots
    sur fixture controlee. Verifie 0 regression structurelle (rows + stats
    + dup detection) apres refactor.
    """

    def _make_movie_folder(self, root: Path, title: str, year: int) -> Path:
        folder = root / f"{title} ({year})"
        folder.mkdir(parents=True, exist_ok=True)
        video = folder / f"{title} ({year}).mkv"
        # 11 MB pour passer au-dessus de MIN_VIDEO_BYTES (10 MB)
        video.write_bytes(b"\x00" * (11 * 1024 * 1024))
        return folder

    def test_plan_library_scan_basic_films(self) -> None:
        from cinesort.app.plan_support_core import plan_library

        with tempfile.TemporaryDirectory(prefix="plan_smoke_") as tmp:
            root = Path(tmp)
            self._make_movie_folder(root, "Dune", 1984)
            self._make_movie_folder(root, "Dune", 2021)
            self._make_movie_folder(root, "Inception", 2010)

            rows, stats = plan_library(
                core.Config(root=root, enable_tmdb=False),
                tmdb=None,
                log=lambda *_args, **_kw: None,
                progress=lambda *_args, **_kw: None,
            )
            self.assertEqual(len(rows), 3)
            self.assertEqual(stats.planned_rows, 3)
            self.assertEqual(stats.singles_seen, 3)

    def test_replan_single_row_pipeline(self) -> None:
        from cinesort.app.plan_support_replan import replan_single_row

        with tempfile.TemporaryDirectory(prefix="replan_smoke_") as tmp:
            root = Path(tmp)
            folder = self._make_movie_folder(root, "Matrix", 1999)
            video = next(folder.glob("*.mkv"))
            cfg = core.Config(root=root, enable_tmdb=False)
            row = replan_single_row(cfg, folder, video, kind="single")
            self.assertIsNotNone(row)
            self.assertEqual(row.kind, "single")

    def test_plan_multi_roots_dedup_cross_root(self) -> None:
        from cinesort.app.plan_support_dedup import plan_multi_roots

        with (
            tempfile.TemporaryDirectory(prefix="multi_a_") as tmp_a,
            tempfile.TemporaryDirectory(prefix="multi_b_") as tmp_b,
        ):
            root_a = Path(tmp_a)
            root_b = Path(tmp_b)
            self._make_movie_folder(root_a, "Inception", 2010)
            self._make_movie_folder(root_b, "Inception", 2010)

            def build_cfg(r: Path) -> core.Config:
                return core.Config(root=r, enable_tmdb=False)

            rows, stats = plan_multi_roots(
                [root_a, root_b],
                build_cfg=build_cfg,
                tmdb=None,
                log=lambda *_args, **_kw: None,
                progress=lambda *_args, **_kw: None,
            )
            self.assertEqual(len(rows), 2)
            self.assertEqual(stats.planned_rows, 2)
            dup_flags = [r for r in rows if "duplicate_cross_root" in (r.warning_flags or [])]
            self.assertEqual(len(dup_flags), 2)

    def test_find_duplicate_targets_callable_from_dedup(self) -> None:
        from cinesort.app.plan_support_dedup import find_duplicate_targets

        with tempfile.TemporaryDirectory(prefix="dup_smoke_") as tmp:
            root = Path(tmp)
            cfg = core.Config(root=root, enable_tmdb=False)
            # No rows : la fonction doit retourner un dict structure.
            result = find_duplicate_targets(cfg, [], {})
            self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
