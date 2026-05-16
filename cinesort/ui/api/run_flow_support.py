from __future__ import annotations

from collections import Counter
import json
import logging
from pathlib import Path
import time
import traceback
from dataclasses import asdict
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

_logger = logging.getLogger(__name__)

import cinesort.domain.core as core
import cinesort.infra.state as state
from cinesort.infra.tmdb_client import TmdbClient
from cinesort.domain.i18n_messages import t
from cinesort.domain.run_models import RunStatus
from cinesort.domain.conversions import to_bool, to_float
from cinesort.ui.api._responses import err as _err_response
from cinesort.app.plan_support import plan_multi_roots
from cinesort.ui.api._validators import requires_valid_run_id
from cinesort.ui.api.settings_support import normalize_user_path


# Seuil duplique dans plan_support._ROOT_BULK_WARNING_THRESHOLD. Non importe
# pour garder ce module decouple de plan_support (eviter cycle import au boot).
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
        # Issue #103 : log structure via err() au lieu de return silencieux
        return _err_response(roots_error, category="config", level="info", log_module=__name__), None
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


def _compute_subtitle_coverage(rows: list) -> float:
    """Calcule le % de films avec sous-titres complets (pas de langue manquante)."""
    if not rows:
        return 100.0
    total = len(rows)
    complete = sum(1 for r in rows if not (getattr(r, "subtitle_missing_langs", None) or []))
    return round(100 * complete / total, 1)


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

    def dlog(msg: str) -> None:
        api._debug_log(state_dir=state_dir, run_id=run_id, enabled=debug_enabled, message=msg)
        if debug_enabled:
            rs.log("DEBUG", msg)

    dlog("start_plan runtime registered")
    tmdb = _init_tmdb_client(settings, state_dir, rs.log, dlog)

    def progress_with_persistence(idx: int, total: int, current: str) -> None:
        rs.progress(idx, total, current)
        try:
            store.update_run_progress(run_id, idx=idx, total=total, current_folder=current)
        except (KeyError, OSError, TypeError, ValueError) as exc:
            dlog(f"progress persistence warning idx={idx}/{total}: {exc}")

    def job_fn(should_cancel: Callable[[], bool]) -> Optional[Dict[str, Any]]:
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
            }
            if bool(getattr(cfg, "incremental_scan_enabled", False)):
                plan_kwargs["scan_index"] = store
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

            _save_plan_artifacts(rs, rows, stats, root, state_dir, dlog)

            # Capturer le snapshot sante bibliotheque dans les stats
            try:
                from cinesort.domain.librarian import generate_suggestions

                lib_result = generate_suggestions(rows, [], settings)
                stats_dict = dict(stats.__dict__)
                stats_dict["health_snapshot"] = {
                    "health_score": lib_result.get("health_score", 100),
                    "subtitle_coverage_pct": _compute_subtitle_coverage(rows),
                    "resolution_4k_pct": None,  # requiert quality reports (pas dispo au scan)
                    "codec_modern_pct": None,  # idem
                }
            except (ImportError, KeyError, OSError, TypeError, ValueError):
                stats_dict = dict(stats.__dict__)

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
                store.insert_error(
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
    if not isinstance(settings, dict):
        return _err_response(
            t("errors.payload_settings_invalid"), category="validation", level="info", log_module=__name__
        )

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
                config=dict(settings or {}),
                run_id_hint=run_id,
                debug_log=(lambda message: dlog(f"jobrunner: {message}")) if debug_enabled else None,
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
    rs = api._get_run(run_id)
    if not rs:
        found = api._find_run_row(run_id)
        if not found:
            return _err_response(t("errors.run_not_found"), category="resource", level="info", log_module=__name__)
        run_row, _store = found
        status_text = str(run_row.get("status") or RunStatus.FAILED.value)
        idx = int(run_row.get("idx") or 0)
        total = int(run_row.get("total") or 0)
        cur = str(run_row.get("current_folder") or "")
        running = status_text in {RunStatus.PENDING.value, RunStatus.RUNNING.value}
        done = status_text in {RunStatus.DONE.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value}
        err = str(run_row.get("error_message") or "") or None
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
        }

    with rs.lock:
        logs = rs.logs[last_log_index:]
        idx = rs.idx
        total = rs.total
        cur = rs.current_folder
        running = rs.running
        done = rs.done
        err = rs.error
        started = rs.started_ts
        samples = list(rs.progress_samples)
        ewma = rs.speed_ewma

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

    speed, eta = _compute_speed_and_eta(idx, total, started, samples, ewma)

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
        "next_log_index": last_log_index + len(logs),
        "status": status_text,
        "cancel_requested": cancel_requested,
    }


@requires_valid_run_id
def save_validation(api: Any, run_id: str, decisions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(decisions, dict):
        return _err_response(
            t("errors.payload_decisions_invalid"), category="validation", level="info", log_module=__name__
        )
    rs = api._get_run(run_id)
    if rs:
        try:
            rows = rs.rows
            if not rows:
                rows = api._load_rows_from_plan_jsonl(rs.paths)
            safe = api._normalize_decisions_for_rows(rows, decisions)
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
        safe = api._normalize_decisions_for_rows(rows, decisions)
        state.atomic_write_json(run_paths.validation_json, safe)
        api._file_logger(run_paths)("INFO", f"Validation enregistrée : {run_paths.validation_json}")
        return {"ok": True, "path": str(run_paths.validation_json)}
    except (KeyError, OSError, PermissionError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


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
        qr = store.get_quality_report(run_id=run_id, row_id=rid)
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
    folder = str(r.get("folder") or "")
    if folder:
        return folder.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    return "?"


def _quality_info_for_row(store: Any, run_id: str, r: Any) -> Dict[str, Any]:
    rid = str((r.get("row_id") if isinstance(r, dict) else "") or "")
    qr: Optional[Dict[str, Any]] = None
    if store and rid:
        try:
            qr = store.get_quality_report(run_id=run_id, row_id=rid)
        except (OSError, KeyError, TypeError, ValueError):
            qr = None
    if qr and isinstance(qr, dict):
        return {"score": int(qr.get("score") or 0), "tier": str(qr.get("tier") or "")}
    return {"score": 0, "tier": ""}


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
        "quality_a": _quality_info_for_row(store, run_id, row_a),
        "quality_b": _quality_info_for_row(store, run_id, row_b),
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
    from cinesort.domain.duplicate_compare import compare_duplicates

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
    group["comparison"] = _build_comparison_payload(result, rows[0], rows[1], store, run_id)


def _enrich_groups_with_quality_comparison(
    data: Dict[str, Any],
    run_id: str,
    store: Any,
) -> None:
    """Enrichit les groupes de doublons avec une comparaison qualite si les probes sont disponibles."""
    for group in data.get("groups") or []:
        _enrich_one_group(group, run_id, store)


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
            safe = api._normalize_decisions_for_rows(rows, decisions)
            # Cf #83 etape 2 PR 3 : point d'entree app/plan_support.
            from cinesort.app.plan_support import find_duplicate_targets as _find_dups

            data = _find_dups(rs.cfg, rows, safe)
            _enrich_groups_with_quality_comparison(data, run_id, rs.store)
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
        safe = api._normalize_decisions_for_rows(rows, decisions)
        cfg = api._cfg_from_run_row(row)
        # Cf #83 etape 2 PR 3 : point d'entree app/plan_support.
        from cinesort.app.plan_support import find_duplicate_targets as _find_dups

        data = _find_dups(cfg, rows, safe)
        _enrich_groups_with_quality_comparison(data, run_id, found_store)
        return {"ok": True, **data}
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)
