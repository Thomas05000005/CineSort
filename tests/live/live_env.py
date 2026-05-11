from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

from cinesort.infra.probe.tools_manager import detect_probe_tools

TRUTHY_VALUES = {"1", "true", "yes", "on"}
REPO_ROOT = Path(__file__).resolve().parents[2]
_CAPABILITY_STATE_DIR = Path(tempfile.gettempdir()) / "cinesort_live_probe_capability"


def env_flag(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in TRUTHY_VALUES


def env_text(name: str) -> str:
    return str(os.environ.get(name, "")).strip()


def env_path(name: str) -> Path | None:
    raw = env_text(name)
    if not raw:
        return None
    return Path(os.path.expandvars(os.path.expanduser(raw))).resolve()


def _mask_secret(raw: str) -> str:
    if not raw:
        return "<unset>"
    return f"<set len={len(raw)}>"


def _subprocess_platform_kwargs() -> Dict[str, object]:
    if os.name != "nt":
        return {}
    kwargs: Dict[str, object] = {"creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0))}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
    startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
    kwargs["startupinfo"] = startupinfo
    return kwargs


def tmdb_capability() -> Dict[str, Any]:
    enabled = env_flag("CINESORT_LIVE_TMDB")
    api_key = env_text("CINESORT_TMDB_API_KEY")
    reason = ""
    if not enabled:
        reason = "CINESORT_LIVE_TMDB=1 requis pour activer la preuve TMDb."
    elif not api_key:
        reason = "CINESORT_TMDB_API_KEY manquant."
    return {
        "enabled": enabled,
        "api_key_present": bool(api_key),
        "api_key_hint": _mask_secret(api_key),
        "ready": enabled and bool(api_key),
        "reason": reason,
    }


def probe_capability() -> Dict[str, Any]:
    enabled = env_flag("CINESORT_LIVE_PROBE")
    ffprobe_override = env_path("CINESORT_FFPROBE_PATH")
    mediainfo_override = env_path("CINESORT_MEDIAINFO_PATH")
    media_sample_override = env_path("CINESORT_MEDIA_SAMPLE_PATH")
    ffmpeg_path = str(shutil.which("ffmpeg") or "").strip()

    status = detect_probe_tools(
        settings={
            "probe_backend": "auto",
            "ffprobe_path": str(ffprobe_override or ""),
            "mediainfo_path": str(mediainfo_override or ""),
        },
        state_dir=_CAPABILITY_STATE_DIR,
        check_versions=True,
        scan_winget_packages=True,
    )
    tools = status.get("tools", {}) if isinstance(status.get("tools"), dict) else {}
    ffprobe = tools.get("ffprobe", {}) if isinstance(tools.get("ffprobe"), dict) else {}
    mediainfo = tools.get("mediainfo", {}) if isinstance(tools.get("mediainfo"), dict) else {}
    compatible_count = sum(
        1 for tool in (ffprobe, mediainfo) if bool(tool.get("available")) and bool(tool.get("compatible"))
    )

    sample_override_exists = bool(
        media_sample_override and media_sample_override.exists() and media_sample_override.is_file()
    )
    reason = ""
    if not enabled:
        reason = "CINESORT_LIVE_PROBE=1 requis pour activer la preuve probe."
    elif compatible_count <= 0:
        reason = "Aucun outil probe compatible detecte."
    elif (not sample_override_exists) and (not ffmpeg_path):
        reason = "Aucun media sample fourni et ffmpeg introuvable pour generer un fichier temporaire."

    return {
        "enabled": enabled,
        "ready": enabled and compatible_count > 0 and (sample_override_exists or bool(ffmpeg_path)),
        "reason": reason,
        "ffprobe": ffprobe,
        "mediainfo": mediainfo,
        "compatible_count": compatible_count,
        "sample_override": str(media_sample_override or ""),
        "sample_override_exists": sample_override_exists,
        "ffmpeg_path": ffmpeg_path,
        "status": status,
    }


def pywebview_capability() -> Dict[str, Any]:
    enabled = env_flag("CINESORT_LIVE_PYWEBVIEW")
    session_name = env_text("SESSIONNAME")
    import_error = ""
    module_path = ""
    try:
        import webview  # type: ignore[import-not-found]

        module_path = str(Path(webview.__file__).resolve())
    except Exception as exc:  # pragma: no cover - runtime capability only
        import_error = str(exc)

    reason = ""
    if not enabled:
        reason = "CINESORT_LIVE_PYWEBVIEW=1 requis pour activer la preuve native pywebview."
    elif os.name != "nt":
        reason = "Windows requis pour la preuve native pywebview."
    elif import_error:
        reason = f"pywebview indisponible: {import_error}"
    elif session_name.lower() == "services":
        reason = "Session Windows interactive requise (SESSIONNAME=Services)."

    return {
        "enabled": enabled,
        "windows": os.name == "nt",
        "session_name": session_name or "<unknown>",
        "pywebview_module": module_path or "<missing>",
        "ready": enabled and os.name == "nt" and not import_error and session_name.lower() != "services",
        "reason": reason,
    }


def describe_capabilities() -> Dict[str, Any]:
    return {
        "tmdb": tmdb_capability(),
        "probe": probe_capability(),
        "pywebview": pywebview_capability(),
    }


def print_capabilities() -> None:
    print(json.dumps(describe_capabilities(), ensure_ascii=False, indent=2))


def require_tmdb_live() -> Dict[str, Any]:
    capability = tmdb_capability()
    if not capability["ready"]:
        raise unittest.SkipTest(str(capability["reason"] or "TMDb live disabled."))
    return capability


def require_probe_live() -> Dict[str, Any]:
    capability = probe_capability()
    if not capability["enabled"]:
        raise unittest.SkipTest(str(capability["reason"] or "Probe live disabled."))
    return capability


def require_pywebview_live() -> Dict[str, Any]:
    capability = pywebview_capability()
    if not capability["ready"]:
        raise unittest.SkipTest(str(capability["reason"] or "pywebview live disabled."))
    return capability


def ensure_sample_media(output_dir: Path) -> Path:
    sample_override = env_path("CINESORT_MEDIA_SAMPLE_PATH")
    if sample_override is not None:
        if not sample_override.exists() or not sample_override.is_file():
            raise RuntimeError(f"CINESORT_MEDIA_SAMPLE_PATH invalide: {sample_override}")
        return sample_override

    ffmpeg_path = str(shutil.which("ffmpeg") or "").strip()
    if not ffmpeg_path:
        raise RuntimeError("CINESORT_MEDIA_SAMPLE_PATH absent et ffmpeg introuvable dans PATH.")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "probe_live_sample.mp4"
    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=320x180:rate=24",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000",
        "-t",
        "1",
        "-shortest",
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        str(output_path),
    ]
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30.0,
        **_subprocess_platform_kwargs(),
    )
    if completed.returncode != 0:
        details = str(completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"Generation du media temporaire impossible via ffmpeg: {details[:400]}")
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise RuntimeError("Le media temporaire genere par ffmpeg est introuvable ou vide.")
    return output_path
