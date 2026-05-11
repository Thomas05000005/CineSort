"""Internal run data serialization helpers for the pywebview API facade."""

from __future__ import annotations

from dataclasses import asdict
import json
import logging
from typing import Any, Dict, List

import cinesort.domain.core as core
from cinesort.domain.conversions import to_int
from cinesort.ui.api.settings_support import clamp_year

logger = logging.getLogger(__name__)


def serialize_rows_for_payload(rows: List[core.PlanRow]) -> List[Dict[str, Any]]:
    payload: List[Dict[str, Any]] = []
    for row in rows:
        data = asdict(row)
        data["candidates"] = [asdict(candidate) for candidate in row.candidates]
        payload.append(data)
    return payload


def candidate_from_json(data: Dict[str, Any]) -> core.Candidate:
    tmdb_id: int | None
    try:
        tmdb_id = int(data["tmdb_id"]) if data.get("tmdb_id") is not None else None
    except (ImportError, KeyError, OSError, TypeError, ValueError):
        tmdb_id = None
    year: int | None
    try:
        year = int(data["year"]) if data.get("year") is not None else None
    except (OSError, KeyError, TypeError, ValueError):
        year = None
    return core.Candidate(
        title=str(data.get("title") or ""),
        year=year,
        source=str(data.get("source") or "unknown"),
        tmdb_id=tmdb_id,
        poster_url=str(data.get("poster_url")) if data.get("poster_url") else None,
        score=float(data.get("score") or 0.0),
        note=str(data.get("note") or ""),
    )


def _optional_str(data: Dict[str, Any], key: str) -> str | None:
    raw = data.get(key)
    return str(raw) if raw else None


def _str_list(data: Dict[str, Any], key: str) -> List[str]:
    return [str(s) for s in (data.get(key) or [])]


def _parse_candidates(data: Dict[str, Any]) -> List[core.Candidate]:
    raw = data.get("candidates")
    if not isinstance(raw, list):
        return []
    return [candidate_from_json(item) for item in raw if isinstance(item, dict)]


def _parse_warning_flags(data: Dict[str, Any]) -> List[str]:
    raw = data.get("warning_flags")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item or "").strip()]


def _str_with_default(data: Dict[str, Any], key: str, default: str = "") -> str:
    return str(data.get(key) or default)


def _parse_basic_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "row_id": _str_with_default(data, "row_id"),
        "kind": _str_with_default(data, "kind", "single"),
        "folder": _str_with_default(data, "folder"),
        "video": _str_with_default(data, "video"),
        "proposed_title": _str_with_default(data, "proposed_title"),
        "proposed_year": to_int(data.get("proposed_year"), 0),
        "proposed_source": _str_with_default(data, "proposed_source", "unknown"),
        "confidence": to_int(data.get("confidence"), 0),
        "confidence_label": _str_with_default(data, "confidence_label", "low"),
        "notes": _str_with_default(data, "notes"),
        "detected_year": to_int(data.get("detected_year"), 0),
        "detected_year_reason": _str_with_default(data, "detected_year_reason"),
    }


def _parse_optional_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "nfo_path": _optional_str(data, "nfo_path"),
        "collection_name": _optional_str(data, "collection_name"),
        "tmdb_collection_id": to_int(data.get("tmdb_collection_id"), 0) or None,
        "tmdb_collection_name": _optional_str(data, "tmdb_collection_name"),
        "edition": _optional_str(data, "edition"),
        "source_root": _optional_str(data, "source_root"),
    }


def _parse_subtitle_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "subtitle_count": to_int(data.get("subtitle_count"), 0),
        "subtitle_languages": _str_list(data, "subtitle_languages"),
        "subtitle_formats": _str_list(data, "subtitle_formats"),
        "subtitle_missing_langs": _str_list(data, "subtitle_missing_langs"),
        "subtitle_orphans": to_int(data.get("subtitle_orphans"), 0),
    }


def row_from_json(data: Dict[str, Any]) -> core.PlanRow:
    return core.PlanRow(
        candidates=_parse_candidates(data),
        warning_flags=_parse_warning_flags(data),
        **_parse_basic_fields(data),
        **_parse_optional_fields(data),
        **_parse_subtitle_fields(data),
    )


def load_rows_from_plan_jsonl(run_paths: Any) -> List[core.PlanRow]:
    plan_path = run_paths.plan_jsonl
    if not plan_path.exists():
        raise FileNotFoundError(f"Plan introuvable: {plan_path}")
    rows: List[core.PlanRow] = []
    with plan_path.open("r", encoding="utf-8") as file_obj:
        for line in file_obj:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if isinstance(data, dict):
                rows.append(row_from_json(data))
    return rows


def load_decisions_from_validation(api: Any, run_paths: Any, *, env_truthy_fn: Any) -> Dict[str, Dict[str, Any]]:
    validation_path = run_paths.validation_json
    if not validation_path.exists():
        return {}
    try:
        data = json.loads(validation_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        decisions: Dict[str, Dict[str, Any]] = {}
        for key, value in data.items():
            if isinstance(key, str) and isinstance(value, dict):
                decisions[key] = dict(value)
        return decisions
    except (KeyError, OSError, PermissionError, TypeError, ValueError, json.JSONDecodeError) as exc:
        state_dir_guess = api._state_dir
        try:
            state_dir_guess = run_paths.run_dir.parent.parent
        except (KeyError, OSError, PermissionError, TypeError, ValueError, json.JSONDecodeError):
            state_dir_guess = api._state_dir
        api._debug_log(
            state_dir=state_dir_guess,
            run_id=run_paths.run_id,
            enabled=env_truthy_fn("CINESORT_DEBUG"),
            message=f"_load_decisions_from_validation warning path={validation_path} error={exc}",
        )
        logger.debug("Validation JSON invalide ignoree path=%s err=%s", validation_path, exc)
        return {}


def merge_decisions(
    primary: Dict[str, Dict[str, Any]], fallback: Dict[str, Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for key in set(primary.keys()) | set(fallback.keys()):
        out: Dict[str, Any] = {}
        fallback_value = fallback.get(key)
        if isinstance(fallback_value, dict):
            out.update(fallback_value)
        primary_value = primary.get(key)
        if isinstance(primary_value, dict):
            out.update(primary_value)
        merged[key] = out
    return merged


def normalize_decisions_for_rows(
    rows: List[core.PlanRow],
    decisions: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    safe: Dict[str, Dict[str, Any]] = {}
    incoming = decisions if isinstance(decisions, dict) else {}

    for row in rows:
        raw = incoming.get(row.row_id, {})
        raw = raw if isinstance(raw, dict) else {}
        ok = bool(raw.get("ok", False))
        title_in = str(raw.get("title") or row.proposed_title).strip()
        title = core.windows_safe(title_in) if title_in else core.windows_safe(row.proposed_title)
        year_raw = to_int(raw.get("year"), row.proposed_year)
        year = clamp_year(year_raw)
        if year == 0:
            year = clamp_year(int(row.proposed_year or 0))
        safe[row.row_id] = {
            "ok": ok,
            "title": title,
            "year": year,
        }
    return safe
