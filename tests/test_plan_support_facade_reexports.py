"""Backward compatibility tests for plan_support facade (VP-E refactor).

Verifie qu'apres decoupe en sous-modules, le facade `cinesort.app.plan_support`
re-exporte 100% des symboles publics historiques pour preserver tous les
call-sites existants (UI api, tests legacy, run_flow_support, etc.).
"""

from __future__ import annotations

import unittest


class PlanSupportFacadeReexportTests(unittest.TestCase):
    """Tous les symboles publics historiques restent importables depuis plan_support."""

    def test_main_entrypoints_reexported(self) -> None:
        from cinesort.app.plan_support import (
            find_duplicate_targets,
            plan_library,
            plan_multi_roots,
            replan_single_row,
        )

        self.assertTrue(callable(find_duplicate_targets))
        self.assertTrue(callable(plan_library))
        self.assertTrue(callable(plan_multi_roots))
        self.assertTrue(callable(replan_single_row))

    def test_jsonable_helpers_reexported(self) -> None:
        from cinesort.app.plan_support import (
            plan_row_from_jsonable,
            plan_row_to_jsonable,
        )

        # Test smoke pour jsonable round-trip.
        self.assertIsNone(plan_row_from_jsonable(None))
        self.assertIsNone(plan_row_from_jsonable("not a dict"))

    def test_signature_helpers_reexported(self) -> None:
        from cinesort.app.plan_support import (
            cfg_signature_for_incremental,
            folder_signature,
            resolve_incremental_quick_hash,
        )

        self.assertTrue(callable(cfg_signature_for_incremental))
        self.assertTrue(callable(folder_signature))
        self.assertTrue(callable(resolve_incremental_quick_hash))

    def test_stats_helpers_reexported(self) -> None:
        from cinesort.app.plan_support import (
            stats_apply_cached_delta,
            stats_delta_for_cache,
            stats_snapshot_for_cache,
        )

        self.assertTrue(callable(stats_apply_cached_delta))
        self.assertTrue(callable(stats_delta_for_cache))
        self.assertTrue(callable(stats_snapshot_for_cache))

    def test_private_helpers_reexported_for_tests_and_run_flow(self) -> None:
        """Quelques helpers privates etaient utilises par tests/run_flow_support.

        Ces re-exports sont obligatoires : sans eux, des fixtures comme
        `tests/test_pause_cooperative_v77._PlanLibraryContext` ou
        `tests/test_runtime_hard_filter_v77._apply_runtime_hard_filter_to_tmdb_cands`
        casseraient.
        """
        from cinesort.app.plan_support import (
            _ALT_TITLES_FETCH_THRESHOLD,
            _NFO_SIG_CACHE,
            _PLAN_CACHE_VERSION,
            _ROOT_BULK_WARNING_THRESHOLD,
            _apply_integrity_check,
            _apply_not_a_movie_detection,
            _apply_runtime_hard_filter_to_tmdb_cands,
            _apply_subtitle_detection,
            _augment_candidates_from_nfo_imdb,
            _augment_candidates_from_nfo_tmdb_id,
            _build_nfo_candidates,
            _build_resolved_row,
            _build_tmdb_fallback_candidates,
            _build_unresolved_row,
            _classify_and_plan_folder,
            _dedup_and_finalize_phase,
            _detect_cross_root_duplicates,
            _disambiguate_candidates,
            _filter_dossiers_phase,
            _merge_local_candidate_into_ctx,
            _merge_stats,
            _nfo_signature,
            _plan_collection_item,
            _plan_item,
            _plan_single,
            _plan_tv_episode,
            _PlanLibraryContext,
            _rescore_with_alternative_titles,
            _resolve_file_runtime_min,
            _resolve_folder_context,
            _resolve_path_cached,
            _resolve_tmdb_collection,
            _scan_root_phase,
            _store_row_cache,
            _try_apply_folder_cache,
            _try_lookup_row_cache,
        )

        # Verif callable / type sur quelques uns.
        self.assertTrue(callable(_apply_runtime_hard_filter_to_tmdb_cands))
        self.assertTrue(callable(_augment_candidates_from_nfo_imdb))
        self.assertTrue(callable(_augment_candidates_from_nfo_tmdb_id))
        self.assertTrue(callable(_build_nfo_candidates))
        self.assertTrue(callable(_build_resolved_row))
        self.assertTrue(callable(_build_unresolved_row))
        self.assertTrue(callable(_classify_and_plan_folder))
        self.assertTrue(callable(_dedup_and_finalize_phase))
        self.assertTrue(callable(_detect_cross_root_duplicates))
        self.assertTrue(callable(_disambiguate_candidates))
        self.assertTrue(callable(_filter_dossiers_phase))
        self.assertTrue(callable(_merge_local_candidate_into_ctx))
        self.assertTrue(callable(_merge_stats))
        self.assertTrue(callable(_nfo_signature))
        self.assertTrue(callable(_plan_collection_item))
        self.assertTrue(callable(_plan_item))
        self.assertTrue(callable(_plan_single))
        self.assertTrue(callable(_plan_tv_episode))
        self.assertTrue(callable(_rescore_with_alternative_titles))
        self.assertTrue(callable(_resolve_file_runtime_min))
        self.assertTrue(callable(_resolve_folder_context))
        self.assertTrue(callable(_resolve_tmdb_collection))
        self.assertTrue(callable(_scan_root_phase))
        self.assertTrue(callable(_store_row_cache))
        self.assertTrue(callable(_try_apply_folder_cache))
        self.assertTrue(callable(_try_lookup_row_cache))
        self.assertIsInstance(_NFO_SIG_CACHE, dict)
        self.assertIsInstance(_PLAN_CACHE_VERSION, int)
        self.assertIsInstance(_ROOT_BULK_WARNING_THRESHOLD, int)
        self.assertIsInstance(_ALT_TITLES_FETCH_THRESHOLD, float)
        self.assertTrue(isinstance(_PlanLibraryContext, type))
        self.assertTrue(callable(_apply_integrity_check))
        self.assertTrue(callable(_apply_not_a_movie_detection))
        self.assertTrue(callable(_apply_subtitle_detection))
        self.assertTrue(callable(_resolve_path_cached))
        self.assertTrue(callable(_build_tmdb_fallback_candidates))

    def test_legacy_import_aliases_still_work(self) -> None:
        """Patterns historiques d'import : `import cinesort.app.plan_support as plan_support`."""

        import cinesort.app.plan_support as plan_support

        self.assertTrue(callable(plan_support.plan_library))
        self.assertTrue(callable(plan_support.plan_multi_roots))
        self.assertTrue(callable(plan_support.find_duplicate_targets))
        self.assertTrue(callable(plan_support.replan_single_row))

    def test_module_level_log_singleton_present(self) -> None:
        """`plan_support._log` est patche par certains tests; reste accessible."""
        import logging

        from cinesort.app.plan_support import _log

        self.assertIsInstance(_log, logging.Logger)

    def test_module_attribute_patching_legacy_pattern(self) -> None:
        """test_api_bridge_lot3 fait `plan_support.plan_library = slow_plan_library`.

        Ce patch attribute-level doit fonctionner sur le facade comme avant.
        Critique pour les tests d'integration UI api qui patchent ces symboles.
        """
        import cinesort.app.plan_support as plan_support

        original = plan_support.plan_library
        try:
            sentinel = object()
            plan_support.plan_library = sentinel  # type: ignore[assignment]
            self.assertIs(plan_support.plan_library, sentinel)
        finally:
            plan_support.plan_library = original  # type: ignore[assignment]


if __name__ == "__main__":
    unittest.main()
