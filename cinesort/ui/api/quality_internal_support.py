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
    store.quality.save_quality_profile(
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


def profil_durable_des_reglages(api: Any) -> Dict[str, Any] | None:
    """Profil que l'utilisateur a choisi, tel que les REGLAGES le conservent.

    LE SENS EST UNIQUE : reglages -> base. `settings.custom_quality_profiles`
    est la bibliotheque durable (elle survit a `reset_database`, qui n'efface
    que le fichier SQLite, et part avec la sauvegarde des reglages) ; la base
    n'en est que la materialisation, ce que lit le scoring.

    CE QUE CETTE FONCTION EMPECHE. `reset_database` supprime le fichier SQLite
    entier. Sans elle, `ensure_quality_profile` reconstruisait le profil PAR
    DEFAUT, et le reglage patiemment ajuste disparaissait sans un mot — mesure
    de bout en bout : poids video 70 -> 60, `ok: True`, aucun avertissement. Un
    utilisateur qui appuie sur « Reinitialiser la base » pour reparer un scan
    perdait son profil au passage.

    Rend `None` si les reglages ne nomment aucun profil, ou si celui qu'ils
    nomment est introuvable ou invalide — l'appelant retombe alors sur le
    defaut, comme avant.
    """
    try:
        settings = api.settings.get_settings() or {}
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    pid = str(settings.get("active_quality_profile_id") or "").strip()
    if not pid:
        return None
    for entree in settings.get("custom_quality_profiles") or []:
        if not isinstance(entree, dict) or str(entree.get("id") or "") != pid:
            continue
        ok, _errs, normalise = validate_quality_profile(entree)
        # Un profil devenu invalide (schema durci entre deux versions) ne doit pas
        # bloquer le demarrage : on le laisse passer la main au defaut.
        return normalise if ok else None
    return None


def ensure_quality_profile(_api: Any, store: SQLiteStore) -> Dict[str, Any]:
    active = store.quality.get_active_quality_profile()
    if not active:
        # La base est vide — premier lancement, ou `reset_database`. On rematerialise
        # depuis les reglages AVANT de retomber sur le defaut.
        durable = profil_durable_des_reglages(_api)
        if durable:
            store.quality.save_quality_profile(
                profile_id=str(durable["id"]),
                version=int(durable.get("version") or 1),
                profile_json=durable,
                is_active=True,
            )
            restaure = store.quality.get_active_quality_profile()
            if restaure:
                return restaure
    if active and isinstance(active.get("profile_json"), dict):
        ok, _errs, normalized = validate_quality_profile(active.get("profile_json"))
        if ok:
            if normalized.get("id") != active.get("id") or int(normalized.get("version") or 0) != int(
                active.get("version") or 0
            ):
                normalized["id"] = str(active.get("id") or normalized.get("id") or "CinemaLux_v1")
                normalized["version"] = int(active.get("version") or normalized.get("version") or 1)
                store.quality.save_quality_profile(
                    profile_id=str(normalized["id"]),
                    version=int(normalized["version"]),
                    profile_json=normalized,
                    is_active=True,
                )
                active = store.quality.get_active_quality_profile()
            if active:
                return active
        else:
            default_profile = default_quality_profile()
            store.quality.save_quality_profile(
                profile_id=str(default_profile["id"]),
                version=int(default_profile["version"]),
                profile_json=default_profile,
                is_active=True,
            )
            active = store.quality.get_active_quality_profile()
            if active:
                return active

    default_profile = default_quality_profile()
    store.quality.save_quality_profile(
        profile_id=str(default_profile["id"]),
        version=int(default_profile["version"]),
        profile_json=default_profile,
        is_active=True,
    )
    active_profile = store.quality.get_active_quality_profile()
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
