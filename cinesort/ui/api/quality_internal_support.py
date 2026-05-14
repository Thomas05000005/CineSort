from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cinesort.infra.state as state
from cinesort.domain import default_quality_profile, validate_quality_profile
from cinesort.infra.db import SQLiteStore
from cinesort.ui.api.settings_support import normalize_user_path


def quality_store(api: Any) -> Tuple[Path, SQLiteStore]:
    settings = api.settings.get_settings()
    state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
    store, _runner = api._get_or_create_infra(state_dir)
    return state_dir, store


def active_quality_profile_payload(api: Any) -> Dict[str, Any]:
    _state_dir, store = quality_store(api)
    active = ensure_quality_profile(api, store)
    profile_json = (
        active.get("profile_json") if isinstance(active.get("profile_json"), dict) else default_quality_profile()
    )
    return {
        "active_row": active,
        "profile_json": profile_json,
        "profile_id": str(active.get("id") or profile_json.get("id") or "CinemaLux_v1"),
        "profile_version": int(active.get("version") or profile_json.get("version") or 1),
        "is_active": bool(int(active.get("is_active") or 0)),
    }


def save_active_quality_profile(api: Any, profile_json: Dict[str, Any]) -> Dict[str, Any]:
    _state_dir, store = quality_store(api)
    store.save_quality_profile(
        profile_id=str(profile_json["id"]),
        version=int(profile_json["version"]),
        profile_json=profile_json,
        is_active=True,
    )
    return {
        "profile_id": str(profile_json["id"]),
        "profile_version": int(profile_json["version"]),
        "profile_json": profile_json,
    }


def ensure_quality_profile(_api: Any, store: SQLiteStore) -> Dict[str, Any]:
    active = store.get_active_quality_profile()
    if active and isinstance(active.get("profile_json"), dict):
        ok, _errs, normalized = validate_quality_profile(active.get("profile_json"))
        if ok:
            if normalized.get("id") != active.get("id") or int(normalized.get("version") or 0) != int(
                active.get("version") or 0
            ):
                normalized["id"] = str(active.get("id") or normalized.get("id") or "CinemaLux_v1")
                normalized["version"] = int(active.get("version") or normalized.get("version") or 1)
                store.save_quality_profile(
                    profile_id=str(normalized["id"]),
                    version=int(normalized["version"]),
                    profile_json=normalized,
                    is_active=True,
                )
                active = store.get_active_quality_profile()
            if active:
                return active
        else:
            default_profile = default_quality_profile()
            store.save_quality_profile(
                profile_id=str(default_profile["id"]),
                version=int(default_profile["version"]),
                profile_json=default_profile,
                is_active=True,
            )
            active = store.get_active_quality_profile()
            if active:
                return active

    default_profile = default_quality_profile()
    store.save_quality_profile(
        profile_id=str(default_profile["id"]),
        version=int(default_profile["version"]),
        profile_json=default_profile,
        is_active=True,
    )
    active_profile = store.get_active_quality_profile()
    if active_profile:
        return active_profile
    return {
        "id": str(default_profile["id"]),
        "version": int(default_profile["version"]),
        "profile_json": default_profile,
        "created_ts": time.time(),
        "updated_ts": time.time(),
        "is_active": 1,
    }


def parse_profile_payload(payload: Any) -> Tuple[bool, List[str], Dict[str, Any]]:
    if isinstance(payload, str):
        txt = payload.strip()
        if not txt:
            return False, ["Profil vide."], default_quality_profile()
        try:
            parsed = json.loads(txt)
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return False, [f"JSON invalide: {exc}"], default_quality_profile()
        return validate_quality_profile(parsed)
    return validate_quality_profile(payload)
