"""Utilitaire pour lancer CineSort en mode E2E."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def start_app(mode: str = "dev", cdp_port: int = 9222) -> subprocess.Popen:
    """Lance CineSort et attend que le port CDP soit ouvert.

    mode: "dev" (python app.py) ou "exe" (dist/CineSort.exe)
    """
    env = os.environ.copy()
    env["CINESORT_E2E"] = "1"
    env["CINESORT_CDP_PORT"] = str(cdp_port)

    if mode == "exe":
        exe = PROJECT_ROOT / "dist" / "CineSort.exe"
        cmd = [str(exe)]
    else:
        cmd = [sys.executable, "app.py"]

    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Attendre le port CDP
    wait_for_port("localhost", cdp_port, timeout_s=30)
    return proc


def wait_for_port(host: str, port: int, timeout_s: int = 30) -> bool:
    """Attend qu'un port TCP soit ouvert. Retourne True si ouvert."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            s = socket.create_connection((host, port), timeout=1)
            s.close()
            return True
        except (ConnectionRefusedError, OSError):
            time.sleep(1)
    return False
