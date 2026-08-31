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
# PLAFONDS gelés : (chemin POSIX relatif a la racine du repo, nom) -> taille
# MAXIMALE toleree, en lignes.
#
# Ce fichier a longtemps porte une simple allowlist, et documentait lui-meme sa
# limite : « une fonction allowlistee peut grossir — c'est la limite assumee ».
# Elle n'etait pas theorique. MESURE du 2026-08-06 : 136 fonctions depassent le
# seuil, la plus grosse — `apply_rows`, sur le chemin qui DEPLACE les films —
# fait 744 lignes. Rien n'empechait qu'elle en fasse 1 500.
#
# Les tailles etaient d'ailleurs deja la, en commentaire (`# 744 LOC`) : elles
# n'etaient simplement jamais verifiees. Elles sont desormais la VALEUR du
# dictionnaire, donc un plafond. Elles ont ete REMESUREES sur l'arbre, pas
# reprises des commentaires.
#
# Le cliquet tourne donc dans les deux sens :
#   - une NOUVELLE fonction > MAX_LINES est refusee (test_no_new_...) ;
#   - une fonction listee qui GROSSIT est refusee (test_..._ne_grossissent_pas) ;
#   - une fonction listee repassee sous le seuil doit sortir (test_..._stale).
#
# Faire monter un plafond est possible, mais devient une ligne de diff visible
# en review — c'est tout l'objet.
# ---------------------------------------------------------------------------
PLAFONDS: dict[tuple[str, str], int] = {
    # 744 -> 773 : ultra-audit 2026-08. Deux clauses de la boucle par-row
    # comptaient l'erreur sans jamais dire LAQUELLE (`error_messages` vide,
    # « Erreurs : 1 » sans explication), et la clause d'etat n'attrapait pas le
    # refus du garde anti-echappement de la racine.
    ("cinesort/app/apply_core.py", "apply_rows"): 773,
    ("cinesort/domain/quality_score.py", "compute_quality_score"): 500,
    # Nouvelle entree : le pre-check gagne le controle du second volume.
    ("cinesort/app/disk_space_check.py", "check_disk_space_for_apply"): 101,
    ("cinesort/ui/api/library_support.py", "_build_library_rows"): 429,
    # 385 -> 400 : #901 rouverte. La closure `record_apply_op` relance desormais
    # l'echec d'ecriture au lieu de l'avaler (sans quoi le compteur d'echecs de
    # journal reste a 0) et n'incremente `op_index` qu'apres succes. +2 lignes de
    # code, +13 de commentaire qui disent POURQUOI le `raise` doit rester : c'est
    # son absence qui avait fait rouvrir l'issue.
    ("cinesort/ui/api/apply_support.py", "_execute_apply"): 400,
    ("cinesort/domain/scan_helpers.py", "discover_candidate_folders"): 382,
    # 369 -> 386 : #901. `disk_touched` prend un TROISIEME terme (journal_failures)
    # et le commentaire dit pourquoi chacun est necessaire. Le correctif rendait
    # `op_index` honnete, ce qui le mettait a 0 sur un journal verrouille — donc
    # eteignait l'alerte exactement dans le mode de panne qu'elle sert. Trouve en
    # revue adversaire ; ces lignes existent pour que ca ne se reperde pas.
    ("cinesort/ui/api/apply_support.py", "_apply_changes_body"): 386,
    ("cinesort/ui/api/dashboard_support.py", "_build_dashboard_section"): 360,
    # 335 -> 350 : les conflits d'undo deviennent une DONNEE de la reponse
    # (row_id, source, destination, ce qui bloquait) au lieu d'une chaine de
    # message dont aucune surface ne pouvait rien faire.
    #
    # 350 -> 364 (#987, 2026-08-07) : la mise en quarantaine d'undo est
    # desormais JOURNALISEE comme une operation a part entiere, sans quoi le
    # film restait dans un bac qu'aucun des trois chemins de reprise ne savait
    # atteindre. L'ajout est de 14 lignes irreductibles — le « pourquoi » a ete
    # deplace dans les docstrings de `_premier_index_libre` et
    # `_journaliser_quarantaine_undo` precisement pour ne pas gonfler ce corps.
    #
    # CE PLAFOND EST UN AVEU, PAS UNE SOLUTION. Cette fonction est la plus
    # longue du chemin destructif et elle etait DEJA a son plafond : toute
    # correction qui la touche rencontrera ce mur. Son bloc de conflit (~60
    # lignes) est une couture d'extraction evidente. Il n'a pas ete extrait ICI
    # parce que deplacer soixante lignes de deplacement de fichiers au milieu
    # d'un correctif de surete des donnees enlarge le diff sur le chemin le plus
    # dangereux de l'application — cet eclatement merite sa propre verification.
    ("cinesort/ui/api/apply_support.py", "_execute_undo_ops"): 364,
    ("cinesort/ui/api/run_flow_support.py", "_build_plan_job_fn"): 304,
    ("cinesort/ui/api/perceptual_support.py", "_execute_perceptual_analysis"): 298,
    ("cinesort/app/job_runner.py", "_run_worker"): 292,
    # 275 -> 265 : la decision « dst manquant » a ete extraite dans
    # `_verdict_dst_manquant` le 2026-08-29 (un volume injoignable n'est plus
    # confondu avec un fichier deja deplace). Plafond resserre sur la taille
    # obtenue plutot que monte.
    ("cinesort/app/apply_rollback.py", "_revert_one_op"): 265,
    ("cinesort/domain/librarian.py", "generate_suggestions"): 272,
    ("cinesort/ui/api/run_flow_support.py", "job_fn"): 271,
    ("cinesort/app/runtime_probe_check.py", "cross_check_rows_with_probe"): 258,
    ("cinesort/app/plan_support_replan.py", "_plan_item"): 254,
    ("cinesort/ui/api/runtime_support.py", "get_or_create_infra"): 238,
    ("cinesort/app/apply_core.py", "apply_tv_episode"): 237,
    ("cinesort/ui/api/history_support.py", "_get_history_stats_impl"): 237,
    ("cinesort/app/jellyfin_sync.py", "restore_watched"): 231,
    ("cinesort/domain/duplicate_support.py", "find_duplicate_targets"): 225,
    ("cinesort/domain/tiers_helpers.py", "apply_tier_hierarchy"): 223,
    ("cinesort/app/apply_core.py", "apply_collection_item"): 217,
    ("cinesort/app/apply_core.py", "move_duplicate_losers_to_user_decided"): 214,
    ("cinesort/app/apply_core.py", "apply_single"): 212,
    ("cinesort/domain/scan_helpers.py", "_walk"): 211,
    ("cinesort/infra/omdb_client.py", "test_connection"): 210,
    ("cinesort/infra/probe/service.py", "probe_file"): 204,
    ("cinesort/ui/api/film_support.py", "_get_film_full_impl"): 197,
    ("cinesort/ui/api/dashboard_support.py", "get_global_stats"): 196,
    ("cinesort/app/apply_core.py", "move_file_with_collision_policy"): 195,
    ("cinesort/ui/api/quality_report_support.py", "get_quality_report"): 195,
    ("cinesort/ui/api/run_flow_support.py", "_get_status_impl"): 194,
    ("cinesort/ui/api/apply_support.py", "_summarize_apply"): 191,
    ("cinesort/domain/perceptual/audio_perceptual.py", "analyze_audio_perceptual"): 187,
    ("cinesort/ui/api/apply_support.py", "_build_apply_preview_body"): 187,
    ("cinesort/ui/api/library_support.py", "_row_matches"): 187,
    ("cinesort/app/apply_core.py", "move_marked_for_deletion_to_bucket"): 185,
    ("cinesort/ui/api/apply_support.py", "undo_selected_rows"): 184,
    ("cinesort/ui/api/library_actions_support.py", "_rematch_tmdb_and_update_plan"): 184,
    ("cinesort/infra/integrations/poster_proxy.py", "fetch_and_cache"): 180,
    ("cinesort/domain/quality_score.py", "_score_video"): 175,
    # 175 -> 176 : l'insight « DNR partiel » etait le dernier site de cette
    # fonction a compter sur les 20 derniers runs au lieu du dernier scan. UNE
    # ligne (`dnr_run_ids`), et la fonction etait pile a son plafond. Le
    # « pourquoi » vit dans la docstring de `count_v2_warnings_flag` et dans
    # `tests/test_audit_wave3_r2_counter_and_insight.py`, pas ici : ce corps
    # n'avait pas a grossir de neuf lignes de commentaire.
    ("cinesort/ui/api/dashboard_support.py", "_compute_active_insights"): 176,
    ("cinesort/domain/perceptual/comparison.py", "build_comparison_report"): 174,
    ("cinesort/domain/quality_score.py", "_build_quality_presets_catalog"): 167,
    ("cinesort/app/jellyfin_validation.py", "build_sync_report"): 165,
    ("cinesort/ui/api/dashboard_support.py", "get_dashboard"): 165,
    ("cinesort/app/plan_support_core.py", "_filter_dossiers_phase"): 163,
    ("cinesort/domain/subtitle_helpers.py", "build_subtitle_report"): 161,
    # 157 -> 163 : mesure de la vague 2. La relecture des PRAGMA (six `PRAGMA` de
    # plus par ouverture) devient optionnelle sur le seul chemin qui IGNORE le
    # retour, et le commentaire porte les chiffres qui l'expliquent — c'est eux
    # qui evitent qu'on croie avoir trouve le cout de la connexion.
    ("cinesort/infra/db/connection.py", "connect_sqlite"): 163,
    ("cinesort/ui/api/perceptual_support.py", "get_perceptual_compare_frames"): 157,
    ("cinesort/app/apply_batches_reconciliation.py", "reconcile_pending_batches"): 155,
    ("cinesort/app/apply_rollback.py", "rollback_forward"): 155,
    ("cinesort/domain/duplicate_multi_signal.py", "_phase_b_fuzzy_title"): 154,
    ("cinesort/ui/api/library_timeline_support.py", "_get_library_timeline_impl"): 153,
    ("cinesort/ui/api/settings_support.py", "write_settings"): 152,
    ("cinesort/domain/perceptual/composite_score.py", "detect_cross_verdicts"): 150,
    ("cinesort/infra/rest_server.py", "_handle_post"): 150,
    # 150 -> 170 : le pre-check d'espace disque regarde desormais le SECOND
    # volume (les bacs vivent sous le state_dir, pas sous la bibliotheque).
    ("cinesort/ui/api/apply_support.py", "_validate_apply"): 170,
    ("cinesort/ui/api/perceptual_support.py", "get_perceptual_compare_audio"): 149,
    ("cinesort/infra/probe/_normalize_merge.py", "_merge_probes"): 148,
    ("cinesort/app/job_runner.py", "start_job"): 147,
    ("cinesort/domain/perceptual/audio_fingerprint.py", "_run_ffmpeg_pipe_fpcalc"): 146,
    ("cinesort/ui/api/export_support.py", "export_full_library"): 146,
    ("cinesort/app/plan_support_replan.py", "_build_resolved_row"): 145,
    ("cinesort/app/quarantine_ttl.py", "list_review_bucket_files"): 145,
    ("cinesort/ui/api/perceptual_support.py", "compare_perceptual"): 145,
    ("cinesort/infra/db/nas_validation.py", "run_nas_benchmark"): 143,
    ("cinesort/app/apply_core.py", "merge_dir_safe"): 141,
    ("cinesort/domain/perceptual/audio_fingerprint.py", "compute_audio_fingerprint"): 136,
    ("cinesort/ui/api/apply_support.py", "_cleanup_apply"): 136,
    ("cinesort/ui/api/perceptual_support.py", "_video_task"): 136,
    ("cinesort/domain/film_history.py", "get_film_timeline"): 133,
    ("cinesort/domain/perceptual/composite_score_v2.py", "apply_contextual_adjustments"): 133,
    ("cinesort/app/plugin_hooks.py", "_run_plugin"): 132,
    ("cinesort/app/plan_support_replan.py", "_plan_tv_episode"): 131,
    ("cinesort/infra/probe/_normalize_ffprobe.py", "_extract_ffprobe"): 131,
    ("cinesort/ui/api/quality_report_support.py", "_probe_and_score"): 131,
    ("cinesort/ui/api/run_flow_support.py", "_persist_duplicate_winner"): 131,
    ("cinesort/ui/api/run_flow_support.py", "_validate_and_init_plan_context"): 130,
    ("cinesort/app/move_reconciliation.py", "reconcile_pending_moves"): 128,
    ("cinesort/infra/jellyfin_client.py", "get_all_movies"): 128,
    ("cinesort/ui/api/tmdb_support.py", "search_tmdb"): 128,
    ("cinesort/app/plan_support_core.py", "_classify_and_plan_folder"): 127,
    ("cinesort/app/quarantine_ttl.py", "purge_review_bucket"): 123,
    ("cinesort/domain/perceptual/av1_grain_metadata.py", "extract_av1_film_grain_params"): 123,
    ("cinesort/domain/core.py", "build_candidates_from_tmdb"): 122,
    # `parse_release_name` est SORTIE de ce plafond le 2026-08-31 : 147 -> 91
    # lignes, apres extraction de `_parse_audio_hints` (64). Le cliquet avait
    # rougi a 147 > 122 en documentant le repli DTS:X ; il demande de DECOUPER.
    ("cinesort/ui/api/library_support.py", "set_film_tmdb_candidate"): 122,
    ("cinesort/domain/calibration.py", "suggest_weight_adjustment"): 121,
    ("cinesort/domain/perceptual/grain_classifier.py", "classify_grain_nature"): 121,
    ("cinesort/ui/api/apply_support.py", "build_undo_preview_payload"): 121,
    ("cinesort/ui/api/library_actions_support.py", "export_films"): 121,
    ("cinesort/infra/db/sqlite_store.py", "_attempt_auto_restore"): 120,
    ("cinesort/ui/api/library_podiums_support.py", "_get_library_podiums_impl"): 120,
    ("cinesort/infra/db/repositories/decisions.py", "upgrade_deferred_to_accepted"): 118,
    ("cinesort/app/watchlist.py", "compare_watchlist"): 117,
    ("cinesort/domain/scene_parser.py", "parse_scene_title"): 109,
    ("cinesort/domain/duplicate_compare.py", "compare_by_criteria"): 116,
    ("cinesort/domain/video_hash.py", "extract_video_thumbnails"): 116,
    # 114 -> 108 : la route jaquettes a ete documentee et durcie le 2026-08-29,
    # ce qui l'a fait deborder (140). Plutot que monter le plafond, trois blocs
    # ont ete extraits (`_force_demande`, `_invalider_le_cache`,
    # `_servir_sans_cle_tmdb`). Le plafond est resserre sur la taille obtenue.
    ("cinesort/infra/integrations/poster_proxy.py", "serve_poster"): 108,
    # 114 -> 172 : un undo qui n'a restaure AUCUN fichier ne consomme plus
    # l'annulation. Le cas et sa justification tiennent en une trentaine de
    # lignes de commentaire — c'est le prix pour que personne ne les reperde.
    # 172 -> 161 le 2026-08-31 : le triangle sur l'undo ajoutait deux lignes
    # irreductibles (la photo des `undo_status` AVANT la boucle, et l'appel au
    # verdict), et une premiere version de cette PR portait donc le plafond a
    # 174. Le cliquet ne monte pas : `_payload_de_fin_d_undo` a ete EXTRAITE a
    # la place. Ce bloc ne consultait que des variables locales deja calculees,
    # donc rien ne le retenait ici — la fonction passe SOUS son plafond
    # historique au lieu de le repousser.
    ("cinesort/ui/api/apply_support.py", "_execute_and_finalize_undo"): 161,
    ("cinesort/ui/api/perceptual_support.py", "_validate_and_load_context"): 114,
    ("cinesort/ui/api/profiles_support_import_export.py", "get_breakdown_5_axes"): 114,
    ("cinesort/ui/api/tmdb_support.py", "enrich_tmdb_ids_by_title"): 114,
    ("cinesort/infra/db/sqlite_store.py", "_bootstrap_schema_latest"): 112,
    # `_save_settings_payload_locked` a quitte cette liste : sa chaine de sections
    # est passee dans `_appliquer_les_sections`, et elle est repassee sous le
    # seuil. Le cliquet l'a signalee comme PERIMEE — c'est son autre sens, celui
    # qui empeche un plafond de rester acquis apres un decoupage.
    ("cinesort/ui/api/settings_support.py", "read_settings"): 110,
    ("cinesort/app/plan_support_dedup.py", "_augment_candidates_from_nfo_tmdb_id"): 109,
    ("cinesort/infra/tmdb_client.py", "purge_expired_tmdb_cache"): 109,
    ("cinesort/ui/api/profiles_support_import_export.py", "_yaml_parse_lines"): 109,
    ("cinesort/domain/perceptual/audio_perceptual.py", "_compute_audio_score"): 108,
    ("cinesort/ui/api/quality_audit_support.py", "_recompute_worker"): 108,
    ("cinesort/ui/api/settings_support.py", "build_cfg_from_settings"): 108,
    ("cinesort/app/watcher.py", "_snapshot_root"): 107,
    ("cinesort/domain/genre_rules.py", "compute_genre_adjustments"): 107,
    ("cinesort/domain/quality_score.py", "_score_extras"): 107,
    ("cinesort/domain/perceptual/audio_perceptual.py", "analyze_clipping_segments"): 106,
    ("cinesort/infra/db/migration_manager.py", "_split_sql_statements"): 106,
    ("cinesort/infra/db/pragma_profile.py", "_record_pragma_history"): 106,
    ("cinesort/domain/quality_score.py", "_apply_custom_rules_helper"): 105,
    ("cinesort/infra/plex_client.py", "get_movies"): 105,
    ("cinesort/infra/probe/tools_manager.py", "_build_tool_status"): 105,
    ("cinesort/ui/api/perceptual_support.py", "analyze_perceptual_batch"): 105,
    ("cinesort/app/export_support.py", "export_nfo_for_run"): 104,
    ("cinesort/ui/api/dashboard_support.py", "_build_row_payload"): 104,
    ("cinesort/app/apply_core.py", "quarantine_row"): 103,
    ("cinesort/app/cleanup.py", "preview_cleanup_residual_folders"): 102,
    ("cinesort/app/radarr_sync.py", "build_radarr_report"): 102,
    ("cinesort/ui/api/apply_support.py", "build_undo_by_row_preview"): 102,
    ("cinesort/ui/api/dashboard_support.py", "compose_score_explanation"): 102,
    ("cinesort/domain/perceptual/grain_analysis.py", "analyze_grain_v2"): 101,
    ("cinesort/ui/api/profiles_support_crud.py", "save_profile"): 101,
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


def _depassements(mesures, plafonds):
    """Fonctions listees dont la taille MESUREE depasse leur plafond.

    Isole du parcours du depot pour pouvoir etre eprouve sur des entrees
    controlees : sans cela, une comparaison inversee (`<` au lieu de `>`)
    passerait inapercue tant que l'inventaire courant est conforme.
    """
    return [
        (rel, name, loc, plafonds[(rel, name)])
        for rel, name, loc in mesures
        if (rel, name) in plafonds and loc > plafonds[(rel, name)]
    ]


def _plafonds_morts(plafonds, seuil):
    """Plafonds <= seuil : la fonction sortirait de l'inventaire, ils ne mordraient jamais."""
    return sorted((rel, name, plafond) for (rel, name), plafond in plafonds.items() if plafond <= seuil)


def test_no_new_oversized_function():
    """Aucune fonction > MAX_LINES hors allowlist gelee (#677)."""
    offenders = [(rel, name, loc) for rel, name, loc in _iter_oversized_functions() if (rel, name) not in PLAFONDS]
    assert not offenders, (
        f"{len(offenders)} nouvelle(s) fonction(s) > {MAX_LINES} LOC hors allowlist. "
        "Decouper la fonction, ou (si justifie) l'ajouter a PLAFONDS dans "
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
    stale = sorted(set(PLAFONDS) - current)
    assert not stale, (
        f"{len(stale)} entree(s) d'allowlist perimee(s) (fonction decoupee ou "
        "renommee sous le seuil) — les retirer de PLAFONDS : " + ", ".join(f"{rel}:{name}" for rel, name in stale)
    )


def test_les_fonctions_listees_ne_grossissent_pas():
    """Une fonction deja trop longue ne doit pas s'allonger davantage.

    C'est le trou que ce fichier documentait comme sa limite assumee : geler la
    LISTE sans geler les TAILLES laissait `apply_rows` (744 lignes, sur le
    chemin qui deplace les films de l'utilisateur) libre d'en atteindre 1 500,
    sans qu'aucun test ne bronche.

    Faire monter un plafond reste possible — il suffit d'editer la valeur — mais
    cela devient une ligne de diff visible en review, au lieu d'une derive
    silencieuse. C'est le meme cliquet que celui des imports, et il est a marge
    ZERO : la moindre ligne de plus rougit.
    """
    depassements = _depassements(_iter_oversized_functions(), PLAFONDS)
    assert not depassements, (
        f"{len(depassements)} fonction(s) deja trop longue(s) ont GROSSI. "
        "Les decouper, ou (si justifie) monter leur plafond dans PLAFONDS — "
        "ce qui doit rester un choix explicite en review. Detail : "
        + ", ".join(f"{rel}:{name} ({loc} > {plafond})" for rel, name, loc, plafond in depassements)
    )


def test_les_plafonds_sont_au_dessus_du_seuil():
    """Un plafond <= MAX_LINES serait mort : la fonction sortirait de la liste.

    Sans ce controle, une valeur erronee (0, ou une taille d'avant decoupe)
    passerait inapercue et le plafond ne mordrait jamais.
    """
    morts = _plafonds_morts(PLAFONDS, MAX_LINES)
    assert not morts, (
        f"{len(morts)} plafond(s) <= MAX_LINES ({MAX_LINES}) : la fonction ne serait plus "
        "listee, donc le plafond ne s'appliquerait jamais. " + ", ".join(f"{rel}:{name}={p}" for rel, name, p in morts)
    )


# ---------------------------------------------------------------------------
# Controles du DETECTEUR lui-meme.
#
# Les deux tests ci-dessus ne parcourent que l'arbre courant : ils resteraient
# VERTS si la detection devenait inoperante, tant que l'inventaire est conforme.
# C'est le meme piege que le test vide au site d'appel — verifier l'etat plutot
# que l'instrument qui le mesure. Les cas ci-dessous eprouvent les helpers sur
# des entrees controlees, donc sans dependre de l'etat du depot.
# ---------------------------------------------------------------------------


def test_le_detecteur_voit_un_depassement():
    trouve = _depassements([("a/b.py", "f", 150)], {("a/b.py", "f"): 120})
    assert trouve == [("a/b.py", "f", 150, 120)], trouve


def test_une_taille_EGALE_au_plafond_passe():
    """La borne est un plafond inclusif : sinon le depot rougirait a l'identique."""
    assert _depassements([("a/b.py", "f", 120)], {("a/b.py", "f"): 120}) == []


def test_une_fonction_ABSENTE_des_plafonds_n_est_pas_un_depassement():
    """Elle releve de `test_no_new_oversized_function`, pas de ce controle-ci."""
    assert _depassements([("a/b.py", "inconnue", 999)], {("a/b.py", "f"): 120}) == []


def test_le_detecteur_voit_un_plafond_mort():
    assert _plafonds_morts({("a/b.py", "f"): 80}, 100) == [("a/b.py", "f", 80)]
    assert _plafonds_morts({("a/b.py", "f"): 100}, 100) == [("a/b.py", "f", 100)]


def test_un_plafond_au_dessus_du_seuil_n_est_pas_mort():
    assert _plafonds_morts({("a/b.py", "f"): 101}, 100) == []
