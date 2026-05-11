from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from cinesort.infra.subprocess_safety import tracked_run

RunnerFn = Callable[[List[str], float], Tuple[int, str, str]]
WhichFn = Callable[[str], Optional[str]]


def _runner_platform_kwargs() -> Dict[str, object]:
    """
    Windows-only subprocess kwargs to avoid console flicker when probing media tools.
    Kept isolated for testability and cross-platform safety.
    """
    if os.name != "nt":
        return {}
    kwargs: Dict[str, object] = {"creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0))}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
    startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
    kwargs["startupinfo"] = startupinfo
    return kwargs


@dataclass(frozen=True)
class ToolStatus:
    name: str
    available: bool
    path: str
    version: str
    message: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "available": bool(self.available),
            "path": self.path,
            "version": self.version,
            "message": self.message,
        }


def default_runner(cmd: List[str], timeout_s: float) -> Tuple[int, str, str]:
    platform_kwargs = _runner_platform_kwargs()
    cp = tracked_run(
        cmd,
        capture_output=True,
        text=True,
        timeout=max(1.0, float(timeout_s)),
        encoding="utf-8",
        errors="replace",
        **platform_kwargs,
    )
    return int(cp.returncode), str(cp.stdout or ""), str(cp.stderr or "")


def _resolve_tool_path(explicit_value: str, tool_name: str, which_fn: WhichFn) -> str:
    explicit = str(explicit_value or "").strip()
    if explicit:
        return explicit
    return str(which_fn(tool_name) or "")


def _extract_first_non_empty_line(text: str) -> str:
    for line in str(text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _probe_version(
    tool_name: str,
    path: str,
    runner: RunnerFn,
) -> str:
    if not path:
        return ""
    try:
        from cinesort.infra.probe.constants import VERSION_PROBE_TIMEOUT_S

        if tool_name == "mediainfo":
            rc, out, err = runner([path, "--Version"], VERSION_PROBE_TIMEOUT_S)
        else:
            rc, out, err = runner([path, "-version"], VERSION_PROBE_TIMEOUT_S)
        if rc == 0:
            return _extract_first_non_empty_line(out)
        return _extract_first_non_empty_line(err)
    except (ImportError, OSError):
        return ""


def get_tools_status(
    *,
    mediainfo_path: str,
    ffprobe_path: str,
    runner: RunnerFn = default_runner,
    which_fn: WhichFn = shutil.which,
) -> Dict[str, ToolStatus]:
    out: Dict[str, ToolStatus] = {}
    mediainfo_bin = _resolve_tool_path(mediainfo_path, "mediainfo", which_fn)
    ffprobe_bin = _resolve_tool_path(ffprobe_path, "ffprobe", which_fn)

    if mediainfo_bin:
        version = _probe_version("mediainfo", mediainfo_bin, runner)
        out["mediainfo"] = ToolStatus(
            name="mediainfo",
            available=True,
            path=mediainfo_bin,
            version=version,
            message="MediaInfo detecte." if version else "MediaInfo detecte (version non lue).",
        )
    else:
        out["mediainfo"] = ToolStatus(
            name="mediainfo",
            available=False,
            path="",
            version="",
            message="MediaInfo manquant (chemin non configure et introuvable dans PATH).",
        )

    if ffprobe_bin:
        version = _probe_version("ffprobe", ffprobe_bin, runner)
        out["ffprobe"] = ToolStatus(
            name="ffprobe",
            available=True,
            path=ffprobe_bin,
            version=version,
            message="ffprobe detecte." if version else "ffprobe detecte (version non lue).",
        )
    else:
        out["ffprobe"] = ToolStatus(
            name="ffprobe",
            available=False,
            path="",
            version="",
            message="ffprobe manquant (chemin non configure et introuvable dans PATH).",
        )

    return out
