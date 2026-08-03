"""Runner ffmpeg pour l'analyse perceptuelle — binaire et texte.

Les fonctions `run_ffmpeg_*` utilisent `tracked_run()` (cf
`cinesort.infra.subprocess_safety`) afin de garantir que les processus
ffmpeg.exe sont tues + wait meme en cas d'exception non rattrapee remontant
depuis l'analyse perceptuelle. Sans ce wrapper, un crash mid-analysis
laissait des zombies ffmpeg sur Windows (finding R5-CRASH-2 + R4-PERC-4).

Limitation : SIGKILL externe (Task Manager > End Process force, kill -9 sur
Linux) n'est PAS gere — l'OS tue le parent immediatement, sans laisser
executer le cleanup. Cf docstring de `subprocess_safety` pour le detail.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from cinesort.domain._runners import tracked_run

logger = logging.getLogger(__name__)


def _runner_platform_kwargs() -> dict:
    """Kwargs subprocess Windows pour eviter le flash console."""
    if os.name != "nt":
        return {}
    kwargs: dict = {"creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0))}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
    si.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
    kwargs["startupinfo"] = si
    return kwargs


# R8-033 (F3) : noms de binaire ffprobe attendus. Defini localement car
# domain/ ne peut pas importer infra/probe/tooling (contrat domain_pure).
# Coherent avec EXPECTED_BINARY_NAMES['ffprobe'] (infra/probe/tooling.py).
_ALLOWED_FFPROBE_NAMES = frozenset({"ffprobe.exe", "ffprobe"})


def resolve_ffmpeg_path(ffprobe_path: str) -> Optional[str]:
    """Trouve ffmpeg comme sibling de ffprobe (meme dossier, meme package).

    R8-033 (F3) : ne derive le sibling QUE si `ffprobe_path` porte un nom de
    binaire ffprobe attendu. Sinon (chemin arbitraire / non-ffprobe), on ne fait
    PAS confiance au dossier parent et on retombe sur le ffmpeg du PATH systeme —
    evite d'executer le `ffmpeg.exe` voisin d'un binaire arbitraire configure.
    """
    if not ffprobe_path:
        return shutil.which("ffmpeg")
    try:
        probe_name = Path(ffprobe_path).name.lower()
    except (OSError, ValueError):
        return shutil.which("ffmpeg")
    if probe_name not in _ALLOWED_FFPROBE_NAMES:
        return shutil.which("ffmpeg")
    parent = Path(ffprobe_path).parent
    for name in ("ffmpeg.exe", "ffmpeg"):
        candidate = parent / name
        if candidate.is_file():
            return str(candidate)
    return shutil.which("ffmpeg")


def run_ffmpeg_binary(cmd: List[str], timeout_s: float) -> Tuple[int, bytes, str]:
    """Execute ffmpeg et retourne stdout brut (bytes) + stderr texte.

    Utilise `tracked_run` : le child ffmpeg est garanti d'etre tue + wait
    en cas d'exception remontante (TimeoutExpired ou autre).
    """
    logger.debug("ffmpeg: binary %s (timeout=%ds)", cmd[0] if cmd else "?", int(timeout_s))
    platform_kwargs = _runner_platform_kwargs()
    cp = tracked_run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=max(1.0, float(timeout_s)),
        **platform_kwargs,
    )
    stderr_text = cp.stderr.decode("utf-8", errors="replace") if cp.stderr else ""
    return int(cp.returncode), cp.stdout or b"", stderr_text


def run_ffmpeg_text(cmd: List[str], timeout_s: float) -> Tuple[int, str, str]:
    """Execute ffmpeg et retourne stdout + stderr en texte.

    Utilise `tracked_run` : le child ffmpeg est garanti d'etre tue + wait
    en cas d'exception remontante (TimeoutExpired ou autre).
    """
    logger.debug("ffmpeg: text %s (timeout=%ds)", cmd[0] if cmd else "?", int(timeout_s))
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
