#!/usr/bin/env python3
"""Tests E2E niveau 2 : smoke EXE post-build (standalone, hors pytest).

Lance `dist/CineSort.exe` (GUI complete pywebview) et verifie que :
- Le process ne crashe pas immediatement (DLL/import manquant)
- Aucune erreur fatale dans stderr (ImportError/ModuleNotFoundError/DLL)
- Un port HTTP local est ouvert si --api est demande (REST server)

Usage :
    python tests/e2e/smoke_exe.py
    python tests/e2e/smoke_exe.py --api  # active la verif port REST

Exit codes :
    0  succes
    1  EXE absent (skip propre)
    2  process crashe pendant la fenetre d'attente
    3  erreur fatale detectee dans stderr
    4  port HTTP attendu non ouvert

Ce script est INDEPENDANT de pytest (build PyInstaller ~10 min, on ne veut
pas le faire tourner a chaque `pytest tests/`). Il est triggerable :
- localement apres un build local (pyinstaller CineSort.spec)
- en CI via .github/workflows/smoke-exe.yml (workflow_dispatch)
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
EXE_PATH = REPO_ROOT / "dist" / "CineSort.exe"

# Erreurs fatales attendues dans stderr (regex case-insensitive)
FATAL_STDERR_PATTERNS = [
    re.compile(r"\bImportError\b", re.IGNORECASE),
    re.compile(r"\bModuleNotFoundError\b", re.IGNORECASE),
    re.compile(r"DLL load failed", re.IGNORECASE),
    re.compile(r"failed to load", re.IGNORECASE),
    re.compile(r"is not a valid Win32 application", re.IGNORECASE),
]

# Patterns acceptables (warnings non-bloquants des sous-systemes optionnels)
IGNORE_STDERR_PATTERNS = [
    re.compile(r"DeprecationWarning", re.IGNORECASE),
    re.compile(r"FutureWarning", re.IGNORECASE),
]


def _log(msg: str) -> None:
    """Print to stderr to keep stdout reservable for machine-readable output."""
    print(f"[smoke_exe] {msg}", file=sys.stderr, flush=True)


def _port_open(port: int, host: str = "127.0.0.1", timeout_s: float = 0.5) -> bool:
    """Verifie si un port TCP est ouvert (connect succeeds)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout_s)
            return s.connect_ex((host, port)) == 0
    except OSError:
        return False


def _wait_port(port: int, timeout_s: float = 15.0) -> bool:
    """Poll jusqu'a ce qu'un port soit ouvert (max timeout_s)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.2)
    return False


def _scan_local_ports(start: int = 8080, end: int = 9100) -> List[int]:
    """Scanne les ports 127.0.0.1:[start..end] et retourne ceux ouverts."""
    open_ports: List[int] = []
    for port in range(start, end + 1):
        if _port_open(port, timeout_s=0.05):
            open_ports.append(port)
    return open_ports


def _check_stderr_for_fatal(stderr_text: str) -> Optional[str]:
    """Retourne le 1er pattern fatal trouve dans stderr, ou None."""
    for line in stderr_text.splitlines():
        # Skip lines matching ignore patterns
        if any(pat.search(line) for pat in IGNORE_STDERR_PATTERNS):
            continue
        for pat in FATAL_STDERR_PATTERNS:
            if pat.search(line):
                return f"Pattern '{pat.pattern}' matched line: {line.strip()[:200]}"
    return None


def _terminate(proc: subprocess.Popen, *, grace_s: float = 3.0) -> None:
    """Kill propre : SIGTERM -> wait grace_s -> SIGKILL."""
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=grace_s)
    except subprocess.TimeoutExpired:
        _log(f"Process pas termine en {grace_s}s, kill force")
        proc.kill()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            _log("kill() n'a pas pu nettoyer le process")


def run_smoke(*, use_api: bool, wait_s: float = 10.0) -> int:
    """Execute le smoke test. Retourne le code de sortie."""
    if not EXE_PATH.exists():
        _log(f"EXE absent: {EXE_PATH}")
        _log("Build d'abord avec : pyinstaller CineSort.spec --clean --noconfirm")
        return 1

    _log(f"EXE trouve: {EXE_PATH} ({EXE_PATH.stat().st_size // (1024 * 1024)} MB)")

    cmd = [str(EXE_PATH)]
    expected_port: Optional[int] = None

    if use_api:
        # Mode --api : pas de GUI, juste le REST server. Plus simple a verifier en CI.
        expected_port = 8642
        # Trouve un port libre pour ne pas conflit avec une instance existante
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            expected_port = int(s.getsockname()[1])
        cmd.extend(["--api", "--port", str(expected_port)])
        _log(f"Mode --api sur port {expected_port}")
    else:
        _log("Mode GUI complet (pywebview)")

    # Isoler state_dir pour ne pas toucher au home utilisateur
    env = os.environ.copy()
    import json
    import secrets
    import tempfile

    tmpdir = tempfile.mkdtemp(prefix="cinesort_smoke_e2e_")
    env["CINESORT_STATE_DIR"] = tmpdir
    # IMPORTANT : default_state_dir() utilise LOCALAPPDATA, pas
    # CINESORT_STATE_DIR. On force LOCALAPPDATA vers tmpdir/.. pour que
    # le sous-chemin "<LOCALAPPDATA>/CineSort" pointe vers tmpdir.
    local_appdata = Path(tmpdir) / "LocalAppData"
    cinesort_subdir = local_appdata / "CineSort"
    cinesort_subdir.mkdir(parents=True, exist_ok=True)
    env["LOCALAPPDATA"] = str(local_appdata)

    if use_api:
        # En mode --api, le boot exige un rest_api_token dans settings.json.
        # On en cree un fort (>= 32 chars hex) pour passer le MIN_LAN_TOKEN_LENGTH.
        settings_payload = {
            "rest_api_token": secrets.token_hex(24),
            "rest_api_port": expected_port,
        }
        (cinesort_subdir / "settings.json").write_text(json.dumps(settings_payload), encoding="utf-8")
        _log(f"settings.json cree dans {cinesort_subdir} (token genere)")

    creationflags = 0
    if sys.platform == "win32":
        creationflags = 0x08000000  # CREATE_NO_WINDOW

    _log(f"Lancement: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )

    exit_code = 0
    stderr_bytes = b""
    stdout_bytes = b""
    try:
        if expected_port is not None:
            # Wait for port to open (with bounded timeout)
            _log(f"Attente port {expected_port} (max {wait_s}s)...")
            if not _wait_port(expected_port, timeout_s=wait_s):
                _log(f"ECHEC : port {expected_port} pas ouvert apres {wait_s}s")
                # Capture stderr pour diagnostic
                _terminate(proc)
                if proc.stdout:
                    stdout_bytes = proc.stdout.read() or b""
                if proc.stderr:
                    stderr_bytes = proc.stderr.read() or b""
                _log(f"stdout: {stdout_bytes[:2000].decode('utf-8', errors='replace')}")
                _log(f"stderr: {stderr_bytes[:2000].decode('utf-8', errors='replace')}")
                return 4
            _log(f"Port {expected_port} ouvert OK")
        else:
            # Mode GUI : on attend wait_s puis on regarde si le process est encore vivant
            _log(f"Attente {wait_s}s pour boot pywebview...")
            time.sleep(wait_s)

        # Le process doit etre encore vivant
        if proc.poll() is not None:
            _log(f"ECHEC : process termine prematurement avec code {proc.returncode}")
            if proc.stdout:
                stdout_bytes = proc.stdout.read() or b""
            if proc.stderr:
                stderr_bytes = proc.stderr.read() or b""
            _log(f"stdout: {stdout_bytes[:2000].decode('utf-8', errors='replace')}")
            _log(f"stderr: {stderr_bytes[:2000].decode('utf-8', errors='replace')}")
            return 2

        # Scan ports pour info (pywebview peut exposer un debug port si DEBUG=1)
        open_ports = _scan_local_ports()
        if open_ports:
            _log(f"Ports ouverts detectes: {open_ports}")
        else:
            _log("Aucun port HTTP local detecte sur 8080-9100 (normal en mode GUI sans REST)")

        _log("Process vivant et stable OK")

    finally:
        _terminate(proc)
        # Drainage non-bloquant des buffers stdout/stderr via communicate
        # (peut etre vide si on a deja drain en cas d'erreur).
        if (not stdout_bytes) and (not stderr_bytes):
            try:
                out_b, err_b = proc.communicate(timeout=5.0)
                stdout_bytes = out_b or b""
                stderr_bytes = err_b or b""
            except subprocess.TimeoutExpired:
                _log("Drainage stdout/stderr timeout — process pipes encore ouverts")
                proc.kill()
                try:
                    out_b, err_b = proc.communicate(timeout=2.0)
                    stdout_bytes = out_b or b""
                    stderr_bytes = err_b or b""
                except (subprocess.TimeoutExpired, ValueError, OSError):
                    pass
            except (OSError, ValueError):
                pass

    # Check stderr pour erreurs fatales (apres terminate, le buffer est complet)
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")
    if stderr_text.strip():
        fatal = _check_stderr_for_fatal(stderr_text)
        if fatal:
            _log(f"ECHEC : erreur fatale dans stderr : {fatal}")
            _log(f"stderr complet :\n{stderr_text[:3000]}")
            exit_code = 3
        else:
            _log("Aucune erreur fatale dans stderr")
            _log(f"stderr (informationnel, premiers 500 char) :\n{stderr_text[:500]}")
    else:
        _log("stderr vide")

    # Cleanup tmpdir
    try:
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)
    except OSError:
        pass

    if exit_code == 0:
        _log("SUCCES : smoke EXE OK")
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test pour dist/CineSort.exe (niveau 2 E2E)")
    parser.add_argument(
        "--api",
        action="store_true",
        help="Lance l'EXE en mode --api (REST server, plus simple a verifier en CI)",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=10.0,
        help="Secondes d'attente apres lancement (defaut: 10)",
    )
    args = parser.parse_args()

    try:
        return run_smoke(use_api=args.api, wait_s=args.wait)
    except KeyboardInterrupt:
        _log("Interrompu par l'utilisateur")
        return 130


if __name__ == "__main__":
    sys.exit(main())
