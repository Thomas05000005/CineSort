"""PyInstaller runtime hook: console attach for --api standalone mode.

This hook runs BEFORE app.py. It provides:
- AllocConsole for --api standalone mode so logs are visible in the console.

Le splash screen est desormais gere par pywebview dans app.py (splash HTML).
"""

from __future__ import annotations

import ctypes
import sys


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


_attach_console_if_api_mode()
