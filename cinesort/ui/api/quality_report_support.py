from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from cinesort.domain import compute_quality_score, default_quality_profile
from cinesort.domain.i18n_messages import t
from cinesort.infra.probe import ProbeService
from cinesort.domain.conversions import to_bool
from cinesort.ui.api._validators import requires_valid_run_id
from cinesort.ui.api.settings_support import normalize_user_path
from cinesort.ui.api._responses import err as _err_response


# Seuils cross-check runtime NFO vs probe (P1.1.d).
# 10% de delta gère les films courts ; 8 min évite de flaguer les remaster/director-cut mineurs.
_NFO_RUNTIME_MISMATCH_PCT_THRESHOLD = 0.10
_NFO_RUNTIME_MISMATCH_MIN_MINUTES = 8.0


def detect_nfo_runtime_mismatch(
    *,
    nfo_runtime_min: Optional[int],
    probe_duration_s: Optional[float],
) -> Optional[Dict[str, Any]]:
    """Retourne un dict de détail si le runtime NFO diverge de la probe.

    Renvoie None s'il n'y a pas d'information suffisante ou si l'écart est mineur.
    Les deux seuils doivent être franchis simultanément pour déclencher le flag :
    delta > 10% ET delta > 8 minutes (garde-fou vs remaster/director-cut).
    """
    if not nfo_runtime_min or not probe_duration_s:
        return None
    if not isinstance(probe_duration_s, (int, float)) or probe_duration_s <= 0:
        return None
    expected = float(nfo_runtime_min)
    if expected <= 0:
        return None
    probe_runtime_min = float(probe_duration_s) / 60.0
    delta_min = abs(probe_runtime_min - expected)
    delta_pct = delta_min / expected if expected > 0 else 0.0
    if delta_pct <= _NFO_RUNTIME_MISMATCH_PCT_THRESHOLD:
        return None
    if delta_min <= _NFO_RUNTIME_MISMATCH_MIN_MINUTES:
        return None
    return {
        "nfo_minutes": int(expected),
        "probe_minutes": round(probe_runtime_min, 1),
        "delta_minutes": round(delta_min, 1),
        "delta_pct": round(delta_pct * 100.0, 1),
    }


def _extract_confidence_and_explanation(metrics_obj: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    confidence = metrics_obj.get("score_confidence")
    if not isinstance(confidence, dict):
        confidence = {"value": 0, "label": "Faible", "reasons": []}
    explanation = metrics_obj.get("score_explanation")
    if not isinstance(explanation, dict):
        explanation = {"narrative": "", "top_positive": [], "top_negative": [], "factors": []}
    if not isinstance(explanation.get("factors"), list):
        explanation["factors"] = []
    return confidence, explanation


def _probe_and_score(
    api: Any,
    store: Any,
    run_row: Any,
    run_id: str,
    row_id: str,
    row: Any,
    media_path: Any,
    *,
    profile_json: Dict[str, Any],
    active_profile_id: str,
    active_profile_version: int,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    probe_settings = api._effective_probe_settings_for_runtime(run_row)
    probe = ProbeService(store)
    probe_result = probe.probe_file(media_path=media_path, settings=probe_settings)
    normalized = probe_result.get("normalized") if isinstance(probe_result.get("normalized"), dict) else {}

    # P4.2 : récupérer les genres TMDb pour le scoring genre-aware.
    tmdb_genres: list = []
    try:
        candidates = getattr(row, "candidates", []) or []
        tmdb_id_lookup = 0
        for c in candidates:
            if getattr(c, "tmdb_id", None):
                tmdb_id_lookup = int(c.tmdb_id)
                break
        if tmdb_id_lookup > 0:
            tmdb = api._tmdb_client() if hasattr(api, "_tmdb_client") else None
            if tmdb:
                meta = tmdb.get_movie_metadata_for_perceptual(tmdb_id_lookup)
                if meta and isinstance(meta.get("genres"), list):
                    tmdb_genres = list(meta["genres"])
    except (ImportError, KeyError, OSError, TypeError, ValueError, AttributeError):
        tmdb_genres = []

    report = compute_quality_score(
        normalized_probe=normalized,
        profile=profile_json,
        folder_name=Path(str(row.folder or "")).name,
        expected_title=str(row.proposed_title or ""),
        expected_year=int(row.proposed_year or 0),
        release_name=str(row.video or ""),
        tmdb_genres=tmdb_genres or None,
    )
    store.upsert_quality_report(
        run_id=run_id,
        row_id=row_id,
        score=int(report.get("score") or 0),
        tier=str(report.get("tier") or "Reject"),
        reasons=list(report.get("reasons") or []),
        metrics=dict(report.get("metrics") or {}),
        profile_id=active_profile_id,
        profile_version=active_profile_version,
    )

    persisted = store.get_quality_report(run_id=run_id, row_id=row_id)
    out = (
        persisted
        if persisted
        else {
            "run_id": run_id,
            "row_id": row_id,
            "score": int(report.get("score") or 0),
            "tier": str(report.get("tier") or "Reject"),
            "reasons": list(report.get("reasons") or []),
            "metrics": dict(report.get("metrics") or {}),
            "profile_id": active_profile_id,
            "profile_version": active_profile_version,
            "ts": time.time(),
        }
    )
    return probe_result, out


@requires_valid_run_id
def get_quality_report(api: Any, run_id: str, row_id: str, options: Any = None) -> Dict[str, Any]:
    if not run_id or not row_id:
        return _err_response(
            "Les identifiants run_id et row_id sont requis.", category="validation", level="info", log_module=__name__
        )
    try:
        opts = options if isinstance(options, dict) else {}
        reuse_existing = to_bool(opts.get("reuse_existing"), False)
        found = api._find_run_row(run_id)
        if not found:
            return _err_response("Run introuvable.", category="resource", level="info", log_module=__name__)
        run_row, store = found
        state_dir = normalize_user_path(run_row.get("state_dir"), api._state_dir)
        run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=False)
        rs = api._get_run(run_id)
        active = api._ensure_quality_profile(store)
        profile_json = (
            active.get("profile_json") if isinstance(active.get("profile_json"), dict) else default_quality_profile()
        )
        active_profile_id = str(active.get("id") or profile_json.get("id") or "CinemaLux_v1")
        active_profile_version = int(active.get("version") or profile_json.get("version") or 1)
        active_engine_version = str(profile_json.get("engine_version") or "CinemaLux_v1")

        if reuse_existing:
            existing = store.get_quality_report(run_id=run_id, row_id=row_id)
            if existing:
                existing_metrics = existing.get("metrics") if isinstance(existing.get("metrics"), dict) else {}
                existing_engine = str(existing_metrics.get("engine_version") or "")
                existing_profile_id = str(existing.get("profile_id") or "")
                existing_profile_version = int(existing.get("profile_version") or 0)
                if (
                    existing_engine == active_engine_version
                    and existing_profile_id == active_profile_id
                    and existing_profile_version == active_profile_version
                ):
                    probe_quality = str(existing_metrics.get("probe_quality") or "UNKNOWN")
                    confidence, explanation = _extract_confidence_and_explanation(existing_metrics)
                    return {
                        "ok": True,
                        **existing,
                        "probe_quality": probe_quality,
                        "confidence": confidence,
                        "explanation": explanation,
                        "cache_hit_probe": True,
                        "cache_hit_quality": True,
                        "status": "ignored_existing",
                        "skipped_existing": True,
                        "media_path": "",
                    }

        rows = rs.rows if rs and rs.rows else api._load_rows_from_plan_jsonl(run_paths)
        row = next((item for item in rows if str(item.row_id) == str(row_id)), None)
        if row is None:
            return _err_response(
                "Film introuvable dans ce plan (row_id).", category="resource", level="info", log_module=__name__
            )

        cfg = rs.cfg if rs else api._cfg_from_run_row(run_row)
        media_path = api._resolve_media_path_for_row(cfg, row)
        if media_path is None or (not media_path.exists()):
            return _err_response(
                t("errors.media_not_found_for_row"), category="validation", level="info", log_module=__name__
            )

        probe_result, out = _probe_and_score(
            api,
            store,
            run_row,
            run_id,
            row_id,
            row,
            media_path,
            profile_json=profile_json,
            active_profile_id=active_profile_id,
            active_profile_version=active_profile_version,
        )
        normalized = probe_result.get("normalized") if isinstance(probe_result.get("normalized"), dict) else {}

        log_fn = rs.log if rs else api._file_logger(run_paths)
        log_fn("INFO", f"QUALITE {row_id}: score={out['score']} tier={out['tier']}")
        metrics_obj = out.get("metrics") if isinstance(out.get("metrics"), dict) else {}
        confidence, explanation = _extract_confidence_and_explanation(metrics_obj)
        pq = str(normalized.get("probe_quality") or "FAILED")
        result = {
            "ok": True,
            **out,
            "probe_quality": pq,
            "confidence": confidence,
            "explanation": explanation,
            "cache_hit_probe": bool(probe_result.get("cache_hit")),
            "cache_hit_quality": False,
            "status": "analyzed",
            "skipped_existing": False,
            "media_path": str(media_path),
        }
        # Flag integrite si la probe a echoue
        if pq == "FAILED":
            result["integrity_probe_failed"] = True
        # Analyse d'encodage (upscale, 4K light, re-encode degrade)
        from cinesort.domain.encode_analysis import analyze_encode_quality

        detected_for_encode = metrics_obj.get("detected") or {}
        encode_flags = analyze_encode_quality(detected_for_encode)
        if encode_flags:
            result["encode_warnings"] = encode_flags
        # Analyse audio approfondie
        from cinesort.domain.audio_analysis import analyze_audio

        audio_tracks = normalized.get("audio_tracks") or []
        audio_report = analyze_audio(audio_tracks)
        result["audio_analysis"] = audio_report
        if audio_report.get("duplicate_tracks"):
            result.setdefault("encode_warnings", [])
            if "audio_duplicate_track" not in result["encode_warnings"]:
                result["encode_warnings"].append("audio_duplicate_track")
        # Warnings coherence langue audio
        if audio_report.get("missing_language_count", 0) > 0:
            result.setdefault("encode_warnings", [])
            if "audio_language_missing" not in result["encode_warnings"]:
                result["encode_warnings"].append("audio_language_missing")
        if audio_report.get("incomplete_languages"):
            result.setdefault("encode_warnings", [])
            if "audio_language_incomplete" not in result["encode_warnings"]:
                result["encode_warnings"].append("audio_language_incomplete")
        # P1.1.d : cross-check runtime NFO vs duree probe réelle.
        mismatch = detect_nfo_runtime_mismatch(
            nfo_runtime_min=getattr(row, "nfo_runtime", None),
            probe_duration_s=normalized.get("duration_s"),
        )
        if mismatch is not None:
            result.setdefault("encode_warnings", [])
            if "nfo_runtime_mismatch" not in result["encode_warnings"]:
                result["encode_warnings"].append("nfo_runtime_mismatch")
            result["nfo_runtime_mismatch_detail"] = mismatch

        # Conflit titre conteneur MKV/MP4
        container_title = normalized.get("container_title")
        if container_title:
            result["container_title"] = container_title
            from cinesort.domain.mkv_title_check import check_container_title

            title_flags = check_container_title(container_title, str(row.proposed_title or ""))
            if title_flags:
                result.setdefault("encode_warnings", [])
                for flag in title_flags:
                    if flag not in result["encode_warnings"]:
                        result["encode_warnings"].append(flag)
        # Enrichir avec les donnees perceptuelles si disponibles
        # V4-05 (Polish Total v7.7.0, R4-PERC-7 / H16) : propage le toggle
        # `composite_score_version` (V1 par defaut, V2 opt-in via reglages).
        from cinesort.ui.api.perceptual_support import enrich_quality_report_with_perceptual
        from cinesort.ui.api.settings_support import _normalize_composite_score_version

        try:
            settings = api.settings.get_settings() if api else {}
        except (AttributeError, KeyError, OSError, TypeError, ValueError):
            settings = {}
        score_version = _normalize_composite_score_version(
            settings.get("composite_score_version") if isinstance(settings, dict) else None
        )
        enrich_quality_report_with_perceptual(store, run_id, row_id, result, composite_score_version=score_version)
        return result
    except (ImportError, KeyError, OSError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)
