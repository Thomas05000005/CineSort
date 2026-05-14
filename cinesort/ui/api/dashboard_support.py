from __future__ import annotations

from collections import Counter
import csv
import io
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cinesort.domain.core as core
from cinesort.ui.api._validators import requires_valid_run_id
import cinesort.infra.state as state
from cinesort.infra.db import SQLiteStore
from cinesort.domain.conversions import to_bool, to_int
from cinesort.ui.api.settings_support import normalize_user_path

logger = logging.getLogger(__name__)


def _hdr_label(detected: Dict[str, Any]) -> str:
    """Construit un label HDR lisible depuis les flags detected."""
    parts = []
    if detected.get("hdr_dolby_vision"):
        parts.append("DV")
    if detected.get("hdr10_plus"):
        parts.append("HDR10+")
    elif detected.get("hdr10"):
        parts.append("HDR10")
    return " + ".join(parts) if parts else "SDR"


def _parse_stats_json(stats_json: Any) -> Dict[str, Any]:
    if isinstance(stats_json, str) and stats_json.strip():
        try:
            parsed = json.loads(stats_json)
            if isinstance(parsed, dict):
                return parsed
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return {}
    return {}


def _runs_history_payload(
    api: Any,
    *,
    runs: List[Dict[str, Any]],
    state_dir: Path,
    error_counts: Dict[str, Any],
    quality_counts: Dict[str, Dict[str, Any]],
    anomaly_counts: Dict[str, Any],
) -> List[Dict[str, Any]]:
    history: List[Dict[str, Any]] = []
    for run_row in runs:
        run_id = str(run_row.get("run_id") or "")
        stats_obj = _parse_stats_json(run_row.get("stats_json"))
        started_ts = float(run_row.get("started_ts") or run_row.get("created_ts") or 0.0)
        ended_ts = float(run_row.get("ended_ts") or 0.0)
        duration_s = 0
        if started_ts > 0 and ended_ts > 0 and ended_ts >= started_ts:
            duration_s = int(round(ended_ts - started_ts))
        total_rows = int(stats_obj.get("planned_rows") or run_row.get("total") or 0)
        applied_rows = int(stats_obj.get("applied_count") or 0)
        qstats = quality_counts.get(run_id, {})
        history.append(
            {
                "run_id": run_id,
                "run_dir": str(
                    api._run_paths_for(
                        normalize_user_path(run_row.get("state_dir"), state_dir),
                        run_id,
                        ensure_exists=False,
                    ).run_dir
                ),
                "started_ts": started_ts,
                "ended_ts": ended_ts,
                "duration_s": duration_s,
                "total_rows": total_rows,
                "applied_rows": applied_rows,
                "errors_count": int(error_counts.get(run_id, 0)),
                "anomalies_count": int(anomaly_counts.get(run_id, qstats.get("low_count", 0))),
            }
        )
    return history


def _empty_dashboard_payload(mode: str, runs_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "ok": True,
        "mode": mode,
        "run_id": None,
        "run_dir": None,
        "kpis": {
            "score_avg": 0.0,
            "score_premium_pct": 0.0,
            "total_movies": 0,
            "scored_movies": 0,
            "probe_partial_count": 0,
        },
        "distributions": {
            "score_bins": [{"label": f"{i * 10}-{(i * 10) + 9 if i < 9 else 100}", "count": 0} for i in range(10)],
            "resolutions": {"2160p": 0, "1080p": 0, "720p": 0, "other": 0},
            "hdr": {"SDR": 0, "HDR10": 0, "HDR10+": 0, "DV": 0, "Unknown": 0},
            "audio_codecs": [],
        },
        "anomalies_top": [],
        "outliers": {"low_bitrate": [], "sdr_4k": [], "vo_missing": []},
        "runs_history": runs_history,
        "message": "Aucun run disponible pour le dashboard.",
    }


def _severity_rank(level: str) -> int:
    normalized = str(level or "").upper()
    if normalized == "ERROR":
        return 3
    if normalized == "WARN":
        return 2
    return 1


# ---------------------------------------------------------------------------
# Phase 12 v7.8.0 : classifieurs purs extraits de `_build_dashboard_section`
# pour reduire la taille de la boucle d'agregation (241L -> ~120L).
# ---------------------------------------------------------------------------


def _classify_resolution(detected_resolution: str) -> str:
    """Range une chaine `detected.resolution` dans 4 buckets dashboard."""
    r = str(detected_resolution or "").lower()
    if "2160" in r:
        return "2160p"
    if "1080" in r:
        return "1080p"
    if "720" in r:
        return "720p"
    return "other"


def _classify_hdr(detected: Dict[str, Any], resolution_bucket: str) -> str:
    """Determine le bucket HDR (DV / HDR10+ / HDR10 / SDR / Unknown).

    `resolution_bucket` permet de distinguer "SDR" (resolution detectee, pas
    HDR) vs "Unknown" (pas meme de resolution).
    """
    if bool(detected.get("hdr_dolby_vision")):
        return "DV"
    if bool(detected.get("hdr10_plus")):
        return "HDR10+"
    if bool(detected.get("hdr10")):
        return "HDR10"
    return "SDR" if resolution_bucket != "other" else "Unknown"


def _classify_audio_bucket(detected: Dict[str, Any]) -> Optional[str]:
    """Range `detected.audio_best_codec` dans un bucket dashboard, ou None."""
    audio_codec = str(detected.get("audio_best_codec") or "").lower()
    if not audio_codec:
        return None
    if ("truehd" in audio_codec) or ("atmos" in audio_codec):
        return "TrueHD/Atmos"
    if ("dts-hd" in audio_codec) or ("dtshd" in audio_codec) or (("dts" in audio_codec) and ("ma" in audio_codec)):
        return "DTS-HD MA"
    if "dts" in audio_codec:
        return "DTS"
    if "aac" in audio_codec:
        return "AAC"
    return "Autre"


def _detect_vo_missing(detected: Dict[str, Any]) -> bool:
    """True si aucune piste audio VO (anglais) detectee."""
    languages = detected.get("languages") if isinstance(detected.get("languages"), list) else []
    languages_norm = {str(item).strip().lower() for item in languages if str(item).strip()}
    return not languages_norm.intersection({"en", "eng", "english", "vo", "vost"})


# 241L : assemblage lineaire du payload dashboard (rows, stats,
# distribution, anomalies, KPIs). Donnees heterogenes, pas de branchement.
def _build_dashboard_section(
    api: Any,
    *,
    run_id: str,
    run_row: Dict[str, Any],
    run_paths: state.RunPaths,
    store: SQLiteStore,
    rows: List[core.PlanRow],
) -> Dict[str, Any]:
    rows_by_id: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        rows_by_id[str(row.row_id)] = {
            "title": str(row.proposed_title or ""),
            "year": int(row.proposed_year or 0),
            "path": str(row.folder or ""),
            "video": str(row.video or ""),
        }

    reports = store.list_quality_reports(run_id=run_id)
    scores = [int(item.get("score") or 0) for item in reports]
    scored_movies = len(scores)
    score_avg = round(sum(scores) / scored_movies, 1) if scored_movies else 0.0
    premium_count = sum(1 for score in scores if score >= 85)
    score_premium_pct = round((premium_count * 100.0) / scored_movies, 1) if scored_movies else 0.0
    stats_obj = _parse_stats_json(run_row.get("stats_json"))
    total_movies = int(stats_obj.get("planned_rows") or len(rows) or 0)

    score_bins = [0 for _ in range(10)]
    resolutions = {"2160p": 0, "1080p": 0, "720p": 0, "other": 0}
    hdr_counts = {"SDR": 0, "HDR10": 0, "HDR10+": 0, "DV": 0, "Unknown": 0}
    audio_counter: Counter[str] = Counter()
    probe_partial_count = 0
    low_bitrate: List[Dict[str, Any]] = []
    sdr_4k: List[Dict[str, Any]] = []
    vo_missing: List[Dict[str, Any]] = []
    anomalies_light: List[Dict[str, Any]] = []

    def add_anomaly(level: str, code: str, message: str, *, row_id: str, path: str, action: str) -> None:
        anomalies_light.append(
            {
                "severity": str(level).upper(),
                "code": str(code),
                "message": str(message),
                "path": str(path),
                "run_id": run_id,
                "row_id": row_id,
                "recommended_action": str(action),
            }
        )

    for report in reports:
        score_i = int(report.get("score") or 0)
        idx = max(0, min(score_i // 10, 9))
        score_bins[idx] += 1

        metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
        detected = metrics.get("detected") if isinstance(metrics.get("detected"), dict) else {}
        thresholds = metrics.get("thresholds_used") if isinstance(metrics.get("thresholds_used"), dict) else {}
        probe_quality = str(metrics.get("probe_quality") or "")
        if probe_quality.upper() in {"PARTIAL", "FAILED"}:
            probe_partial_count += 1

        row_id = str(report.get("row_id") or "")
        row_meta = rows_by_id.get(row_id, {})
        title = str(row_meta.get("title") or "")
        year = int(row_meta.get("year") or 0)
        path = str(row_meta.get("path") or "")

        resolution_bucket = _classify_resolution(detected.get("resolution"))
        resolutions[resolution_bucket] += 1

        has_dv = bool(detected.get("hdr_dolby_vision"))
        has_hdr10p = bool(detected.get("hdr10_plus"))
        has_hdr10 = bool(detected.get("hdr10"))
        hdr_counts[_classify_hdr(detected, resolution_bucket)] += 1

        audio_bucket = _classify_audio_bucket(detected)
        if audio_bucket is not None:
            audio_counter[audio_bucket] += 1

        bitrate_kbps = int(detected.get("bitrate_kbps") or 0)
        threshold_2160 = int(thresholds.get("bitrate_min_kbps_2160p") or 0)
        if (
            (resolution_bucket == "2160p")
            and (bitrate_kbps > 0)
            and (threshold_2160 > 0)
            and (bitrate_kbps < threshold_2160)
        ):
            low_bitrate.append(
                {
                    "title": title,
                    "year": year,
                    "bitrate_kbps": bitrate_kbps,
                    "path": path,
                    "run_id": run_id,
                    "row_id": row_id,
                }
            )
            add_anomaly(
                "WARN",
                "LOW_BITRATE_4K",
                f"Debit faible pour 2160p ({bitrate_kbps} kbps).",
                row_id=row_id,
                path=path,
                action="Verifier une meilleure source ou version remux.",
            )

        if (resolution_bucket == "2160p") and (not has_dv) and (not has_hdr10p) and (not has_hdr10):
            sdr_4k.append(
                {
                    "title": title,
                    "year": year,
                    "path": path,
                    "run_id": run_id,
                    "row_id": row_id,
                }
            )
            add_anomaly(
                "INFO",
                "SDR_4K",
                "Fichier 4K sans HDR detecte (SDR).",
                row_id=row_id,
                path=path,
                action="Verifier si une edition HDR existe.",
            )

        if _detect_vo_missing(detected):
            vo_missing.append(
                {
                    "title": title,
                    "year": year,
                    "path": path,
                    "run_id": run_id,
                    "row_id": row_id,
                }
            )
            add_anomaly(
                "WARN",
                "VO_MISSING",
                "VO non detectee dans les pistes audio.",
                row_id=row_id,
                path=path,
                action="Verifier pistes audio et langues dans le fichier.",
            )

        if probe_quality.upper() == "FAILED":
            add_anomaly(
                "WARN",
                "PROBE_FAILED",
                "Analyse technique incomplete (probe FAILED).",
                row_id=row_id,
                path=path,
                action="Verifier la disponibilite de MediaInfo/ffprobe.",
            )
        elif probe_quality.upper() == "PARTIAL":
            add_anomaly(
                "INFO",
                "PROBE_PARTIAL",
                "Analyse technique partielle (probe PARTIAL).",
                row_id=row_id,
                path=path,
                action="Activer les deux outils probe pour plus de precision.",
            )

    anomalies_db = store.list_anomalies_for_run(run_id=run_id, limit=50)
    if anomalies_db:
        anomalies_top = [
            {
                "severity": str(item.get("severity") or "INFO"),
                "code": str(item.get("code") or ""),
                "message": str(item.get("message") or ""),
                "path": str(item.get("path") or ""),
                "run_id": str(item.get("run_id") or run_id),
                "row_id": str(item.get("row_id") or ""),
                "recommended_action": str(item.get("recommended_action") or ""),
            }
            for item in anomalies_db
        ]
    else:
        anomalies_light.sort(
            key=lambda item: (-_severity_rank(str(item.get("severity") or "INFO")), str(item.get("code") or ""))
        )
        anomalies_top = anomalies_light[:50]

    low_bitrate.sort(key=lambda item: int(item.get("bitrate_kbps") or 0))
    low_bitrate = low_bitrate[:20]
    sdr_4k = sdr_4k[:20]
    vo_missing = vo_missing[:20]
    bins_payload = [
        {"label": f"{i * 10}-{(i * 10) + 9}" if i < 9 else "90-100", "count": int(count)}
        for i, count in enumerate(score_bins)
    ]
    audio_top = [{"label": label, "count": int(count)} for label, count in audio_counter.most_common(6)]

    return {
        "kpis": {
            "score_avg": score_avg,
            "score_premium_pct": score_premium_pct,
            "total_movies": total_movies,
            "scored_movies": scored_movies,
            "probe_partial_count": probe_partial_count,
        },
        "distributions": {
            "score_bins": bins_payload,
            "resolutions": resolutions,
            "hdr": hdr_counts,
            "audio_codecs": audio_top,
        },
        "anomalies_top": anomalies_top,
        "outliers": {
            "low_bitrate": low_bitrate,
            "sdr_4k": sdr_4k,
            "vo_missing": vo_missing,
        },
        "message": "Dashboard genere avec succes." if scored_movies else "Run non score ou partiellement score.",
        "rows": _build_library_rows(rows, reports),
    }


def _build_library_rows(rows: list, reports: list) -> list:
    """Construit la liste de films pour la vue library du dashboard."""
    score_by_id = {}
    for r in reports:
        rid = str(r.get("row_id") or "")
        score_by_id[rid] = {
            "score": int(r.get("score") or 0),
            "tier": str(r.get("tier") or ""),
            "metrics": r.get("metrics") if isinstance(r.get("metrics"), dict) else {},
        }
    out = []
    for row in rows:
        rid = str(row.row_id)
        q = score_by_id.get(rid, {})
        metrics = q.get("metrics", {})
        detected = metrics.get("detected") if isinstance(metrics.get("detected"), dict) else {}
        out.append(
            {
                "row_id": rid,
                "proposed_title": str(row.proposed_title or ""),
                "proposed_year": int(row.proposed_year or 0),
                "resolution": str(detected.get("resolution_label") or ""),
                "score": q.get("score"),
                "confidence": int(getattr(row, "confidence", 0) or 0),
                "source": str(row.proposed_source or ""),
                "warning_flags": ",".join(getattr(row, "warning_flags", []) or []),
                "edition": str(getattr(row, "edition", "") or ""),
                "tmdb_collection_name": str(getattr(row, "tmdb_collection_name", "") or ""),
                "run_id": "",
            }
        )
    return out


def get_dashboard(api: Any, run_id: str = "latest") -> Dict[str, Any]:
    target_run = str(run_id or "latest").strip()
    try:
        settings = api.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _runner = api._get_or_create_infra(state_dir)

        mode = "latest"
        if target_run.lower() in {"", "latest", "dernier"}:
            run_row = store.get_latest_run()
        else:
            run_row = store.get_run(target_run)
            mode = "explicit"

        runs = store.list_runs(limit=20)
        run_ids = [str(item.get("run_id") or "") for item in runs if str(item.get("run_id") or "")]
        error_counts = store.get_error_counts_for_runs(run_ids)
        quality_counts = store.get_quality_counts_for_runs(run_ids)
        anomaly_counts = store.get_anomaly_counts_for_runs(run_ids)
        runs_history = _runs_history_payload(
            api,
            runs=runs,
            state_dir=state_dir,
            error_counts=error_counts,
            quality_counts=quality_counts,
            anomaly_counts=anomaly_counts,
        )

        if not run_row:
            return _empty_dashboard_payload(mode, runs_history)

        resolved_run_id = str(run_row.get("run_id") or "")
        run_paths = api._run_paths_for(
            normalize_user_path(run_row.get("state_dir"), state_dir),
            resolved_run_id,
            ensure_exists=False,
        )
        cached_payload = api._load_dashboard_cache(run_row=run_row, run_paths=run_paths, store=store)
        if isinstance(cached_payload, dict):
            return {
                "ok": True,
                "mode": mode,
                "run_id": resolved_run_id,
                "run_dir": str(run_paths.run_dir),
                **cached_payload,
                "runs_history": runs_history,
            }

        run_state = api._get_run(resolved_run_id)
        if run_state and run_state.rows:
            rows = run_state.rows
        else:
            try:
                rows = api._load_rows_from_plan_jsonl(run_paths)
            except (OSError, TypeError, ValueError):
                rows = []

        cached_section = _build_dashboard_section(
            api,
            run_id=resolved_run_id,
            run_row=run_row,
            run_paths=run_paths,
            store=store,
            rows=rows,
        )
        try:
            api._write_dashboard_cache(run_row=run_row, run_paths=run_paths, store=store, payload=cached_section)
        except (KeyError, OSError, TypeError, ValueError) as cache_exc:
            logger.debug("Dashboard cache write ignoree run_id=%s err=%s", resolved_run_id, cache_exc)

        return {
            "ok": True,
            "mode": mode,
            "run_id": resolved_run_id,
            "run_dir": str(run_paths.run_dir),
            **cached_section,
            "runs_history": runs_history,
        }
    except (OSError, TypeError, ValueError) as exc:
        api.log_api_exception(
            "get_dashboard",
            exc,
            run_id=None if target_run.lower() in {"", "latest", "dernier"} else target_run,
            state_dir=state_dir if "state_dir" in locals() else None,
            store=store if "store" in locals() else None,
            extra={"requested_run_id": target_run},
        )
        return {"ok": False, "message": "Impossible de charger la synthese du run."}


def _load_report_context(api: Any, run_id: str) -> Optional[Tuple[Any, Any, list, Any, str, Dict[str, Any]]]:
    """Load rows, run_paths, store, cfg_root for a run. Returns None tuple on error (error dict is first element)."""
    run_state = api._get_run(run_id)
    if run_state and not run_state.done:
        return None

    found = api._find_run_row(run_id)
    run_row: Dict[str, Any] = {}
    store: Optional[SQLiteStore] = None
    cfg_root = ""
    if run_state:
        store = run_state.store
        cfg_root = str(run_state.cfg.root)
        try:
            rows = run_state.rows if run_state.rows else api._load_rows_from_plan_jsonl(run_state.paths)
        except (OSError, TypeError, ValueError):
            return None
        run_paths = run_state.paths
        if found:
            run_row = found[0]
    else:
        if not found:
            return None
        run_row, store = found
        state_dir = normalize_user_path(run_row.get("state_dir"), api._state_dir)
        run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=False)
        try:
            rows = api._load_rows_from_plan_jsonl(run_paths)
        except (OSError, KeyError, TypeError, ValueError):
            return None
        cfg_root = str(api._cfg_from_run_row(run_row).root)

    return store, run_paths, rows, run_state, cfg_root, run_row


def _build_row_payload(
    run_id: str,
    row: Any,
    decision: Dict[str, Any],
    quality: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool, str, bool]:
    """Construit le payload d'une row pour le report. Retourne (payload, decision_ok, tier, is_partial)."""
    metrics = quality.get("metrics") if isinstance(quality.get("metrics"), dict) else {}
    probe_quality = str(metrics.get("probe_quality") or "")
    is_partial = probe_quality.upper() in {"PARTIAL", "FAILED"}
    tier = str(quality.get("tier") or "").strip()
    decision_ok = to_bool(decision.get("ok"), False)

    detected = metrics.get("detected") or {} if metrics else {}
    subscores = metrics.get("subscores") or {} if metrics else {}
    explanation = metrics.get("score_explanation") or {} if metrics else {}

    payload = {
        "run_id": run_id,
        "row_id": str(row.row_id),
        "kind": str(row.kind),
        "folder": str(row.folder),
        "video": str(row.video),
        "proposed_title": str(row.proposed_title),
        "proposed_year": int(row.proposed_year or 0),
        "proposed_source": str(row.proposed_source),
        "confidence": int(row.confidence or 0),
        "confidence_label": str(row.confidence_label),
        "decision_ok": decision_ok,
        "decision_title": str(decision.get("title") or row.proposed_title or ""),
        "decision_year": to_int(decision.get("year"), int(row.proposed_year or 0)),
        "quality_status": "analyzed" if bool(quality) else "not_analyzed",
        "quality_score": int(quality.get("score") or 0) if quality else None,
        "quality_tier": tier,
        "probe_quality": probe_quality,
        "quality_resolution": str(detected.get("resolution") or ""),
        "quality_video_codec": str(detected.get("video_codec") or ""),
        "quality_bitrate_kbps": int(detected.get("bitrate_kbps") or 0),
        "quality_audio_codec": str(detected.get("audio_best_codec") or ""),
        "quality_audio_channels": int(detected.get("audio_best_channels") or 0),
        "quality_hdr": _hdr_label(detected),
        "quality_subscore_video": int(subscores.get("video") or 0),
        "quality_subscore_audio": int(subscores.get("audio") or 0),
        "quality_subscore_extras": int(subscores.get("extras") or 0),
        "quality_explanation": str(explanation.get("narrative") or ""),
        "warning_flags": "|".join(row.warning_flags) if row.warning_flags else "",
        "nfo_present": bool(row.nfo_path),
        "subtitle_count": int(getattr(row, "subtitle_count", 0) or 0),
        "subtitle_languages": "|".join(getattr(row, "subtitle_languages", None) or []),
        "subtitle_missing": "|".join(getattr(row, "subtitle_missing_langs", None) or []),
        "subtitle_orphans": int(getattr(row, "subtitle_orphans", 0) or 0),
        "notes": str(row.notes or ""),
    }
    return payload, decision_ok, tier, is_partial


def _read_report_meta(run_paths: Any) -> Tuple[str, List[str]]:
    """Lit le resume et les derniers logs d'un run."""
    try:
        summary_text = state.read_text_safe(run_paths.summary_txt).strip()
    except (KeyError, OSError, PermissionError, TypeError, ValueError):
        summary_text = ""
    try:
        all_logs = run_paths.ui_log_txt.read_text(encoding="utf-8").splitlines()
        log_tail = all_logs[-200:]
    except (KeyError, OSError, PermissionError, TypeError, ValueError):
        log_tail = []
    return summary_text, log_tail


def build_run_report_payload(api: Any, run_id: str) -> Tuple[Dict[str, Any], Optional[state.RunPaths]]:
    """Assemble le payload complet du rapport d'un run."""
    ctx = _load_report_context(api, run_id)
    if ctx is None:
        run_state = api._get_run(run_id)
        if run_state and not run_state.done:
            return {"ok": False, "message": "Plan pas pret."}, None
        return {"ok": False, "message": "Run introuvable."}, None
    store, run_paths, rows, run_state, cfg_root, run_row = ctx

    decisions = api._normalize_decisions_for_rows(rows, api._load_decisions_from_validation(run_paths))

    quality_by_row: Dict[str, Dict[str, Any]] = {}
    if store:
        try:
            reports = store.list_quality_reports(run_id=run_id)
        except (OSError, TypeError, ValueError):
            reports = []
        for report in reports:
            row_id = str(report.get("row_id") or "").strip()
            if row_id:
                quality_by_row[row_id] = report

    rows_payload: List[Dict[str, Any]] = []
    validated_ok = 0
    quality_tiers: Counter[str] = Counter()
    quality_partial = 0
    for row in rows:
        payload, decision_ok, tier, is_partial = _build_row_payload(
            run_id,
            row,
            decisions.get(row.row_id, {}),
            quality_by_row.get(row.row_id, {}),
        )
        rows_payload.append(payload)
        if decision_ok:
            validated_ok += 1
        if tier:
            quality_tiers[tier] += 1
        if is_partial:
            quality_partial += 1

    stats_obj = _parse_stats_json(run_row.get("stats_json") if isinstance(run_row, dict) else None)
    summary_text, log_tail = _read_report_meta(run_paths)

    total_rows = len(rows_payload)
    report = {
        "schema": "run_report_v1",
        "run_id": run_id,
        "generated_ts": time.time(),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "run": {
            "status": str(run_row.get("status") or ("DONE" if run_state and run_state.done else "UNKNOWN")),
            "root": str(run_row.get("root") or cfg_root),
            "state_dir": str(run_row.get("state_dir") or str(api._state_dir)),
            "started_ts": float(run_row.get("started_ts") or 0.0),
            "ended_ts": float(run_row.get("ended_ts") or 0.0),
            "stats": stats_obj,
        },
        "paths": {
            "run_dir": str(run_paths.run_dir),
            "plan_jsonl": str(run_paths.plan_jsonl),
            "validation_json": str(run_paths.validation_json),
            "summary_txt": str(run_paths.summary_txt),
            "ui_log_txt": str(run_paths.ui_log_txt),
        },
        "counts": {
            "rows_total": total_rows,
            "validated_ok": validated_ok,
            "validated_ko": max(0, total_rows - validated_ok),
            "quality_reports": len(quality_by_row),
            "quality_probe_partial": quality_partial,
            "quality_tiers": dict(quality_tiers),
        },
        "rows": rows_payload,
        "apply_summary": summary_text,
        "logs_tail": log_tail,
    }
    return {"ok": True, "report": report}, run_paths


def report_to_csv_text(report: Dict[str, Any]) -> str:
    fieldnames = [
        "run_id",
        "row_id",
        "kind",
        "folder",
        "video",
        "proposed_title",
        "proposed_year",
        "proposed_source",
        "confidence",
        "confidence_label",
        "decision_ok",
        "decision_title",
        "decision_year",
        "quality_status",
        "quality_score",
        "quality_tier",
        "probe_quality",
        "quality_resolution",
        "quality_video_codec",
        "quality_bitrate_kbps",
        "quality_audio_codec",
        "quality_audio_channels",
        "quality_hdr",
        "quality_subscore_video",
        "quality_subscore_audio",
        "quality_subscore_extras",
        "quality_explanation",
        "warning_flags",
        "nfo_present",
        "notes",
    ]
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=fieldnames, delimiter=";")
    writer.writeheader()
    rows = report.get("rows")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                writer.writerow({key: row.get(key, "") for key in fieldnames})
    return out.getvalue()


def write_run_report_file(
    api: Any,
    *,
    run_paths: state.RunPaths,
    run_id: str,
    export_format: str,
    report: Dict[str, Any],
) -> Path:
    report_stem = f"report_{run_id}"
    if export_format == "json":
        out_path = run_paths.run_dir / f"{report_stem}.json"
        state.atomic_write_json(out_path, report)
        return out_path

    if export_format == "html":
        from cinesort.app.export_support import export_html_report

        out_path = run_paths.run_dir / f"{report_stem}.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(export_html_report(report), encoding="utf-8")
        return out_path

    out_path = run_paths.run_dir / f"{report_stem}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report_to_csv_text(report), encoding="utf-8-sig")
    return out_path


@requires_valid_run_id
def export_run_report(api: Any, run_id: str, fmt: str = "json") -> Dict[str, Any]:
    export_format = str(fmt or "json").strip().lower()
    if export_format not in {"json", "csv", "html"}:
        return {"ok": False, "message": "Format invalide. Utilisez 'json', 'csv' ou 'html'."}

    built, run_paths = build_run_report_payload(api, run_id)
    if not built.get("ok"):
        return built
    report = built.get("report") if isinstance(built.get("report"), dict) else {}
    if not report or run_paths is None:
        return {"ok": False, "message": "Impossible de construire le rapport de run."}

    try:
        out_path = write_run_report_file(
            api,
            run_paths=run_paths,
            run_id=run_id,
            export_format=export_format,
            report=report,
        )
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "message": f"Echec export rapport: {exc}"}

    counts = report.get("counts") if isinstance(report.get("counts"), dict) else {}
    return {
        "ok": True,
        "run_id": run_id,
        "format": export_format,
        "path": str(out_path),
        "rows_total": int(counts.get("rows_total") or 0),
    }


# ---------------------------------------------------------------------------
#  Global stats — multi-run dashboard
# ---------------------------------------------------------------------------

_TREND_RECENT_WINDOW = 5
_TREND_PREVIOUS_WINDOW = 5


def _compute_score_trend(quality_counts: Dict[str, Dict[str, Any]], run_ids: List[str]) -> str:
    """Compute trend indicator comparing recent 5 runs vs previous 5."""
    ordered = [rid for rid in run_ids if rid in quality_counts]
    if len(ordered) < 2:
        return "→"
    recent = ordered[:_TREND_RECENT_WINDOW]
    previous = ordered[_TREND_RECENT_WINDOW : _TREND_RECENT_WINDOW + _TREND_PREVIOUS_WINDOW]
    if not previous:
        return "→"
    avg_recent = sum(quality_counts[r].get("score_avg", 0) for r in recent) / len(recent)
    avg_prev = sum(quality_counts[r].get("score_avg", 0) for r in previous) / len(previous)
    delta = avg_recent - avg_prev
    if delta > 2.0:
        return "↑"
    if delta < -2.0:
        return "↓"
    return "→"


def _compute_health_trend(timeline: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calcule le delta de sante entre les 2 derniers runs ayant un snapshot."""
    points_with_hs = [p for p in reversed(timeline) if p.get("health_score") is not None]
    if len(points_with_hs) < 1:
        return {"arrow": "→", "delta": 0, "message": "Pas de donnees", "current": None}
    current = int(points_with_hs[0].get("health_score", 0))
    if len(points_with_hs) < 2:
        return {"arrow": "→", "delta": 0, "message": f"Sante : {current}%", "current": current}
    previous = int(points_with_hs[1].get("health_score", 0))
    delta = current - previous
    if delta > 0:
        arrow = "↑"
        msg = f"↑ +{delta}% depuis le dernier run"
    elif delta < 0:
        arrow = "↓"
        msg = f"↓ {delta}% depuis le dernier run"
    else:
        arrow = "→"
        msg = "→ Stable"
    return {"arrow": arrow, "delta": delta, "message": msg, "current": current}


def _compute_librarian_suggestions(
    api: Any,
    store: Any,
    latest_run_id: str,
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    """Calcule les suggestions bibliothecaire depuis les rows + quality reports du dernier run."""
    from cinesort.domain.librarian import generate_suggestions

    empty = {"suggestions": [], "health_score": 100}
    if not latest_run_id:
        return empty
    try:
        run_paths = api._run_paths_for(
            normalize_user_path(settings.get("state_dir"), state.default_state_dir()),
            latest_run_id,
            ensure_exists=False,
        )
        rows = api._load_rows_from_plan_jsonl(run_paths)
        reports = store.list_quality_reports(run_id=latest_run_id)
        return generate_suggestions(rows, reports, settings)
    except (ImportError, KeyError, OSError, TypeError, ValueError) as exc:
        logger.debug("librarian suggestions error: %s", exc)
        return empty


def _compute_space_analysis(store: Any, latest_run_id: str) -> Dict[str, Any]:
    """Calcule les metriques d'espace disque depuis les quality reports du dernier run."""
    empty: Dict[str, Any] = {
        "total_bytes": 0,
        "avg_bytes": 0,
        "film_count": 0,
        "by_tier": {},
        "by_resolution": {},
        "by_codec": {},
        "top_wasteful": [],
        "archivable_bytes": 0,
        "archivable_count": 0,
    }
    if not latest_run_id:
        return empty
    try:
        reports = store.list_quality_reports(run_id=latest_run_id)
    except (OSError, TypeError, ValueError):
        return empty
    if not reports:
        return empty

    by_tier: Dict[str, int] = {}
    by_res: Dict[str, int] = {}
    by_codec: Dict[str, int] = {}
    total = 0
    wasteful: list = []
    archivable_bytes = 0
    archivable_count = 0

    for r in reports:
        metrics = r.get("metrics") if isinstance(r.get("metrics"), dict) else {}
        detected = metrics.get("detected") or {} if metrics else {}
        size = int(detected.get("file_size_bytes") or 0)
        if size <= 0:
            # Fallback : estimer depuis bitrate + duration
            dur = float(detected.get("duration_s") or 0)
            br = int(detected.get("bitrate_kbps") or 0)
            if dur > 0 and br > 0:
                size = int(dur * br * 1000 / 8)
        if size <= 0:
            continue

        tier = str(r.get("tier") or "").strip()
        res = str(detected.get("resolution") or "SD")
        codec = str(detected.get("video_codec") or "autre").lower()
        score = int(r.get("score") or 0)

        total += size
        by_tier[tier] = by_tier.get(tier, 0) + size
        by_res[res] = by_res.get(res, 0) + size
        by_codec[codec] = by_codec.get(codec, 0) + size

        # U1 audit : "reject" (nouveau) + anciens noms "mauvais"/"faible" pour
        # les rapports anterieurs a la migration 011.
        if tier.lower() in ("reject", "mauvais", "faible"):
            archivable_bytes += size
            archivable_count += 1

        # Waste score : size_gb × (100 - score) / 100
        size_gb = size / (1024 * 1024 * 1024)
        waste = round(size_gb * (100 - score) / 100, 2)
        wasteful.append(
            {
                "row_id": str(r.get("row_id") or ""),
                "title": str(detected.get("title") or r.get("row_id") or ""),
                "size_bytes": size,
                "score": score,
                "tier": tier,
                "waste_score": waste,
            }
        )

    # Top 10 gaspilleurs
    wasteful.sort(key=lambda x: x["waste_score"], reverse=True)
    film_count = len(
        [
            r
            for r in reports
            if int((r.get("metrics") or {}).get("detected", {}).get("file_size_bytes") or 0) > 0
            or int((r.get("metrics") or {}).get("detected", {}).get("bitrate_kbps") or 0) > 0
        ]
    )

    return {
        "total_bytes": total,
        "avg_bytes": total // max(1, film_count),
        "film_count": film_count,
        "by_tier": by_tier,
        "by_resolution": by_res,
        "by_codec": by_codec,
        "top_wasteful": wasteful[:10],
        "archivable_bytes": archivable_bytes,
        "archivable_count": archivable_count,
    }


def _compute_v2_tier_distribution(store: Any, run_ids: List[str]) -> Dict[str, Any]:
    """v7.6.0 Vague 2 : distribution par tier V2 (Platinum/Gold/Silver/Bronze/Reject).

    Renvoie un dict avec counts + percentages + total.
    Les rows pre-v7.5 sans global_tier_v2 sont comptees comme "unknown".
    """
    try:
        dist = store.get_global_tier_v2_distribution(run_ids=run_ids) if run_ids else {}
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        logger.debug("tier_v2_distribution error: %s", exc)
        dist = {}

    total = sum(int(v) for v in dist.values()) if dist else 0
    if not dist:
        dist = {
            "platinum": 0,
            "gold": 0,
            "silver": 0,
            "bronze": 0,
            "reject": 0,
            "unknown": 0,
        }

    # Percentages (hors unknown pour le calcul si on veut les scores actifs)
    scored_total = sum(int(dist.get(t, 0)) for t in ("platinum", "gold", "silver", "bronze", "reject"))
    percentages = {}
    for tier, count in dist.items():
        if scored_total > 0 and tier != "unknown":
            percentages[tier] = round(int(count) / scored_total * 100.0, 1)
        else:
            percentages[tier] = 0.0

    return {
        "counts": {tier: int(v) for tier, v in dist.items()},
        "percentages": percentages,
        "total": total,
        "scored_total": scored_total,
    }


def _compute_trend_30days(store: Any) -> List[Dict[str, Any]]:
    """v7.6.0 Vague 2 : tendance score V2 moyen sur 30 derniers jours.

    Renvoie une liste de 30 points (1 par jour) avec avg_score (None si pas de data),
    pour affichage dans line-chart.js de la Home.
    """
    import time as _time

    now = _time.time()
    since = now - 30 * 86400.0

    try:
        raw = store.get_global_score_v2_trend(since_ts=since, until_ts=now)
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        logger.debug("trend_30days error: %s", exc)
        raw = []

    # Constituer une map par date
    by_date: Dict[str, Dict[str, Any]] = {r["date"]: r for r in raw}

    # Generer 30 points consecutifs
    points: List[Dict[str, Any]] = []
    for i in range(30, -1, -1):
        ts = now - i * 86400.0
        date_str = _time.strftime("%Y-%m-%d", _time.localtime(ts))
        pt = by_date.get(date_str)
        points.append(
            {
                "date": date_str,
                "avg_score": pt["avg_score"] if pt else None,
                "count": pt["count"] if pt else 0,
            }
        )

    return points


def _compute_active_insights(
    api: Any,
    store: Any,
    run_ids: List[str],
    settings: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """v7.6.0 Vague 2 : insights proactifs affiches sur la Home.

    Retourne une liste triee par severity desc + count desc :
      [{type, severity, count, label, filter_hint, icon}]
    Max 5 insights.
    """
    import time as _time

    insights: List[Dict[str, Any]] = []

    # 1. Run actif en cours
    try:
        for r in store.list_runs(limit=1):
            if r.get("status") == "running":
                insights.append(
                    {
                        "type": "run_in_progress",
                        "severity": "info",
                        "count": 0,
                        "label": "Analyse en cours",
                        "filter_hint": None,
                        "icon": "activity",
                    }
                )
                break
    except (AttributeError, OSError):
        pass

    # 2. Nouveaux Reject sur le dernier run
    if run_ids:
        latest_rid = run_ids[0]
        try:
            reports = store.list_perceptual_reports(run_id=latest_rid)
            reject_count = sum(1 for r in reports if str(r.get("global_tier_v2") or "").lower() == "reject")
            if reject_count > 0:
                insights.append(
                    {
                        "type": "new_rejects",
                        "severity": "warning",
                        "count": reject_count,
                        "label": f"{reject_count} film{'s' if reject_count > 1 else ''} classe{'s' if reject_count > 1 else ''} Reject dans le dernier scan",
                        "filter_hint": {"tier": ["reject"], "run_id": latest_rid},
                        "icon": "alert-triangle",
                    }
                )
        except (AttributeError, OSError):
            pass

    # 3. Doublons a trancher (sur le dernier run)
    if run_ids:
        try:
            anomaly_counts = store.get_anomaly_counts_for_runs([run_ids[0]])
            dup_count = int(anomaly_counts.get(run_ids[0], 0) or 0)
            # Filtre approximatif : compte total d'anomalies, ajustable si besoin
            if dup_count > 3:
                insights.append(
                    {
                        "type": "duplicates_to_resolve",
                        "severity": "warning",
                        "count": dup_count,
                        "label": f"{dup_count} anomalies a traiter",
                        "filter_hint": {"warning": "anomaly"},
                        "icon": "alert-circle",
                    }
                )
        except (AttributeError, OSError):
            pass

    # 4. DNR partiel (nouveau insight §15)
    try:
        dnr_count = store.count_v2_warnings_flag(flag="dnr_partial", run_ids=run_ids)
        if dnr_count > 0:
            insights.append(
                {
                    "type": "dnr_partial",
                    "severity": "info",
                    "count": dnr_count,
                    "label": f"{dnr_count} film{'s' if dnr_count > 1 else ''} en DNR partiel (grain supprime)",
                    "filter_hint": {"warning": "dnr_partial"},
                    "icon": "film",
                }
            )
    except (AttributeError, OSError):
        pass

    # 5. Nouveaux Platinum ce mois
    try:
        month_ago = _time.time() - 30 * 86400.0
        plat_count = store.count_v2_tier_since(tier="platinum", since_ts=month_ago)
        if plat_count > 0:
            insights.append(
                {
                    "type": "new_platinum_month",
                    "severity": "success",
                    "count": plat_count,
                    "label": f"{plat_count} film{'s' if plat_count > 1 else ''} Platinum ajoute{'s' if plat_count > 1 else ''} ce mois",
                    "filter_hint": {"tier": ["platinum"]},
                    "icon": "award",
                }
            )
    except (AttributeError, OSError):
        pass

    # Tri par severity puis count desc
    severity_order = {"warning": 0, "info": 1, "success": 2}
    insights.sort(key=lambda it: (severity_order.get(it["severity"], 9), -int(it.get("count") or 0)))

    # Limite a 5 insights
    return insights[:5]


def get_global_stats(api: Any, limit_runs: int = 20) -> Dict[str, Any]:
    """Aggregate statistics across multiple runs for global dashboard."""
    lim = max(2, min(100, int(limit_runs or 20)))
    try:
        settings = api.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _runner = api._get_or_create_infra(state_dir)

        # 1. Runs timeline
        runs_summary = store.get_runs_summary(limit=lim)
        run_ids = [r["run_id"] for r in runs_summary]
        if not run_ids:
            return {
                "ok": True,
                "summary": {
                    "total_runs": 0,
                    "total_films": 0,
                    "avg_score": 0,
                    "premium_pct": 0,
                    "trend": "→",
                    "unscored_films": 0,
                },
                "timeline": [],
                "tier_distribution": {},
                "top_anomalies": [],
                "activity": [],
                "runs_summary": [],
            }

        # 2. Quality counts per run (batch)
        quality_counts = store.get_quality_counts_for_runs(run_ids)
        error_counts = store.get_error_counts_for_runs(run_ids)
        anomaly_counts = store.get_anomaly_counts_for_runs(run_ids)

        # 3. Global tier distribution
        tier_data = store.get_global_tier_distribution(limit_runs=lim)

        # 4. Top anomaly codes
        top_anomalies = store.get_top_anomaly_codes(limit_runs=lim, limit_codes=10)

        # 5. Aggregated summary
        total_films = sum(r.get("total_rows", 0) for r in runs_summary)
        all_scored = sum(qc.get("scored_movies", 0) for qc in quality_counts.values())
        all_premium = sum(qc.get("premium_count", 0) for qc in quality_counts.values())
        weighted_scores = [
            (qc["score_avg"], qc["scored_movies"]) for qc in quality_counts.values() if qc.get("scored_movies", 0) > 0
        ]
        if weighted_scores:
            total_weight = sum(w for _, w in weighted_scores)
            avg_score = sum(s * w for s, w in weighted_scores) / total_weight if total_weight else 0.0
        else:
            avg_score = 0.0
        premium_pct = (all_premium / all_scored * 100) if all_scored else 0.0

        # 6. Trend (↑↓→)
        trend = _compute_score_trend(quality_counts, run_ids)

        # 7. Unscored films count (from latest run)
        unscored = 0
        if run_ids:
            latest_rid = run_ids[0]
            latest_total = next((r["total_rows"] for r in runs_summary if r["run_id"] == latest_rid), 0)
            latest_scored = quality_counts.get(latest_rid, {}).get("scored_movies", 0)
            unscored = max(0, latest_total - latest_scored)

        # 8. Timeline (per-run data points, avec health snapshot si disponible)
        timeline = []
        for r in reversed(runs_summary):
            rid = r["run_id"]
            qc = quality_counts.get(rid, {})
            point = {
                "run_id": rid,
                "start_ts": r.get("start_ts", 0),
                "score_avg": round(qc.get("score_avg", 0), 1),
                "scored_movies": qc.get("scored_movies", 0),
                "premium_count": qc.get("premium_count", 0),
                "total_rows": r.get("total_rows", 0),
                "errors": error_counts.get(rid, 0),
                "anomalies": anomaly_counts.get(rid, 0),
            }
            hs = r.get("health_snapshot")
            if isinstance(hs, dict):
                point["health_score"] = hs.get("health_score")
                point["subtitle_coverage_pct"] = hs.get("subtitle_coverage_pct")
                point["resolution_4k_pct"] = hs.get("resolution_4k_pct")
                point["codec_modern_pct"] = hs.get("codec_modern_pct")
            timeline.append(point)

        # 8b. Health trend (delta entre les 2 derniers runs ayant un snapshot)
        health_trend = _compute_health_trend(timeline)

        # 9. Activity (same as runs_summary but enriched)
        activity = []
        for r in runs_summary:
            rid = r["run_id"]
            qc = quality_counts.get(rid, {})
            activity.append(
                {
                    **r,
                    "score_avg": round(qc.get("score_avg", 0), 1),
                    "errors": error_counts.get(rid, 0),
                    "anomalies": anomaly_counts.get(rid, 0),
                }
            )

        # 10. Space analysis (depuis les quality reports du dernier run)
        space = _compute_space_analysis(store, run_ids[0] if run_ids else "")

        # 11. Librarian suggestions
        librarian_data = _compute_librarian_suggestions(api, store, run_ids[0] if run_ids else "", settings)

        # 12. v7.6.0 Vague 2 — Home overview-first payloads
        v2_tier_distribution = _compute_v2_tier_distribution(store, run_ids)
        trend_30days = _compute_trend_30days(store)
        insights = _compute_active_insights(api, store, run_ids, settings)

        # v7.6.0 Vague 9 : miroir des insights actifs dans le notification
        # center (deduplique par (code, source) pour la session).
        try:
            from cinesort.ui.api import notifications_support

            notifications_support.emit_from_insights(api, insights, source="dashboard")
        except ImportError:
            pass

        return {
            "ok": True,
            "summary": {
                "total_runs": len(runs_summary),
                "total_films": total_films,
                "avg_score": round(avg_score, 1),
                "premium_pct": round(premium_pct, 1),
                "trend": trend,
                "unscored_films": unscored,
            },
            "timeline": timeline,
            "tier_distribution": tier_data.get("tiers", {}),
            "total_scored": tier_data.get("total_scored", 0),
            "top_anomalies": top_anomalies,
            "activity": activity,
            "runs_summary": activity,  # alias pour le dashboard runs.js
            "space_analysis": space,
            "librarian": librarian_data,
            "health_trend": health_trend,
            # v7.6.0 Vague 2 — Home overview-first
            "v2_tier_distribution": v2_tier_distribution,
            "trend_30days": trend_30days,
            "insights": insights,
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        logger.warning("get_global_stats error: %s", exc, exc_info=True)
        return {"ok": False, "message": f"Impossible de calculer les statistiques globales: {exc}"}


# =========================================================
# V3-04 — Sidebar counters (badges)
# =========================================================

_SIDEBAR_CRITICAL_FLAGS = frozenset({"integrity_header_invalid", "integrity_probe_failed", "duplicate_quality"})
_SIDEBAR_REVIEW_CONFIDENCE_THRESHOLD = 70


def _row_needs_review(row: Any) -> bool:
    """Heuristique V3-04 : confiance < seuil OU warning critique."""
    conf = int(getattr(row, "confidence", 0) or 0)
    if conf < _SIDEBAR_REVIEW_CONFIDENCE_THRESHOLD:
        return True
    flags = getattr(row, "warning_flags", None) or []
    return any(f in _SIDEBAR_CRITICAL_FLAGS for f in flags)


def get_sidebar_counters(api: Any) -> Dict[str, int]:
    """V3-04 — Compteurs pour les badges sidebar.

    Retourne {validation, application, quality} pour le run le plus recent.
    Un compteur a 0 signifie "rien a faire", le badge correspondant restera invisible.
    """
    empty = {"validation": 0, "application": 0, "quality": 0}
    try:
        settings = api.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _runner = api._get_or_create_infra(state_dir)

        run_row = store.get_latest_run()
        if not run_row:
            return empty

        run_id = str(run_row.get("run_id") or "")
        if not run_id:
            return empty

        run_paths = api._run_paths_for(
            normalize_user_path(run_row.get("state_dir"), state_dir),
            run_id,
            ensure_exists=False,
        )

        try:
            rows = api._load_rows_from_plan_jsonl(run_paths)
        except (OSError, TypeError, ValueError):
            rows = []

        decisions = api._load_decisions_from_validation(run_paths) or {}

        approved_ids = {str(rid) for rid, dec in decisions.items() if isinstance(dec, dict) and bool(dec.get("ok"))}

        last_batch = None
        try:
            last_batch = store.get_last_reversible_apply_batch(run_id)
        except (OSError, AttributeError, TypeError, ValueError):
            last_batch = None

        validation = sum(1 for r in rows if _row_needs_review(r) and str(getattr(r, "row_id", "")) not in approved_ids)
        application = 0 if last_batch else len(approved_ids)
        quality = sum(1 for r in rows if getattr(r, "warning_flags", None))

        return {
            "validation": int(validation),
            "application": int(application),
            "quality": int(quality),
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        logger.debug("get_sidebar_counters fallback (err=%s)", exc)
        return empty
