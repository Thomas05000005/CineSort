from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import traceback
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

_logger = logging.getLogger(__name__)

import contextlib

import cinesort.domain.core as core
import cinesort.infra.state as state
from cinesort.app.omdb_cross_check import cross_check_rows_with_omdb
from cinesort.app.plan_support import find_duplicate_targets as _find_dups
from cinesort.app.plan_support import plan_multi_roots
from cinesort.app.runtime_probe_check import cross_check_rows_with_probe
from cinesort.domain.conversions import to_bool, to_float
from cinesort.domain.duplicate_compare import compare_duplicates
from cinesort.domain.i18n_messages import t
from cinesort.domain.run_models import RunStatus
from cinesort.infra.omdb_client import OmdbClient
from cinesort.infra.tmdb_client import TmdbClient
from cinesort.ui.api._responses import err as _err_response
from cinesort.ui.api._validators import clamp_non_negative_int, requires_valid_run_id
from cinesort.ui.api.settings_support import (
    _SECRET_FIELDS,
    _SECRET_MASK,
    normalize_user_path,
    read_settings,
)

# Seuil duplique dans plan_support._ROOT_BULK_WARNING_THRESHOLD.
_ROOT_BULK_THRESHOLD = 20


def _count_row_categories(rows: list) -> Tuple[Counter, Counter, Counter]:
    confidence_counter = Counter((r.confidence_label or "unknown") for r in rows)
    source_counter = Counter((r.proposed_source or "unknown") for r in rows)
    kind_counter = Counter((r.kind or "unknown") for r in rows)
    return confidence_counter, source_counter, kind_counter


def _count_warning_flags(rows: list) -> Tuple[Counter, int]:
    warning_counter: Counter = Counter(
        str(flag or "").strip()
        for row in rows
        for flag in (getattr(row, "warning_flags", None) or [])
        if str(flag or "").strip()
    )
    review_like_count = sum(
        1
        for row in rows
        if (getattr(row, "warning_flags", None) or [])
        or str(getattr(row, "confidence_label", "")).lower() in ("med", "low")
    )
    return warning_counter, review_like_count


def _extract_ignore_stats(stats: Any) -> Tuple[Dict[str, Any], int, List[Tuple[str, Any]]]:
    ignore_map = dict(getattr(stats, "analyse_ignores_par_raison", {}) or {})
    ignore_total = int(getattr(stats, "analyse_ignores_total", 0) or 0)
    ignore_ext_map = dict(getattr(stats, "analyse_ignores_extensions", {}) or {})
    top_ignore_exts = sorted(ignore_ext_map.items(), key=lambda kv: int(kv[1]), reverse=True)[:6]
    return ignore_map, ignore_total, top_ignore_exts


def _build_root_level_lines(stats: Any) -> List[str]:
    root_level_count = int(getattr(stats, "root_level_films_seen", 0) or 0)
    if root_level_count <= 0:
        return []
    lines = [
        "",
        "FILMS DETECTES A LA RACINE",
        (
            f"- {root_level_count} film(s) pose(s) directement a la racine → sera(ont) range(s) "
            f"dans des sous-dossiers 'Titre (Annee)/' lors de l'apply."
        ),
    ]
    if root_level_count >= _ROOT_BULK_THRESHOLD:
        lines.append(
            f"- ATTENTION : racine en vrac ({root_level_count} >= {_ROOT_BULK_THRESHOLD}). "
            f"Verifier le dry-run avant apply, {root_level_count} sous-dossiers seront crees d'un coup."
        )
    return lines


def _build_situation_section(stats: Any, root_lines: List[str], review_like_count: int, ignore_total: int) -> List[str]:
    safe_like_count = max(int(stats.planned_rows or 0) - int(review_like_count or 0), 0)
    return [
        "SITUATION ANALYSE",
        f"- Lignes generees pour le run : {stats.planned_rows}",
        f"- Cas probablement surs : {safe_like_count}",
        f"- Cas a verifier : {review_like_count}",
        f"- Entrees ignorees pendant analyse : {ignore_total}",
        *root_lines,
    ]


def _build_priority_section(warning_counter: Counter, confidence_counter: Counter) -> List[str]:
    return [
        "CE QUI EST A VERIFIER EN PRIORITE",
        f"- NFO rejetes (titre incoherent) : {int(warning_counter.get('nfo_title_mismatch', 0))}",
        f"- NFO rejetes (annee incoherente) : {int(warning_counter.get('nfo_year_mismatch', 0))}",
        f"- Conflits annee dossier / fichier : {int(warning_counter.get('year_conflict_folder_file', 0))}",
        f"- TMDb avec delta d'annee : {int(warning_counter.get('tmdb_year_delta', 0))}",
        f"- Confiance moyenne : {int(confidence_counter.get('med', 0))}",
        f"- Confiance faible : {int(confidence_counter.get('low', 0))}",
    ]


def _build_ignored_section(ignore_map: Dict[str, Any]) -> List[str]:
    labels = core.ANALYSE_IGNORE_LABELS_FR
    pairs = [
        ("ignore_tv_like", "Ignore (ressemble a une serie)"),
        ("ignore_nfo_incoherent", "Ignore (NFO incoherent)"),
        ("ignore_non_supporte", "Ignore (format non supporte)"),
        ("ignore_chemin_invalide", "Ignore (chemin invalide)"),
        ("ignore_autre", "Ignore (autre)"),
    ]
    return ["ENTREES IGNOREES"] + [
        f"- {labels.get(key, fallback)}: {int(ignore_map.get(key, 0))}" for key, fallback in pairs
    ]


def _build_extensions_section(top_ignore_exts: List[Tuple[str, Any]]) -> List[str]:
    body = [f"- {ext}: {cnt}" for ext, cnt in top_ignore_exts] if top_ignore_exts else ["- aucune extension dominante"]
    return ["FICHIERS ANNEXES / NON SUPPORTES OBSERVES", "(independant du total d'entrees ignorees ci-dessus)"] + body


def _build_run_details_section(stats: Any, kind_counter: Counter, source_counter: Counter, run_paths: Any) -> List[str]:
    return [
        "DETAILS RUN",
        f"- Dossiers scannes : {stats.folders_scanned}",
        f"- Collections detectees : {stats.collections_seen}",
        f"- Lignes collection generees : {kind_counter.get('collection', 0)}",
        f"- Singles detectes : {stats.singles_seen}",
        f"- Lignes single : {kind_counter.get('single', 0)}",
        (
            "- Sources retenues : "
            f"NFO={source_counter.get('nfo', 0)} "
            f"TMDb={source_counter.get('tmdb', 0)} "
            f"Nom={source_counter.get('name', 0)}"
        ),
        (
            "- Cache incremental (dossiers) : "
            f"hits={int(getattr(stats, 'incremental_cache_hits', 0) or 0)} "
            f"misses={int(getattr(stats, 'incremental_cache_misses', 0) or 0)} "
            f"rows_reused={int(getattr(stats, 'incremental_cache_rows_reused', 0) or 0)}"
        ),
        (
            "- Cache incremental (videos) : "
            f"row_hits={int(getattr(stats, 'incremental_cache_row_hits', 0) or 0)} "
            f"row_misses={int(getattr(stats, 'incremental_cache_row_misses', 0) or 0)}"
        ),
        f"- Plan : {run_paths.plan_jsonl}",
    ]


def _build_analysis_summary(
    rows: list,
    stats: Any,
    root: Any,
    state_dir: Any,
    run_paths: Any,
) -> str:
    confidence_counter, source_counter, kind_counter = _count_row_categories(rows)
    warning_counter, review_like_count = _count_warning_flags(rows)
    ignore_map, ignore_total, top_ignore_exts = _extract_ignore_stats(stats)
    root_level_lines = _build_root_level_lines(stats)

    summary: List[str] = [
        "=== RESUME ANALYSE ===",
        f"ROOT={root}",
        f"STATE_DIR={state_dir}",
        "",
        *_build_situation_section(stats, root_level_lines, review_like_count, ignore_total),
        "",
        *_build_priority_section(warning_counter, confidence_counter),
        "",
        *_build_ignored_section(ignore_map),
        "",
        *_build_extensions_section(top_ignore_exts),
        "",
        *_build_run_details_section(stats, kind_counter, source_counter, run_paths),
    ]
    return "\n".join(summary) + "\n"


def _init_tmdb_client(
    settings: Dict[str, Any],
    state_dir: Any,
    log_fn: Any,
    dlog: Any,
) -> Optional[TmdbClient]:
    tmdb_enabled = to_bool(settings.get("tmdb_enabled"), True)
    tmdb_timeout_s = to_float(settings.get("tmdb_timeout_s"), 10.0)
    api_key = (settings.get("tmdb_api_key") or "").strip()
    # V5-03 polish v7.7.0 (R5-STRESS-4) : propager le TTL configurable.
    try:
        cache_ttl_days = int(settings.get("tmdb_cache_ttl_days") or 30)
    except (TypeError, ValueError):
        cache_ttl_days = 30
    if tmdb_enabled and api_key:
        try:
            dlog("start_plan initializing TMDb client")
            tmdb = TmdbClient(
                api_key=api_key,
                cache_path=state_dir / "tmdb_cache.json",
                timeout_s=tmdb_timeout_s,
                cache_ttl_days=cache_ttl_days,
            )
            log_fn("INFO", "TMDb: enabled (cache local)")
            dlog("start_plan TMDb client ready")
            return tmdb
        except (OSError, KeyError, TypeError, ValueError) as exc:
            log_fn("ERROR", f"TMDb init failed: {exc}")
            dlog(f"start_plan TMDb init failed: {exc}")
            return None
    elif tmdb_enabled:
        log_fn("WARN", "TMDb active mais cle vide (utilise 'Tester la cle').")
        dlog("start_plan TMDb enabled but api_key empty")
    return None


def _validate_and_init_plan_context(
    api: Any,
    settings: Dict[str, Any],
    run_state_cls: Type[Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Valide les inputs et initialise le contexte du plan.

    Retourne (error_response, context) — l'un des deux est None.
    """
    state_dir, state_dir_present = api._resolve_payload_state_dir(settings)
    debug_enabled = api._debug_enabled(settings if isinstance(settings, dict) else None)

    safe_settings: Dict[str, Any] = dict(settings)
    if safe_settings.get("tmdb_api_key"):
        safe_settings["tmdb_api_key"] = f"***len={len(str(safe_settings.get('tmdb_api_key') or ''))}"
    api._debug_log(
        state_dir=state_dir, run_id=None, enabled=debug_enabled, message=f"start_plan called settings={safe_settings}"
    )

    roots, roots_error = api._resolve_roots_from_payload(
        settings,
        state_dir=state_dir,
        state_dir_present=state_dir_present,
        missing_message=t("errors.root_required_scan"),
    )
    if roots_error:
        # Issue #103 : log structure via err() au lieu de return silencieux.
        # category="validation" : roots manquantes dans le payload = erreur d'input
        # utilisateur, pas une config systeme invalide.
        return _err_response(roots_error, category="validation", level="info", log_module=__name__), None
    assert roots is not None and len(roots) > 0
    # Verifier qu'au moins un root existe
    accessible_roots = [r for r in roots if r.exists() and r.is_dir()]
    if not accessible_roots:
        if len(roots) == 1:
            return (
                _err_response(
                    t("errors.root_not_found", root=str(roots[0])),
                    category="resource",
                    level="warning",
                    log_module=__name__,
                ),
                None,
            )
        return (
            _err_response(
                t("errors.no_root_accessible", count=len(roots)),
                category="resource",
                level="warning",
                log_module=__name__,
            ),
            None,
        )
    root = roots[0]  # root principal pour compat (runs.root, cfg initial)

    state_dir.mkdir(parents=True, exist_ok=True)
    # H7 : mutation de _state_dir protegee par lock
    with api._state_dir_lock:
        api._state_dir = state_dir
    api._debug_log(
        state_dir=state_dir,
        run_id=None,
        enabled=debug_enabled,
        message=f"start_plan resolved roots={[str(r) for r in roots]} state_dir={state_dir}",
    )

    try:
        state.clean_old_runs(state_dir, keep_last=20)
    except (OSError, PermissionError, TypeError, ValueError) as exc:
        api._debug_log(
            state_dir=state_dir, run_id=None, enabled=debug_enabled, message=f"start_plan clean_old_runs warning: {exc}"
        )

    api._debug_log(
        state_dir=state_dir, run_id=None, enabled=debug_enabled, message="start_plan before _get_or_create_infra"
    )
    store, runner = api._get_or_create_infra(state_dir)
    api._debug_log(
        state_dir=state_dir,
        run_id=None,
        enabled=debug_enabled,
        message=f"start_plan infra ready db_path={store.db_path}",
    )

    run_id = api._generate_unique_run_id(store)
    run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=True)
    api._debug_log(
        state_dir=state_dir,
        run_id=run_id,
        enabled=debug_enabled,
        message=f"start_plan run created run_id={run_id} run_dir={run_paths.run_dir}",
    )

    cfg = api._build_cfg_from_settings(settings, root)
    rs = run_state_cls(run_paths, cfg, runner=runner, store=store)

    with api._runs_lock:
        api._runs[run_id] = rs
        api._purge_terminal_runs_locked()
    roots_label = ", ".join(str(r) for r in roots)
    rs.log("INFO", f"=== START PLAN ROOTS=[{roots_label}] ({len(roots)} root(s)) ===")

    return None, {
        "state_dir": state_dir,
        "debug_enabled": debug_enabled,
        "root": root,
        "roots": roots,
        "store": store,
        "runner": runner,
        "run_id": run_id,
        "run_paths": run_paths,
        "cfg": cfg,
        "rs": rs,
    }


def _build_scan_health_snapshot() -> Dict[str, Any]:
    """Snapshot sante persiste dans runs.stats_json a la FIN du scan.

    AUDIT 2026-07-13 (M1, anti-pattern A) : au scan AUCUN quality_report n'existe
    encore en BDD — `recompute_all_scores` tourne en background (cf _build_plan_job_fn,
    juste apres le scan). Toute metrique dependante du probe doit donc rester None,
    sinon on FIGE une valeur fausse jamais reconciliee :
      - health_score : autrefois calcule via generate_suggestions en lui passant
        une liste de reports VIDE -> codecs obsoletes / basse resolution jamais
        vus, et pistes de sous-titres EMBARQUEES invisibles (librarian.py ne peut
        rien reconcilier) -> faux "sans subs FR" -> health_score errone.
      - subtitle_coverage_pct : autrefois calcule sur `subtitle_missing_langs`
        BRUT (etat scan pre-probe) -> couverture sous-estimee.
    Mirroir de resolution_4k_pct / codec_modern_pct, deja a None pour ce motif.
    Le dashboard recalcule ces metriques LIVE avec les vrais reports
    (dashboard_support._compute_librarian_suggestions), et _compute_health_trend
    ignore deja les snapshots dont health_score est None (dashboard_support.py).
    """
    return {
        "health_score": None,  # requiert quality reports (pas dispo au scan)
        "subtitle_coverage_pct": None,  # idem (pistes embarquees invisibles au scan)
        "resolution_4k_pct": None,
        "codec_modern_pct": None,
    }


def _build_plan_job_fn(
    api: Any,
    ctx: Dict[str, Any],
    settings: Dict[str, Any],
) -> Callable[[Callable[[], bool]], Optional[Dict[str, Any]]]:
    """Construit la closure job_fn pour le plan avec tout le contexte necessaire."""
    rs = ctx["rs"]
    store = ctx["store"]
    run_id = ctx["run_id"]
    cfg = ctx["cfg"]
    root = ctx["root"]
    roots: List[Path] = ctx.get("roots") or [root]
    state_dir = ctx["state_dir"]
    debug_enabled = ctx["debug_enabled"]
    runner = ctx.get("runner")  # R8-037 : pour câbler le cancel_event au batch perceptuel

    def dlog(msg: str) -> None:
        api._debug_log(state_dir=state_dir, run_id=run_id, enabled=debug_enabled, message=msg)
        if debug_enabled:
            rs.log("DEBUG", msg)

    dlog("start_plan runtime registered")
    tmdb = _init_tmdb_client(settings, state_dir, rs.log, dlog)

    def progress_with_persistence(idx: int, total: int, current: str) -> None:
        rs.progress(idx, total, current)
        try:
            store.run.update_run_progress(run_id, idx=idx, total=total, current_folder=current)
        except (KeyError, OSError, TypeError, ValueError) as exc:
            dlog(f"progress persistence warning idx={idx}/{total}: {exc}")

    def job_fn(
        should_cancel: Callable[[], bool],
        should_pause: Optional[Callable[[], bool]] = None,
    ) -> Optional[Dict[str, Any]]:
        # VN-E.3 : job_fn accepte should_pause comme kwarg optionnel — le
        # JobRunner inspecte la signature et l'injecte si present. Backward
        # compat : si non fourni (legacy call), comportement inchange.
        dlog("job_fn started")
        dlog("job_fn writing ui_log.txt heartbeat")
        with rs.lock:
            rs.running = True
            rs.done = False
            rs.error = None
        try:
            if should_cancel():
                with rs.lock:
                    rs.running = False
                    rs.done = True
                rs.log("WARN", "Plan annule avant le demarrage effectif.")
                dlog("job_fn cancelled before plan_support.plan_library")
                return {"cancelled_before_plan": True}

            dlog(f"job_fn calling plan_multi_roots with {len(roots)} root(s)")
            plan_kwargs: Dict[str, Any] = {
                "tmdb": tmdb,
                "log": rs.log,
                "progress": progress_with_persistence,
                "should_cancel": should_cancel,
                # VN-E.3 : injection should_pause vers plan_library (no-op
                # si non fourni par le JobRunner pour ce run).
                "should_pause": should_pause,
            }
            if bool(getattr(cfg, "incremental_scan_enabled", False)):
                # #85 phase B8c : Repository pattern (store.scan au lieu de store).
                plan_kwargs["scan_index"] = store.scan
                plan_kwargs["run_id"] = run_id

            # Sous-titres : langues attendues depuis les settings
            if to_bool(settings.get("subtitle_detection_enabled"), True):
                raw_langs = settings.get("subtitle_expected_languages")
                if isinstance(raw_langs, list):
                    plan_kwargs["subtitle_expected_languages"] = [
                        str(l).strip().lower() for l in raw_langs if str(l).strip()
                    ]
                elif isinstance(raw_langs, str) and raw_langs.strip():
                    plan_kwargs["subtitle_expected_languages"] = [
                        l.strip().lower() for l in raw_langs.split(",") if l.strip()
                    ]
                else:
                    plan_kwargs["subtitle_expected_languages"] = []

            def _build_cfg_for_root(r: Path) -> Any:
                return api._build_cfg_from_settings(settings, r)

            rows, stats = plan_multi_roots(roots, build_cfg=_build_cfg_for_root, **plan_kwargs)
            dlog(
                f"job_fn plan returned rows={len(rows)} folders_scanned={stats.folders_scanned} planned_rows={stats.planned_rows}"
            )

            # Phase 6.1.b : probe runtime cross-check (extension de Phase 6.1).
            # Pour les ~60-70% de films sans NFO, on utilise probe.duration_s pour
            # cross-checker contre le runtime TMDb. Couvre le gap de Phase 6.1.
            # Doit s'executer AVANT OMDb car peut deja booster confidence > seuil
            # et eviter un appel OMDb inutile.
            try:
                if tmdb is not None:
                    n_probe = cross_check_rows_with_probe(
                        rows,
                        store,
                        settings,
                        tmdb,
                        log=rs.log,
                        should_cancel=should_cancel,
                    )
                    dlog(f"job_fn probe runtime cross-check : {n_probe} films verifies")
            except (OSError, ImportError, AttributeError, KeyError, TypeError, ValueError) as exc:
                # Echec gracieux : on ne casse pas le run pour un probleme probe
                dlog(f"job_fn probe runtime cross-check skipped: {exc}")

            # Phase 6.2 : OMDb cross-check post-plan (echec gracieux total).
            # Lit settings, instancie OmdbClient, parcourt les rows confidence
            # basse. N'echoue jamais le run en cas de probleme.
            try:
                if settings.get("omdb_enabled") and settings.get("omdb_api_key"):
                    omdb_cache_path = state_dir / "omdb_cache.json"
                    omdb_client = OmdbClient(
                        api_key=str(settings.get("omdb_api_key") or ""),
                        cache_path=omdb_cache_path,
                        timeout_s=10.0,
                    )
                    threshold = int(settings.get("omdb_min_confidence_for_call") or 90)
                    n_checked = cross_check_rows_with_omdb(
                        rows,
                        omdb_client,
                        min_confidence_for_call=threshold,
                        log=rs.log,
                        should_cancel=should_cancel,
                    )
                    dlog(f"job_fn omdb cross-check : {n_checked} films verifies")
            except (OSError, ImportError, AttributeError, KeyError, TypeError, ValueError) as exc:
                # Echec gracieux : on ne casse pas le run pour un probleme OMDb
                dlog(f"job_fn omdb cross-check skipped: {exc}")
            with rs.lock:
                rs.rows = rows
                rs.stats = stats
                rs.done = True
                rs.running = False
            rs.log("INFO", f"=== PLAN READY rows={len(rows)} ===")
            elapsed = round(time.time() - rs.started_ts, 1)
            api._notify.notify(
                "scan_done",
                t("notifications.title_scan_done"),
                t("notifications.scan_done_body", count=len(rows), elapsed=elapsed),
            )
            api._touch_event()
            _hook_data = {
                "run_id": run_id,
                "ts": time.time(),
                "data": {"rows": len(rows), "folders_scanned": stats.folders_scanned, "roots": [str(r) for r in roots]},
            }
            api._dispatch_plugin_hook("post_scan", _hook_data)
            api._dispatch_email("post_scan", _hook_data)

            # Fix audit 2026-05-25 (v1.5.4) Vague I : BUG 1 — apres scan, aucun
            # quality_report n'existe en BDD donc la page Qualite affiche
            # "0 films classes". On declenche en background le calcul des
            # scores V1 (tier) pour tous les films, best-effort. L'utilisateur
            # peut aussi cliquer "Re-calculer" manuellement. Controle par
            # setting `auto_recompute_quality_on_scan` (default True).
            try:
                auto_recompute = to_bool(settings.get("auto_recompute_quality_on_scan"), True)
                if auto_recompute and rows:
                    from cinesort.ui.api import quality_audit_support

                    dlog("job_fn launching auto quality recompute background job")
                    result = quality_audit_support.recompute_all_scores(api)
                    if isinstance(result, dict) and result.get("ok"):
                        dlog(f"job_fn auto recompute started job_id={result.get('job_id')}")
                    else:
                        dlog(f"job_fn auto recompute skipped: {result}")
            except (ImportError, KeyError, OSError, TypeError, ValueError) as exc:
                dlog(f"job_fn auto recompute warning: {exc}")

            # ITER6 cluster settings — fix `perceptual_auto_on_scan` no-op silencieux.
            # Toggle UI Parametres > "Analyse perceptuelle apres chaque scan"
            # etait sauvegarde par _save_section_perceptual mais jamais relu
            # dans le chemin start_plan reel (run_flow / _build_plan_job_fn).
            # Pattern : meme contrat que auto_recompute_quality_on_scan ci-dessus
            # (background, best-effort, log bruyant si echec d'approvisionnement,
            # silencieux si toggle=OFF). Lance analyze_perceptual_batch sur les
            # row_ids du run -- thread daemon non bloquant. Pre-requis
            # `perceptual_enabled` (false par defaut) car le moteur perceptuel
            # n'est pas operationnel sans la cle activee : on logue WARN explicite
            # si l'utilisateur a active l'auto sans avoir active le moteur, pour
            # honorer le contrat ii.b (echec d'approvisionnement bruyant).
            try:
                auto_perceptual = to_bool(settings.get("perceptual_auto_on_scan"), False)
                if auto_perceptual and rows:
                    perceptual_enabled = to_bool(settings.get("perceptual_enabled"), False)
                    if not perceptual_enabled:
                        rs.log(
                            "WARN",
                            "perceptual_auto_on_scan active mais perceptual_enabled=False "
                            "-> analyse perceptuelle skip (active aussi le moteur).",
                        )
                        dlog("job_fn auto perceptual skipped: perceptual_enabled=False")
                    else:
                        from cinesort.ui.api import perceptual_support

                        row_ids = [
                            str(getattr(r, "row_id", "") or "")
                            for r in rows
                            if str(getattr(r, "row_id", "") or "").strip()
                        ]
                        if row_ids:
                            dlog(f"job_fn launching auto perceptual batch ({len(row_ids)} films)")
                            # R8-037 (F4) : câbler le cancel_event du run sur l'api
                            # AVANT le batch -> _resolve_cancel_event(api) le lit ->
                            # request_cancel (qui pose rt.cancel_event) arrête bien
                            # l'analyse perceptuelle (avant : event jamais assigné =
                            # checks d'annulation inertes). Nettoyé en finally.
                            _perc_cancel = runner.get_cancel_event(run_id) if runner else None
                            if _perc_cancel is not None:
                                api._perceptual_cancel_event = _perc_cancel
                            try:
                                perc_result = perceptual_support.analyze_perceptual_batch(
                                    api, run_id, row_ids, options=None
                                )
                            finally:
                                if _perc_cancel is not None:
                                    api._perceptual_cancel_event = None
                            if isinstance(perc_result, dict) and perc_result.get("ok"):
                                dlog(f"job_fn auto perceptual started success_count={perc_result.get('success_count')}")
                            else:
                                dlog(f"job_fn auto perceptual skipped: {perc_result}")
                        else:
                            dlog("job_fn auto perceptual skipped: no row_ids")
            except (ImportError, KeyError, OSError, TypeError, ValueError) as exc:
                dlog(f"job_fn auto perceptual warning: {exc}")

            _save_plan_artifacts(rs, rows, stats, root, state_dir, dlog)

            # AUDIT 2026-06-13 (R5-H1) : enrichissement TMDb post-scan. Les films
            # identifies par NFO/nom n'ont pas de tmdb_id (la recherche TMDb est
            # court-circuitee au scan quand un NFO matche, plan_support_dedup.py:18)
            # -> aucune jaquette. Si l'utilisateur a active TMDb, on resout en
            # ARRIERE-PLAN le tmdb_id (+ jaquette) par titre+annee pour ces films,
            # sans toucher a l'identification. Gate sur tmdb_enabled ; daemon =
            # ne bloque pas la fin du scan ; les jaquettes apparaissent au
            # prochain chargement biblio. Reutilise la fonction testee R5-H2
            # (skip les rows ayant deja un tmdb_id).
            try:
                if to_bool(settings.get("tmdb_enabled"), False) and rows:
                    enrich_ids = [
                        str(getattr(r, "row_id", "") or "") for r in rows if str(getattr(r, "row_id", "") or "").strip()
                    ]
                    if enrich_ids:
                        import threading as _threading

                        from cinesort.ui.api import tmdb_support as _tmdb_support

                        def _bg_tmdb_enrich() -> None:
                            try:
                                res = _tmdb_support.enrich_tmdb_ids_by_title(api, run_id, enrich_ids)
                                resolved = res.get("resolved") if isinstance(res, dict) else "?"
                                dlog(f"job_fn post-scan tmdb enrich resolved={resolved}")
                            except Exception as _exc:  # noqa: BLE001 - daemon best-effort
                                dlog(f"job_fn post-scan tmdb enrich warning: {_exc}")

                        _threading.Thread(target=_bg_tmdb_enrich, name=f"tmdb-enrich-{run_id}", daemon=True).start()
                        dlog(f"job_fn post-scan tmdb enrich launched ({len(enrich_ids)} films)")
            except (ImportError, KeyError, OSError, TypeError, ValueError) as exc:
                dlog(f"job_fn post-scan tmdb enrich skipped: {exc}")

            # Snapshot sante bibliotheque : au scan on NE FIGE aucune metrique
            # dependante du probe (anti-pattern A / M1, cf _build_scan_health_snapshot).
            stats_dict = dict(stats.__dict__)
            stats_dict["health_snapshot"] = _build_scan_health_snapshot()

            dlog("job_fn done")
            return stats_dict
        except (ImportError, KeyError, OSError, TypeError, ValueError) as exc:
            tb_text = traceback.format_exc()
            with rs.lock:
                rs.error = str(exc)
                rs.running = False
                rs.done = True
            rs.log("ERROR", f"Plan failed: {exc}")
            dlog(f"job_fn exception: {exc}")
            api._notify.notify("error", t("notifications.title_scan_error"), str(exc), level="error")
            api._write_crash_file(rs.paths, "job_fn failed", tb_text)
            try:
                store.run.insert_error(
                    run_id=run_id,
                    step="tri_api_job_fn",
                    code=exc.__class__.__name__,
                    message=str(exc),
                    context={"run_id": run_id, "traceback": tb_text},
                )
            except (OSError, TypeError, ValueError) as insert_exc:
                dlog(f"job_fn store.insert_error warning: {insert_exc}")
            raise
        finally:
            if tmdb:
                dlog("job_fn flushing tmdb cache")
                try:
                    tmdb.flush()
                except (OSError, TypeError, ValueError) as exc:
                    dlog(f"job_fn tmdb.flush warning: {exc}")

    return job_fn


def _save_plan_artifacts(rs: Any, rows: list, stats: Any, root: Any, state_dir: Any, dlog: Callable) -> None:
    """Sauvegarde plan.jsonl et summary.txt apres un scan reussi."""
    dlog("job_fn writing plan.jsonl")
    try:
        with open(rs.paths.plan_jsonl, "w", encoding="utf-8") as file_obj:
            for row in rows:
                data = asdict(row)
                data["candidates"] = [asdict(c) for c in row.candidates]
                file_obj.write(json.dumps(data, ensure_ascii=False) + "\n")
    except (KeyError, OSError, PermissionError, TypeError, ValueError, json.JSONDecodeError) as exc:
        rs.log("WARN", f"Plan save failed: {exc}")
        dlog(f"job_fn writing plan.jsonl failed: {exc}")

    dlog("job_fn writing summary.txt")
    try:
        summary_text = _build_analysis_summary(rows, stats, root, state_dir, rs.paths)
        rs.paths.summary_txt.write_text(summary_text, encoding="utf-8")
    except (KeyError, OSError, PermissionError, TypeError, ValueError, json.JSONDecodeError) as exc:
        dlog(f"job_fn writing summary.txt failed: {exc}")


def start_plan(api: Any, settings: Dict[str, Any], *, run_state_cls: Type[Any]) -> Dict[str, Any]:
    """Lance l'analyse d'une bibliotheque. Orchestre validation, init et lancement du job."""
    # Fix audit 2026-05-25 (v1.5.3) Vague G : wrap global pour eviter HTTP 500
    # sur cet endpoint critique (lancement scan). Si une exception inattendue
    # remonte (par ex. ImportError d'un sous-module, RuntimeError du runner),
    # l'UI doit recevoir un user_message clair plutot qu'une 500.
    try:
        return _start_plan_impl(api, settings, run_state_cls=run_state_cls)
    except Exception as exc:  # noqa: BLE001 - boundary top-level
        _logger.exception("start_plan failed")
        return {
            "ok": False,
            "error": "start_plan_failed",
            "message": str(exc),
            "user_message": ("Impossible de lancer le scan. Verifie les sources et reessaie."),
        }


def _hydrate_settings_from_store(
    api: Any,
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    """ITER4 fix racine C : merge le settings on-disk dans le payload caller.

    Le caller REST envoie `POST /api/run/start_plan` avec un body souvent
    minimal (`{settings: {library_path: ...}}`). Sans ce merge, les cles
    persistees (tmdb_api_key dechiffree DPAPI, tmdb_enabled, omdb_api_key,
    ...) sont absentes du dict, ce qui declenche silencieusement la branche
    `elif tmdb_enabled` de `_init_tmdb_client` (api_key vide) et desactive
    TMDb a tort.

    Priorite : **requete OVERRIDE on-disk** pour preserver l'opt-in explicite
    du caller (ex: tests qui passent tmdb_api_key="test_xyz" doivent rester
    inchanges, cf tests/test_plan_tmdb_enrichment_guard.py L51-56).

    Backward compat : si on-disk n'existe pas ou que la lecture leve, on
    retourne le settings d'origine sans alterer.
    """
    if not isinstance(settings, dict):
        return settings
    try:
        state_dir, _present = api._resolve_payload_state_dir(settings)
        persisted = read_settings(state_dir)
    except (OSError, PermissionError, KeyError, TypeError, ValueError):
        return settings
    if not isinstance(persisted, dict) or not persisted:
        return settings
    merged: Dict[str, Any] = dict(persisted)
    # Requete override on-disk : on ecrase persisted par les cles du caller.
    # AUDIT 2026-06-10 (REAL 2/2) : SAUF un secret egal au masque "••••••••".
    # Les callers UI (accueil.js _triggerStartPlan, watcher) renvoient le payload
    # settings/get_settings dont les secrets sont MASQUES. Sans cette exclusion,
    # le masque ecrasait la vraie cle dechiffree on-disk -> tout scan tournait
    # avec tmdb_api_key/omdb_api_key="••••••••" (identification cassee, 401).
    for key, value in settings.items():
        if key in _SECRET_FIELDS and str(value or "").strip() == _SECRET_MASK:
            continue  # garde la vraie valeur persistee
        merged[key] = value
    return merged


def _scrub_secrets_for_persist(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Copie des settings avec les secrets MASQUES, pour persistance.

    AUDIT 2026-06-11 (R1b) : depuis le fix d'hydratation (_hydrate_settings_from_store
    garde les vraies cles dechiffrees DPAPI), le dict settings contient les secrets
    EN CLAIR. Ce dict etait passe tel quel a start_job(config=...) qui le persiste
    dans runs.config_json (json.dumps, infra/db/repositories/run.py) -> fuite des
    secrets en clair dans la base SQLite a chaque scan (viole l'invariant DPAPI).
    Le scan lui-meme lit les vraies cles via le closure job_fn (PAS via config),
    donc masquer la copie de persistance n'affecte pas l'identification.
    """
    if not isinstance(settings, dict):
        return {}
    out = dict(settings)
    for field in _SECRET_FIELDS:
        if str(out.get(field) or "").strip():
            out[field] = _SECRET_MASK
    return out


def scrub_historical_run_configs(store: Any) -> Dict[str, int]:
    """Re-masque les secrets des runs.config_json HISTORIQUES (boot-cleanup).

    AUDIT 2026-06-11 (R4-P6) : les runs crees AVANT le fix R1b (63517d7) ont
    persiste les settings avec secrets EN CLAIR dans runs.config_json — R1b ne
    protege que les NOUVEAUX runs. Ce cleanup au boot re-masque les
    _SECRET_FIELDS non-masques des lignes existantes (top-level + sous-dict
    'settings' defensif). Idempotent : une 2e passe ne touche plus rien
    (valeurs deja au masque). Best-effort : JSON invalide ignore, table runs
    absente toleree (DB pre-v1), le caller wrappe pour ne jamais bloquer le boot.

    Retourne {"scanned": N, "scrubbed": M}.
    """
    report = {"scanned": 0, "scrubbed": 0}
    if store is None:
        return report
    with store._managed_conn() as conn:  # type: ignore[attr-defined]
        try:
            rows = conn.execute(
                "SELECT run_id, config_json FROM runs WHERE config_json IS NOT NULL AND config_json != ''"
            ).fetchall()
        except sqlite3.OperationalError:
            return report
        for row in rows:
            run_id, raw = str(row[0]), str(row[1] or "")
            report["scanned"] += 1
            try:
                cfg = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(cfg, dict):
                continue
            changed = False
            targets = [cfg]
            if isinstance(cfg.get("settings"), dict):
                targets.append(cfg["settings"])
            for target in targets:
                for field in _SECRET_FIELDS:
                    value = target.get(field)
                    if isinstance(value, str) and value.strip() and value != _SECRET_MASK:
                        target[field] = _SECRET_MASK
                        changed = True
            if changed:
                conn.execute(
                    "UPDATE runs SET config_json = ? WHERE run_id = ?",
                    (json.dumps(cfg, ensure_ascii=False, sort_keys=True), run_id),
                )
                report["scrubbed"] += 1
    return report


def _start_plan_impl(api: Any, settings: Dict[str, Any], *, run_state_cls: Type[Any]) -> Dict[str, Any]:
    """Implementation reelle de start_plan, sans wrap global (Vague G)."""
    if not isinstance(settings, dict):
        return _err_response(
            t("errors.payload_settings_invalid"), category="validation", level="info", log_module=__name__
        )

    # ITER4 fix racine C (rupture AMONT settings) : hydrater le dict caller
    # avec le settings.json on-disk AVANT toute resolution (tmdb_api_key
    # DPAPI dechiffree, tmdb_enabled, etc.). Priorite caller > on-disk.
    settings = _hydrate_settings_from_store(api, settings)

    state_dir, _ = api._resolve_payload_state_dir(settings)
    debug_enabled = api._debug_enabled(settings if isinstance(settings, dict) else None)
    run_id: Optional[str] = None
    run_paths: Optional[state.RunPaths] = None

    try:
        error_resp, ctx = _validate_and_init_plan_context(api, settings, run_state_cls)
        if error_resp:
            return error_resp
        assert ctx is not None

        run_id = ctx["run_id"]
        run_paths = ctx["run_paths"]
        runner = ctx["runner"]
        _logger.info("api: start_plan run_id=%s", run_id)

        def dlog(msg: str) -> None:
            api._debug_log(state_dir=state_dir, run_id=run_id, enabled=debug_enabled, message=msg)

        job_fn = _build_plan_job_fn(api, ctx, settings)

        dlog("start_plan before runner.start_job")
        try:
            started_run_id = runner.start_job(
                job_fn=job_fn,
                root=str(ctx["root"]),
                state_dir=str(state_dir),
                # AUDIT 2026-06-11 (R1b) : secrets MASQUES dans la copie persistee
                # en config_json (le scan utilise les vraies cles via job_fn).
                config=_scrub_secrets_for_persist(settings or {}),
                run_id_hint=run_id,
                debug_log=(lambda message: dlog(f"jobrunner: {message}")) if debug_enabled else None,
            )
        except RuntimeError as exc:
            # Fix audit 2026-05-24 : job_runner.start_job() leve RuntimeError
            # "Un run est deja en cours" en cas de double-click utilisateur ou
            # de race frontend. Avant : exception non catchee -> REST 500 +
            # traceback. Maintenant : 409 Conflict avec message clair, plus
            # robuste cote UX (le frontend peut afficher un toast info).
            with api._runs_lock:
                api._runs.pop(run_id, None)
            dlog(f"start_plan rejete : {exc}")
            return _err_response(
                str(exc),
                category="state",
                level="info",
                log_module=__name__,
                http_status=409,
            )
        except (OSError, KeyError, TypeError, ValueError) as exc:
            with api._runs_lock:
                api._runs.pop(run_id, None)
            dlog(f"start_plan runner.start_job failed: {exc}")
            return _err_response(str(exc), category="runtime", level="error", log_module=__name__)

        dlog(f"start_plan after runner.start_job started_run_id={started_run_id}")
        if started_run_id != run_id:
            with api._runs_lock:
                api._runs.pop(run_id, None)
            dlog(f"start_plan run_id mismatch expected={run_id} got={started_run_id}")
            return _err_response(
                t("errors.internal_run_id_unexpected"),
                category="runtime",
                level="error",
                log_module=__name__,
            )

        dlog("start_plan success")
        return {"ok": True, "run_id": run_id, "run_dir": str(run_paths.run_dir)}
    except (OSError, KeyError, TypeError, ValueError) as exc:
        tb_text = traceback.format_exc()
        api._debug_log(
            state_dir=state_dir, run_id=run_id, enabled=debug_enabled, message=f"start_plan fatal exception: {exc}"
        )
        if run_paths:
            api._write_crash_file(run_paths, "start_plan failed", tb_text)
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


def _compute_speed_and_eta(
    idx: int,
    total: int,
    started: float,
    samples: list,
    ewma: float,
) -> Tuple[float, int]:
    now = time.time()
    elapsed = max(0.001, now - started)
    avg_speed = (idx / elapsed) if idx else 0.0
    recent_speed = 0.0

    if len(samples) >= 2:
        cutoff = now - 45.0
        start_ts, start_idx = samples[0]
        for ts_s, idx_s in reversed(samples):
            if ts_s < cutoff:
                start_ts, start_idx = ts_s, idx_s
                break
        end_ts, end_idx = samples[-1]
        dt = end_ts - start_ts
        di = end_idx - start_idx
        if dt > 0.0 and di >= 0:
            recent_speed = di / dt

    speed = recent_speed if recent_speed > 0.01 else (ewma if ewma > 0.01 else avg_speed)
    eta = int((total - idx) / speed) if speed > 0 and total > idx else 0
    return speed, eta


@requires_valid_run_id
def get_status(api: Any, run_id: str, last_log_index: int = 0) -> Dict[str, Any]:
    # Fix audit 2026-05-25 (v1.5.3) Vague F : wrap global pour eviter HTTP 500
    # sur cet endpoint critique appele en polling depuis l'UI Traitement.
    try:
        return _get_status_impl(api, run_id, last_log_index=last_log_index)
    except Exception as exc:  # noqa: BLE001 - boundary top-level
        _logger.exception("get_status failed for run_id=%s", run_id)
        return {
            "ok": False,
            "error": "run_status_unavailable",
            "message": str(exc),
            "user_message": ("Impossible de recuperer l'etat du run. Relance un scan ou redemarre l'app."),
        }


def _get_status_impl(api: Any, run_id: str, last_log_index: int = 0) -> Dict[str, Any]:
    """Implementation reelle de get_status, sans wrap global (Vague F)."""
    # Audit 2026-05-23 : last_log_index < 0 ferait rs.logs[-N:] = tail des N derniers
    # logs (contournement de la pagination + valeur retournee dans next_log_index incoherente).
    # clamp_non_negative_int gere aussi None / str non-numerique / NaN proprement.
    last_log_index = clamp_non_negative_int(last_log_index)
    # Fix audit 2026-05-25 (v1.5.5) Vague J : import local pour eviter cycle
    # run_flow <-> run_data lors du chargement du module.
    # Fix audit 2026-05-26 (v1.5.6) Vague L : count-2. Import en plus de
    # compute_total_fallback pour harmoniser le fallback total entre
    # dashboard/history/run_flow (auparavant run_flow ne lisait que
    # run_row.total, ignorant stats.planned_rows).
    from cinesort.ui.api.run_data_support import (
        compute_total_fallback,
        count_plan_rows,
    )

    rs = api._get_run(run_id)
    if not rs:
        found = api._find_run_row(run_id)
        if not found:
            return _err_response(t("errors.run_not_found"), category="resource", level="info", log_module=__name__)
        run_row, _store = found
        status_text = str(run_row.get("status") or RunStatus.FAILED.value)
        idx = int(run_row.get("idx") or 0)
        # Fix audit 2026-05-26 (v1.5.6) Vague L : count-2. Calcul de stats_obj
        # pour faire passer planned_rows dans compute_total_fallback().
        stats_obj_raw = run_row.get("stats_json")
        stats_obj: Dict[str, Any] = {}
        if isinstance(stats_obj_raw, str) and stats_obj_raw.strip():
            try:
                parsed = json.loads(stats_obj_raw)
                if isinstance(parsed, dict):
                    stats_obj = parsed
            except (ValueError, json.JSONDecodeError):
                stats_obj = {}
        total = compute_total_fallback(run_row, stats_obj)
        cur = str(run_row.get("current_folder") or "")
        running = status_text in {RunStatus.PENDING.value, RunStatus.RUNNING.value}
        done = status_text in {RunStatus.DONE.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value}
        err = str(run_row.get("error_message") or "") or None
        # Fix audit 2026-05-25 (v1.5.5) Vague J : pour les runs termines hors
        # memoire (DB-only), total stocke = discover_total (855 dossiers
        # explores) au lieu de len(plan.jsonl) (853 PlanRow valides). On
        # recompte depuis plan.jsonl pour aligner sur la meme source de verite
        # que dashboard/history/library. Fallback sur total DB si plan.jsonl
        # inaccessible.
        if done:
            try:
                run_paths = api._run_paths_for(
                    normalize_user_path(run_row.get("state_dir"), api._state_dir),
                    run_id,
                    ensure_exists=False,
                )
                total = count_plan_rows(run_paths, fallback=total)
            except (OSError, AttributeError, KeyError, TypeError, ValueError):
                # En cas d'erreur, on garde le total DB (best-effort)
                pass
        return {
            "ok": True,
            "running": running,
            "done": done,
            "error": err,
            "idx": idx,
            "total": total,
            "current": cur,
            "speed": 0.0,
            "eta_s": 0,
            "logs": [],
            "next_log_index": int(last_log_index or 0),
            "status": status_text,
            "cancel_requested": bool(run_row.get("cancel_requested") or 0),
            # APPLY-2 : branche DB-only (run termine hors memoire) — pas de
            # polling de la phase apply possible. On retourne None pour
            # coherence cote frontend (data.apply == null => pas de barre).
            "apply": None,
        }

    with rs.lock:
        # F19 : les index de pagination sont ABSOLUS depuis le debut du run,
        # alors que rs.logs ne conserve que les MAX_RUN_LOG_ITEMS derniers
        # items. rs.logs_offset = nombre d'items deja evinces -> on convertit
        # l'index client en index de liste.
        #
        # F19 (revue R1) : le repli doit tester le TYPE, pas la verite. Sur un
        # rs mocke (unittest.mock.MagicMock) `getattr` ne leve pas et ne rend
        # pas le defaut — il rend un MagicMock truthy dont `int()` vaut 1, soit
        # un decalage silencieux de 1 (une ligne re-emise a chaque poll,
        # next_log_index off-by-one a vie) la ou l'intention etait de
        # NEUTRALISER l'offset.
        _raw_offset = getattr(rs, "logs_offset", 0)
        logs_offset = int(_raw_offset) if isinstance(_raw_offset, int) and not isinstance(_raw_offset, bool) else 0
        start = last_log_index - logs_offset
        if start < 0:
            # Client en retard sur la fenetre de retention : il reprend au plus
            # ancien encore disponible (les evinces restent dans ui_log.txt).
            start = 0
        logs = rs.logs[start:] if start < len(rs.logs) else []
        # Index incoherent (client en avance / nouveau run) : next_log_index
        # resynchronise sur la fin reelle du buffer -> auto-guerison.
        next_log_index = logs_offset + len(rs.logs)
        idx = rs.idx
        total = rs.total
        cur = rs.current_folder
        running = rs.running
        done = rs.done
        err = rs.error
        started = rs.started_ts
        samples = list(rs.progress_samples)
        ewma = rs.speed_ewma
        paths_snapshot = rs.paths
        # APPLY-2 : capture defensive des attributs apply_* sous le meme lock.
        # getattr() avec defaut pour rester compatible tant que la Couche 1
        # (RunState.apply_begin/apply_progress/apply_end) n'est pas deployee.
        apply_running = bool(getattr(rs, "apply_running", False))
        apply_done = bool(getattr(rs, "apply_done", False))
        apply_idx = int(getattr(rs, "apply_idx", 0) or 0)
        apply_total = int(getattr(rs, "apply_total", 0) or 0)
        apply_current = str(getattr(rs, "apply_current", "") or "")
        apply_phase = str(getattr(rs, "apply_phase", "") or "")
        apply_dry_run = bool(getattr(rs, "apply_dry_run", False))
        apply_started_ts = float(getattr(rs, "apply_started_ts", 0.0) or 0.0)
        apply_samples = list(getattr(rs, "apply_progress_samples", ()) or ())
        apply_ewma = float(getattr(rs, "apply_speed_ewma", 0.0) or 0.0)

    snap = rs.runner.get_status(run_id)
    status_text = "RUNNING"
    cancel_requested = False
    if snap:
        status_text = snap.status.value
        cancel_requested = bool(snap.cancel_requested)
        running = bool(snap.running)
        done = bool(snap.done)
        if not err and snap.error:
            err = snap.error
    else:
        if err:
            status_text = RunStatus.FAILED.value
        elif done:
            status_text = RunStatus.DONE.value
        elif running:
            status_text = RunStatus.RUNNING.value
        else:
            status_text = RunStatus.PENDING.value

    # Fix audit 2026-05-25 (v1.5.5) Vague J : une fois le scan termine, rs.total
    # vaut encore discover_total (nombre de dossiers explores, ex. 855) alors
    # que len(rs.rows) = nombre de PlanRow finaux (ex. 853, certains dossiers
    # sans video ont ete ignores). L'etape Doublons / barre de progression
    # affichait donc "855 films" alors que la Bibliotheque/Qualite affichaient
    # 853. On recompte depuis plan.jsonl (source unique de verite Vague I.C)
    # une fois le scan done. Pendant le scan (running), on garde rs.total =
    # discover_total comme cible attendue de la barre de progression.
    if done and not running:
        with contextlib.suppress(OSError, AttributeError, KeyError, TypeError, ValueError):
            total = count_plan_rows(paths_snapshot, fallback=total)

    speed, eta = _compute_speed_and_eta(idx, total, started, samples, ewma)

    # APPLY-2 : payload distinct pour la phase apply. On expose les compteurs
    # uniquement si la phase est ou a ete active (apply_running ou apply_done)
    # afin de garder data.apply == None pendant la phase scan/analyse et eviter
    # un re-render inutile cote frontend. Backward-compat : les champs
    # top-level running/idx/total/current/... restent dedies au scan.
    apply_payload: Optional[Dict[str, Any]] = None
    if apply_running or apply_done:
        apply_speed, apply_eta = _compute_speed_and_eta(
            apply_idx, apply_total, apply_started_ts or started, apply_samples, apply_ewma
        )
        apply_payload = {
            "running": apply_running,
            "done": apply_done,
            "idx": apply_idx,
            "total": apply_total,
            "current": apply_current,
            "phase": apply_phase,
            "dry_run": apply_dry_run,
            "speed": apply_speed,
            "eta_s": apply_eta,
        }

    return {
        "ok": True,
        "running": running,
        "done": done,
        "error": err,
        "idx": idx,
        "total": total,
        "current": cur,
        "speed": speed,
        "eta_s": eta,
        "logs": logs,
        "next_log_index": next_log_index,
        "status": status_text,
        "cancel_requested": cancel_requested,
        "apply": apply_payload,
    }


@requires_valid_run_id
def save_validation(api: Any, run_id: str, decisions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Persiste les decisions de validation.

    Vague P / VP-D : accepte AUSSI une cle optionnelle `decision`
    (`accepted` / `rejected` / `deferred`) en plus du legacy `ok: bool`.

    **Backward compat ABSOLUE** (AC-2) :
      - Si une row ne contient que `ok: bool` (shape legacy), la reponse
        retourne `{ok: bool, path: ...}` comme avant.
      - Si une row contient `decision: 'deferred'` (nouveau VP-D), la
        decision est miroir-ee dans la table SQL `film_decisions_v2` via
        `store.decisions.set_decision`, et la shape de retour `{ok: bool}`
        EST PRESERVEE (les decisions "deferred" sont projetees a `ok=false`
        dans validation.json pour ne pas etre apply-ees).
      - Aucun appel legacy ne casse : helper `to_legacy_ok_bool`
        (cf cinesort/infra/db/repositories/decisions.py).

    Coordination Vague P :
      - VP-A `apply_atomic` : aucun kwarg `apply_atomic` n'est consomme
        ici — pas de collision possible (AC-5).
      - VP-C `field_locks` : transition `deferred -> accepted` consulte
        les locks (via DecisionsRepository.upgrade_deferred_to_accepted)
        — la repo expose les locks dans sa reponse (AC-3).
    """
    if not isinstance(decisions, dict):
        return _err_response(
            t("errors.payload_decisions_invalid"), category="validation", level="info", log_module=__name__
        )
    # BUG-003 / BUG-004 (VP-D, hotfix) : si une row porte `decision` tri-etat,
    # on PROJETTE `ok` via to_legacy_ok_bool AVANT _normalize_decisions_for_rows
    # afin que validation.json et le mirror SQL voient la meme verite
    # (sinon `decision=deferred` avec ok absent/true entraine une drift
    # vers `ok=true` apply-ee a tort, ou un `ok=None` rejected).
    projected_decisions = _project_decisions_ok_from_tri_state(decisions)
    # BUG-011 (hotfix) : verrou inter-thread par run_id pour eviter
    # last-write-wins lors d'un double-click UI sur "Enregistrer".
    save_lock = _get_save_validation_lock(api, run_id)
    with save_lock:
        rs = api._get_run(run_id)
        if rs:
            try:
                rows = rs.rows
                if not rows:
                    rows = api._load_rows_from_plan_jsonl(rs.paths)
                safe = api._normalize_decisions_for_rows(rows, projected_decisions)
                # VP-D : miroir tri-etat en SQL (best-effort, non bloquant).
                _mirror_decisions_to_sql(api, run_id, projected_decisions, getattr(rs, "store", None))
                state.atomic_write_json(rs.paths.validation_json, safe)
                rs.log("INFO", f"Validation enregistrée : {rs.paths.validation_json}")
                return {"ok": True, "path": str(rs.paths.validation_json)}
            except (OSError, PermissionError, TypeError, ValueError) as exc:
                return _err_response(str(exc), category="runtime", level="error", log_module=__name__)

        found = api._find_run_row(run_id)
        if not found:
            return _err_response(t("errors.run_not_found"), category="resource", level="info", log_module=__name__)
        row, _store = found
        run_paths = api._run_paths_for(
            normalize_user_path(row.get("state_dir"), api._state_dir),
            run_id,
            ensure_exists=False,
        )
        try:
            rows = api._load_rows_from_plan_jsonl(run_paths)
            safe = api._normalize_decisions_for_rows(rows, projected_decisions)
            # VP-D : miroir tri-etat en SQL (best-effort, non bloquant).
            _mirror_decisions_to_sql(api, run_id, projected_decisions, _store)
            state.atomic_write_json(run_paths.validation_json, safe)
            api._file_logger(run_paths)("INFO", f"Validation enregistrée : {run_paths.validation_json}")
            return {"ok": True, "path": str(run_paths.validation_json)}
        except (KeyError, OSError, PermissionError, TypeError, ValueError) as exc:
            return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


def _get_save_validation_lock(api: Any, run_id: str) -> "threading.Lock":
    """BUG-011 (hotfix2) : retourne le verrou par-run_id pour save_validation.

    Initialisation lazy de l'attribut `api._save_validation_locks` (dict
    run_id -> Lock) afin de ne pas toucher au constructeur de CineSortAPI
    et preserver la backward compat ABSOLUE.

    REGRESSION FIX (R2-BUG-011) : la creation lazy du Lock par-run_id DOIT
    se faire SOUS `_runs_lock` avec un pattern double-check locking. Sinon
    deux threads concurrents creent chacun leur propre Lock distinct, le
    second ecrase le premier dans le dict, et la mutex exclusive entre les
    deux threads est PERDUE (race condition restauree sur save_validation).
    """
    locks_map = getattr(api, "_save_validation_locks", None)
    if locks_map is None:
        # Section critique courte : on initialise le map lui-meme sous
        # un lock connu (le _runs_lock existe deja sur l'API).
        runs_lock = getattr(api, "_runs_lock", None)
        if runs_lock is not None:
            with runs_lock:
                locks_map = getattr(api, "_save_validation_locks", None)
                if locks_map is None:
                    locks_map = {}
                    api._save_validation_locks = locks_map
        else:
            locks_map = {}
            api._save_validation_locks = locks_map

    # Fast path sans lock : si le Lock existe deja, on le retourne direct.
    # Lecture d'un dict Python = atomique (GIL), pas de race sur read-only.
    lock = locks_map.get(run_id)
    if lock is not None:
        return lock

    # Slow path : creation du Lock SOUS _runs_lock avec double-check.
    # Sans ce verrou, deux threads concurrents creeraient chacun leur
    # propre Lock et le second ecraserait le premier => race condition.
    runs_lock = getattr(api, "_runs_lock", None)
    if runs_lock is not None:
        with runs_lock:
            lock = locks_map.get(run_id)
            if lock is None:
                lock = threading.Lock()
                locks_map[run_id] = lock
    else:
        # Fallback degrade : pas de runs_lock disponible, on cree sans
        # protection (best-effort, comportement pre-existant).
        lock = threading.Lock()
        locks_map[run_id] = lock
    return lock


def _project_decisions_ok_from_tri_state(
    decisions: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """BUG-003 / BUG-004 (hotfix VP-D) : projette `ok` depuis `decision`.

    Si une row du payload porte un champ `decision` (tri-etat
    accepted/rejected/deferred), on REECRIT son champ `ok` via
    `to_legacy_ok_bool(decision)` afin que :
      - `validation.json` (produit via `_normalize_decisions_for_rows` qui
        ne lit que `raw.get("ok")`) soit COHERENT avec la decision tri-etat.
      - Le mirror SQL via `_mirror_decisions_to_sql` reste consistant.

    Backward compat ABSOLUE :
      - Si une row ne porte PAS de `decision`, son `ok` est conserve tel
        quel (shape legacy intacte).
      - Le dict d'entree n'est pas mute (copie shallow par row).
    """
    if not isinstance(decisions, dict):
        return {}
    try:
        from cinesort.infra.db.repositories.decisions import to_legacy_ok_bool
    except ImportError:
        # Si l'import echoue (cycle, env degrade), on retourne tel quel
        # pour ne pas casser le flow legacy {ok: bool}.
        return decisions

    out: Dict[str, Dict[str, Any]] = {}
    for row_id, raw in decisions.items():
        if not isinstance(raw, dict):
            out[row_id] = raw
            continue
        explicit_decision = raw.get("decision")
        if explicit_decision is None:
            out[row_id] = raw
            continue
        # Projection : on cree une copie shallow et on ecrase `ok`.
        copied = dict(raw)
        copied["ok"] = to_legacy_ok_bool(explicit_decision)
        out[row_id] = copied
    return out


def _mirror_decisions_to_sql(
    api: Any,
    run_id: str,
    decisions: Dict[str, Dict[str, Any]],
    store: Any,
) -> None:
    """Vague P / VP-D : mirror tri-etat vers `film_decisions_v2` (best-effort).

    Ne JAMAIS lever d'exception : la persistance JSON reste la source
    primaire. Cette fonction est un complement enrichi (tri-etat
    accepted/rejected/deferred) qui permet l'historique long-terme + le
    filtre UI. Si le store n'est pas dispo ou si l'ecriture echoue, on
    log et on continue.

    Backward compat ABSOLUE :
      - Si le payload ne contient que `ok: bool`, on projete via
        `from_legacy_ok_bool` (accepted/rejected uniquement).
      - Si `decision` est explicitement specifie, on l'utilise tel quel
        (validation stricte dans DecisionsRepository.set_decision).
    """
    if not store:
        return
    decisions_repo = getattr(store, "decisions", None)
    if decisions_repo is None:
        return

    try:
        # Import tardif pour eviter cycle (`infra.db` -> `ui.api` via store).
        from cinesort.infra.db.repositories.decisions import (
            DECISION_REJECTED,
            from_legacy_ok_bool,
        )
    except ImportError:
        return

    for row_id, payload in (decisions or {}).items():
        if not isinstance(payload, dict):
            continue
        rid = str(row_id or "").strip()
        if not rid:
            continue

        # Cle stable film_id : on prefere tmdb_id si fourni, sinon
        # fallback sur le row_id (cle inter-runs minimaliste).
        tmdb_id = payload.get("tmdb_id")
        if tmdb_id:
            film_id = f"tmdb:{tmdb_id}"
        else:
            film_id = f"row:{rid}"

        explicit_decision = payload.get("decision")
        if explicit_decision is not None:
            decision = str(explicit_decision).strip().lower()
        else:
            # Backward compat : projete `ok: bool` vers tri-etat.
            ok_value = payload.get("ok")
            if ok_value is None:
                # Pas d'info : on stocke rien (evite un faux 'rejected').
                continue
            decision = from_legacy_ok_bool(ok_value)

        try:
            decisions_repo.set_decision(
                film_id,
                run_id,
                decision,
                row_id=rid,
                decided_by=str(payload.get("decided_by") or "user"),
                reason=str(payload.get("reason") or ""),
            )
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
            _logger.debug("save_validation: mirror SQL ignore pour row %s : %s", rid, exc)
            # On force malgre tout decision=DECISION_REJECTED pour eviter
            # le silence complet (ce code branch est defensif).
            _ = DECISION_REJECTED


def _build_pseudo_probe(detected: Dict[str, Any]) -> Dict[str, Any]:
    """Reconstitue un pseudo-probe depuis les metriques detected d'un quality_report."""
    return {
        "video": {
            "height": detected.get("height") or detected.get("resolution_height") or 0,
            "codec": detected.get("video_codec") or "",
            "bitrate": detected.get("bitrate_bps") or (int(detected.get("bitrate_kbps") or 0) * 1000),
            "hdr10": detected.get("hdr10", False),
            "hdr10_plus": detected.get("hdr10_plus", False),
            "hdr_dolby_vision": detected.get("hdr_dolby_vision", False),
        },
        "audio_tracks": [
            {
                "codec": detected.get("audio_best_codec") or "",
                "channels": detected.get("audio_best_channels") or 0,
            }
        ],
        "duration_s": detected.get("duration_s") or 0,
    }


def _load_probe_for_row(store: Any, run_id: str, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rid = str(item.get("row_id") or "")
    if not rid or store is None:
        return None
    try:
        qr = store.quality.get_quality_report(run_id=run_id, row_id=rid)
    except (OSError, KeyError, TypeError, ValueError):
        return None
    if not qr or not isinstance(qr.get("metrics"), dict):
        return None
    detected = qr["metrics"].get("detected") or {}
    return _build_pseudo_probe(detected)


def _filename_from_row(r: Any) -> str:
    if not isinstance(r, dict):
        return "?"
    vid = str(r.get("video") or "")
    if vid:
        return vid
    # AUDIT 2026-06-14 (R6-D) : les items de groupe (find_duplicate_targets)
    # exposent `source_folder`, pas `folder` -> on retombait sur "?" pour le nom
    # de fichier du comparateur. On accepte les deux cles.
    folder = str(r.get("folder") or r.get("source_folder") or "")
    if folder:
        return folder.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    return "?"


def _quality_info_for_row(store: Any, run_id: str, r: Any, probe: Any = None) -> Dict[str, Any]:
    rid = str((r.get("row_id") if isinstance(r, dict) else "") or "")
    qr: Optional[Dict[str, Any]] = None
    if store and rid:
        try:
            qr = store.quality.get_quality_report(run_id=run_id, row_id=rid)
        except (OSError, KeyError, TypeError, ValueError):
            qr = None
    info: Dict[str, Any] = {"score": 0, "tier": ""}
    if qr and isinstance(qr, dict):
        info = {"score": int(qr.get("score") or 0), "tier": str(qr.get("tier") or "")}
    # R8-059 (F5) : codec / résolution / audio depuis le probe — doublons.js
    # (cartes A/B, L375-388) lit qualityA.codec/.resolution/.audio_codec, jamais
    # fournis AVANT (seuls score+tier renvoyés) -> lignes Codec/Résolution/Audio
    # jamais affichées.
    if isinstance(probe, dict):
        video = probe.get("video") or {}
        codec = str(video.get("codec") or "")
        if codec:
            info["codec"] = codec
        w, h = video.get("width"), video.get("height")
        if w and h:
            info["resolution"] = f"{int(w)}x{int(h)}"
        tracks = probe.get("audio_tracks") or []
        if tracks and isinstance(tracks[0], dict):
            ac = str(tracks[0].get("codec") or "")
            if ac:
                info["audio_codec"] = ac
    return info


def _verdict_for(winner: str, side: str) -> str:
    if winner == side:
        return "À conserver"
    if winner in ("a", "b") and winner != side:
        return "Supprimable"
    return "Équivalent"


def _build_comparison_payload(
    result: Any,
    row_a: Dict[str, Any],
    row_b: Dict[str, Any],
    store: Any,
    run_id: str,
    probe_a: Any = None,
    probe_b: Any = None,
) -> Dict[str, Any]:
    winner = result.winner
    return {
        "winner": winner,
        "winner_label": result.winner_label,
        "total_score_a": result.total_score_a,
        "total_score_b": result.total_score_b,
        "recommendation": result.recommendation,
        "file_a_size": result.file_a_size,
        "file_b_size": result.file_b_size,
        "size_savings": result.size_savings,
        "file_a_name": _filename_from_row(row_a),
        "file_b_name": _filename_from_row(row_b),
        "quality_a": _quality_info_for_row(store, run_id, row_a, probe_a),
        "quality_b": _quality_info_for_row(store, run_id, row_b, probe_b),
        "verdict_a": _verdict_for(winner, "a"),
        "verdict_b": _verdict_for(winner, "b"),
        "criteria": [
            {
                "name": c.name,
                "label": c.label,
                "value_a": c.value_a,
                "value_b": c.value_b,
                "winner": c.winner,
                "points_delta": c.points_delta,
            }
            for c in result.criteria
        ],
    }


def _enrich_one_group(group: Dict[str, Any], run_id: str, store: Any) -> None:
    rows = group.get("rows") or []
    if len(rows) < 2:
        return
    probes = [_load_probe_for_row(store, run_id, item) for item in rows]
    if probes[0] is None or probes[1] is None:
        return
    try:
        result = compare_duplicates(probes[0], probes[1])
    except (OSError, KeyError, TypeError, ValueError):
        return
    group["comparison"] = _build_comparison_payload(
        result,
        rows[0],
        rows[1],
        store,
        run_id,
        probes[0],
        probes[1],  # R8-059 : probes -> codec/résolution/audio
    )


def _enrich_groups_with_quality_comparison(
    data: Dict[str, Any],
    run_id: str,
    store: Any,
) -> None:
    """Enrichit les groupes de doublons avec une comparaison qualite si les probes sont disponibles."""
    for group in data.get("groups") or []:
        _enrich_one_group(group, run_id, store)


def _annotate_groups_with_decisions(data: Dict[str, Any], run_id: str, store: Any) -> None:
    """R8-057 (F5) : joint les décisions doublons PERSISTÉES (table duplicate_decisions)
    au payload check_duplicates -> `winner_decided`/`winner_side`/`winner_row_id`.

    AVANT : check_duplicates ne relisait JAMAIS la décision -> au refresh le badge
    « Décidé » disparaissait (decidedCount=0), bien que la décision soit persistée
    et honorée à l'apply. On indexe les décisions par `group_key` (même clé que
    mark_duplicate_winner via `_group_key_for`) et on annote chaque groupe.
    """
    apply_repo = getattr(store, "apply", None) if store else None
    lister = getattr(apply_repo, "list_duplicate_decisions", None)
    if not callable(lister):
        return
    try:
        decisions = lister(run_id=run_id)
    except (OSError, KeyError, TypeError, ValueError):
        return
    by_key = {str(d.get("group_key") or ""): d for d in (decisions or []) if d.get("group_key")}
    if not by_key:
        return
    for group in data.get("groups") or []:
        dec = by_key.get(_group_key_for(group))
        if not dec:
            continue
        winner_row_id = str(dec.get("winner_row_id") or "")
        group["winner_decided"] = True
        group["winner_row_id"] = winner_row_id
        rows = group.get("rows") or []
        for idx, item in enumerate(rows[:2]):
            if str((item or {}).get("row_id") or "") == winner_row_id and winner_row_id:
                group["winner_side"] = "a" if idx == 0 else "b"
                break


def _compute_size_savings_total(data: Dict[str, Any]) -> int:
    """Agrege sum(group.comparison.size_savings) sur tous les groupes.

    Cf spec 01-doublons.md section 1 "Compteur Y Go recuperables".
    Tolere groupes sans `comparison` (probes indisponibles).
    """
    total = 0
    for g in data.get("groups") or []:
        comp = g.get("comparison") if isinstance(g, dict) else None
        if not isinstance(comp, dict):
            continue
        try:
            total += int(comp.get("size_savings") or 0)
        except (TypeError, ValueError):
            continue
    return total


def _group_key_for(group: Dict[str, Any]) -> str:
    """Cle stable pour identifier un groupe de doublons.

    Si le groupe expose deja une `group_key` / `id` / `signature`, on l'utilise.
    Sinon on fallback sur title|year (cf spec section 1).
    """
    for key in ("group_key", "id", "signature"):
        val = group.get(key)
        if val:
            return str(val)
    title = str(group.get("title") or "").strip().lower()
    year = group.get("year") or group.get("proposed_year") or ""
    return f"{title}|{year}".strip("|")


def mark_duplicate_winner(
    api: Any,
    run_id: str,
    group_key: str,
    winner_row_id: str,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Persiste la decision utilisateur "garder ce winner" pour un groupe.

    Cf docs/internal/design/refonte_2026_05_17/screens/01-doublons.md §3 :
      - Le winner est designe par son row_id (visible dans `check_duplicates`).
      - Les autres rows du groupe deviennent "losers". A l'apply,
        ils seront deplaces vers `<root>/_review/_duplicates_user_decided/`.
      - Persistance via ApplyRepository.upsert_duplicate_decision (PK = run+group).

    Retour : `{ok, group_key, winner_row_id, losers}` (cf signature dans le prompt).
    """
    if not run_id or not str(run_id).strip():
        return _err_response("run_id requis.", category="validation", level="info", log_module=__name__)
    if not group_key or not str(group_key).strip():
        return _err_response("group_key requis.", category="validation", level="info", log_module=__name__)
    if not winner_row_id or not str(winner_row_id).strip():
        return _err_response("winner_row_id requis.", category="validation", level="info", log_module=__name__)

    found = api._find_run_row(str(run_id))
    if not found:
        return _err_response(t("errors.run_not_found"), category="resource", level="info", log_module=__name__)
    _run_row, store = found

    # Recharge le groupe pour deduire les losers a partir du run (source de verite).
    #
    # F28 : cette recharge peut legitimement NE PAS retrouver le groupe. La
    # recharge `check_duplicates(api, run_id, {})` refusionne les decisions du
    # DISQUE (validation.json) et `_browse_all_if_none_approved` cesse
    # d'elargir des qu'UN row a ok=True -> find_duplicate_targets ne groupe plus
    # que les rows approuves, et le groupe affiche depuis le cache UI
    # (_groupsCache de doublons.js, qui survit aux navigations) disparait.
    # AVANT : on persistait alors loser_row_ids=[] avec ok=True -> a l'apply,
    # apply_support consomme les losers persistes SANS recompute et apply_core
    # early-return si vide : AUCUN fichier deplace, zero erreur, toast
    # « Decide » mensonger. On rend donc la persistance FAIL-CLOSED.
    losers: List[str] = []
    group_row_ids: List[str] = []
    group_found = False
    # F28 (revue R1) : nombre de groupes du reload qui portent CETTE cle. Deux
    # groupes DISTINCTS peuvent legitimement la partager — find_duplicate_targets
    # groupe sur movie_key(title, year, edition) (H11) alors que _group_key_for
    # retombe sur title|year (l'edition n'est pas dans le dict de groupe).
    matching_groups = 0
    try:
        check_resp = check_duplicates(api, str(run_id), {})
        if isinstance(check_resp, dict) and check_resp.get("ok"):
            for g in check_resp.get("groups") or []:
                if _group_key_for(g) != str(group_key):
                    continue
                matching_groups += 1
                row_ids = [str(r.get("row_id") or "") for r in (g.get("rows") or []) if isinstance(r, dict)]
                if str(winner_row_id) not in row_ids:
                    # Winner etranger a CE groupe : sans ce garde TOUS ses
                    # membres deviendraient losers et le film entier partirait au
                    # bucket _review. On NE s'arrete PAS : un autre groupe de
                    # meme cle peut etre le bon. S'arreter ici rendait le 2e
                    # groupe INDECIDABLE A VIE, avec un message trompeur
                    # (« Actualiser » reproduit exactement la meme collision).
                    continue
                if not group_found:
                    group_found = True
                    group_row_ids = row_ids
                    losers = [rid for rid in row_ids if rid and rid != str(winner_row_id)]
    except (KeyError, OSError, TypeError, ValueError, sqlite3.Error) as exc:
        # sqlite3.Error n'herite PAS de OSError : sans lui, une DB verrouillee
        # remontait jusqu'au boundary REST (500 generique).
        _logger.warning("mark_duplicate_winner: recharge groupes a echoue (%s) — decision refusee", exc)

    if not group_found:
        return _err_response(
            "Ce groupe de doublons n'est plus present dans le run (liste perimee) : "
            "clique sur Actualiser puis redecide.",
            category="state",
            level="info",
            log_module=__name__,
            group_key=str(group_key),
            stale=True,
        )

    # F28 (revue R1) : la PK de duplicate_decisions est (run_id, group_key). Quand
    # deux groupes REELS partagent la cle, persister le second ECRASE
    # silencieusement la decision prise sur le premier (upsert DO UPDATE) : ses
    # perdants ne sont plus deplaces a l'apply, sans aucun signal cote UI. On
    # refuse explicitement plutot que de detruire une decision utilisateur.
    # Garde volontairement borne au SEUL cas de collision (matching_groups > 1) :
    # le chemin nominal, y compris la re-decision d'un meme groupe, est inchange.
    if matching_groups > 1:
        previous: Optional[Dict[str, Any]] = None
        try:
            previous = store.apply.get_duplicate_decision(run_id=str(run_id), group_key=str(group_key))
        except (sqlite3.Error, OSError, AttributeError, TypeError, ValueError) as exc:
            # Lecture best-effort : si elle echoue, l'upsert ci-dessous echouera
            # de la meme facon et renverra une erreur explicite.
            _logger.warning("mark_duplicate_winner: lecture decision existante impossible (%s)", exc)
        prev_winner = str((previous or {}).get("winner_row_id") or "")
        if prev_winner and prev_winner != str(winner_row_id) and prev_winner not in group_row_ids:
            return _err_response(
                "Deux groupes de doublons distincts portent la meme cle "
                f"« {group_key} » (meme titre et meme annee, editions differentes). "
                "Enregistrer cette decision effacerait celle deja prise sur l'autre "
                "groupe : applique d'abord la decision en cours, ou differencie les "
                "titres/annees des deux editions.",
                category="state",
                level="warning",
                log_module=__name__,
                group_key=str(group_key),
                ambiguous_group_key=True,
            )

    try:
        decision = store.apply.upsert_duplicate_decision(
            run_id=str(run_id),
            group_key=str(group_key),
            winner_row_id=str(winner_row_id),
            loser_row_ids=losers,
            notes=notes,
        )
    except (OSError, TypeError, ValueError) as exc:
        return _err_response(
            f"Persistance decision impossible : {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )

    persisted_losers = list(decision.get("loser_row_ids") or [])
    return {
        "ok": True,
        "group_key": str(decision.get("group_key", group_key)),
        "winner_row_id": str(decision.get("winner_row_id", winner_row_id)),
        "losers": persisted_losers,
        # F28 (revue R1) : un groupe a UN SEUL row (cible deja existante sur
        # disque, cf existing_paths de find_duplicate_targets) n'a AUCUN perdant.
        # La decision est enregistree — elle vaut arbitrage — mais elle ne
        # deplacera RIEN a l'apply (apply_core early-return sur losers vide).
        # On l'annonce explicitement pour que l'UI cesse d'afficher un
        # « ✓ Decide » mensonger ; l'edit doublons.js est hors de ce fichier.
        "no_op": not persisted_losers,
        "decided_ts": float(decision.get("decided_ts") or 0.0),
    }


@requires_valid_run_id
def rescan_row(api: Any, run_id: str, row_id: str) -> Dict[str, Any]:
    """Spec 06 §3.6 : relance probe + analyse perceptuelle pour un seul row.

    Comportement pragmatique :
      - Invalide les caches probe / quality_report / perceptual_report pour la
        ligne.
      - Reappelle `quality/get_quality_report` qui re-execute le probe et le
        scoring.
      - Reappelle `perceptual/get_perceptual_report` qui relance l'analyse V2.
      - Retourne le plan_row courant + les nouveaux scores (quality.score + V2).

    Note : le match TMDb n'est PAS re-execute (le plan complet n'est pas
    rejoue ici — trop couteux pour 1 row). Les `candidates` existants restent
    valides. Pour reforcer un match TMDb, l'utilisateur doit relancer le run
    complet ou utiliser `set_film_tmdb_candidate` pour choisir manuellement.
    """
    rid_s = str(row_id or "").strip()
    if not rid_s:
        return _err_response("row_id manquant.", category="validation", level="info", log_module=__name__)

    found = api._find_run_row(run_id)
    if not found:
        return _err_response(t("errors.run_not_found"), category="resource", level="info", log_module=__name__)
    _, store = found

    # 1. Invalider les caches pour cette ligne
    try:
        with store._managed_conn() as conn:
            conn.execute(
                "DELETE FROM quality_reports WHERE run_id=? AND row_id=?",
                (str(run_id), rid_s),
            )
            conn.execute(
                "DELETE FROM perceptual_reports WHERE run_id=? AND row_id=?",
                (str(run_id), rid_s),
            )
    except (OSError, KeyError, TypeError, ValueError, AttributeError) as exc:
        _logger.warning("rescan_row: cache invalidation failed (%s)", exc)

    # 2. Re-execute la pipeline quality (probe + score)
    new_quality: Dict[str, Any] = {}
    try:
        from cinesort.ui.api import quality_report_support

        qres = quality_report_support.get_quality_report(api, str(run_id), rid_s, options={"reuse_existing": False})
        if isinstance(qres, dict) and qres.get("ok"):
            new_quality = {
                "score": int(qres.get("score") or 0),
                "tier": str(qres.get("tier") or ""),
            }
    except (ImportError, OSError, KeyError, TypeError, ValueError) as exc:
        _logger.warning("rescan_row: get_quality_report failed (%s)", exc)

    # 3. Re-execute la pipeline perceptuelle V2
    new_perceptual: Dict[str, Any] = {}
    try:
        from cinesort.ui.api import perceptual_support

        pres = perceptual_support.get_perceptual_report(api, str(run_id), rid_s)
        if isinstance(pres, dict) and pres.get("ok"):
            payload = pres.get("perceptual") if isinstance(pres.get("perceptual"), dict) else {}
            gv2 = payload.get("global_score_v2") or payload.get("global_score") or 0
            new_perceptual = {
                "global_score_v2": float(gv2 or 0),
                "global_tier_v2": str(payload.get("global_tier_v2") or payload.get("global_tier") or ""),
            }
    except (ImportError, OSError, KeyError, TypeError, ValueError) as exc:
        _logger.warning("rescan_row: get_perceptual_report failed (%s)", exc)

    # 4. Recharger la plan_row a jour
    plan = api.run.get_plan(str(run_id))
    plan_row: Optional[Dict[str, Any]] = None
    if plan and plan.get("ok"):
        for r in plan.get("rows") or []:
            if str(r.get("row_id") or "") == rid_s:
                plan_row = r
                break

    return {
        "ok": True,
        "run_id": str(run_id),
        "row_id": rid_s,
        "plan_row": plan_row,
        "quality": new_quality,
        "perceptual": new_perceptual,
    }


def _browse_all_if_none_approved(rows: Any, safe: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """AUDIT 2026-06-13 (R5-J) : la vue Doublons est un NAVIGATEUR de doublons.

    find_duplicate_targets ne groupe QUE les films approuves (`dec.ok`), car
    c'est concu comme une securite "collision de destination avant apply". Mais
    la vue Doublons (et son entree menu R5-E) appelle check_duplicates avec
    decisions={} HORS du workflow d'apply -> aucun film approuve -> 0 groupe
    affiche, alors que le badge/chip annoncent des doublons (meme titre+annee).

    Correctif : quand AUCUN film n'est approuve, on traite tous les films comme
    candidats pour que la vue montre les groupes (2+ films -> meme dossier
    destination). Si au moins un film est approuve (workflow apply en cours), on
    respecte les decisions. La securite pre-apply (apply_support.py:1235) reste
    INCHANGEE : elle appelle find_duplicate_targets directement avec les vraies
    decisions, jamais via check_duplicates.
    """
    try:
        any_ok = any(bool((safe.get(getattr(r, "row_id", "")) or {}).get("ok")) for r in rows)
    except (AttributeError, TypeError):
        return safe
    if any_ok:
        return safe
    browse = dict(safe)
    for r in rows:
        rid = getattr(r, "row_id", "")
        if not rid:
            continue
        browse[rid] = {
            "ok": True,
            "title": getattr(r, "proposed_title", "") or "",
            "year": getattr(r, "proposed_year", 0) or 0,
        }
    return browse


@requires_valid_run_id
def check_duplicates(api: Any, run_id: str, decisions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(decisions, dict):
        return _err_response(
            t("errors.payload_decisions_invalid"), category="validation", level="info", log_module=__name__
        )
    rs = api._get_run(run_id)
    if rs:
        if not rs.done:
            return _err_response(t("errors.plan_not_ready"), category="state", level="info", log_module=__name__)
        try:
            rows = rs.rows
            if not rows:
                rows = api._load_rows_from_plan_jsonl(rs.paths)
            incoming = decisions if isinstance(decisions, dict) else {}
            # Fix R6-02 : projette le tri-etat `decision` -> `ok` AVANT
            # _merge_decisions/_normalize_decisions_for_rows. Sinon un client
            # qui envoie `{decision: "accepted"}` sans `ok` voit son film
            # vu comme rejected dans check_duplicates (run_data_support.py:292)
            # et l'ecart avec apply diverge.
            incoming = _project_decisions_ok_from_tri_state(incoming)
            disk_decisions = api._load_decisions_from_validation(rs.paths)
            merged = api._merge_decisions(incoming, disk_decisions)
            safe = api._normalize_decisions_for_rows(rows, merged)
            safe = _browse_all_if_none_approved(rows, safe)  # R5-J : vue = navigateur
            data = _find_dups(rs.cfg, rows, safe)
            _enrich_groups_with_quality_comparison(data, run_id, rs.store)
            _annotate_groups_with_decisions(data, run_id, rs.store)  # R8-057
            data["size_savings_total"] = _compute_size_savings_total(data)
            return {"ok": True, **data}
        except (KeyError, OSError, TypeError, ValueError) as exc:
            return _err_response(str(exc), category="runtime", level="error", log_module=__name__)

    found = api._find_run_row(run_id)
    if not found:
        return _err_response(t("errors.run_not_found"), category="resource", level="info", log_module=__name__)
    row, found_store = found
    status_text = str(row.get("status") or "")
    if status_text not in {RunStatus.DONE.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value}:
        return _err_response(t("errors.plan_not_ready"), category="state", level="info", log_module=__name__)
    run_paths = api._run_paths_for(
        normalize_user_path(row.get("state_dir"), api._state_dir),
        run_id,
        ensure_exists=False,
    )
    try:
        rows = api._load_rows_from_plan_jsonl(run_paths)
        incoming = decisions if isinstance(decisions, dict) else {}
        # Fix R6-02 : projette le tri-etat `decision` -> `ok` (cf branche
        # rs ci-dessus). Cohere check_duplicates avec apply reel.
        incoming = _project_decisions_ok_from_tri_state(incoming)
        disk_decisions = api._load_decisions_from_validation(run_paths)
        merged = api._merge_decisions(incoming, disk_decisions)
        safe = api._normalize_decisions_for_rows(rows, merged)
        safe = _browse_all_if_none_approved(rows, safe)  # R5-J : vue = navigateur
        cfg = api._cfg_from_run_row(row)
        data = _find_dups(cfg, rows, safe)
        _enrich_groups_with_quality_comparison(data, run_id, found_store)
        _annotate_groups_with_decisions(data, run_id, found_store)  # R8-057
        data["size_savings_total"] = _compute_size_savings_total(data)
        return {"ok": True, **data}
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


# ---------------------------------------------------------------------------
# V2.4 — Fusion doublons Chromaprint + videohash (feature flag opt-in)
# Backward compat ABSOLUE : la fonction `check_duplicates` ci-dessus est
# INCHANGEE et reste le chemin actif par defaut. Cette nouvelle fonction est
# gate par CINESORT_FUSION_DOUBLONS (off par defaut) ; OFF -> stub vide.
# ---------------------------------------------------------------------------


def _row_field(row: Any, *keys: str, default: Any = None) -> Any:
    """Acces tolerant a un row (dataclass-like ou dict) sur plusieurs cles candidates."""
    for k in keys:
        if isinstance(row, dict):
            if k in row and row[k] is not None:
                return row[k]
        else:
            val = getattr(row, k, None)
            if val is not None:
                return val
    return default


def _fusion_video_path_for(row: Any, item: Any) -> str:
    """Chemin video absolu d'un membre de groupe doublons.

    F35 : les items produits par find_duplicate_targets (duplicate_support.py)
    n'exposent QUE row_id/kind/title/year/target/source_folder/source_root/
    warning_flags — aucune cle 'src'/'source_path'/'path'. On tente d'abord les
    cles explicites (formes tolerees / appelants historiques) puis on retombe
    sur les champs canoniques du PlanRow (folder + video).
    """
    explicit = _row_field(item, "src", "source_path", "path", "video_path") or _row_field(
        row, "src", "source_path", "path"
    )
    if explicit:
        return str(explicit)
    folder = _row_field(row, "folder", default="") or _row_field(item, "source_folder", default="")
    video = _row_field(row, "video", default="")
    if folder and video:
        return str(Path(str(folder)) / str(video))
    return ""


def _fusion_signals_from_store(store: Any, run_id: str, row_id: str) -> Tuple[float, Optional[str]]:
    """(duree, empreinte Chromaprint) lues depuis les artefacts deja persistes.

    F35 : PlanRow ne porte NI duration_s NI audio_fingerprint. La duree vient du
    quality_report (meme source que _build_pseudo_probe) et l'empreinte du
    perceptual_report (colonne audio_fingerprint, migration 015).

    Best-effort strict : ces deux lectures passent par _managed_conn, et
    sqlite3.Error n'herite PAS de OSError -> sans capture explicite, une DB
    verrouillee ferait tomber TOUT l'endpoint. Defauts 0.0 / None.
    """
    duration_s = 0.0
    chromaprint: Optional[str] = None
    if store is None or not row_id:
        return duration_s, chromaprint
    _swallowed = (sqlite3.Error, OSError, AttributeError, KeyError, TypeError, ValueError)
    try:
        report = store.quality.get_quality_report(run_id=str(run_id), row_id=str(row_id))
        if isinstance(report, dict) and isinstance(report.get("metrics"), dict):
            detected = report["metrics"].get("detected") or {}
            duration_s = float(detected.get("duration_s") or 0.0)
    except _swallowed:
        duration_s = 0.0
    try:
        perceptual = store.perceptual.get_perceptual_report(run_id=str(run_id), row_id=str(row_id))
        if isinstance(perceptual, dict):
            fingerprint = perceptual.get("audio_fingerprint")
            chromaprint = str(fingerprint) if fingerprint else None
    except _swallowed:
        chromaprint = None
    return duration_s, chromaprint


def _build_fusion_inputs_from_groups(
    groups: List[Any],
    rows: List[Any],
    *,
    store: Any = None,
    run_id: str = "",
) -> List[List[Any]]:
    """Convertit les groupes doublons legacy en groupes de FilmFusionInput.

    Strategie : on lit les rows referencees par chaque groupe et on cree un
    FilmFusionInput par film (chemin video, duree, fingerprint Chromaprint
    deja calcule si dispo). Le pipeline app gerera le calcul videohash et
    la fusion.

    F35 : les groupes de check_duplicates portent leurs membres sous la cle
    'rows' (duplicate_support.py, cf _enrich_one_group / _group_key_for), PAS
    'members' — la lecture historique rendait donc systematiquement 0 bucket et
    check_duplicates_fusion repondait toujours pairs=[]. 'members' reste tolere.

    `store` / `run_id` sont OPTIONNELS (retro-compat des appelants existants) :
    sans eux, duree et empreinte valent 0.0 / None et seul le signal video est
    exploitable.

    ATTENTION cout : avec le flag CINESORT_FUSION_DOUBLONS actif, chaque film
    retourne ici declenche une extraction ffmpeg en aval, et les paires sont en
    O(n^2) par groupe.
    """
    from cinesort.app.duplicate_pipeline import FilmFusionInput

    # Index rapide row_id -> row.
    row_by_id: Dict[str, Any] = {}
    for r in rows:
        rid = _row_field(r, "row_id", "id")
        if rid:
            row_by_id[str(rid)] = r

    out: List[List[FilmFusionInput]] = []
    for grp in groups or []:
        if isinstance(grp, dict):
            members = grp.get("rows") or grp.get("members")
        else:
            members = getattr(grp, "rows", None) or getattr(grp, "members", None)
        if not members or not isinstance(members, list):
            continue
        bucket: List[FilmFusionInput] = []
        for m in members:
            rid = str(m.get("row_id") if isinstance(m, dict) else getattr(m, "row_id", "") or "")
            if not rid:
                continue
            row = row_by_id.get(rid)
            video_path = _fusion_video_path_for(row, m)
            if not video_path:
                continue
            duration_s = _row_field(row, "duration_s", "duration", default=None)
            chromaprint = _row_field(row, "audio_fingerprint", "chromaprint", default=None)
            if duration_s is None or chromaprint is None:
                store_duration, store_fingerprint = _fusion_signals_from_store(store, run_id, rid)
                if duration_s is None:
                    duration_s = store_duration
                if chromaprint is None:
                    chromaprint = store_fingerprint
            bucket.append(
                FilmFusionInput(
                    row_id=rid,
                    video_path=str(video_path),
                    duration_s=float(duration_s or 0.0),
                    chromaprint=str(chromaprint) if chromaprint else None,
                )
            )
        if len(bucket) >= 2:
            out.append(bucket)
    return out


def _drop_unpositionable_films(fusion_groups: List[List[Any]]) -> List[List[Any]]:
    """Ecarte les films dont la duree est INCONNUE (<= 0) avant tout calcul video.

    F35 (revue R1) : `extract_video_thumbnails` (domain/video_hash.py) repartit
    ses N frames entre `start` et `end` ; avec `duration_s <= 0` la fenetre
    retombe sur [0.0, 1.0] et les 10 frames comparees tombent TOUTES dans la
    PREMIERE SECONDE du film — la zone ou quasiment tous les films sont noirs
    (logo studio / fondu d'ouverture). Deux films DIFFERENTS rendent alors une
    distance pHash nulle -> video_sim = 1.0 -> verdict 'confirmed'.

    Or duration_s vaut 0.0 des qu'il n'y a pas de quality_report : le recalcul
    qualite est un job de FOND lance apres le scan, desactivable
    (auto_recompute_quality_on_scan), et le probe peut echouer (SMB, fichier
    corrompu). Le cas nominal « scan tout juste termine » produit donc un
    « doublon confirme » sur deux films sans aucun rapport.

    Choix : degrader en MANQUE DE DETECTION (aucune paire) plutot qu'en FAUX
    POSITIF. Le prix est la perte de la comparaison audio-seule pour ces films
    — la neutralisation fine du seul signal video vit dans
    `cinesort/app/duplicate_pipeline.py::_videohash_for` (`return b''` si
    duree <= 0), hors du perimetre de fichiers de ce correctif.
    """
    kept: List[List[Any]] = []
    dropped = 0
    for bucket in fusion_groups or []:
        usable = [film for film in bucket if float(getattr(film, "duration_s", 0.0) or 0.0) > 0.0]
        dropped += len(bucket) - len(usable)
        if len(usable) >= 2:
            kept.append(usable)
    if dropped:
        _logger.warning(
            "fusion doublons : %d film(s) ecarte(s) — duree inconnue, le hash video "
            "serait calcule sur la seule 1re seconde (faux 'doublon confirme')",
            dropped,
        )
    return kept


@requires_valid_run_id
def check_duplicates_fusion(
    api: Any,
    run_id: str,
    decisions: Dict[str, Dict[str, Any]],
    *,
    audio_weight: Optional[float] = None,
    video_weight: Optional[float] = None,
) -> Dict[str, Any]:
    """V2.4 — Detection doublons via fusion Chromaprint + videohash.

    Backward compat ABSOLUE : ne touche AUCUN appelant existant ; la
    detection legacy `check_duplicates` reste seule active par defaut.
    Cet endpoint est gate par `CINESORT_FUSION_DOUBLONS` env var :
      - OFF -> retourne `{ok: True, enabled: False, pairs: []}` (stub).
      - ON  -> reutilise le regroupement legacy puis applique la fusion
              ponderee a chaque paire intra-groupe.
    """
    # Lazy import pour eviter d'introduire une dependance forte du module
    # de support sur le pipeline app au boot (idem pattern des autres helpers).
    from cinesort.app.duplicate_pipeline import (
        DEFAULT_AUDIO_WEIGHT,
        DEFAULT_VIDEO_WEIGHT,
        compute_fusion_for_groups,
        is_fusion_enabled,
        serialize_fusion_pairs,
    )

    if not is_fusion_enabled():
        # Feature flag off : aucun calcul, payload minimal pour la UI.
        return {"ok": True, "enabled": False, "pairs": []}

    if not isinstance(decisions, dict):
        return _err_response(
            t("errors.payload_decisions_invalid"),
            category="validation",
            level="info",
            log_module=__name__,
        )

    a_w = float(audio_weight) if audio_weight is not None else DEFAULT_AUDIO_WEIGHT
    v_w = float(video_weight) if video_weight is not None else DEFAULT_VIDEO_WEIGHT

    # On reutilise check_duplicates legacy pour obtenir les groupes candidats,
    # puis on enrichit chaque paire avec la fusion. Avantage : on profite des
    # validations et merges de decisions existants (R6-02 etc.), sans dupliquer
    # la logique. Si jamais la detection legacy renvoie une erreur, on la
    # propage telle quelle.
    legacy = check_duplicates(api, run_id, decisions)
    if not legacy.get("ok"):
        return legacy

    groups = legacy.get("groups") or legacy.get("duplicates") or []

    # Reconstruit les rows pour avoir acces a duration et fingerprint.
    # F35 : le store est indispensable — duree et empreinte Chromaprint ne sont
    # PAS des champs de PlanRow, elles vivent dans quality_reports /
    # perceptual_reports.
    rs = api._get_run(run_id)
    rows: List[Any] = []
    store: Any = None
    if rs:
        rows = rs.rows or api._load_rows_from_plan_jsonl(rs.paths) or []
        store = getattr(rs, "store", None)
    else:
        found = api._find_run_row(run_id)
        if found:
            row, store = found
            run_paths = api._run_paths_for(
                normalize_user_path(row.get("state_dir"), api._state_dir),
                run_id,
                ensure_exists=False,
            )
            rows = api._load_rows_from_plan_jsonl(run_paths) or []

    try:
        fusion_groups = _build_fusion_inputs_from_groups(groups, rows, store=store, run_id=run_id)
        # F35 (revue R1) : garde OBLIGATOIRE avant le premier appel ffmpeg — une
        # duree inconnue rend le hash video systematiquement « identique ».
        fusion_groups = _drop_unpositionable_films(fusion_groups)
        pairs = compute_fusion_for_groups(
            fusion_groups,
            audio_weight=a_w,
            video_weight=v_w,
        )
    except (OSError, ValueError, TypeError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)

    return {
        "ok": True,
        "enabled": True,
        "audio_weight": a_w,
        "video_weight": v_w,
        "pairs": serialize_fusion_pairs(pairs),
        # Echo legacy : la UI peut afficher les groupes brut a cote des paires.
        "groups": groups,
    }
