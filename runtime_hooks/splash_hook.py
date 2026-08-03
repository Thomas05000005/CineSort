"""PyInstaller runtime hook: console attach for --api standalone mode.

This hook runs BEFORE app.py. It provides:
- AllocConsole for --api standalone mode so logs are visible in the console.

Le splash screen est desormais gere par pywebview dans app.py (splash HTML).
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path


def _attach_console_if_api_mode() -> None:
    """Attach or allocate a console when running in --api mode from a windowed EXE."""
    if "--api" not in sys.argv[1:]:
        return
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    # Try attaching to parent console first (launched from cmd/powershell)
    if not kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
        kernel32.AllocConsole()
    # Reopen stdio so print() works
    sys.stdout = open("CONOUT$", "w", encoding="utf-8")  # noqa: SIM115
    sys.stderr = open("CONOUT$", "w", encoding="utf-8")  # noqa: SIM115


def _enable_debug_via_flag_file() -> None:
    """V-DEBUG 2026-06-08 : active CINESORT_DEBUG=1 si %APPDATA%/CineSort/debug.flag existe.

    Permet de declencher le debug verbose token/auth en prod (binaire dist) sans
    rebuild ni edition de settings.json, simplement en creant un fichier vide.
    Non-intrusif : si le fichier est absent (defaut prod), le mode debug reste OFF.
    Si CINESORT_DEBUG est deja positionne dans l'env, on respecte (setdefault).
    """
    try:
        flag = Path(os.environ.get("APPDATA", "")) / "CineSort" / "debug.flag"
        if flag.is_file():
            os.environ.setdefault("CINESORT_DEBUG", "1")
    except Exception:
        # Best-effort only : ne jamais bloquer le boot pour un probleme de flag.
        pass


_attach_console_if_api_mode()
_enable_debug_via_flag_file()
