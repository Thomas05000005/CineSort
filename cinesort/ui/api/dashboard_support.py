from __future__ import annotations

import csv
import io
import json
import logging
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cinesort.domain.core as core
import cinesort.infra.state as state
from cinesort.app.export_support import export_html_report
from cinesort.domain.confidence_thresholds import CONF_MEDIUM
from cinesort.domain.conversions import to_bool, to_int
from cinesort.domain.i18n_messages import t
from cinesort.domain.librarian import generate_suggestions
from cinesort.domain.probe_models import probe_quality_is_failed, probe_quality_is_partial_or_failed
from cinesort.domain.run_models import UNDO_DEADLINE_SECONDS
from cinesort.domain.subtitle_helpers import _normalize_iso639
from cinesort.domain.tiers_helpers import is_premium_tier
from cinesort.infra.db import SQLiteStore

# Imports MODULE-STYLE (pas `from X import f`) pour les modules `ui/api` :
# les tests patchent `cinesort.ui.api.<module>.<fonction>` et un import de
# symbole figerait le binding au chargement, rendant le patch inoperant en
# silence. Cf. la convention « module-style imports pour tests mockes ».
from cinesort.ui.api import (
    film_support,
    history_support,
    library_audit_support,
    notifications_support,
    run_read_support,
)
from cinesort.ui.api._responses import err as _err_response
from cinesort.ui.api._validators import requires_valid_run_id
from cinesort.ui.api.run_data_support import compute_total_fallback, count_plan_rows
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
    applied_counts: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    history: List[Dict[str, Any]] = []
    applied_counts = applied_counts or {}
    for run_row in runs:
        run_id = str(run_row.get("run_id") or "")
        stats_obj = _parse_stats_json(run_row.get("stats_json"))
        started_ts = float(run_row.get("started_ts") or run_row.get("created_ts") or 0.0)
        ended_ts = float(run_row.get("ended_ts") or 0.0)
        duration_s = 0
        if started_ts > 0 and ended_ts > 0 and ended_ts >= started_ts:
            duration_s = int(round(ended_ts - started_ts))
        # Fix audit 2026-05-25 (v1.5.4) Vague I : source unique de verite =
        # count_plan_rows(plan.jsonl). Fallback sur stats.planned_rows /
        # run_row.total uniquement si plan.jsonl absent (run en cours, run
        # FAILED avant ecriture du plan).
        # Fix audit 2026-05-26 (v1.5.6) Vague L : count-2. Fallback delegue a
        # compute_total_fallback() pour aligner avec history/run_flow.
        run_paths_for_count = api._run_paths_for(
            normalize_user_path(run_row.get("state_dir"), state_dir),
            run_id,
            ensure_exists=False,
        )
        total_rows = count_plan_rows(
            run_paths_for_count,
            fallback=compute_total_fallback(run_row, stats_obj),
        )
        # AUDIT 2026-07-13 (HIGH-7) : applied_count vit dans
        # apply_batches.summary_json (ecrit par l'apply), PAS dans runs.stats_json
        # (cle jamais ecrite) -> fallback stats_obj conserve pour les fixtures/demo.
        applied_rows = int(applied_counts.get(run_id, 0) or stats_obj.get("applied_count") or 0)
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
                # AUDIT 2026-06-10 : exposer le `status` (DB) — sans lui le CTA
                # "Reprendre la validation" (accueil showResume, statut
                # AWAITING_VALIDATION) et les filtres Statut/Undone de l'historique
                # ne matchaient jamais. Source : runs.status (list_runs SELECT *).
                "status": str(run_row.get("status") or "PENDING"),
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


def _active_run_id(api: Any) -> Optional[str]:
    """run_id du run actuellement en cours (running et pas done), ou None.

    AUDIT 2026-06-10 : get_dashboard ne renvoyait pas `active_run_id` (il
    n'existait que sur GET /api/health). L'accueil (_extractScanProgress) le
    lisait dans le payload get_dashboard -> la carte "Scan en cours" ne
    s'affichait jamais. Meme logique que rest_server._find_active_run_id.
    """
    runs = getattr(api, "_runs", None)
    runs_lock = getattr(api, "_runs_lock", None)
    if not runs or not runs_lock:
        return None
    try:
        with runs_lock:
            for run_id, rs in runs.items():
                if getattr(rs, "running", False) and not getattr(rs, "done", False):
                    return str(run_id)
    except (RuntimeError, AttributeError):
        return None
    return None


def _active_run_info(api: Any) -> Optional[Dict[str, Any]]:
    """AUDIT 2026-06-14 (R7-7) : bloc de progression du scan en cours, lu par
    accueil.js _extractScanProgress (total_rows/current_index/phase/status).
    get_dashboard n'exposait qu'active_run_id -> barre figee a "0/0" sans ETA.
    None si aucun scan actif."""
    try:
        rid = _active_run_id(api)
        if not rid:
            return None
        rs = api._get_run(rid)
        if rs is None:
            return None
        running = bool(getattr(rs, "running", False))
        return {
            "run_id": str(rid),
            "status": "running" if running else "idle",
            "phase": "running" if running else "idle",
            "total_rows": int(getattr(rs, "total", 0) or 0),
            "current_index": int(getattr(rs, "idx", 0) or 0),
        }
    except (AttributeError, OSError, TypeError, ValueError):
        return None


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

    reports = store.quality.list_quality_reports(run_id=run_id)
    scores = [int(item.get("score") or 0) for item in reports]
    scored_movies = len(scores)
    score_avg = round(sum(scores) / scored_movies, 1) if scored_movies else 0.0
    # AUDIT 2026-06-14 (R6-I) : confiance moyenne (identification) = moyenne des
    # PlanRow.confidence (0..100). Avant, l'accueil lisait latestRun.
    # avg_confidence_pct qui n'existe pas dans runs_history -> "Confiance
    # moyenne : —". On la calcule ici et on l'expose dans kpis.
    confidences = [int(getattr(r, "confidence", 0) or 0) for r in rows]
    confidence_avg = round(sum(confidences) / len(confidences), 1) if confidences else 0.0
    # AUDIT 2026-06-14 (R6-I) : Etape 2 "Verification" affichait toujours "0 cas"
    # car le backend n'exposait ni review_queue_count ni conflicts_count. On les
    # calcule depuis les rows : "cas a verifier" = film avec une alerte OU une
    # confiance faible ; "conflits" = film avec un flag d'incoherence de source.
    # [partition] Source UNIQUE : is_auto_approvable (run_read_support). "cas à vérifier"
    # = NON auto-approuvable (confiance < seuil, OU flag critique/intégrité/conflit, OU
    # titre/année absent). "conflits" = flag de conflit, désormais SOUS-ENSEMBLE de
    # "à examiner" (is_auto_approvable bloque sur _CONFLICT_FLAGS). Donc :
    #   auto (843) + à-examiner (62) = total,  et  843 + 157 ne peut plus dépasser total.
    # Avant : "à vérifier" = (flags OU low) comptait TOUT le run (905), et auto/conflits
    # se chevauchaient. Le seuil est celui de l'auto-approbation (settings) -> cohérent
    # avec la carte "Auto-approuvables (confiance ≥ N)".
    try:
        _auto_thr = to_int(api._get_settings_impl().get("auto_approve_threshold"), 85)
    except Exception:  # noqa: BLE001 — settings illisibles -> défaut 85
        _auto_thr = 85
    # Flags EFFECTIFS (bruts − alertes ignorées) = MÊME entrée que le payload get_plan
    # (history_support._subtract_ignored_flags), sinon "Cas à vérifier" (KPI) diverge de la
    # liste "Tous problèmes" dès qu'une alerte bloquante est ignorée par l'utilisateur.
    _ignored = run_read_support.ignored_alerts_by_row(store, [str(getattr(r, "row_id", "")) for r in rows])
    review_queue_count = 0
    conflicts_count = 0
    for _r in rows:
        _flags = run_read_support.effective_flags(
            getattr(_r, "warning_flags", []), _ignored.get(str(getattr(_r, "row_id", "")))
        )
        if not run_read_support.is_auto_approvable_flags(
            _flags,
            getattr(_r, "confidence", 0),
            getattr(_r, "proposed_title", ""),
            getattr(_r, "proposed_year", 0),
            _auto_thr,
        ):
            review_queue_count += 1
        if _flags & run_read_support._CONFLICT_FLAGS:
            conflicts_count += 1
    # #472 : SECONDE definition du meme KPI (la premiere est le `premium_count`
    # SQL de `quality.get_quality_counts_for_runs`). Elle portait le meme
    # litteral fossile `score >= 85` — seuil Platinum de l'echelle PRE-v1.5.5,
    # abandonnee pour 70/66/55/40. Les deux passent desormais par la MEME bande
    # de tiers (`domain.tiers_helpers`), donc `score_premium_pct` (stats du run)
    # et `premium_pct` (summary global) ne peuvent plus repondre differemment
    # sur la meme bibliotheque. Le tier lu est celui persiste avec le rapport,
    # calcule avec le profil actif au moment du scoring.
    premium_count = sum(1 for item in reports if is_premium_tier(item.get("tier")))
    score_premium_pct = round((premium_count * 100.0) / scored_movies, 1) if scored_movies else 0.0
    stats_obj = _parse_stats_json(run_row.get("stats_json"))
    # Fix audit 2026-05-26 (v1.5.6) Vague L : count-1. Aligner sur la source
    # unique de verite count_plan_rows(plan.jsonl) au lieu de len(rows). Le bug
    # subtil : si rows etait charge depuis un cache memoire RunState desynchro
    # apres une re-ecriture du plan, len(rows) divergait de count_plan_rows()
    # utilise par get_status / get_history_stats / runs_history. On standardise
    # toutes les surfaces compteur sur count_plan_rows. Fallback senior : on
    # garde l'ancienne priorite (stats.planned_rows puis 0) pour les cas ou le
    # plan.jsonl est inaccessible, mais on log un debug pour aider diagnostic.
    total_movies = count_plan_rows(
        run_paths,
        fallback=int(stats_obj.get("planned_rows") or 0),
    )

    # VAL-1 : compteurs validated/rejected calcules en live sur les decisions
    # persistees pour que les KPI cards refletent la realite immediatement
    # apres bulk-approve. Recalcul a chaque appel (cf get_dashboard pour le
    # contournement du cache _load_dashboard_cache).
    # R6-06 : compteur tri-etat explicite. Les decisions `deferred` sont
    # persistees avec ok=false (via to_legacy_ok_bool) — sans separation,
    # elles enflaient rejected_count et la carte "En attente" restait a 0.
    # On prefere le champ explicite `decision` (accepted/rejected/deferred),
    # fallback sur `ok` pour les payloads legacy sans `decision`.
    try:
        decisions = api._load_decisions_from_validation(run_paths) or {}
    except (OSError, TypeError, ValueError, AttributeError):
        decisions = {}
    accepted_count = 0
    rejected_count = 0
    deferred_count = 0
    for d in decisions.values():
        if not isinstance(d, dict):
            continue
        decision_val = d.get("decision")
        if decision_val == "accepted":
            accepted_count += 1
        elif decision_val == "rejected":
            rejected_count += 1
        elif decision_val == "deferred":
            deferred_count += 1
        elif decision_val is None:
            # Fallback legacy : pas de champ `decision`, on retombe sur `ok`.
            if d.get("ok") is True:
                accepted_count += 1
            elif d.get("ok") is False:
                rejected_count += 1
    # Backward compat : validated_count = accepted_count (ancien alias).
    validated_count = accepted_count

    # SCAN-1 : diagnostic scan expose depuis stats_obj pour la carte
    # "Diagnostic scan : N fichiers exclus par categorie". Sans cela
    # l'utilisateur ne peut pas savoir POURQUOI il manque des films.
    scan_diagnostic = {
        "films_rejected_ext": int(stats_obj.get("films_rejected_ext") or 0),
        "films_rejected_size": int(stats_obj.get("films_rejected_size") or 0),
        "films_rejected_name": int(stats_obj.get("films_rejected_name") or 0),
        "folders_rejected_underscore": int(stats_obj.get("folders_rejected_underscore") or 0),
        "folders_rejected_depth": int(stats_obj.get("folders_rejected_depth") or 0),
        "folders_rejected_scandir_error": int(stats_obj.get("folders_rejected_scandir_error") or 0),
    }
    scan_diagnostic["total_excluded"] = int(
        scan_diagnostic["films_rejected_ext"]
        + scan_diagnostic["films_rejected_size"]
        + scan_diagnostic["films_rejected_name"]
        + scan_diagnostic["folders_rejected_underscore"]
        + scan_diagnostic["folders_rejected_depth"]
        + scan_diagnostic["folders_rejected_scandir_error"]
    )

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
        # BUG-018 (hotfix1) : helper centralise (case-insensitive) au lieu de .upper() inline.
        if probe_quality_is_partial_or_failed(probe_quality):
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

        # BUG-018 (hotfix1) : helper centralise vs .upper() inline.
        if probe_quality_is_failed(probe_quality):
            add_anomaly(
                "WARN",
                "PROBE_FAILED",
                t("library.technical_analysis_incomplete"),
                row_id=row_id,
                path=path,
                action="Verifier la disponibilite de MediaInfo/ffprobe.",
            )
        elif probe_quality.upper() == "PARTIAL":
            add_anomaly(
                "INFO",
                "PROBE_PARTIAL",
                t("library.technical_analysis_partial"),
                row_id=row_id,
                path=path,
                action="Activer les deux outils probe pour plus de precision.",
            )

    anomalies_db = store.anomaly.list_anomalies_for_run(run_id=run_id, limit=50)
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

    # R8-066 (F5) : nombre de groupes de doublons DÉCIDÉS (même source que l'onglet
    # Historique : list_duplicate_decisions). AVANT : `duplicates_groups` absent des
    # kpis live -> stat « Groupes de doublons » toujours 0 + fallback d'estimation
    # des moves faussé (traitement.js:245/641/1444). NB : décidés (cohérent avec
    # l'historique), pas l'ensemble détecté (la détection n'est pas dans ce chemin).
    duplicates_groups = 0
    try:
        duplicates_groups = len(store.apply.list_duplicate_decisions(run_id=run_id) or [])
    except (AttributeError, OSError, KeyError, TypeError, ValueError):
        duplicates_groups = 0

    return {
        "kpis": {
            "score_avg": score_avg,
            "confidence_avg": confidence_avg,  # R6-I : confiance moyenne d'identification
            "review_queue_count": int(review_queue_count),  # R6-I : Etape 2 "cas a verifier"
            "conflicts_count": int(conflicts_count),  # R6-I : Etape 2 "conflits"
            "score_premium_pct": score_premium_pct,
            "total_movies": total_movies,
            "scored_movies": scored_movies,
            "probe_partial_count": probe_partial_count,
            # VAL-1 : exposition validated/rejected pour les KPI cards
            # Traitement (Valides / Rejetes / En attente).
            # R6-06 : exposition explicite tri-etat (accepted/rejected/
            # deferred). validated_count == accepted_count (backward compat).
            "validated_count": int(validated_count),
            "rejected_count": int(rejected_count),
            "accepted_count": int(accepted_count),
            "deferred_count": int(deferred_count),
            "duplicates_groups": int(duplicates_groups),  # R8-066 (F5)
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
        # SCAN-1 : carte "Diagnostic scan" avec breakdown des exclusions.
        "scan_diagnostic": scan_diagnostic,
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
                # Issue #866 : la cle ecrite par le producteur unique de
                # `metrics.detected` (quality_score._build_metrics:1960) est
                # `resolution`, pas `resolution_label` -- ce dernier n'est qu'un
                # nom de variable LOCAL dans le scoring. `resolution_label`
                # n'existant dans aucun `detected` produit, le `.get()` rendait
                # None sur 100% des films et la colonne Resolution de ces rows
                # etait vide par construction. `_classify_resolution` (l.448)
                # lit deja la bonne cle sur le meme dict, dans ce meme fichier.
                "resolution": str(detected.get("resolution") or ""),
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


# Issue #491 : le delai d'annulation post-apply (Spec 08 §3.5) etait recopie
# ici ET dans `apply_support`. Le compte a rebours affiche par la vue Traitement
# et le refus HTTP 410 du backend decrivent la MEME promesse : ils lisent
# maintenant la meme constante, `domain.run_models.UNDO_DEADLINE_SECONDS`.


def _build_pending_undo_payload(store: SQLiteStore, run_id: str) -> Optional[Dict[str, Any]]:
    """Resume du dernier apply reversible : timestamp + deadline 24h.

    Retourne None si aucun batch apply reel n'est associe au run, sinon un dict
    consomme par la carte "Annulation possible" de la vue Traitement (spec 08
    §3.5). Calcule en dehors du cache dashboard pour que le countdown reste
    a jour a chaque get_dashboard.
    """
    try:
        batch = store.apply.get_last_reversible_apply_batch(run_id)
    except (OSError, AttributeError, TypeError, ValueError):
        return None
    if not batch:
        return None

    batch_id = str(batch.get("batch_id") or "")
    apply_ts = float(batch.get("started_ts") or 0.0)
    now = time.time()
    deadline_ts = apply_ts + UNDO_DEADLINE_SECONDS if apply_ts > 0 else 0.0
    expired = bool(apply_ts > 0 and now >= deadline_ts)

    reversible_count = 0
    try:
        ops = store.apply.list_apply_operations(batch_id=batch_id) if batch_id else []
        reversible_count = sum(1 for op in ops if int(op.get("reversible") or 0) == 1)
    except (OSError, AttributeError, TypeError, ValueError):
        reversible_count = 0

    if reversible_count <= 0:
        # Aucun op reversible : on n'expose pas la carte (rien a annuler).
        return None

    return {
        "batch_id": batch_id,
        "apply_ts": apply_ts,
        "deadline_ts": deadline_ts,
        "deadline_seconds_total": UNDO_DEADLINE_SECONDS,
        "remaining_seconds": max(0, int(deadline_ts - now)) if deadline_ts > 0 else 0,
        "expired": expired,
        "reversible_count": int(reversible_count),
    }


def get_dashboard(api: Any, run_id: str = "latest") -> Dict[str, Any]:
    target_run = str(run_id or "latest").strip()
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _runner = api._get_or_create_infra(state_dir)

        mode = "latest"
        if target_run.lower() in {"", "latest", "dernier"}:
            run_row = store.run.get_latest_run()
        else:
            run_row = store.run.get_run(target_run)
            mode = "explicit"

        runs = store.run.list_runs(limit=20)
        run_ids = [str(item.get("run_id") or "") for item in runs if str(item.get("run_id") or "")]
        error_counts = store.run.get_error_counts_for_runs(run_ids)
        quality_counts = store.quality.get_quality_counts_for_runs(run_ids)
        anomaly_counts = store.anomaly.get_anomaly_counts_for_runs(run_ids)
        # AUDIT 2026-07-13 (HIGH-7) : applied_count reel depuis apply_batches
        # (best-effort : {} si la table est indisponible, ne bloque pas l'accueil).
        try:
            applied_counts = store.apply.get_applied_counts_for_runs(run_ids)
        except (OSError, AttributeError, TypeError, ValueError):
            applied_counts = {}
        runs_history = _runs_history_payload(
            api,
            runs=runs,
            state_dir=state_dir,
            error_counts=error_counts,
            quality_counts=quality_counts,
            anomaly_counts=anomaly_counts,
            applied_counts=applied_counts,
        )

        if not run_row:
            return {**_empty_dashboard_payload(mode, runs_history), "active_run_id": _active_run_id(api)}

        resolved_run_id = str(run_row.get("run_id") or "")
        run_paths = api._run_paths_for(
            normalize_user_path(run_row.get("state_dir"), state_dir),
            resolved_run_id,
            ensure_exists=False,
        )
        # Spec 08 §3.5 : recalcul "live" du delai d'undo a chaque appel
        # (hors cache dashboard) — countdown qui s'ecoule entre deux GET.
        pending_undo = _build_pending_undo_payload(store, resolved_run_id)

        # VAL-1 : recalcul live de validated_count / rejected_count pour que
        # les KPI cards refletent immediatement bulk-approve / annulation sans
        # attendre l'invalidation du cache dashboard.
        # R6-06 : meme logique tri-etat que _build_dashboard_section.
        try:
            _decisions_live = api._load_decisions_from_validation(run_paths) or {}
        except (OSError, TypeError, ValueError, AttributeError):
            _decisions_live = {}
        accepted_live = 0
        rejected_live = 0
        deferred_live = 0
        for d in _decisions_live.values():
            if not isinstance(d, dict):
                continue
            decision_val = d.get("decision")
            if decision_val == "accepted":
                accepted_live += 1
            elif decision_val == "rejected":
                rejected_live += 1
            elif decision_val == "deferred":
                deferred_live += 1
            elif decision_val is None:
                if d.get("ok") is True:
                    accepted_live += 1
                elif d.get("ok") is False:
                    rejected_live += 1
        validated_live = accepted_live

        cached_payload = api._load_dashboard_cache(run_row=run_row, run_paths=run_paths, store=store)
        if isinstance(cached_payload, dict):
            # VAL-1 : injecter les compteurs live dans kpis pour contourner le cache stale.
            cached_kpis = cached_payload.get("kpis") if isinstance(cached_payload.get("kpis"), dict) else {}
            if isinstance(cached_kpis, dict):
                cached_kpis = dict(cached_kpis)
                cached_kpis["validated_count"] = int(validated_live)
                cached_kpis["rejected_count"] = int(rejected_live)
                # R6-06 : injection tri-etat dans le cache pour la carte
                # "En attente" / "Reporte".
                cached_kpis["accepted_count"] = int(accepted_live)
                cached_kpis["deferred_count"] = int(deferred_live)
                # AUDIT 2026-07-13 (HIGH-7) : applied_rows LIVE (source
                # apply_batches) pour l'etape Apply (traitement.js) — injecte hors
                # cache car l'apply survient APRES l'ecriture du cache dashboard.
                cached_kpis["applied_rows"] = int(applied_counts.get(resolved_run_id, 0))
                cached_payload = {**cached_payload, "kpis": cached_kpis}
            return {
                "ok": True,
                "mode": mode,
                "run_id": resolved_run_id,
                "run_dir": str(run_paths.run_dir),
                **cached_payload,
                "runs_history": runs_history,
                "pending_undo": pending_undo,
                "active_run_id": _active_run_id(api),
                "run_info": _active_run_info(api),
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

        # AUDIT 2026-07-13 (HIGH-7) : applied_rows LIVE injecte APRES l'ecriture du
        # cache (le cache ne doit pas figer le 0 du scan ; le chemin cache ci-dessus
        # re-injecte la valeur live a chaque GET).
        if isinstance(cached_section.get("kpis"), dict):
            cached_section["kpis"]["applied_rows"] = int(applied_counts.get(resolved_run_id, 0))

        return {
            "ok": True,
            "mode": mode,
            "run_id": resolved_run_id,
            "run_dir": str(run_paths.run_dir),
            **cached_section,
            "runs_history": runs_history,
            "pending_undo": pending_undo,
            "active_run_id": _active_run_id(api),
            "run_info": _active_run_info(api),
        }
    # Fix audit 2026-05-25 (v1.5.3) Vague F : elargi a Exception pour eviter
    # HTTP 500 sur RuntimeError/MemoryError/etc (cas run obsolete + DB locked).
    # On preserve le message historique (test_dashboard verifie l'egalite stricte)
    # et on ajoute user_message + error pour le contrat homogene Vague F.
    except Exception as exc:  # noqa: BLE001 - boundary top-level pour endpoint accueil
        api.log_api_exception(
            "get_dashboard",
            exc,
            run_id=None if target_run.lower() in {"", "latest", "dernier"} else target_run,
            state_dir=state_dir if "state_dir" in locals() else None,
            store=store if "store" in locals() else None,
            extra={"requested_run_id": target_run},
        )
        logger.exception("get_dashboard failed for run_id=%s", target_run)
        return {
            "ok": False,
            "error": "dashboard_load_failed",
            "message": "Impossible de charger la synthese du run.",
            "user_message": ("Impossible de charger la synthese du run. Relance un scan ou redemarre l'app."),
            "detail": str(exc),
        }


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


_CATEGORY_LABELS_FR_FALLBACK: Dict[str, str] = {
    "video": "Vidéo",
    "audio": "Audio",
    "extras": "Extras",
    "custom_rules": "Règles personnalisées",
}


def compose_score_explanation(
    quality_report: Optional[Dict[str, Any]],
    custom_rules_result: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Compose les sources `score_explanation` (build_rich_explanation) et
    `applied_rule_ids` (apply_custom_rules) en une structure waterfall unifiee
    pour l'inspecteur frontend.

    VO-C-BACKEND : helper PURE (stateless, deterministe). Ne modifie aucune
    des sources et n'execute aucune logique de scoring : se contente d'agreger
    les champs deja calcules pour exposer une vue waterfall coherente au
    frontend.

    Args:
        quality_report: dict report qualite (peut contenir `metrics` ou etre
            deja le metrics) OU directement le dict `score_explanation`. Si
            None ou vide -> renvoie None (backward compat : le frontend gere
            l'absence).
        custom_rules_result: dict retourne par `apply_custom_rules`
            (contient `applied_rule_ids`). Optionnel : si None, on tente de
            recuperer `applied_rule_ids` depuis `quality_report.metrics`.

    Returns:
        dict {categories, baseline, suggestions, applied_rule_ids, narrative,
              top_positive, top_negative} ou None si pas d'explanation
        disponible.

        - categories : list[{name, label, contribution, ...}] avec videos/
          audio/extras venant de build_rich_explanation + une entree
          custom_rules ajoutee SI applied_rule_ids non vide.
        - applied_rule_ids : list[str] toujours presente (vide si pas de
          regles appliquees).
        - autres champs : passthrough depuis build_rich_explanation.
    """
    if not quality_report or not isinstance(quality_report, dict):
        return None

    # Le quality_report peut etre soit le report complet (contient `metrics`),
    # soit directement le metrics, soit directement le score_explanation.
    explanation: Dict[str, Any] = {}
    metrics: Dict[str, Any] = {}
    if isinstance(quality_report.get("score_explanation"), dict):
        # quality_report est en realite le metrics dict
        explanation = quality_report["score_explanation"]
        metrics = quality_report
    elif isinstance(quality_report.get("metrics"), dict):
        metrics = quality_report["metrics"]
        if isinstance(metrics.get("score_explanation"), dict):
            explanation = metrics["score_explanation"]
    elif "categories" in quality_report or "narrative" in quality_report:
        # quality_report est en realite le score_explanation deja extrait
        explanation = quality_report

    if not explanation:
        return None

    # categories : dict -> list, en ajoutant une entree custom_rules si pertinent.
    raw_categories = explanation.get("categories") or {}
    categories_list: List[Dict[str, Any]] = []
    if isinstance(raw_categories, dict):
        for name, info in raw_categories.items():
            if not isinstance(info, dict):
                continue
            entry = {"name": str(name), **info}
            entry.setdefault("label", _CATEGORY_LABELS_FR_FALLBACK.get(str(name), str(name)))
            categories_list.append(entry)
    elif isinstance(raw_categories, list):
        categories_list = [dict(item) for item in raw_categories if isinstance(item, dict)]

    # applied_rule_ids : priorite au parametre explicite, sinon depuis metrics.
    applied_rule_ids: List[str] = []
    if custom_rules_result and isinstance(custom_rules_result, dict):
        raw = custom_rules_result.get("applied_rule_ids") or []
        if isinstance(raw, list):
            applied_rule_ids = [str(r) for r in raw if str(r or "").strip()]
    if not applied_rule_ids and metrics:
        raw = metrics.get("applied_rule_ids") or []
        if isinstance(raw, list):
            applied_rule_ids = [str(r) for r in raw if str(r or "").strip()]

    # Si des regles ont ete appliquees, ajouter une categorie synthetique
    # custom_rules pour la cohérence du waterfall (contribution non chiffrée
    # ici car deja agregee dans la video subscore par compute_quality_score).
    if applied_rule_ids and not any(c.get("name") == "custom_rules" for c in categories_list):
        categories_list.append(
            {
                "name": "custom_rules",
                "label": _CATEGORY_LABELS_FR_FALLBACK["custom_rules"],
                "rule_ids": list(applied_rule_ids),
                "rules_count": len(applied_rule_ids),
            }
        )

    return {
        "categories": categories_list,
        "baseline": dict(explanation.get("baseline") or {}),
        "suggestions": list(explanation.get("suggestions") or []),
        "applied_rule_ids": applied_rule_ids,
        "narrative": str(explanation.get("narrative") or ""),
        "top_positive": list(explanation.get("top_positive") or []),
        "top_negative": list(explanation.get("top_negative") or []),
    }


def _report_row_tmdb_id(row: Any, override: Optional[Dict[str, Any]]) -> int:
    """Identifiant TMDb du film d'une `PlanRow`, ou 0 s'il n'est pas etabli.

    Issue #612 : l'export NFO sait ecrire un `<uniqueid type="tmdb">` — sans lui
    Jellyfin et Kodi re-scrapent tout le film — mais les rows du rapport ne
    portaient AUCUN `tmdb_id`, si bien que `export_nfo_for_run` lisait une clef
    absente et produisait invariablement un .nfo sans identifiant. Le correctif
    d'origine n'avait touche que le constructeur XML, en aval du trou.

    `PlanRow` n'a pas de champ `tmdb_id` : l'identifiant vit sur les
    `Candidate`, et le choix MANUEL de l'utilisateur vit, lui, dans la table
    `film_tmdb_overrides` (parametre `override`, deja lu par l'appelant). On ne
    reimplemente ni la priorite (`chosen_tmdb_id` > `tmdb_id` > candidat) ni la
    selection du candidat : ce sont `film_support` et
    `library_audit_support._plan_row_tmdb_id` qui les portent, sur une row
    SERIALISEE — d'ou la vue dict construite ici.

    Le detour par `_plan_row_tmdb_id` n'est pas cosmetique : prendre
    `candidates[0]` a l'aveugle rendrait l'identifiant d'un AUTRE film, la liste
    n'etant pas triee (cf. #714). Ecrire ce mauvais identifiant dans un .nfo
    ferait telecharger a Jellyfin les metadonnees du mauvais film.
    """
    candidates: List[Dict[str, Any]] = []
    for cand in getattr(row, "candidates", None) or []:
        if isinstance(cand, dict):
            candidates.append(cand)
            continue
        candidates.append(
            {
                "title": getattr(cand, "title", "") or "",
                "year": getattr(cand, "year", None),
                "tmdb_id": getattr(cand, "tmdb_id", None),
                "score": getattr(cand, "score", 0.0),
            }
        )
    view: Dict[str, Any] = {
        "row_id": str(getattr(row, "row_id", "") or ""),
        "proposed_title": str(getattr(row, "proposed_title", "") or ""),
        "proposed_year": int(getattr(row, "proposed_year", 0) or 0),
        "candidates": candidates,
    }
    # L'override manuel prime sur le match automatique : meme regle, meme code
    # que la Bibliotheque et la fiche film (`film_support.apply_tmdb_override`).
    film_support.apply_tmdb_override(view, override)
    return int(library_audit_support._plan_row_tmdb_id(view) or 0)  # noqa: SLF001


def _build_row_payload(
    run_id: str,
    row: Any,
    decision: Dict[str, Any],
    quality: Dict[str, Any],
    ignored_alerts: Optional[Any] = None,
) -> Tuple[Dict[str, Any], bool, str, bool]:
    """Construit le payload d'une row pour le report. Retourne (payload, decision_ok, tier, is_partial).

    ``ignored_alerts`` : codes d'alertes IGNOREES par l'utilisateur pour cette row
    (run_read_support.ignored_alerts_by_row, recupere en BULK par l'appelant
    build_run_report_payload — pas de requete DB par row). Soustrait des warning_flags
    AVANT toute reconciliation, pour que l'export (JSON/CSV/HTML/NFO) soit le miroir exact
    de l'ecran Verification (history_support._subtract_ignored_flags -> _enrich_plan_payload).
    None (defaut) = aucune soustraction (backward compat)."""
    metrics = quality.get("metrics") if isinstance(quality.get("metrics"), dict) else {}
    probe_quality = str(metrics.get("probe_quality") or "")
    # BUG-018 (hotfix1) : helper centralise (case-insensitive) au lieu de .upper() inline.
    is_partial = probe_quality_is_partial_or_failed(probe_quality)
    tier = str(quality.get("tier") or "").strip()
    decision_ok = to_bool(decision.get("ok"), False)

    detected = metrics.get("detected") or {} if metrics else {}
    subscores = metrics.get("subscores") or {} if metrics else {}
    explanation = metrics.get("score_explanation") or {} if metrics else {}
    score_explanation_full = compose_score_explanation(metrics) if metrics else None

    # AUDIT 2026-07-13 (HIGH-5) : reconcilier les flags exportes avec le
    # quality_report DEJA dans le scope (miroir de
    # history_support._enrich_plan_payload). Sinon le rapport JSON/CSV/HTML livre
    # un faux subtitle_missing_<lang> sur les films dont la piste est muxee (non
    # vue au scan), en contradiction directe avec l'ecran Verification du meme run.
    present_langs: set = set()
    for _lang in getattr(row, "subtitle_languages", None) or []:
        _n = _normalize_iso639(str(_lang)) or str(_lang).strip().lower()
        if _n:
            present_langs.add(_n)
    _embedded = metrics.get("subtitles_embedded") if metrics else None
    if isinstance(_embedded, list):
        for _track in _embedded:
            if isinstance(_track, dict):
                _n = _normalize_iso639(str(_track.get("language") or "").strip().lower())
                if _n:
                    present_langs.add(_n)
    # AUDIT 2026-07-13 (H4/LOW) : soustraire les alertes IGNOREES (film_modal) AVANT la
    # reconciliation sous-titres. Sinon une alerte que l'utilisateur a "Ignoree" reste dans
    # l'export alors qu'elle a disparu de l'ecran Verification (qui passe par
    # _subtract_ignored_flags -> _enrich_plan_payload). Order-preserving comme
    # _subtract_ignored_flags (filtre de liste, PAS effective_flags qui renvoie un set non trie).
    _ignored_codes = {str(_c) for _c in (ignored_alerts or ())}
    _raw_flags = [str(_f) for _f in (getattr(row, "warning_flags", None) or []) if str(_f) not in _ignored_codes]
    # F12 (2026-08-03) : un `subtitle_forced_only_<lang>` n'est perime que si une
    # piste MUXEE COMPLETE existe -> `full_langs_from_embedded` (qui lit `forced`),
    # surtout pas `present_langs` (qui contient deja la langue du fichier force).
    _flags = run_read_support.reconcile_subtitle_flags(
        _raw_flags, present_langs, run_read_support.full_langs_from_embedded(_embedded)
    )
    _missing = [
        str(_l)
        for _l in (getattr(row, "subtitle_missing_langs", None) or [])
        if (_normalize_iso639(str(_l)) or str(_l).strip().lower()) not in present_langs
    ]

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
        # VO-C-BACKEND : payload waterfall complet (categories + baseline +
        # suggestions + applied_rule_ids + narrative + top_positive/negative).
        # None si pas d'explanation disponible (backward compat frontend).
        "score_explanation_full": score_explanation_full,
        "warning_flags": "|".join(_flags),
        "nfo_present": bool(row.nfo_path),
        "subtitle_count": int(getattr(row, "subtitle_count", 0) or 0),
        "subtitle_languages": "|".join(getattr(row, "subtitle_languages", None) or []),
        "subtitle_missing": "|".join(_missing),
        "subtitle_orphans": int(getattr(row, "subtitle_orphans", 0) or 0),
        "notes": str(row.notes or ""),
    }
    return payload, decision_ok, tier, is_partial


def _read_report_meta(run_paths: Any) -> Tuple[str, List[str]]:
    """Lit le resume et les derniers logs d'un run."""
    try:
        summary_text = state.read_text_safe(run_paths.summary_txt).strip()
    except (KeyError, OSError, TypeError, ValueError):
        summary_text = ""
    try:
        all_logs = run_paths.ui_log_txt.read_text(encoding="utf-8").splitlines()
        log_tail = all_logs[-200:]
    except (KeyError, OSError, TypeError, ValueError):
        log_tail = []
    return summary_text, log_tail


def build_run_report_payload(api: Any, run_id: str) -> Tuple[Dict[str, Any], Optional[state.RunPaths]]:
    """Assemble le payload complet du rapport d'un run."""
    ctx = _load_report_context(api, run_id)
    if ctx is None:
        run_state = api._get_run(run_id)
        if run_state and not run_state.done:
            return _err_response("Plan pas pret.", category="state", level="debug", log_module=__name__), None
        return _err_response("Run introuvable.", category="resource", level="info", log_module=__name__), None
    store, run_paths, rows, run_state, cfg_root, run_row = ctx

    decisions = api._normalize_decisions_for_rows(rows, api._load_decisions_from_validation(run_paths))

    quality_by_row: Dict[str, Dict[str, Any]] = {}
    if store:
        try:
            reports = store.quality.list_quality_reports(run_id=run_id)
        except (OSError, TypeError, ValueError):
            reports = []
        for report in reports:
            row_id = str(report.get("row_id") or "").strip()
            if row_id:
                quality_by_row[row_id] = report

    # AUDIT 2026-07-13 (H4/LOW) : alertes IGNOREES en BULK (1 requete/chunk, PAS 1/row) pour que
    # _build_row_payload livre les flags EFFECTIFS (bruts - ignores) = miroir exact de l'ecran
    # Verification (get_plan). Le store n'est pas dans le scope de _build_row_payload -> on le
    # resout ici (seul appelant) et on transmet le set par row. Best-effort : {} si indisponible.
    ignored_by_row = run_read_support.ignored_alerts_by_row(store, [str(getattr(r, "row_id", "")) for r in rows])

    # Issue #612 : identifiants TMDb, pour que l'export NFO puisse ecrire un
    # `<uniqueid>`. UNE requete pour tout le run (`list_tmdb_overrides_bulk`),
    # pas deux connexions SQLite par film.
    #
    # `None` = les overrides manuels sont ILLISIBLES (store absent, table
    # inaccessible, lecture partielle). On n'ecrit alors AUCUN `tmdb_id` : sans
    # savoir si l'utilisateur a corrige le match a la main, publier le match
    # automatique dans un .nfo ferait scraper le mauvais film par Jellyfin. Un
    # .nfo sans identifiant se re-scrape ; un .nfo qui affirme le mauvais
    # identifiant se croit sur parole. Le doute va donc dans le sens restrictif.
    tmdb_overrides = film_support.list_tmdb_overrides_bulk(store, run_id)

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
            ignored_by_row.get(str(row.row_id)),
        )
        if tmdb_overrides is not None:
            payload["tmdb_id"] = _report_row_tmdb_id(row, tmdb_overrides.get(str(row.row_id)))
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
        out_path = run_paths.run_dir / f"{report_stem}.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(export_html_report(report), encoding="utf-8")
        return out_path

    out_path = run_paths.run_dir / f"{report_stem}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # LOTD-EXP-01 : csv.writer emet deja \r\n ; sans newline="" l'OS retraduit
    # \n -> \r\n (=> \r\r\n sur disque, une ligne vide par enregistrement).
    out_path.write_text(report_to_csv_text(report), encoding="utf-8-sig", newline="")
    return out_path


@requires_valid_run_id
def export_run_report(api: Any, run_id: str, fmt: str = "json") -> Dict[str, Any]:
    export_format = str(fmt or "json").strip().lower()
    if export_format not in {"json", "csv", "html"}:
        return _err_response(
            "Format invalide. Utilisez 'json', 'csv' ou 'html'.",
            category="validation",
            level="info",
            log_module=__name__,
        )

    built, run_paths = build_run_report_payload(api, run_id)
    if not built.get("ok"):
        return built
    report = built.get("report") if isinstance(built.get("report"), dict) else {}
    if not report or run_paths is None:
        return _err_response(
            "Impossible de construire le rapport de run.", category="runtime", level="warning", log_module=__name__
        )

    try:
        out_path = write_run_report_file(
            api,
            run_paths=run_paths,
            run_id=run_id,
            export_format=export_format,
            report=report,
        )
        # LOTD-EXP-02 : l'UI (#/logs) telecharge via Blob et exige "content" ;
        # on renvoie le texte exact ecrit sur disque (lecture utf-8 stricte :
        # le BOM du CSV reste en tete -> le download demeure lisible par Excel).
        # LOTD-EXP-04 : on veut le texte EXACT du disque, sans traduction
        # universal-newlines (sinon le \r\n du CSV, fix EXP-01, est retraduit en
        # \n). AUDIT 2026-07-13 (vague 2) : l'ancien `read_text(newline="")` levait
        # un TypeError sur Python 3.12 (le kwarg newline de Path.read_text n'existe
        # qu'en 3.13) -> avale par l'except -> export JSON/CSV/HTML mort ({ok:False})
        # pour l'utilisateur. read_bytes().decode preserve les CRLF ET le BOM UTF-8
        # (decode "utf-8" strict, pas "utf-8-sig") et marche sur 3.12+.
        content = out_path.read_bytes().decode("utf-8")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return _err_response(f"Echec export rapport: {exc}", category="runtime", level="error", log_module=__name__)

    counts = report.get("counts") if isinstance(report.get("counts"), dict) else {}
    return {
        "ok": True,
        "run_id": run_id,
        "format": export_format,
        "path": str(out_path),
        "content": content,
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


def _is_low_confidence_identification(row: Any) -> bool:
    """Film identifie mais a confiance BASSE : 0 < confidence < CONF_MEDIUM (60).

    AUDIT 2026-07-15 (M3) : seuil unifie sur le canonique
    domain.confidence_thresholds.CONF_MEDIUM (60), auparavant 50 ici alors que
    tout le reste (label "low", _row_unidentified, compute_confidence) borne a
    60. `conf == 0` reste VOLONTAIREMENT exclu : ces films sont "non identifies"
    (couverts par films_not_identified / row_unidentified), pas "basse
    confiance". Le drill-down Bibliotheque (bibliotheque.js, filtre low_confidence)
    est aligne sur ce meme intervalle [1, CONF_MEDIUM - 1].
    """
    conf = int(getattr(row, "confidence", 0) or 0)
    return 0 < conf < CONF_MEDIUM


def _compute_librarian_suggestions(
    api: Any,
    store: Any,
    latest_run_id: str,
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    """Calcule les suggestions bibliothecaire depuis les rows + quality reports du dernier run."""
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
        reports = store.quality.list_quality_reports(run_id=latest_run_id)
        # LIMITE CONNUE (revue vague 4B R2, differee) : generate_suggestions resout
        # le tmdb_id depuis les CANDIDATS (parite chip fermee, cas courant), mais
        # n'applique PAS l'override TMDb MANUEL (film_tmdb_overrides). Un film
        # identifie a la main mais sans candidat fiable reste donc "non identifie"
        # sur la carte Accueil alors que le chip Bibliotheque le montre identifie.
        # Non ferme ici car overlay_tmdb_override opere sur des dict et rows est
        # une liste de PlanRow -> le cabler proprement demande d'unifier le format
        # (chantier separe, pas une duplication de la logique d'override).
        result = generate_suggestions(rows, reports, settings)
        # R8-049 (F5) : compte des films basse-confiance d'identification, source de
        # l'insight métier `films_low_confidence` (le librarian n'émet pas ce type).
        if isinstance(result, dict):
            result["low_confidence_count"] = sum(1 for r in rows if _is_low_confidence_identification(r))
        return result
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
        reports = store.quality.list_quality_reports(run_id=latest_run_id)
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
        dist = store.perceptual.get_global_tier_v2_distribution(run_ids=run_ids) if run_ids else {}
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
    now = time.time()
    since = now - 30 * 86400.0

    try:
        raw = store.perceptual.get_global_score_v2_trend(since_ts=since, until_ts=now)
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        logger.debug("trend_30days error: %s", exc)
        raw = []

    # Constituer une map par date
    by_date: Dict[str, Dict[str, Any]] = {r["date"]: r for r in raw}

    # Generer exactement 30 points consecutifs (J-29 .. J0).
    # Fix : range(30,-1,-1) produisait 31 points (de 30 a 0 inclus), decalait
    # la fenetre et dupliquait la donnee de J-30.
    points: List[Dict[str, Any]] = []
    for i in range(29, -1, -1):
        ts = now - i * 86400.0
        date_str = time.strftime("%Y-%m-%d", time.localtime(ts))
        pt = by_date.get(date_str)
        points.append(
            {
                "date": date_str,
                "avg_score": pt["avg_score"] if pt else None,
                "count": pt["count"] if pt else 0,
            }
        )

    return points


def _log_insight_skipped(name: str, exc: BaseException) -> None:
    """Trace un insight Home abandonne apres une erreur du store (issue #545).

    Niveau WARNING, PAS debug. La verbosite par defaut du produit est INFO
    (`app.py`, `CINESORT_LOG_LEVEL > CINESORT_DEBUG > defaut INFO`) : un
    `logger.debug` laisserait l'echec aussi invisible qu'un `pass` nu, alors que
    c'est exactement cette invisibilite qui est le defaut. Le prix de cette
    famille est deja paye dans ce produit : une `AttributeError` avalee sur
    `get_movies` / `get_all_movies` a fait passer la source de dates Jellyfin
    pour vide pendant des mois (cf `library_timeline_support`, audit 2026-06-10).

    L'appelant continue DELIBEREMENT : la Home est un agregat best-effort et
    faire echouer tout le payload pour un encart serait une regression. Ce qui
    change, c'est que l'absence d'un insight n'est plus indistinguable de « rien
    a signaler » : le type d'exception et son message sont desormais lisibles au
    niveau de log par defaut. A noter que ces sites ne couvrent QUE
    `AttributeError`/`OSError` : une `sqlite3.Error` n'herite pas d'`OSError` et
    remonte donc jusqu'au garde global de `get_global_stats`, qui la rend
    visible en `ok=False`.
    """
    logger.warning("insights: %s abandonne apres erreur du store (%s: %s)", name, type(exc).__name__, exc)


def _compute_active_insights(
    api: Any,
    store: Any,
    run_ids: List[str],
    settings: Dict[str, Any],
    librarian_data: Optional[Dict[str, Any]] = None,
    latest_scan_rid: str = "",
) -> List[Dict[str, Any]]:
    """v7.6.0 Vague 2 : insights proactifs affiches sur la Home.

    Retourne une liste triee par severity desc + count desc :
      [{type, severity, count, label, filter_hint, icon}]
    Max 8 insights.

    R8-049/051/052 (F5) : émet le VOCABULAIRE MÉTIER attendu par le front
    (_INSIGHT_ROUTE_BY_TYPE dans accueil.js : quality_reject, duplicates_probable,
    films_not_identified, subs_missing_fr, sagas_incomplete, films_low_confidence,
    health_low). AVANT, ce producteur n'émettait que des types « physiques »
    (new_rejects, duplicates_to_resolve…) qu'AUCUNE route/notification ne reconnaissait
    -> panneaux morts, clics non routés, miroir Centre de notifications vide.
    Les types métier sont dérivés du bibliothécaire (generate_suggestions) déjà calculé.
    """
    insights: List[Dict[str, Any]] = []
    librarian_data = librarian_data if isinstance(librarian_data, dict) else {}

    # 1. Run actif en cours
    try:
        for r in store.run.list_runs(limit=1):
            if str(r.get("status") or "").upper() == "RUNNING":
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
    except (AttributeError, OSError) as exc:
        _log_insight_skipped("run_in_progress", exc)

    # 2. Nouveaux Reject sur le dernier run
    # Revue vague 3 R2 : `latest_scan_rid` (resolu par get_latest_run, exclut les
    # runs utilitaires de bulk-rescan) doit primer sur run_ids[0] brut ; sinon,
    # apres un re-scan groupe, run_ids[0] = run parasite (0 perceptual_report) ->
    # reject_count=0 -> l'insight Reject disparait, desynchronise du reste du
    # payload (deja passe a latest_scan_rid).
    if run_ids or latest_scan_rid:
        latest_rid = latest_scan_rid or run_ids[0]
        try:
            reports = store.perceptual.list_perceptual_reports(run_id=latest_rid)
            reject_count = sum(1 for r in reports if str(r.get("global_tier_v2") or "").lower() == "reject")
            if reject_count > 0:
                insights.append(
                    {
                        # R8-049 (F5) : type métier `quality_reject` (routé /qualite par le front),
                        # avant `new_rejects` que _INSIGHT_ROUTE_BY_TYPE ne connaissait pas.
                        "type": "quality_reject",
                        "severity": "warning",
                        "count": reject_count,
                        "label": f"{reject_count} film{'s' if reject_count > 1 else ''} classe{'s' if reject_count > 1 else ''} Reject dans le dernier scan",
                        "filter_hint": {"tier": ["reject"], "run_id": latest_rid},
                        "icon": "alert-triangle",
                    }
                )
        except (AttributeError, OSError) as exc:
            # Site le plus couteux du lot : sans trace, la Home n'affiche aucune
            # alerte Reject et l'utilisateur lit « rien a signaler » alors que le
            # comptage n'a jamais eu lieu.
            _log_insight_skipped(f"quality_reject (run_id={latest_rid})", exc)

    # 3. Insights MÉTIER dérivés du bibliothécaire (R8-049/051/052 F5) : on traduit les
    #    suggestions generate_suggestions vers les types attendus par _INSIGHT_ROUTE_BY_TYPE
    #    (accueil.js). Avant, le seul insight « doublons » comptait des ANOMALIES (label
    #    trompeur « X anomalies à traiter ») et portait un type mort `duplicates_to_resolve`.
    _LIBRARIAN_TO_INSIGHT = {
        # librarian id -> (type métier, severity, icon, filter_hint)
        "duplicates": ("duplicates_probable", "warning", "copy", {"filter": "duplicates"}),
        "unidentified": ("films_not_identified", "warning", "help-circle", {"filter": "not_identified"}),
        "missing_subtitles": ("subs_missing_fr", "info", "message-square", {"filter": "subs_missing_fr"}),
        "collections_info": ("sagas_incomplete", "info", "layers", {"filter": "sagas_incomplete"}),
    }
    for sug in librarian_data.get("suggestions") or []:
        if not isinstance(sug, dict):
            continue
        mapping = _LIBRARIAN_TO_INSIGHT.get(str(sug.get("id") or ""))
        if not mapping:
            continue
        count = int(sug.get("count") or 0)
        if count <= 0:
            continue
        itype, severity, icon, filter_hint = mapping
        insights.append(
            {
                "type": itype,
                "severity": severity,
                "count": count,
                "label": str(sug.get("message") or itype),
                "filter_hint": filter_hint,
                "icon": icon,
            }
        )

    # 3b. Films basse confiance d'identification (films_low_confidence).
    low_conf = int(librarian_data.get("low_confidence_count") or 0)
    if low_conf > 0:
        insights.append(
            {
                "type": "films_low_confidence",
                "severity": "info",
                "count": low_conf,
                "label": f"{low_conf} film{'s' if low_conf > 1 else ''} a verifier (identification incertaine)",
                "filter_hint": {"filter": "low_confidence"},
                "icon": "help-circle",
            }
        )

    # 3c. Sante bibliotheque faible (health_low).
    health = int(librarian_data.get("health_score") or 100)
    if health < 60:
        insights.append(
            {
                "type": "health_low",
                "severity": "warning" if health < 40 else "info",
                "count": health,
                "label": f"Sante bibliotheque : {health}/100",
                "filter_hint": None,
                "icon": "activity",
            }
        )

    # 4. DNR partiel (nouveau insight §15)
    try:
        dnr_count = store.perceptual.count_v2_warnings_flag(flag="dnr_partial", run_ids=run_ids)
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
    except (AttributeError, OSError) as exc:
        _log_insight_skipped("dnr_partial", exc)

    # 5. Nouveaux Platinum ce mois
    try:
        month_ago = time.time() - 30 * 86400.0
        plat_count = store.perceptual.count_v2_tier_since(tier="platinum", since_ts=month_ago)
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
    except (AttributeError, OSError) as exc:
        _log_insight_skipped("new_platinum_month", exc)

    # Tri par severity puis count desc
    severity_order = {"warning": 0, "info": 1, "success": 2}
    insights.sort(key=lambda it: (severity_order.get(it["severity"], 9), -int(it.get("count") or 0)))

    # R8-049 (F5) : limite portée à 8 (les 7 types métier + statut run_in_progress
    # peuvent coexister ; avant [:5] tronquait silencieusement les insights métier).
    return insights[:8]


def get_global_stats(api: Any, limit_runs: int = 20) -> Dict[str, Any]:
    """Aggregate statistics across multiple runs for global dashboard."""
    lim = max(2, min(100, int(limit_runs or 20)))
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _runner = api._get_or_create_infra(state_dir)

        # 1. Runs timeline
        runs_summary = store.run.get_runs_summary(limit=lim)
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
        quality_counts = store.quality.get_quality_counts_for_runs(run_ids)
        error_counts = store.run.get_error_counts_for_runs(run_ids)
        anomaly_counts = store.anomaly.get_anomaly_counts_for_runs(run_ids)

        # AUDIT 2026-07-13 (HIGH-8 residu) : le "dernier run" pour les KPI globaux
        # + les distributions de tiers (page Qualite) doit EXCLURE les runs
        # utilitaires de bulk re-scan (config rescan_run_id). Sinon, apres un
        # re-scan groupe, run_ids[0] pointe le run de tracking parasite (sans plan
        # ni quality_reports) -> total_films / avg_score / tier_distribution a 0,
        # en divergence avec la Bibliotheque. MEME resolution que la vague 2
        # (get_latest_run filtre deja les rescans). Fallback run_ids[0] si
        # get_latest_run ne renvoie rien.
        try:
            _latest_scan_row = store.run.get_latest_run()
        except (OSError, AttributeError, TypeError, ValueError):
            _latest_scan_row = None
        latest_scan_rid = str((_latest_scan_row or {}).get("run_id") or "") or (run_ids[0] if run_ids else "")

        # 3. Global tier distribution
        # AUDIT 2026-06-14 (R6-F) : distribution "etat courant" = DERNIER run
        # SEULEMENT (limit_runs=1). Avant, l'agregation sur `lim` runs (20)
        # cumulait les films de plusieurs scans -> "films classes" gonfle et
        # tiers fausses sur la page Qualite (ex: 1249 quasi tout Bronze) alors
        # que la Biblio (V1 dernier run) montre la vraie repartition.
        tier_data = store.quality.get_global_tier_distribution(limit_runs=1)

        # 4. Top anomaly codes
        top_anomalies = store.anomaly.get_top_anomaly_codes(limit_runs=lim, limit_codes=10)

        # 5. Aggregated summary
        # AUDIT 2026-06-14 (R7-5) : complement de R6-F. total_films/avg_score/
        # premium_pct etaient cumules sur `lim` runs (defaut 20) alors que chaque
        # run est un snapshot complet independant -> un film present dans N scans
        # etait compte N fois (KPI gonfles). On scope au DERNIER run, comme la
        # distribution par tier (limit_runs=1) et la Bibliotheque.
        latest_rid = latest_scan_rid or None
        latest_summary = next((r for r in runs_summary if r.get("run_id") == latest_rid), None)
        total_films = int(latest_summary.get("total_rows", 0)) if latest_summary else 0
        latest_qc = quality_counts.get(latest_rid, {}) if latest_rid else {}
        all_scored = int(latest_qc.get("scored_movies", 0) or 0)
        all_premium = int(latest_qc.get("premium_count", 0) or 0)
        avg_score = float(latest_qc.get("score_avg", 0.0) or 0.0)
        premium_pct = (all_premium / all_scored * 100) if all_scored else 0.0

        # 6. Trend (↑↓→)
        trend = _compute_score_trend(quality_counts, run_ids)

        # 7. Unscored films count (from latest run)
        unscored = 0
        if run_ids:
            latest_rid = latest_scan_rid
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
        space = _compute_space_analysis(store, latest_scan_rid)

        # 11. Librarian suggestions
        librarian_data = _compute_librarian_suggestions(api, store, latest_scan_rid, settings)

        # 12. v7.6.0 Vague 2 — Home overview-first payloads
        # AUDIT 2026-06-14 (R6-F) : V2 perceptuel du DERNIER run uniquement
        # (run_ids[:1]). Avant, le cumul sur 20 runs donnait ~1265 lignes quasi
        # toutes "bronze" (perceptuel partiel/ancien) -> faux "Sante 0% / tout Bronze".
        v2_tier_distribution = _compute_v2_tier_distribution(store, [latest_scan_rid] if latest_scan_rid else [])
        trend_30days = _compute_trend_30days(store)
        insights = _compute_active_insights(
            api, store, run_ids, settings, librarian_data, latest_scan_rid=latest_scan_rid
        )

        # 13. Spec 10 Qualite — by_decade distribution top-level (best-effort).
        # Cf docs/internal/design/refonte_2026_05_17/screens/10-qualite.md
        by_decade: Dict[str, int] = {}
        try:
            by_decade = library_audit_support.compute_by_decade(api, run_id=latest_scan_rid or None)
        except (OSError, AttributeError, ImportError, KeyError, TypeError, ValueError) as exc:
            logger.debug("get_global_stats by_decade fallback (err=%s)", exc)
            by_decade = {}

        # v7.6.0 Vague 9 : miroir des insights actifs dans le notification
        # center (deduplique par (code, source) pour la session).
        notifications_support.emit_from_insights(api, insights, source="dashboard")

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
            # Spec 10 Qualite — distribution films par decennie
            "by_decade": by_decade,
        }
    # Fix audit 2026-05-26 (v1.5.6) Vague L : dash-1. L'ancien tuple
    # (OSError, KeyError, TypeError, ValueError) laissait passer RuntimeError,
    # AttributeError, MemoryError, etc., provoquant un HTTP 500 cote pywebview
    # quand par exemple la couche store/perceptual levait une RuntimeError
    # ("dependency unavailable"). On wrap en Exception et on renvoie un payload
    # standardise {ok:False, error, user_message, message} aligne avec les
    # autres endpoints Vague F/G (get_status / get_plan / get_history_stats /
    # cancel_run).
    except Exception as exc:  # noqa: BLE001 - boundary top-level dashboard global
        logger.exception("get_global_stats failed: %s", exc)
        return {
            "ok": False,
            "error": "global_stats_failed",
            "message": str(exc),
            "user_message": ("Impossible de calculer les statistiques globales. Relance un scan ou redemarre l'app."),
        }


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


def _count_duplicate_films(rows: Any) -> int:
    """Nombre de films dans un groupe de doublons (meme titre+annee, >= 2 films).

    AUDIT 2026-07-15 (M4) : EXCLUT les episodes TV, miroir EXACT du detecteur
    reel (duplicate_support.find_duplicate_targets qui skip kind == "tv_episode").
    Sans ce filtre, le badge "Doublons" promettait des doublons que l'ecran
    Doublons ne montre JAMAIS (plusieurs episodes d'une serie partagent le meme
    titre+annee mais sont exclus de la detection). Le filtre s'applique AVANT le
    comptage des cles ET a l'iteration finale, sinon un film unique partageant
    son titre+annee avec des episodes TV serait compte a tort.
    """
    dup_rows = [r for r in rows if str(getattr(r, "kind", "") or "") != "tv_episode"]
    dup_keys: Counter = Counter()
    for r in dup_rows:
        title = str(getattr(r, "proposed_title", "") or "").strip().lower()
        if not title:
            continue
        year = int(getattr(r, "proposed_year", 0) or 0)
        dup_keys[(title, year)] += 1
    return sum(
        1
        for r in dup_rows
        if str(getattr(r, "proposed_title", "") or "").strip()
        and dup_keys[
            (
                str(getattr(r, "proposed_title", "") or "").strip().lower(),
                int(getattr(r, "proposed_year", 0) or 0),
            )
        ]
        >= 2
    )


def get_sidebar_counters(api: Any) -> Dict[str, int]:
    """V3-04 — Compteurs pour les badges sidebar.

    Retourne {validation, application, quality} pour le run le plus recent.
    Un compteur a 0 signifie "rien a faire", le badge correspondant restera invisible.
    """
    empty = {"validation": 0, "application": 0, "quality": 0, "duplicates": 0}
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _runner = api._get_or_create_infra(state_dir)

        run_row = store.run.get_latest_run()
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
            last_batch = store.apply.get_last_reversible_apply_batch(run_id)
        except (OSError, AttributeError, TypeError, ValueError):
            last_batch = None

        validation = sum(1 for r in rows if _row_needs_review(r) and str(getattr(r, "row_id", "")) not in approved_ids)
        application = 0 if last_batch else len(approved_ids)
        # AUDIT 2026-07-13 (HIGH-4) : badge "Qualite" sur les flags EFFECTIFS
        # (bruts - alertes ignorees - subtitle_missing_<lang> perimes), MEME
        # chaine que l'ecran Verification (history_support._enrich_plan_payload)
        # et le KPI "Cas a verifier" (_build_dashboard_section). Sans ca le badge
        # comptait tout flag BRUT (le FR muxe non vu au scan pose un faux
        # subtitle_missing_fr) -> ~898 alors que l'ecran annonce ~186.
        qr_by_id: Dict[str, Dict[str, Any]] = {}
        if hasattr(store, "quality"):
            try:
                qr_by_id = run_read_support.build_qr_by_id(store.quality.list_quality_reports(run_id=run_id))
            except (OSError, AttributeError, TypeError, ValueError):
                qr_by_id = {}
        _ignored_q = run_read_support.ignored_alerts_by_row(store, [str(getattr(r, "row_id", "")) for r in rows])

        quality = 0
        for r in rows:
            rid = str(getattr(r, "row_id", ""))
            eff = run_read_support.effective_flags(getattr(r, "warning_flags", None), _ignored_q.get(rid))
            present = history_support._present_langs_from_payload(
                {"row_id": rid, "subtitle_languages": getattr(r, "subtitle_languages", None) or []},
                qr_by_id,
            )
            # F12 (2026-08-03) : meme reconciliation que l'ecran Verification, y
            # compris pour `subtitle_forced_only_<lang>`. Sans le 3e argument, une
            # row dont l'unique alerte est un forced_only DEMENTI par une piste
            # muxee complete gonflerait ce badge sans apparaitre a l'ecran — la
            # divergence exacte que HIGH-4 a corrigee.
            if run_read_support.reconcile_subtitle_flags(
                eff, present, history_support._full_langs_from_payload({"row_id": rid}, qr_by_id)
            ):
                quality += 1

        # AUDIT 2026-06-13 (R5-E) : badge "Doublons" = films dans un groupe de
        # doublons (meme titre+annee >= 2 occurrences). Meme semantique que le
        # chip biblio "Dans doublons" (library_support._count_duplicates_and_sagas).
        # AUDIT 2026-07-15 (M4) : delegue a _count_duplicate_films, qui EXCLUT les
        # episodes TV (miroir du detecteur reel duplicate_support.py).
        duplicates = _count_duplicate_films(rows)

        return {
            "validation": int(validation),
            "application": int(application),
            "quality": int(quality),
            "duplicates": int(duplicates),
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        logger.debug("get_sidebar_counters fallback (err=%s)", exc)
        return empty
