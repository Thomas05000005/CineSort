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
    ("cinesort/app/apply_core.py", "apply_rows"),  # 744 LOC
    ("cinesort/domain/quality_score.py", "compute_quality_score"),  # 500 LOC
    ("cinesort/ui/api/library_support.py", "_build_library_rows"),  # 429 LOC
    ("cinesort/ui/api/apply_support.py", "_execute_apply"),  # 385 LOC
    ("cinesort/domain/scan_helpers.py", "discover_candidate_folders"),  # 382 LOC
    ("cinesort/ui/api/apply_support.py", "_apply_changes_body"),  # 369 LOC
    ("cinesort/ui/api/dashboard_support.py", "_build_dashboard_section"),  # 360 LOC
    ("cinesort/ui/api/apply_support.py", "_execute_undo_ops"),  # 335 LOC
    ("cinesort/ui/api/run_flow_support.py", "_build_plan_job_fn"),  # 304 LOC
    ("cinesort/ui/api/perceptual_support.py", "_execute_perceptual_analysis"),  # 298 LOC
    ("cinesort/app/job_runner.py", "_run_worker"),  # 292 LOC
    ("cinesort/app/apply_rollback.py", "_revert_one_op"),  # 275 LOC
    ("cinesort/domain/librarian.py", "generate_suggestions"),  # 272 LOC
    ("cinesort/ui/api/run_flow_support.py", "job_fn"),  # 271 LOC
    ("cinesort/app/runtime_probe_check.py", "cross_check_rows_with_probe"),  # 258 LOC
    ("cinesort/app/plan_support_replan.py", "_plan_item"),  # 254 LOC
    ("cinesort/ui/api/runtime_support.py", "get_or_create_infra"),  # 238 LOC
    ("cinesort/app/apply_core.py", "apply_tv_episode"),  # 237 LOC
    ("cinesort/ui/api/history_support.py", "_get_history_stats_impl"),  # 237 LOC
    ("cinesort/app/jellyfin_sync.py", "restore_watched"),  # 231 LOC
    ("cinesort/domain/duplicate_support.py", "find_duplicate_targets"),  # 225 LOC
    ("cinesort/domain/tiers_helpers.py", "apply_tier_hierarchy"),  # 223 LOC
    ("cinesort/app/apply_core.py", "apply_collection_item"),  # 217 LOC
    ("cinesort/app/apply_core.py", "move_duplicate_losers_to_user_decided"),  # 214 LOC
    ("cinesort/app/apply_core.py", "apply_single"),  # 212 LOC
    ("cinesort/domain/scan_helpers.py", "_walk"),  # 211 LOC
    ("cinesort/infra/omdb_client.py", "test_connection"),  # 210 LOC
    ("cinesort/infra/probe/service.py", "probe_file"),  # 204 LOC
    ("cinesort/ui/api/film_support.py", "_get_film_full_impl"),  # 197 LOC
    ("cinesort/ui/api/dashboard_support.py", "get_global_stats"),  # 196 LOC
    ("cinesort/app/apply_core.py", "move_file_with_collision_policy"),  # 195 LOC
    ("cinesort/ui/api/quality_report_support.py", "get_quality_report"),  # 195 LOC
    ("cinesort/ui/api/run_flow_support.py", "_get_status_impl"),  # 194 LOC
    ("cinesort/ui/api/apply_support.py", "_summarize_apply"),  # 191 LOC
    ("cinesort/domain/perceptual/audio_perceptual.py", "analyze_audio_perceptual"),  # 187 LOC
    ("cinesort/ui/api/apply_support.py", "_build_apply_preview_body"),  # 187 LOC
    ("cinesort/ui/api/library_support.py", "_row_matches"),  # 187 LOC
    ("cinesort/app/apply_core.py", "move_marked_for_deletion_to_bucket"),  # 185 LOC
    ("cinesort/ui/api/apply_support.py", "undo_selected_rows"),  # 184 LOC
    ("cinesort/ui/api/library_actions_support.py", "_rematch_tmdb_and_update_plan"),  # 184 LOC
    ("cinesort/infra/integrations/poster_proxy.py", "fetch_and_cache"),  # 180 LOC
    ("cinesort/domain/quality_score.py", "_score_video"),  # 175 LOC
    ("cinesort/ui/api/dashboard_support.py", "_compute_active_insights"),  # 175 LOC
    ("cinesort/domain/perceptual/comparison.py", "build_comparison_report"),  # 174 LOC
    ("cinesort/domain/quality_score.py", "_build_quality_presets_catalog"),  # 167 LOC
    ("cinesort/app/jellyfin_validation.py", "build_sync_report"),  # 165 LOC
    ("cinesort/ui/api/dashboard_support.py", "get_dashboard"),  # 165 LOC
    ("cinesort/app/plan_support_core.py", "_filter_dossiers_phase"),  # 163 LOC
    ("cinesort/domain/subtitle_helpers.py", "build_subtitle_report"),  # 161 LOC
    ("cinesort/ui/api/perceptual_support.py", "get_perceptual_compare_frames"),  # 157 LOC
    ("cinesort/app/apply_batches_reconciliation.py", "reconcile_pending_batches"),  # 155 LOC
    ("cinesort/app/apply_rollback.py", "rollback_forward"),  # 155 LOC
    ("cinesort/domain/duplicate_multi_signal.py", "_phase_b_fuzzy_title"),  # 154 LOC
    ("cinesort/ui/api/library_timeline_support.py", "_get_library_timeline_impl"),  # 153 LOC
    ("cinesort/ui/api/settings_support.py", "write_settings"),  # 152 LOC
    ("cinesort/domain/perceptual/composite_score.py", "detect_cross_verdicts"),  # 150 LOC
    ("cinesort/infra/rest_server.py", "_handle_post"),  # 150 LOC
    ("cinesort/ui/api/apply_support.py", "_validate_apply"),  # 150 LOC
    ("cinesort/ui/api/perceptual_support.py", "get_perceptual_compare_audio"),  # 149 LOC
    ("cinesort/infra/probe/_normalize_merge.py", "_merge_probes"),  # 148 LOC
    ("cinesort/app/job_runner.py", "start_job"),  # 147 LOC
    ("cinesort/domain/perceptual/audio_fingerprint.py", "_run_ffmpeg_pipe_fpcalc"),  # 146 LOC
    ("cinesort/ui/api/export_support.py", "export_full_library"),  # 146 LOC
    ("cinesort/app/plan_support_replan.py", "_build_resolved_row"),  # 145 LOC
    ("cinesort/app/quarantine_ttl.py", "list_review_bucket_files"),  # 145 LOC
    ("cinesort/ui/api/perceptual_support.py", "compare_perceptual"),  # 145 LOC
    ("cinesort/infra/db/nas_validation.py", "run_nas_benchmark"),  # 143 LOC
    ("cinesort/app/apply_core.py", "merge_dir_safe"),  # 141 LOC
    ("cinesort/infra/db/connection.py", "connect_sqlite"),  # 140 LOC
    ("cinesort/domain/perceptual/audio_fingerprint.py", "compute_audio_fingerprint"),  # 136 LOC
    ("cinesort/ui/api/apply_support.py", "_cleanup_apply"),  # 136 LOC
    ("cinesort/ui/api/perceptual_support.py", "_video_task"),  # 136 LOC
    ("cinesort/domain/film_history.py", "get_film_timeline"),  # 133 LOC
    ("cinesort/domain/perceptual/composite_score_v2.py", "apply_contextual_adjustments"),  # 133 LOC
    ("cinesort/app/plugin_hooks.py", "_run_plugin"),  # 132 LOC
    ("cinesort/app/plan_support_replan.py", "_plan_tv_episode"),  # 131 LOC
    ("cinesort/infra/probe/_normalize_ffprobe.py", "_extract_ffprobe"),  # 131 LOC
    ("cinesort/ui/api/quality_report_support.py", "_probe_and_score"),  # 131 LOC
    ("cinesort/ui/api/run_flow_support.py", "_persist_duplicate_winner"),  # 131 LOC
    ("cinesort/ui/api/run_flow_support.py", "_validate_and_init_plan_context"),  # 130 LOC
    ("cinesort/app/move_reconciliation.py", "reconcile_pending_moves"),  # 128 LOC
    ("cinesort/infra/jellyfin_client.py", "get_all_movies"),  # 128 LOC
    ("cinesort/ui/api/tmdb_support.py", "search_tmdb"),  # 128 LOC
    ("cinesort/app/plan_support_core.py", "_classify_and_plan_folder"),  # 127 LOC
    ("cinesort/infra/rest_server.py", "_handle_get"),  # 125 LOC
    ("cinesort/app/quarantine_ttl.py", "purge_review_bucket"),  # 123 LOC
    ("cinesort/domain/perceptual/av1_grain_metadata.py", "extract_av1_film_grain_params"),  # 123 LOC
    ("cinesort/domain/core.py", "build_candidates_from_tmdb"),  # 122 LOC
    ("cinesort/domain/release_name_parser.py", "parse_release_name"),  # 122 LOC
    ("cinesort/ui/api/library_support.py", "set_film_tmdb_candidate"),  # 122 LOC
    ("cinesort/domain/calibration.py", "suggest_weight_adjustment"),  # 121 LOC
    ("cinesort/domain/perceptual/grain_classifier.py", "classify_grain_nature"),  # 121 LOC
    ("cinesort/ui/api/apply_support.py", "build_undo_preview_payload"),  # 121 LOC
    ("cinesort/ui/api/library_actions_support.py", "export_films"),  # 121 LOC
    ("cinesort/infra/db/sqlite_store.py", "_attempt_auto_restore"),  # 120 LOC
    ("cinesort/ui/api/library_podiums_support.py", "_get_library_podiums_impl"),  # 120 LOC
    ("cinesort/infra/db/repositories/decisions.py", "upgrade_deferred_to_accepted"),  # 118 LOC
    ("cinesort/app/watchlist.py", "compare_watchlist"),  # 117 LOC
    ("cinesort/domain/scene_parser.py", "parse_scene_title"),  # 117 LOC
    ("cinesort/domain/duplicate_compare.py", "compare_by_criteria"),  # 116 LOC
    ("cinesort/domain/video_hash.py", "extract_video_thumbnails"),  # 116 LOC
    ("cinesort/infra/integrations/poster_proxy.py", "serve_poster"),  # 114 LOC
    ("cinesort/ui/api/apply_support.py", "_execute_and_finalize_undo"),  # 114 LOC
    ("cinesort/ui/api/perceptual_support.py", "_validate_and_load_context"),  # 114 LOC
    ("cinesort/ui/api/profiles_support_import_export.py", "get_breakdown_5_axes"),  # 114 LOC
    ("cinesort/ui/api/tmdb_support.py", "enrich_tmdb_ids_by_title"),  # 114 LOC
    ("cinesort/infra/db/sqlite_store.py", "_bootstrap_schema_latest"),  # 112 LOC
    ("cinesort/ui/api/settings_support.py", "_save_settings_payload_locked"),  # 112 LOC
    ("cinesort/ui/api/settings_support.py", "read_settings"),  # 110 LOC
    ("cinesort/app/plan_support_dedup.py", "_augment_candidates_from_nfo_tmdb_id"),  # 109 LOC
    ("cinesort/infra/tmdb_client.py", "purge_expired_tmdb_cache"),  # 109 LOC
    ("cinesort/ui/api/profiles_support_import_export.py", "_yaml_parse_lines"),  # 109 LOC
    ("cinesort/domain/perceptual/audio_perceptual.py", "_compute_audio_score"),  # 108 LOC
    ("cinesort/ui/api/quality_audit_support.py", "_recompute_worker"),  # 108 LOC
    ("cinesort/ui/api/settings_support.py", "build_cfg_from_settings"),  # 108 LOC
    ("cinesort/app/watcher.py", "_snapshot_root"),  # 107 LOC
    ("cinesort/domain/genre_rules.py", "compute_genre_adjustments"),  # 107 LOC
    ("cinesort/domain/quality_score.py", "_score_extras"),  # 107 LOC
    ("cinesort/domain/perceptual/audio_perceptual.py", "analyze_clipping_segments"),  # 106 LOC
    ("cinesort/infra/db/migration_manager.py", "_split_sql_statements"),  # 106 LOC
    ("cinesort/infra/db/pragma_profile.py", "_record_pragma_history"),  # 106 LOC
    ("cinesort/ui/api/quality_audit_support.py", "get_history"),  # 106 LOC
    ("cinesort/domain/quality_score.py", "_apply_custom_rules_helper"),  # 105 LOC
    ("cinesort/infra/plex_client.py", "get_movies"),  # 105 LOC
    ("cinesort/infra/probe/tools_manager.py", "_build_tool_status"),  # 105 LOC
    ("cinesort/ui/api/perceptual_support.py", "analyze_perceptual_batch"),  # 105 LOC
    ("cinesort/app/export_support.py", "export_nfo_for_run"),  # 104 LOC
    ("cinesort/ui/api/dashboard_support.py", "_build_row_payload"),  # 104 LOC
    ("cinesort/app/apply_core.py", "quarantine_row"),  # 103 LOC
    ("cinesort/app/cleanup.py", "preview_cleanup_residual_folders"),  # 102 LOC
    ("cinesort/app/radarr_sync.py", "build_radarr_report"),  # 102 LOC
    ("cinesort/infra/rest_server.py", "start"),  # 102 LOC
    ("cinesort/ui/api/apply_support.py", "build_undo_by_row_preview"),  # 102 LOC
    ("cinesort/ui/api/dashboard_support.py", "compose_score_explanation"),  # 102 LOC
    ("cinesort/domain/perceptual/grain_analysis.py", "analyze_grain_v2"),  # 101 LOC
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
    offenders = [(rel, name, loc) for rel, name, loc in _iter_oversized_functions() if (rel, name) not in ALLOWLIST]
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
        "renommee sous le seuil) — les retirer de ALLOWLIST : " + ", ".join(f"{rel}:{name}" for rel, name in stale)
    )
