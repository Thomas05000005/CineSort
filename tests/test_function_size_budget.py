"""Garde-fou anti-regression sur la taille des fonctions (issue #677).

Contexte
--------
L'inventaire des fonctions > 100 lignes (#215) derive a la hausse en silence
apres chaque chantier de decoupe : le pattern « extraire le corps dans un
helper `_body` » reduit la fonction *publique* mais recree un helper prive
tout aussi gros qui ne retombe jamais dans le suivi manuel de l'audit-bot.
Constat au re-audit transverse 2026-07-19 : **117 fonctions > 100 LOC** contre
14 documentees le 17 mai puis ~22 le 28 juin — sans qu'aucun signal CI ne se
declenche.

Strategie (issue #677, Option B — zero dependance)
--------------------------------------------------
On gele l'existant dans une allowlist `(chemin, nom)` et on **bloque uniquement
les regressions** : toute *nouvelle* fonction > MAX_LINES, ou toute fonction
existante non listee qui franchit le seuil, casse la CI. Le mainteneur doit
alors soit decouper la fonction, soit l'ajouter explicitement a l'allowlist
(choix visible en review). On resorbe l'allowlist au fil des PR de decoupe
(#215) en la vidant progressivement, puis on pourra abaisser MAX_LINES.

Ce test ne mesure PAS la complexite cyclomatique (cf `radon cc` en Option A) :
il borne la seule metrique LOC, la plus simple a comprendre en review.
"""

from __future__ import annotations

import ast
import pathlib

# Seuil glissant. On demarre au seuil historique de l'audit (100). Objectif :
# faire descendre MAX_LINES par paliers (150 -> 120 -> 100) a mesure que
# l'allowlist se vide via les PR de decoupe #215.
MAX_LINES = 100

# Racine du package a auditer (le dossier de tests interne est exclu).
_PACKAGE_ROOT = pathlib.Path(__file__).resolve().parent.parent / "cinesort"

# ---------------------------------------------------------------------------
# Allowlist gelee au 2026-07-19 (117 fonctions). Chaque entree = (chemin POSIX
# relatif a la racine du repo, nom de la fonction). Le commentaire indique la
# taille au gel : il sert de reference pour prioriser la resorption (#215),
# il n'est PAS verifie (une fonction allowlistee peut grossir — c'est la limite
# assumee de l'approche « freeze existant, bloque le nouveau »).
#
# NE PAS ajouter d'entree sans justification en review : l'ajout d'une ligne
# ici est un signal explicite qu'on accepte une fonction > MAX_LINES.
# ---------------------------------------------------------------------------
ALLOWLIST: set[tuple[str, str]] = {
    ("cinesort/app/apply_core.py", "apply_rows"),  # 598 LOC
    ("cinesort/domain/quality_score.py", "compute_quality_score"),  # 435 LOC
    ("cinesort/ui/api/dashboard_support.py", "_build_dashboard_section"),  # 360 LOC
    ("cinesort/ui/api/apply_support.py", "_execute_apply"),  # 350 LOC
    ("cinesort/ui/api/library_support.py", "_build_library_rows"),  # 347 LOC
    ("cinesort/ui/api/run_flow_support.py", "_build_plan_job_fn"),  # 311 LOC
    ("cinesort/ui/api/perceptual_support.py", "_execute_perceptual_analysis"),  # 295 LOC
    ("cinesort/app/job_runner.py", "_run_worker"),  # 286 LOC
    ("cinesort/ui/api/apply_support.py", "_apply_changes_body"),  # 286 LOC
    ("cinesort/ui/api/run_flow_support.py", "job_fn"),  # 278 LOC
    ("cinesort/app/apply_rollback.py", "_revert_one_op"),  # 267 LOC
    ("cinesort/ui/api/apply_support.py", "_execute_undo_ops"),  # 258 LOC
    ("cinesort/ui/api/history_support.py", "_get_history_stats_impl"),  # 246 LOC
    ("cinesort/app/plan_support_replan.py", "_plan_item"),  # 245 LOC
    ("cinesort/domain/librarian.py", "generate_suggestions"),  # 233 LOC
    ("cinesort/ui/api/runtime_support.py", "get_or_create_infra"),  # 225 LOC
    ("cinesort/domain/duplicate_support.py", "find_duplicate_targets"),  # 216 LOC
    ("cinesort/app/apply_core.py", "move_duplicate_losers_to_user_decided"),  # 208 LOC
    ("cinesort/domain/scan_helpers.py", "discover_candidate_folders"),  # 205 LOC
    ("cinesort/ui/api/dashboard_support.py", "get_global_stats"),  # 205 LOC
    ("cinesort/app/apply_core.py", "apply_single"),  # 204 LOC
    ("cinesort/infra/probe/service.py", "probe_file"),  # 204 LOC
    ("cinesort/app/runtime_probe_check.py", "cross_check_rows_with_probe"),  # 198 LOC
    ("cinesort/infra/omdb_client.py", "test_connection"),  # 198 LOC
    ("cinesort/ui/api/film_support.py", "_get_film_full_impl"),  # 198 LOC
    ("cinesort/ui/api/apply_support.py", "_build_apply_preview_body"),  # 194 LOC
    ("cinesort/domain/tiers_helpers.py", "apply_tier_hierarchy"),  # 193 LOC
    ("cinesort/domain/perceptual/audio_perceptual.py", "analyze_audio_perceptual"),  # 191 LOC
    ("cinesort/app/apply_core.py", "apply_collection_item"),  # 190 LOC
    ("cinesort/ui/api/library_actions_support.py", "_rematch_tmdb_and_update_plan"),  # 188 LOC
    ("cinesort/ui/api/quality_report_support.py", "get_quality_report"),  # 188 LOC
    ("cinesort/app/apply_core.py", "move_file_with_collision_policy"),  # 187 LOC
    ("cinesort/ui/api/library_support.py", "_row_matches"),  # 186 LOC
    ("cinesort/ui/api/apply_support.py", "_summarize_apply"),  # 184 LOC
    ("cinesort/app/apply_core.py", "move_marked_for_deletion_to_bucket"),  # 181 LOC
    ("cinesort/domain/quality_score.py", "_score_video"),  # 180 LOC
    ("cinesort/infra/integrations/poster_proxy.py", "fetch_and_cache"),  # 180 LOC
    ("cinesort/app/apply_core.py", "apply_tv_episode"),  # 178 LOC
    ("cinesort/ui/api/run_flow_support.py", "_get_status_impl"),  # 177 LOC
    ("cinesort/ui/api/dashboard_support.py", "_compute_active_insights"),  # 172 LOC
    ("cinesort/ui/api/apply_support.py", "undo_selected_rows"),  # 171 LOC
    ("cinesort/ui/api/dashboard_support.py", "get_dashboard"),  # 168 LOC
    ("cinesort/domain/quality_score.py", "_build_quality_presets_catalog"),  # 167 LOC
    ("cinesort/app/plan_support_core.py", "_filter_dossiers_phase"),  # 165 LOC
    ("cinesort/app/apply_rollback.py", "rollback_forward"),  # 164 LOC
    ("cinesort/app/jellyfin_sync.py", "restore_watched"),  # 163 LOC
    ("cinesort/ui/api/perceptual_support.py", "get_perceptual_compare_frames"),  # 158 LOC
    ("cinesort/app/jellyfin_validation.py", "build_sync_report"),  # 152 LOC
    ("cinesort/ui/api/settings_support.py", "write_settings"),  # 152 LOC
    ("cinesort/ui/api/perceptual_support.py", "get_perceptual_compare_audio"),  # 149 LOC
    ("cinesort/domain/perceptual/audio_fingerprint.py", "_run_ffmpeg_pipe_fpcalc"),  # 146 LOC
    ("cinesort/app/quarantine_ttl.py", "list_review_bucket_files"),  # 145 LOC
    ("cinesort/ui/api/perceptual_support.py", "compare_perceptual"),  # 145 LOC
    ("cinesort/ui/api/library_actions_support.py", "export_films"),  # 144 LOC
    ("cinesort/infra/db/nas_validation.py", "run_nas_benchmark"),  # 139 LOC
    ("cinesort/infra/probe/_normalize_merge.py", "_merge_probes"),  # 139 LOC
    ("cinesort/domain/duplicate_multi_signal.py", "_phase_b_fuzzy_title"),  # 138 LOC
    ("cinesort/domain/perceptual/comparison.py", "build_comparison_report"),  # 137 LOC
    ("cinesort/domain/perceptual/audio_fingerprint.py", "compute_audio_fingerprint"),  # 136 LOC
    ("cinesort/infra/rest_server.py", "_handle_post"),  # 135 LOC
    ("cinesort/ui/api/library_timeline_support.py", "_get_library_timeline_impl"),  # 135 LOC
    ("cinesort/domain/perceptual/composite_score.py", "detect_cross_verdicts"),  # 134 LOC
    ("cinesort/infra/probe/_normalize_ffprobe.py", "_extract_ffprobe"),  # 133 LOC
    ("cinesort/ui/api/perceptual_support.py", "_video_task"),  # 133 LOC
    ("cinesort/domain/perceptual/composite_score_v2.py", "apply_contextual_adjustments"),  # 131 LOC
    ("cinesort/infra/jellyfin_client.py", "get_all_movies"),  # 131 LOC
    ("cinesort/app/plan_support_core.py", "_classify_and_plan_folder"),  # 129 LOC
    ("cinesort/app/plugin_hooks.py", "_run_plugin"),  # 129 LOC
    ("cinesort/infra/rest_server.py", "_handle_get"),  # 128 LOC
    ("cinesort/app/quarantine_ttl.py", "purge_review_bucket"),  # 127 LOC
    ("cinesort/app/plan_support_replan.py", "_build_resolved_row"),  # 126 LOC
    ("cinesort/ui/api/apply_support.py", "_validate_apply"),  # 126 LOC
    ("cinesort/domain/film_history.py", "get_film_timeline"),  # 122 LOC
    ("cinesort/domain/perceptual/av1_grain_metadata.py", "extract_av1_film_grain_params"),  # 122 LOC
    ("cinesort/ui/api/library_support.py", "set_film_tmdb_candidate"),  # 122 LOC
    ("cinesort/ui/api/profiles_support_import_export.py", "get_breakdown_5_axes"),  # 122 LOC
    ("cinesort/domain/perceptual/grain_classifier.py", "classify_grain_nature"),  # 121 LOC
    ("cinesort/ui/api/apply_support.py", "build_undo_preview_payload"),  # 121 LOC
    ("cinesort/domain/scan_helpers.py", "_walk"),  # 120 LOC
    ("cinesort/infra/integrations/poster_proxy.py", "serve_poster"),  # 118 LOC
    ("cinesort/ui/api/tmdb_support.py", "search_tmdb"),  # 118 LOC
    ("cinesort/app/watchlist.py", "compare_watchlist"),  # 117 LOC
    ("cinesort/domain/duplicate_compare.py", "compare_by_criteria"),  # 116 LOC
    ("cinesort/domain/video_hash.py", "extract_video_thumbnails"),  # 116 LOC
    ("cinesort/ui/api/run_flow_support.py", "_validate_and_init_plan_context"),  # 114 LOC
    ("cinesort/ui/api/library_podiums_support.py", "_get_library_podiums_impl"),  # 113 LOC
    ("cinesort/ui/api/quality_report_support.py", "_probe_and_score"),  # 113 LOC
    ("cinesort/domain/scene_parser.py", "parse_scene_title"),  # 112 LOC
    ("cinesort/ui/api/settings_support.py", "_save_settings_payload_locked"),  # 112 LOC
    ("cinesort/ui/api/settings_support.py", "read_settings"),  # 112 LOC
    ("cinesort/ui/api/apply_support.py", "_execute_and_finalize_undo"),  # 111 LOC
    ("cinesort/ui/api/export_support.py", "export_full_library"),  # 111 LOC
    ("cinesort/infra/db/connection.py", "connect_sqlite"),  # 110 LOC
    ("cinesort/infra/db/sqlite_store.py", "_bootstrap_schema_latest"),  # 110 LOC
    ("cinesort/ui/api/settings_support.py", "build_cfg_from_settings"),  # 110 LOC
    ("cinesort/ui/api/tmdb_support.py", "enrich_tmdb_ids_by_title"),  # 110 LOC
    ("cinesort/app/plan_support_dedup.py", "_augment_candidates_from_nfo_tmdb_id"),  # 109 LOC
    ("cinesort/domain/core.py", "build_candidates_from_tmdb"),  # 109 LOC
    ("cinesort/domain/release_name_parser.py", "parse_release_name"),  # 109 LOC
    ("cinesort/ui/api/profiles_support_import_export.py", "_yaml_parse_lines"),  # 109 LOC
    ("cinesort/domain/quality_score.py", "_score_extras"),  # 108 LOC
    ("cinesort/infra/db/migration_manager.py", "_split_sql_statements"),  # 108 LOC
    ("cinesort/app/job_runner.py", "start_job"),  # 107 LOC
    ("cinesort/app/radarr_sync.py", "build_radarr_report"),  # 107 LOC
    ("cinesort/ui/api/apply_support.py", "_cleanup_apply"),  # 107 LOC
    ("cinesort/ui/api/quality_audit_support.py", "get_history"),  # 106 LOC
    ("cinesort/app/apply_core.py", "merge_dir_safe"),  # 105 LOC
    ("cinesort/infra/probe/tools_manager.py", "_build_tool_status"),  # 105 LOC
    ("cinesort/ui/api/dashboard_support.py", "_build_row_payload"),  # 104 LOC
    ("cinesort/app/apply_batches_reconciliation.py", "reconcile_pending_batches"),  # 102 LOC
    ("cinesort/app/cleanup.py", "preview_cleanup_residual_folders"),  # 102 LOC
    ("cinesort/infra/rest_server.py", "start"),  # 102 LOC
    ("cinesort/app/move_reconciliation.py", "reconcile_pending_moves"),  # 101 LOC
    ("cinesort/app/plan_support_dedup.py", "_apply_runtime_hard_filter_to_tmdb_cands"),  # 101 LOC
    ("cinesort/domain/perceptual/grain_analysis.py", "analyze_grain_v2"),  # 101 LOC
    ("cinesort/ui/api/perceptual_support.py", "_validate_and_load_context"),  # 101 LOC
    ("cinesort/ui/api/profiles_support_crud.py", "save_profile"),  # 101 LOC
}


def _iter_oversized_functions():
    """Yield (rel_path, func_name, loc) pour chaque fonction > MAX_LINES."""
    repo_root = _PACKAGE_ROOT.parent
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        # Exclut le dossier de tests interne au package.
        if "tests" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = path.relative_to(repo_root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.end_lineno is None:
                    continue
                loc = node.end_lineno - node.lineno + 1
                if loc > MAX_LINES:
                    yield rel, node.name, loc


def test_no_new_oversized_function():
    """Aucune fonction > MAX_LINES hors allowlist gelee (#677)."""
    offenders = [
        (rel, name, loc)
        for rel, name, loc in _iter_oversized_functions()
        if (rel, name) not in ALLOWLIST
    ]
    assert not offenders, (
        f"{len(offenders)} nouvelle(s) fonction(s) > {MAX_LINES} LOC hors allowlist. "
        "Decouper la fonction, ou (si justifie) l'ajouter a ALLOWLIST dans "
        "tests/test_function_size_budget.py (visible en review). Detail : "
        + ", ".join(f"{rel}:{name} ({loc} LOC)" for rel, name, loc in offenders)
    )


def test_allowlist_has_no_stale_entries():
    """Une entree d'allowlist qui n'est plus > MAX_LINES doit etre retiree.

    Empeche l'allowlist de se figer avec des entrees perimees apres une PR de
    decoupe (#215) : quand une fonction repasse sous le seuil, on veut que sa
    ligne d'allowlist soit supprimee pour que le progres reste visible.
    """
    current = {(rel, name) for rel, name, _ in _iter_oversized_functions()}
    stale = sorted(ALLOWLIST - current)
    assert not stale, (
        f"{len(stale)} entree(s) d'allowlist perimee(s) (fonction decoupee ou "
        "renommee sous le seuil) — les retirer de ALLOWLIST : "
        + ", ".join(f"{rel}:{name}" for rel, name in stale)
    )
