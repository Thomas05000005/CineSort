from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from cinesort.infra.probe._retry_backoff import retry_with_backoff
from cinesort.infra.probe.constants import VERSION_PROBE_TIMEOUT_S
from cinesort.infra.subprocess_safety import tracked_run

logger = logging.getLogger(__name__)

RunnerFn = Callable[[List[str], float], Tuple[int, str, str]]
WhichFn = Callable[[str], Optional[str]]

# Cf issue #71 + AUDIT 2026-06-10 : whitelist des noms de binaires acceptes par
# outil. Source de verite unique (tools_manager.validate_tool_path l'importe).
# Empeche d'executer n'importe quel .exe configure via les settings (calc.exe,
# cmd.exe, malware.exe...) avec des arguments de probe.
EXPECTED_BINARY_NAMES: Dict[str, frozenset] = {
    "ffprobe": frozenset({"ffprobe.exe", "ffprobe"}),
    "mediainfo": frozenset({"mediainfo.exe", "mediainfo", "MediaInfo.exe"}),
}


def _binary_name_allowed(tool_name: str, path: str) -> bool:
    """True si le nom de fichier de `path` correspond a l'outil attendu."""
    expected = EXPECTED_BINARY_NAMES.get(str(tool_name or "").strip().lower())
    if not expected:
        # Outil hors whitelist connue : on n'autorise pas un chemin explicite
        # arbitraire (fail-closed).
        return False
    try:
        name = Path(path).name.lower()
    except (OSError, ValueError):
        return False
    return name in {n.lower() for n in expected}


def safe_tool_path(explicit_value: str, tool_name: str) -> str:
    """Resout le chemin d'un binaire de probe AVANT exec, en appliquant la MEME
    garde whitelist que `get_tools_status` (R8-032, filet F3).

    Source de verite unique : `_resolve_tool_path` + `_binary_name_allowed`. Un
    chemin explicite n'est retourne que si (a) il existe sur disque ET (b) son
    nom de fichier est dans `EXPECTED_BINARY_NAMES` ; sinon fallback PATH
    (`shutil.which`). Ferme l'asymetrie save/exec : le flux perceptuel executait
    `settings['ffprobe_path']` en argv[0] sans cette garde -> un .exe arbitraire
    (calc.exe, malware.exe...) configure etait execute. L'auto-install legitime
    (nom `ffprobe.exe`) et la config manuelle d'un vrai ffprobe restent valides.
    """
    return _resolve_tool_path(explicit_value, tool_name, shutil.which)


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


def _runner_label(cmd: List[str]) -> str:
    """Extrait un label court (basename de l'exe) pour les logs de retry.

    Pas de dependance domain/app : reste pur infra. Utilise pour rendre les
    messages "ffprobe retry attempt 2/4" lisibles plutot que "probe retry...".
    """
    if not cmd:
        return "probe"
    first = str(cmd[0])
    for sep in ("\\", "/"):
        if sep in first:
            first = first.rsplit(sep, 1)[-1]
    lower = first.lower()
    for ext in (".exe", ".cmd", ".bat"):
        if lower.endswith(ext):
            first = first[: -len(ext)]
            break
    return first or "probe"


def _run_once(cmd: List[str], timeout_s: float) -> Tuple[int, str, str]:
    """Execution simple sans retry. Conserve le comportement historique."""
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


def default_runner(cmd: List[str], timeout_s: float) -> Tuple[int, str, str]:
    """Runner avec retry exponentiel sur echec transitoire.

    ITER13 (mecanisme RETRY_BACKOFF) : enveloppe `_run_once` dans
    `retry_with_backoff` pour absorber les pannes transitoires :
    - `subprocess.TimeoutExpired` (NAS lent, gros 4K HEVC)
    - `BrokenPipeError` (pipe ferme abruptement)
    - `OSError` reseau (UNC injoignable transitoire, winerror 121)

    Defaults : 3 retries, backoff 1s/2s/4s/8s plafond. Configurable via env
    `CINESORT_PROBE_RETRY_MAX` (cf `_retry_backoff.py`).

    NB : NE retry PAS sur erreurs deterministes (FileNotFoundError=ENOENT,
    PermissionError=EACCES, subprocess rc!=0) — c'est au caller (backends,
    `get_tools_status`) de decider quoi faire d'un echec final.

    Backward-compatible : meme signature `(cmd, timeout_s) -> (rc, out, err)`.
    """
    label = _runner_label(cmd)
    return retry_with_backoff(
        lambda: _run_once(cmd, timeout_s),
        label=label,
    )


def _resolve_tool_path(explicit_value: str, tool_name: str, which_fn: WhichFn) -> str:
    explicit = str(explicit_value or "").strip()
    if explicit:
        # Fix audit 2026-05-25 (v1.5.5) Vague K : verifier que le path explicit
        # existe sur disque AVANT de l'utiliser. Sinon fallback PATH winget.
        # Sans ce check, un settings.json obsolete (relique d'ancien build)
        # cause 100% des probes en FAILED sans aucun feedback utilisateur :
        # subprocess leve WinError 2 (file not found) sur chaque appel.
        try:
            is_file = Path(explicit).is_file()
        except (OSError, ValueError):
            # Path mal forme (ex: caracteres invalides Windows) -> fallback PATH
            is_file = False
        if is_file:
            # AUDIT 2026-06-10 : valider le NOM du binaire AVANT de retourner un
            # chemin qui sera ensuite execute ([path, -version] puis args probe).
            # Le whitelist n'etait applique que dans validate_tool_path() ; un
            # enregistrement via le save_settings generique le contournait et
            # get_tools_status() executait alors n'importe quel .exe configure.
            if _binary_name_allowed(tool_name, explicit):
                return explicit
            logger.warning(
                "Tool %s configure (%s) : nom de binaire non whiteliste, ignore (fallback PATH)",
                tool_name,
                Path(explicit).name,
            )
        else:
            logger.warning(
                "Tool %s configure (%s) introuvable sur disque, fallback PATH",
                tool_name,
                explicit,
            )
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
        if tool_name == "mediainfo":
            rc, out, err = runner([path, "--Version"], VERSION_PROBE_TIMEOUT_S)
        else:
            rc, out, err = runner([path, "-version"], VERSION_PROBE_TIMEOUT_S)
        if rc == 0:
            return _extract_first_non_empty_line(out)
        return _extract_first_non_empty_line(err)
    # `subprocess.TimeoutExpired` DOIT etre nomme : il derive de `SubprocessError`,
    # donc d'`Exception`, et PAS d'`OSError` — meme piege que la regle 4 du
    # CLAUDE.md sur `sqlite3.Error`. Or c'est `default_runner`, dans ce meme
    # fichier, qui sert ce `runner` : `retry_with_backoff` classe le timeout
    # transitoire, le rejoue, puis le RE-LEVE tel quel une fois les tentatives
    # epuisees — sa propre docstring le dit.
    #
    # Sans cette entree, l'exception traversait `get_tools_status`,
    # `ProbeService._get_tools_cached` puis `probe_file`, et ses appelants ne la
    # retenaient pas non plus (`probe_support.recheck_probe_for_row` et
    # `app/runtime_probe_check` attrapent `(OSError, KeyError, TypeError,
    # ValueError)`). ITER13 avait ferme cette famille sur la sonde de FICHIER
    # (`ffprobe_backend`, `mediainfo_backend`, branche parallele de
    # `probe_files`) ; la sonde de VERSION etait restee dehors.
    except (OSError, subprocess.TimeoutExpired):
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
