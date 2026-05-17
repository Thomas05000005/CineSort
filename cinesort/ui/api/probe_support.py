from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import cinesort.infra.state as state
from cinesort.infra.probe import ProbeService
from cinesort.infra.probe.auto_install import install_all
from cinesort.ui.api._responses import err as _err_response
from cinesort.ui.api._validators import requires_valid_run_id
from cinesort.ui.api.settings_support import normalize_probe_backend, normalize_user_path


def probe_settings_from_dict(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw = cfg if isinstance(cfg, dict) else {}
    return {
        "probe_backend": normalize_probe_backend(raw.get("probe_backend")),
        "mediainfo_path": str(raw.get("mediainfo_path") or "").strip(),
        "ffprobe_path": str(raw.get("ffprobe_path") or "").strip(),
    }


def probe_settings_from_run_row(run_row: Dict[str, Any]) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {}
    try:
        data = json.loads(str(run_row.get("config_json") or "{}"))
        if isinstance(data, dict):
            parsed = data
    except (ImportError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        parsed = {}
    return probe_settings_from_dict(parsed)


def probe_tools_status_payload(
    api: Any,
    *,
    settings: Dict[str, Any],
    state_dir: Path,
    detect_probe_tools_fn: Callable[..., Dict[str, Any]],
    force: bool = False,
    check_versions: bool = True,
    scan_winget_packages: bool = True,
) -> Dict[str, Any]:
    cache_key = json.dumps(
        {
            "state_dir": str(state_dir),
            "probe_backend": str(settings.get("probe_backend") or ""),
            "ffprobe_path": str(settings.get("ffprobe_path") or ""),
            "mediainfo_path": str(settings.get("mediainfo_path") or ""),
            "check_versions": bool(check_versions),
            "scan_winget_packages": bool(scan_winget_packages),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    now = time.time()
    if (
        check_versions
        and (not force)
        and str(api._probe_tools_cache.get("key") or "") == cache_key
        and (now - float(api._probe_tools_cache.get("ts") or 0.0)) < 90.0
        and isinstance(api._probe_tools_cache.get("payload"), dict)
    ):
        return dict(api._probe_tools_cache["payload"])

    payload = detect_probe_tools_fn(
        settings=settings,
        state_dir=state_dir,
        check_versions=check_versions,
        scan_winget_packages=scan_winget_packages,
    )
    if check_versions:
        api._probe_tools_cache = {"key": cache_key, "ts": now, "payload": dict(payload)}
    return payload


def effective_probe_settings_for_runtime(
    api: Any,
    run_row: Optional[Dict[str, Any]] = None,
    *,
    detect_probe_tools_fn: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
    current = api.settings.get_settings()
    base = probe_settings_from_run_row(run_row) if isinstance(run_row, dict) else {}
    cfg = probe_settings_from_dict(current if current else base)
    if not cfg.get("ffprobe_path") and base.get("ffprobe_path"):
        cfg["ffprobe_path"] = str(base.get("ffprobe_path") or "").strip()
    if not cfg.get("mediainfo_path") and base.get("mediainfo_path"):
        cfg["mediainfo_path"] = str(base.get("mediainfo_path") or "").strip()
    status = probe_tools_status_payload(
        api,
        settings=cfg,
        state_dir=normalize_user_path(current.get("state_dir"), api._state_dir),
        detect_probe_tools_fn=detect_probe_tools_fn,
        check_versions=False,
        scan_winget_packages=False,
    )
    tools = status.get("tools") if isinstance(status.get("tools"), dict) else {}
    ff = tools.get("ffprobe") if isinstance(tools.get("ffprobe"), dict) else {}
    mi = tools.get("mediainfo") if isinstance(tools.get("mediainfo"), dict) else {}
    if (not str(cfg.get("ffprobe_path") or "").strip()) and ff.get("available"):
        cfg["ffprobe_path"] = str(ff.get("path") or "")
    if (not str(cfg.get("mediainfo_path") or "").strip()) and mi.get("available"):
        cfg["mediainfo_path"] = str(mi.get("path") or "")
    return cfg


def get_probe_tools_status(
    api: Any,
    *,
    detect_probe_tools_fn: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        payload = probe_tools_status_payload(
            api,
            settings=probe_settings_from_dict(settings),
            state_dir=state_dir,
            detect_probe_tools_fn=detect_probe_tools_fn,
            force=False,
            check_versions=True,
            scan_winget_packages=True,
        )
        return {"ok": True, **payload}
    except (OSError, KeyError, TypeError, ValueError) as exc:
        api.log_api_exception(
            "get_probe_tools_status",
            exc,
            extra={"force": False, "check_versions": True, "scan_winget_packages": True},
        )
        return _err_response(
            "Impossible de verifier les outils probe.", category="runtime", level="warning", log_module=__name__
        )


def recheck_probe_tools(
    api: Any,
    *,
    detect_probe_tools_fn: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        payload = probe_tools_status_payload(
            api,
            settings=probe_settings_from_dict(settings),
            state_dir=state_dir,
            detect_probe_tools_fn=detect_probe_tools_fn,
            force=True,
            check_versions=True,
            scan_winget_packages=True,
        )
        return {"ok": True, **payload}
    except (OSError, KeyError, TypeError, ValueError) as exc:
        api.log_api_exception(
            "recheck_probe_tools",
            exc,
            extra={"force": True, "check_versions": True, "scan_winget_packages": True},
        )
        return _err_response(
            "Impossible de recontroler les outils probe.", category="runtime", level="warning", log_module=__name__
        )


def set_probe_tool_paths(
    api: Any,
    payload: Optional[Dict[str, Any]] = None,
    *,
    validate_tool_path_fn: Callable[..., Dict[str, Any]],
    detect_probe_tools_fn: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
    try:
        incoming = payload if isinstance(payload, dict) else {}
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        ff_path = str(incoming.get("ffprobe_path") or "").strip()
        mi_path = str(incoming.get("mediainfo_path") or "").strip()
        backend = normalize_probe_backend(incoming.get("probe_backend") or settings.get("probe_backend"))

        if ff_path:
            check_ff = validate_tool_path_fn(tool_name="ffprobe", tool_path=ff_path, state_dir=state_dir)
            if not check_ff.get("ok"):
                return _err_response(
                    f"Chemin ffprobe invalide: {check_ff.get('message') or ''}",
                    category="config",
                    level="warning",
                    log_module=__name__,
                )
        if mi_path:
            check_mi = validate_tool_path_fn(tool_name="mediainfo", tool_path=mi_path, state_dir=state_dir)
            if not check_mi.get("ok"):
                return _err_response(
                    f"Chemin MediaInfo invalide: {check_mi.get('message') or ''}",
                    category="config",
                    level="warning",
                    log_module=__name__,
                )

        merged = dict(settings)
        merged["probe_backend"] = backend
        merged["ffprobe_path"] = ff_path
        merged["mediainfo_path"] = mi_path
        save_res = api.settings.save_settings(merged)
        if not save_res.get("ok"):
            return save_res
        return api.recheck_probe_tools()
    except (OSError, KeyError, TypeError, ValueError) as exc:
        api.log_api_exception(
            "set_probe_tool_paths",
            exc,
            state_dir=state_dir if "state_dir" in locals() else None,
            extra={
                "probe_backend": backend if "backend" in locals() else None,
                "has_ffprobe_path": bool(ff_path) if "ff_path" in locals() else False,
                "has_mediainfo_path": bool(mi_path) if "mi_path" in locals() else False,
            },
        )
        return _err_response(
            "Impossible d'enregistrer les chemins des outils probe.",
            category="runtime",
            level="warning",
            log_module=__name__,
        )


def _refresh_settings_with_detected_tool_paths(settings: Dict[str, Any], managed: Dict[str, Any]) -> Dict[str, Any]:
    status = managed.get("status") if isinstance(managed.get("status"), dict) else {}
    tools = status.get("tools") if isinstance(status.get("tools"), dict) else {}
    ff = tools.get("ffprobe") if isinstance(tools.get("ffprobe"), dict) else {}
    mi = tools.get("mediainfo") if isinstance(tools.get("mediainfo"), dict) else {}
    merged = dict(settings)
    if ff.get("available") and str(ff.get("path") or "").strip():
        merged["ffprobe_path"] = str(ff.get("path"))
    if mi.get("available") and str(mi.get("path") or "").strip():
        merged["mediainfo_path"] = str(mi.get("path"))
    return merged


def install_probe_tools(
    api: Any,
    options: Optional[Dict[str, Any]] = None,
    *,
    manage_probe_tools_fn: Callable[..., Dict[str, Any]],
    detect_probe_tools_fn: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
    opts = options if isinstance(options, dict) else {}
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        managed = manage_probe_tools_fn(
            action="install",
            options=opts,
            settings=probe_settings_from_dict(settings),
            state_dir=state_dir,
        )
        merged = _refresh_settings_with_detected_tool_paths(settings, managed)
        api.settings.save_settings(merged)
        managed["status"] = probe_tools_status_payload(
            api,
            settings=probe_settings_from_dict(merged),
            state_dir=state_dir,
            detect_probe_tools_fn=detect_probe_tools_fn,
            force=True,
            check_versions=True,
            scan_winget_packages=True,
        )
        return managed
    except (OSError, KeyError, TypeError, ValueError) as exc:
        api.log_api_exception(
            "install_probe_tools",
            exc,
            state_dir=state_dir if "state_dir" in locals() else None,
            extra={
                "scope": str(opts.get("scope") or ""),
                "tools": list(opts.get("tools") or []) if isinstance(opts.get("tools"), list) else [],
            },
        )
        return _err_response(
            "Impossible d'installer les outils probe.", category="runtime", level="warning", log_module=__name__
        )


def update_probe_tools(
    api: Any,
    options: Optional[Dict[str, Any]] = None,
    *,
    manage_probe_tools_fn: Callable[..., Dict[str, Any]],
    detect_probe_tools_fn: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
    opts = options if isinstance(options, dict) else {}
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        managed = manage_probe_tools_fn(
            action="update",
            options=opts,
            settings=probe_settings_from_dict(settings),
            state_dir=state_dir,
        )
        merged = _refresh_settings_with_detected_tool_paths(settings, managed)
        api.settings.save_settings(merged)
        managed["status"] = probe_tools_status_payload(
            api,
            settings=probe_settings_from_dict(merged),
            state_dir=state_dir,
            detect_probe_tools_fn=detect_probe_tools_fn,
            force=True,
            check_versions=True,
            scan_winget_packages=True,
        )
        return managed
    except (OSError, KeyError, TypeError, ValueError) as exc:
        api.log_api_exception(
            "update_probe_tools",
            exc,
            state_dir=state_dir if "state_dir" in locals() else None,
            extra={
                "scope": str(opts.get("scope") or ""),
                "tools": list(opts.get("tools") or []) if isinstance(opts.get("tools"), list) else [],
            },
        )
        return _err_response(
            "Impossible de mettre a jour les outils probe.", category="runtime", level="warning", log_module=__name__
        )


def auto_install_probe_tools(
    api: Any,
    *,
    detect_probe_tools_fn: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
    """Telecharge ffprobe + MediaInfo via HTTP et les installe dans tools/."""
    import logging as _logging

    _logger = _logging.getLogger(__name__)
    try:
        result = install_all()
        installed = result.get("installed", {})
        errors = result.get("errors", [])

        # Mettre a jour les settings avec les chemins installes
        settings = api.settings.get_settings()
        if installed.get("ffprobe"):
            settings["ffprobe_path"] = installed["ffprobe"]
        if installed.get("mediainfo"):
            settings["mediainfo_path"] = installed["mediainfo"]
        api.settings.save_settings(settings)

        # Rafraichir le statut probe
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        status = probe_tools_status_payload(
            api,
            settings=probe_settings_from_dict(settings),
            state_dir=state_dir,
            detect_probe_tools_fn=detect_probe_tools_fn,
            force=True,
            check_versions=True,
            scan_winget_packages=False,
        )
        ok = bool(installed) and not errors
        msg = "Outils installes avec succes." if ok else f"Installation partielle : {'; '.join(errors)}"
        _logger.info("auto_install_probe_tools: ok=%s installed=%s errors=%s", ok, list(installed), errors)
        return {"ok": ok, "installed": installed, "errors": errors, "message": msg, "status": status}
    except (OSError, FileNotFoundError) as exc:
        _logger.error("auto_install_probe_tools: %s", exc)
        return {"ok": False, "message": f"Echec de l'installation : {exc}", "errors": [str(exc)]}


@requires_valid_run_id
def get_probe(
    api: Any,
    run_id: str,
    row_id: str,
    *,
    detect_probe_tools_fn: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
    if not run_id or not row_id:
        return _err_response(
            "Les identifiants run_id et row_id sont requis.", category="validation", level="info", log_module=__name__
        )
    try:
        found = api._find_run_row(run_id)
        if not found:
            return _err_response("Run introuvable.", category="resource", level="info", log_module=__name__)
        run_row, store = found
        state_dir = normalize_user_path(run_row.get("state_dir"), api._state_dir)
        run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=False)
        rs = api._get_run(run_id)

        if rs and rs.rows:
            rows = rs.rows
        else:
            rows = api._load_rows_from_plan_jsonl(run_paths)

        row = next((candidate for candidate in rows if str(candidate.row_id) == str(row_id)), None)
        if row is None:
            return _err_response(
                "Film introuvable dans ce plan (row_id).", category="resource", level="info", log_module=__name__
            )

        cfg = rs.cfg if rs else api._cfg_from_run_row(run_row)
        media_path = api._resolve_media_path_for_row(cfg, row)
        if media_path is None or (not media_path.exists()):
            return _err_response(
                "Fichier media introuvable pour cette ligne.", category="resource", level="warning", log_module=__name__
            )

        probe_settings = effective_probe_settings_for_runtime(
            api,
            run_row,
            detect_probe_tools_fn=detect_probe_tools_fn,
        )
        probe = ProbeService(store)
        result = probe.probe_file(media_path=media_path, settings=probe_settings)

        log_fn = rs.log if rs else api._file_logger(run_paths)
        normalized = result.get("normalized") if isinstance(result.get("normalized"), dict) else {}
        messages = normalized.get("messages") if isinstance(normalized.get("messages"), list) else []
        for message in messages:
            text = str(message)
            lower = text.lower()
            level = (
                "WARN" if any(token in lower for token in ("manquant", "echec", "impossible", "invalide")) else "INFO"
            )
            log_fn(level, f"PROBE {row_id}: {text}")

        return {
            "ok": True,
            "run_id": run_id,
            "row_id": row_id,
            "media_path": str(media_path),
            **result,
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)
