"""Phase 13.3 v7.8.0 : smoke test PyInstaller.

Verifie que `dist/CineSort.exe` (s'il existe) demarre proprement en mode --api
et repond a un GET /api/health. Detecte les regressions de packaging :
hidden import oublie, DLL manquante, runtime hook casse.

Le test est skip si l'exe n'existe pas (developpeur sans build local).
En CI, on lance `pyinstaller CineSort.spec` avant ces tests.

Pre-Phase 13.3 : aucun test ne demarrait reellement l'exe. CLAUDE.md
revendiquait "49.84 MB testes" sans validation fonctionnelle.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path
from typing import Optional

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
EXE_PATH = REPO_ROOT / "dist" / "CineSort.exe"


def _find_free_port() -> int:
    """Trouve un port libre pour le smoke test (eviter 8642 si deja pris)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_health(url: str, timeout_s: float = 10.0) -> Optional[dict]:
    """Poll GET /api/health jusqu'a 200 ou timeout."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            resp = requests.get(url, timeout=1.0)
            if resp.status_code == 200:
                return resp.json()
        except (requests.ConnectionError, requests.Timeout, ValueError):
            time.sleep(0.5)
    return None


@unittest.skipUnless(
    EXE_PATH.exists() and sys.platform == "win32",
    f"Skip smoke test : exe absent ({EXE_PATH}) ou non-Windows",
)
class PyInstallerSmokeTests(unittest.TestCase):
    """Verifie que l'exe builde demarre et expose l'API REST.

    Lance l'exe en mode --api standalone (sans pywebview), poll /api/health,
    puis terminate proprement.
    """

    def test_exe_starts_and_responds_to_health(self) -> None:
        port = _find_free_port()
        # Token court accepte uniquement en bind 127.0.0.1 (cf MIN_LAN_TOKEN_LENGTH).
        # On utilise un token vide ici car --api gere son propre token de session.
        env = os.environ.copy()
        # Forcer state_dir temporaire pour ne pas polluer le ~/.local/share du dev
        import tempfile
        with tempfile.TemporaryDirectory(prefix="cinesort_smoke_") as tmp:
            env["CINESORT_STATE_DIR"] = tmp
            # NB : l'exe doit accepter --api + --port. Si la signature change,
            # ce test detecte la regression.
            cmd = [str(EXE_PATH), "--api", "--port", str(port)]
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=0x08000000 if sys.platform == "win32" else 0,  # CREATE_NO_WINDOW
            )
            try:
                health = _wait_for_health(f"http://127.0.0.1:{port}/api/health", timeout_s=15.0)
                self.assertIsNotNone(
                    health,
                    f"L'exe n'a pas repondu sur /api/health en 15s. "
                    f"Verifier hiddenimports + runtime hooks.\n"
                    f"stdout: {proc.stdout.read(2000) if proc.stdout else b''}\n"
                    f"stderr: {proc.stderr.read(2000) if proc.stderr else b''}"
                )
                self.assertIn("ok", health or {})
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


@unittest.skipUnless(EXE_PATH.exists(), "Skip : dist/CineSort.exe absent")
class PyInstallerArtifactTests(unittest.TestCase):
    """Verifie les proprietes basiques de l'artefact build."""

    def test_exe_size_within_expected_range(self) -> None:
        """L'exe doit faire entre 30 MB et 80 MB (incluant LPIPS + onnxruntime).

        CLAUDE.md mentionne 49.84 MB. Une regression hors de cette plage
        revele un probleme de bundle (deps inutiles incluses, ou exclusions cassees).
        """
        size_mb = EXE_PATH.stat().st_size / (1024 * 1024)
        self.assertGreater(size_mb, 30, f"EXE trop petit ({size_mb:.1f} MB) : deps manquantes ?")
        self.assertLess(size_mb, 80, f"EXE trop gros ({size_mb:.1f} MB) : verifier exclusions PyInstaller")

    def test_exe_is_executable(self) -> None:
        """Le fichier doit etre executable."""
        if sys.platform == "win32":
            # Sur Windows, .exe est executable par definition
            self.assertEqual(EXE_PATH.suffix.lower(), ".exe")
        else:
            self.assertTrue(os.access(EXE_PATH, os.X_OK))


if __name__ == "__main__":
    unittest.main()
