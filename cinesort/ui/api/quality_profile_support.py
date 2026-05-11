from __future__ import annotations

import json
from typing import Any, Dict

from cinesort.domain import (
    default_quality_profile,
    list_quality_presets,
    quality_profile_from_preset,
    validate_quality_profile,
)


def get_quality_profile(api: Any) -> Dict[str, Any]:
    try:
        payload = api._active_quality_profile_payload()
        return {
            "ok": True,
            "profile_id": str(payload["profile_id"]),
            "profile_version": int(payload["profile_version"]),
            "is_active": bool(payload["is_active"]),
            "profile_json": payload["profile_json"],
        }
    except (ImportError, KeyError, OSError, TypeError, ValueError) as exc:
        return {"ok": False, "message": str(exc)}


def get_quality_presets(_api: Any) -> Dict[str, Any]:
    try:
        presets = list_quality_presets(include_profiles=True)
        return {
            "ok": True,
            "presets": presets,
            "default_preset_id": "equilibre",
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "message": str(exc)}


def apply_quality_preset(api: Any, preset_id: str) -> Dict[str, Any]:
    try:
        pid = str(preset_id or "").strip().lower()
        if not pid:
            return {"ok": False, "message": "Preset qualite requis."}
        preset_profile = quality_profile_from_preset(pid)
        if not isinstance(preset_profile, dict):
            return {"ok": False, "message": "Preset qualite inconnu."}
        ok, errs, normalized = validate_quality_profile(preset_profile)
        if not ok:
            return {"ok": False, "message": "Preset qualite invalide.", "errors": errs}
        saved = api._save_active_quality_profile(normalized)
        return {
            "ok": True,
            "preset_id": pid,
            **saved,
        }
    except (OSError, TypeError, ValueError) as exc:
        return {"ok": False, "message": str(exc)}


def save_quality_profile(api: Any, profile_json: Any) -> Dict[str, Any]:
    try:
        ok, errs, normalized = api._parse_profile_payload(profile_json)
        if not ok:
            return {"ok": False, "message": "Profil invalide.", "errors": errs}
        # Custom rules (G6) : validation stricte si presentes
        raw_rules = normalized.get("custom_rules")
        if raw_rules:
            from cinesort.domain.custom_rules import validate_rules as _validate_custom_rules

            rules_ok, rules_errs, rules_norm = _validate_custom_rules(raw_rules)
            if not rules_ok:
                return {"ok": False, "message": "Regles custom invalides.", "errors": rules_errs}
            normalized["custom_rules"] = rules_norm
        saved = api._save_active_quality_profile(normalized)
        return {
            "ok": True,
            "profile_id": str(saved["profile_id"]),
            "profile_version": int(saved["profile_version"]),
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "message": str(exc)}


def reset_quality_profile(api: Any) -> Dict[str, Any]:
    try:
        profile = default_quality_profile()
        saved = api._save_active_quality_profile(profile)
        return {"ok": True, **saved}
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "message": str(exc)}


def export_quality_profile(api: Any) -> Dict[str, Any]:
    try:
        payload = api._active_quality_profile_payload()
        return {
            "ok": True,
            "json": json.dumps(payload["profile_json"], ensure_ascii=False, indent=2),
            "profile_id": str(payload["profile_id"]),
            "profile_version": int(payload["profile_version"]),
        }
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "message": str(exc)}


def import_quality_profile(api: Any, profile_json: Any) -> Dict[str, Any]:
    return save_quality_profile(api, profile_json)
