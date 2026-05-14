from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .tooling import RunnerFn, default_runner


_MIN_VERSIONS = {
    "ffprobe": "5.0",
    "mediainfo": "23.0",
}

_TOOL_EXECUTABLES = {
    "ffprobe": ["ffprobe.exe", "ffprobe"] if os.name == "nt" else ["ffprobe"],
    "mediainfo": ["MediaInfo.exe", "mediainfo.exe", "mediainfo"] if os.name == "nt" else ["mediainfo"],
}

_WINGET_IDS = {
    "ffprobe": ["Gyan.FFmpeg", "BtbN.FFmpeg"],
    "mediainfo": ["MediaArea.MediaInfo", "MediaArea.MediaInfo.GUI"],
}

_SUPPORTED_TOOLS = ("ffprobe", "mediainfo")

# Cf issue #71 : whitelist des noms de binaire pour validate_tool_path —
# empeche d'executer un binaire arbitraire avec "-version" via les settings.
# Mapping tool_name -> noms acceptes (sensible casse-insensible). On accepte
# le nom Windows (.exe) et le nom Unix (sans extension) pour la portabilite
# tests/CI Linux.
_EXPECTED_BINARY_NAMES = {
    "ffprobe": frozenset({"ffprobe.exe", "ffprobe"}),
    "mediainfo": frozenset({"mediainfo.exe", "mediainfo", "MediaInfo.exe"}),
}
_STATUS_OK = "ok"
_STATUS_MISSING = "missing"
_STATUS_INVALID = "invalid_executable"
_STATUS_VERSION_UNKNOWN = "version_unknown"
_STATUS_TOO_OLD = "version_too_old"


def _normalize_backend(value: Any) -> str:
    v = str(value or "auto").strip().lower()
    if v not in {"auto", "ffprobe", "mediainfo", "none"}:
        return "auto"
    return v


def _normalize_scope(value: Any) -> str:
    v = str(value or "user").strip().lower()
    if v not in {"user", "machine"}:
        return "user"
    return v


def _normalize_tool_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return list(_SUPPORTED_TOOLS)
    out: List[str] = []
    for item in value:
        t = str(item or "").strip().lower()
        if t in _SUPPORTED_TOOLS and t not in out:
            out.append(t)
    return out or list(_SUPPORTED_TOOLS)


def _parse_version_tuple(text: str) -> Optional[Tuple[int, ...]]:
    raw = str(text or "").strip()
    if not raw:
        return None
    # Supports lines like: "ffprobe version n7.1.1" or "MediaInfoLib - v24.12".
    m = re.search(r"(?:version|v)\s*([nN]?\d+(?:\.\d+){1,3})", raw, flags=re.IGNORECASE)
    if not m:
        m = re.search(r"([nN]?\d+(?:\.\d+){1,3})", raw)
    if not m:
        return None
    token = m.group(1).lstrip("nN")
    parts: List[int] = []
    for p in token.split("."):
        try:
            parts.append(int(p))
        except (TypeError, ValueError):
            return None
    return tuple(parts) if parts else None


def _version_to_text(vt: Optional[Tuple[int, ...]]) -> str:
    if not vt:
        return ""
    return ".".join(str(x) for x in vt)


def _is_version_compatible(found: Optional[Tuple[int, ...]], minimum: str) -> bool:
    if not found:
        return True  # unknown version -> tolerated with warning
    req = _parse_version_tuple(minimum)
    if not req:
        return True
    a = list(found)
    b = list(req)
    while len(a) < len(b):
        a.append(0)
    while len(b) < len(a):
        b.append(0)
    return tuple(a) >= tuple(b)


def _resolve_explicit_path(value: Any) -> str:
    raw = str(value or "").strip().strip('"').strip("'")
    if not raw:
        return ""
    expanded = os.path.expandvars(os.path.expanduser(raw))
    return str(Path(expanded))


def _safe_file_mtime(path: Path) -> float:
    try:
        return float(path.stat().st_mtime)
    except (OSError, PermissionError, TypeError, ValueError):
        return 0.0


def _candidate_paths_for_tool(
    *, tool_name: str, explicit_path: str, state_dir: Path, which_fn, scan_winget_packages: bool
) -> List[Tuple[str, str]]:
    candidates: List[Tuple[str, str]] = []
    if explicit_path:
        candidates.append(("explicit", explicit_path))

    # Chercher dans state_dir/tools/ et aussi a cote de l'executable (tools/)
    import sys as _sys

    tools_roots = [state_dir / "tools"]
    if getattr(_sys, "frozen", False):
        tools_roots.append(Path(_sys.executable).parent / "tools")
    else:
        tools_roots.append(Path(__file__).resolve().parent.parent.parent.parent / "tools")
    for tools_root in tools_roots:
        for exe in _TOOL_EXECUTABLES[tool_name]:
            p1 = tools_root / tool_name / exe
            p2 = tools_root / exe
            if p1.exists():
                candidates.append(("managed", str(p1)))
            if p2.exists():
                candidates.append(("managed", str(p2)))

    if scan_winget_packages and os.name == "nt":
        local_appdata = str(os.environ.get("LOCALAPPDATA", "")).strip()
        pkg_root = Path(local_appdata) / "Microsoft" / "WinGet" / "Packages" if local_appdata else None
        if pkg_root and pkg_root.exists():
            matched: List[Path] = []
            for exe in _TOOL_EXECUTABLES[tool_name]:
                try:
                    for p in pkg_root.rglob(exe):
                        try:
                            if p.is_file():
                                matched.append(p)
                        except (KeyError, OSError, PermissionError, TypeError, ValueError):
                            continue
                except (KeyError, OSError, PermissionError, TypeError, ValueError):
                    continue
            if matched:
                newest = max(matched, key=_safe_file_mtime)
                candidates.append(("winget_package", str(newest)))

    for exe in _TOOL_EXECUTABLES[tool_name]:
        w = which_fn(exe)
        if w:
            candidates.append(("path", str(w)))

    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for src, path in candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((src, str(path)))
    return out


def _probe_version_line(*, tool_name: str, tool_path: str, runner: RunnerFn) -> Tuple[bool, str, str]:
    if not tool_path:
        return False, "", ""
    cmd = [tool_path, "--Version"] if tool_name == "mediainfo" else [tool_path, "-version"]
    try:
        from cinesort.infra.probe.constants import VERSION_PROBE_DETAILED_TIMEOUT_S

        rc, out, err = runner(cmd, VERSION_PROBE_DETAILED_TIMEOUT_S)
    except (ImportError, OSError, TypeError, ValueError) as exc:
        return False, "", str(exc)
    text = str(out or "").strip() or str(err or "").strip()
    if rc != 0:
        return False, "", text
    first_line = ""
    for line in text.splitlines():
        if line.strip():
            first_line = line.strip()
            break
    return True, first_line, text


def _build_tool_status(
    *,
    tool_name: str,
    explicit_path: str,
    state_dir: Path,
    runner: RunnerFn,
    which_fn,
    check_versions: bool,
    scan_winget_packages: bool,
) -> Dict[str, Any]:
    minimum = _MIN_VERSIONS.get(tool_name, "")
    candidates = _candidate_paths_for_tool(
        tool_name=tool_name,
        explicit_path=explicit_path,
        state_dir=state_dir,
        which_fn=which_fn,
        scan_winget_packages=scan_winget_packages,
    )
    if not candidates:
        return {
            "name": tool_name,
            "status": _STATUS_MISSING,
            "available": False,
            "path": "",
            "version": "",
            "source": "none",
            "compatible": False,
            "min_version": minimum,
            "message": f"{tool_name} manquant (chemin non configure, non trouve dans tools/PATH).",
            "checked_ts": time.time(),
        }

    for source, path in candidates:
        p = Path(path)
        if not p.exists() or not p.is_file():
            continue
        if not check_versions:
            return {
                "name": tool_name,
                "status": _STATUS_OK,
                "available": True,
                "path": str(p),
                "version": "",
                "source": source,
                "compatible": True,
                "min_version": minimum,
                "message": f"{tool_name} detecte ({source}).",
                "checked_ts": time.time(),
            }
        ok_exec, first_line, full_text = _probe_version_line(tool_name=tool_name, tool_path=str(p), runner=runner)
        if not ok_exec:
            continue
        parsed = _parse_version_tuple(first_line)
        version_text = _version_to_text(parsed)
        if not parsed:
            return {
                "name": tool_name,
                "status": _STATUS_VERSION_UNKNOWN,
                "available": True,
                "path": str(p),
                "version": "",
                "source": source,
                "compatible": True,
                "min_version": minimum,
                "message": f"{tool_name} detecte ({source}) mais version non lisible.",
                "checked_ts": time.time(),
            }
        if not _is_version_compatible(parsed, minimum):
            return {
                "name": tool_name,
                "status": _STATUS_TOO_OLD,
                "available": True,
                "path": str(p),
                "version": version_text,
                "source": source,
                "compatible": False,
                "min_version": minimum,
                "message": f"{tool_name} detecte ({version_text}) mais version minimale recommandee: {minimum}.",
                "checked_ts": time.time(),
            }
        return {
            "name": tool_name,
            "status": _STATUS_OK,
            "available": True,
            "path": str(p),
            "version": version_text,
            "source": source,
            "compatible": True,
            "min_version": minimum,
            "message": f"{tool_name} detecte ({version_text}, source={source}).",
            "checked_ts": time.time(),
        }

    return {
        "name": tool_name,
        "status": _STATUS_INVALID,
        "available": False,
        "path": str(candidates[0][1]),
        "version": "",
        "source": str(candidates[0][0]),
        "compatible": False,
        "min_version": minimum,
        "message": f"{tool_name} detecte mais executable invalide.",
        "checked_ts": time.time(),
    }


def detect_probe_tools(
    *,
    settings: Dict[str, Any],
    state_dir: Path,
    runner: RunnerFn = default_runner,
    which_fn=shutil.which,
    check_versions: bool = True,
    scan_winget_packages: bool = True,
) -> Dict[str, Any]:
    cfg = settings if isinstance(settings, dict) else {}
    backend = _normalize_backend(cfg.get("probe_backend"))
    ff_explicit = _resolve_explicit_path(cfg.get("ffprobe_path"))
    mi_explicit = _resolve_explicit_path(cfg.get("mediainfo_path"))

    ff = _build_tool_status(
        tool_name="ffprobe",
        explicit_path=ff_explicit,
        state_dir=state_dir,
        runner=runner,
        which_fn=which_fn,
        check_versions=check_versions,
        scan_winget_packages=scan_winget_packages,
    )
    mi = _build_tool_status(
        tool_name="mediainfo",
        explicit_path=mi_explicit,
        state_dir=state_dir,
        runner=runner,
        which_fn=which_fn,
        check_versions=check_versions,
        scan_winget_packages=scan_winget_packages,
    )
    tools = {"ffprobe": ff, "mediainfo": mi}

    ff_ready = bool(ff.get("available")) and bool(ff.get("compatible"))
    mi_ready = bool(mi.get("available")) and bool(mi.get("compatible"))
    hybrid_ready = ff_ready and mi_ready
    if backend == "none":
        degraded_mode = "disabled"
        msg = "Probe desactivee (backend=none)."
    elif hybrid_ready:
        degraded_mode = "hybrid"
        msg = "Mode hybride pret: ffprobe + MediaInfo disponibles."
    elif ff_ready or mi_ready:
        degraded_mode = "partial"
        if ff_ready:
            msg = "Mode degrade: ffprobe disponible, MediaInfo manquant/incompatible."
        else:
            msg = "Mode degrade: MediaInfo disponible, ffprobe manquant/incompatible."
    else:
        degraded_mode = "none"
        msg = "Aucun outil probe compatible detecte."

    return {
        "probe_backend": backend,
        "tools": tools,
        "hybrid_ready": bool(hybrid_ready),
        "degraded_mode": degraded_mode,
        "message": msg,
        "installer": {
            "strategy": "winget_user_local_first",
            "supported": bool(os.name == "nt"),
            "winget_available": bool(which_fn("winget")),
            "security": "Aucun binaire distant execute directement: installation via winget (source packagee).",
        },
    }


def _build_winget_command(*, winget_path: str, action: str, package_id: str, scope: str) -> List[str]:
    cmd = [
        winget_path,
        action,
        "--id",
        package_id,
        "--exact",
        "--accept-source-agreements",
        "--accept-package-agreements",
        "--silent",
    ]
    if action == "upgrade":
        cmd.append("--include-unknown")
    if scope in {"user", "machine"}:
        cmd.extend(["--scope", scope])
    return cmd


def _run_winget_for_tool(
    *, tool_name: str, action: str, scope: str, runner: RunnerFn, winget_path: str
) -> Dict[str, Any]:
    ids = _WINGET_IDS.get(tool_name, [])
    last_error = ""
    for pkg in ids:
        cmd = _build_winget_command(winget_path=winget_path, action=action, package_id=pkg, scope=scope)
        try:
            from cinesort.infra.probe.constants import WINGET_INSTALL_TIMEOUT_S

            rc, out, err = runner(cmd, WINGET_INSTALL_TIMEOUT_S)
        except (ImportError, KeyError, OSError, TypeError, ValueError) as exc:
            last_error = str(exc)
            continue
        if int(rc) == 0:
            return {
                "ok": True,
                "tool": tool_name,
                "package_id": pkg,
                "message": f"{tool_name} {action} OK via {pkg}.",
                "stdout": str(out or "")[:500],
                "stderr": str(err or "")[:500],
            }
        txt = (str(err or "").strip() or str(out or "").strip())[:800]
        last_error = txt or f"code={rc}"
    return {
        "ok": False,
        "tool": tool_name,
        "message": f"Echec {action} {tool_name}: {last_error or 'erreur inconnue'}",
    }


def manage_probe_tools(
    *,
    action: str,
    options: Optional[Dict[str, Any]],
    settings: Dict[str, Any],
    state_dir: Path,
    runner: RunnerFn = default_runner,
    which_fn=shutil.which,
) -> Dict[str, Any]:
    act = str(action or "").strip().lower()
    if act not in {"install", "update"}:
        return {"ok": False, "message": "Action invalide (install/update attendu)."}
    if os.name != "nt":
        return {"ok": False, "message": "Installation assistee disponible uniquement sous Windows."}

    opts = options if isinstance(options, dict) else {}
    tools = _normalize_tool_list(opts.get("tools"))
    scope = _normalize_scope(opts.get("scope"))
    winget = which_fn("winget")
    if not winget:
        return {"ok": False, "message": "winget introuvable. Installation assistee indisponible."}

    per_tool: List[Dict[str, Any]] = []
    for tool in tools:
        action_name = "upgrade" if act == "update" else "install"
        one = _run_winget_for_tool(
            tool_name=tool,
            action=action_name,
            scope=scope,
            runner=runner,
            winget_path=str(winget),
        )
        # fallback update->install if not installed
        if (not one.get("ok")) and act == "update":
            one = _run_winget_for_tool(
                tool_name=tool,
                action="install",
                scope=scope,
                runner=runner,
                winget_path=str(winget),
            )
        per_tool.append(one)

    status = detect_probe_tools(
        settings=settings,
        state_dir=state_dir,
        runner=runner,
        which_fn=which_fn,
        check_versions=True,
        scan_winget_packages=True,
    )
    tools_status = status.get("tools") if isinstance(status.get("tools"), dict) else {}
    for item in per_tool:
        if bool(item.get("ok")):
            continue
        tool_name = str(item.get("tool") or "").strip().lower()
        tool_state = tools_status.get(tool_name) if isinstance(tools_status, dict) else {}
        if isinstance(tool_state, dict) and bool(tool_state.get("available")) and bool(tool_state.get("compatible")):
            item["ok"] = True
            item["reconciled"] = True
            item["message"] = (
                f"{tool_name} deja disponible et compatible apres verification; "
                "operation winget consideree comme non bloquante."
            )

    ok = all(bool(x.get("ok")) for x in per_tool) if per_tool else False
    return {
        "ok": bool(ok),
        "action": act,
        "scope": scope,
        "results": per_tool,
        "status": status,
        "message": "Operation terminee." if ok else "Operation terminee avec erreurs.",
    }


def validate_tool_path(
    *,
    tool_name: str,
    tool_path: str,
    state_dir: Path,
    runner: RunnerFn = default_runner,
) -> Dict[str, Any]:
    t = str(tool_name or "").strip().lower()
    if t not in _SUPPORTED_TOOLS:
        return {"ok": False, "message": "Outil inconnu.", "tool": t}
    explicit = _resolve_explicit_path(tool_path)
    if not explicit:
        return {"ok": False, "message": "Chemin vide.", "tool": t}
    p = Path(explicit)
    if not p.exists() or not p.is_file():
        return {"ok": False, "message": "Executable introuvable.", "tool": t}
    # Cf issue #71 : valider que le nom du binaire correspond a l'outil attendu
    # AVANT de l'executer avec -version. Empeche d'invoquer n'importe quel
    # .exe (calc.exe, cmd.exe, malware.exe...) via les settings REST.
    expected_names = _EXPECTED_BINARY_NAMES.get(t, frozenset())
    if p.name.lower() not in {n.lower() for n in expected_names}:
        return {
            "ok": False,
            "message": f"Nom de binaire invalide : attendu {sorted(expected_names)}, recu '{p.name}'.",
            "tool": t,
        }
    ok_exec, first_line, _full = _probe_version_line(tool_name=t, tool_path=str(p), runner=runner)
    if not ok_exec:
        return {"ok": False, "message": "Executable invalide ou non executable.", "tool": t}
    parsed = _parse_version_tuple(first_line)
    version_text = _version_to_text(parsed)
    minimum = _MIN_VERSIONS.get(t, "")
    status = _STATUS_OK if _is_version_compatible(parsed, minimum) else _STATUS_TOO_OLD
    if status == _STATUS_TOO_OLD:
        return {
            "ok": False,
            "message": f"Version trop ancienne ({version_text}), minimum {minimum}.",
            "tool": t,
            "status": {
                "name": t,
                "status": status,
                "available": True,
                "path": str(p),
                "version": version_text,
                "source": "explicit",
                "compatible": False,
                "min_version": minimum,
                "message": f"{t} detecte mais version trop ancienne.",
                "checked_ts": time.time(),
            },
        }
    return {
        "ok": True,
        "tool": t,
        "status": {
            "name": t,
            "status": _STATUS_OK if parsed else _STATUS_VERSION_UNKNOWN,
            "available": True,
            "path": str(p),
            "version": version_text,
            "source": "explicit",
            "compatible": True,
            "min_version": minimum,
            "message": f"{t} valide.",
            "checked_ts": time.time(),
        },
    }
