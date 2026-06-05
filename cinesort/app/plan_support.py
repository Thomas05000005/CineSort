"""Facade backward-compat de plan_support (VP-E refactor, sous-lot VP-6).

Ce module preserve l'API publique historique de `cinesort.app.plan_support`
apres decoupe en 3 sous-modules thematiques :

- `plan_support_core`   : orchestrateur `plan_library`, contexte et helpers
                          de (de)serialisation / signature de fichier.
- `plan_support_replan` : pipeline single-row (`_plan_item`, variantes, TV,
                          row builders, enrichments, cache lookup/store).
- `plan_support_dedup`  : scoring NFO/IMDb/TMDb des candidats, runtime HARD
                          filter, multi-roots et detection de doublons.

Tous les symboles publics historiques de `plan_support` restent importables
ici (`from cinesort.app.plan_support import X`). Le `replan_single_row`,
`find_duplicate_targets`, `plan_library` et `plan_multi_roots` restent les
4 entrees publiques de premier plan.
"""

from __future__ import annotations

# Sentinels utilises directement via `plan_support._log` (logger module-level
# historique). Conserves pour les tests qui patchent ce logger.
import logging as _logging

# Re-exports : symboles tiers qui figuraient sur le module legacy
# (importes par certains tests / sites via `cinesort.app.plan_support.X`).
import cinesort.app.apply_core as _apply_core_mod  # noqa: F401
import cinesort.domain.core as core_mod  # noqa: F401
from cinesort.app._local_candidate import (  # noqa: F401
    LocalCandidate,
    parallel_extract_local_candidates,
    resolve_scan_max_workers,
)
from cinesort.app.apply_core import quick_hash_cache_key, sha1_quick  # noqa: F401

# Re-exports : helpers de (de)serialisation, signatures et orchestrateur.
from cinesort.app.plan_support_core import (
    _NFO_SIG_CACHE,
    _NFO_SIG_CACHE_MAX,
    _PLAN_CACHE_VERSION,
    _ROOT_BULK_WARNING_THRESHOLD,
    _classify_and_plan_folder,
    _dedup_and_finalize_phase,
    _filter_dossiers_phase,
    _merge_local_candidate_into_ctx,
    _nfo_signature,
    _PlanLibraryContext,
    _resolve_path_cached,
    _scan_root_phase,
    _try_apply_folder_cache,
    cfg_signature_for_incremental,
    folder_signature,
    plan_library,
    plan_row_from_jsonable,
    plan_row_to_jsonable,
    resolve_incremental_quick_hash,
    stats_apply_cached_delta,
    stats_delta_for_cache,
    stats_snapshot_for_cache,
)

# Re-exports : scoring + multi-roots + duplicate detection.
from cinesort.app.plan_support_dedup import (
    _ALT_TITLES_FETCH_THRESHOLD,
    _apply_runtime_hard_filter_to_tmdb_cands,
    _augment_candidates_from_nfo_imdb,
    _augment_candidates_from_nfo_tmdb_id,
    _build_nfo_candidates,
    _build_tmdb_fallback_candidates,
    _detect_cross_root_duplicates,
    _merge_stats,
    _rescore_with_alternative_titles,
    _resolve_file_runtime_min,
    find_duplicate_targets,
    plan_multi_roots,
)

# Re-exports : pipeline single-row.
from cinesort.app.plan_support_replan import (
    _apply_integrity_check,
    _apply_not_a_movie_detection,
    _apply_subtitle_detection,
    _build_resolved_row,
    _build_unresolved_row,
    _disambiguate_candidates,
    _plan_collection_item,
    _plan_item,
    _plan_single,
    _plan_tv_episode,
    _resolve_folder_context,
    _resolve_tmdb_collection,
    _store_row_cache,
    _try_lookup_row_cache,
    replan_single_row,
)
from cinesort.domain import duplicate_support as _dup  # noqa: F401
from cinesort.domain.edition_helpers import extract_edition, strip_edition  # noqa: F401
from cinesort.domain.integrity_check import check_header  # noqa: F401
from cinesort.domain.runtime_hard_filter import (  # noqa: F401
    DEFAULT_RUNTIME_HARD_THRESHOLD_MIN,
    WARN_RUNTIME_HARD_EXCLUDED,
    WARN_RUNTIME_HARD_KEPT_VIA_EDITION,
    evaluate_runtime_hard_filter,
)
from cinesort.domain.runtime_matching import score_runtime_delta  # noqa: F401
from cinesort.domain.scan_helpers import (  # noqa: F401
    _NOT_A_MOVIE_THRESHOLD,
    discover_candidate_folders,
    not_a_movie_score,
)
from cinesort.domain.subtitle_helpers import build_subtitle_report  # noqa: F401
from cinesort.domain.title_ambiguity import disambiguate_by_context  # noqa: F401
from cinesort.domain.title_helpers import _norm_for_tokens  # noqa: F401
from cinesort.domain.tv_helpers import parse_tv_info  # noqa: F401
from cinesort.infra.fs_safety import is_dir_accessible, safe_path_exists  # noqa: F401
from cinesort.infra.tmdb_client import TmdbClient  # noqa: F401

_log = _logging.getLogger("cinesort.app.plan_support")

__all__ = [
    # API publique principale
    "plan_library",
    "plan_multi_roots",
    "replan_single_row",
    "find_duplicate_targets",
    # Helpers public-ish (utilises par UI api / tests)
    "plan_row_from_jsonable",
    "plan_row_to_jsonable",
    "cfg_signature_for_incremental",
    "folder_signature",
    "resolve_incremental_quick_hash",
    "stats_snapshot_for_cache",
    "stats_delta_for_cache",
    "stats_apply_cached_delta",
]
