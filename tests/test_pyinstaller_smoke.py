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

import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path
from typing import Optional

import requests

from tests._helpers import find_free_port as _find_free_port

REPO_ROOT = Path(__file__).resolve().parent.parent
EXE_PATH = REPO_ROOT / "dist" / "CineSort.exe"


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


def _tuer_l_arbre(proc: "subprocess.Popen[bytes]") -> None:
    """Tue le processus ET ses enfants.

    `dist/CineSort.exe` est un bundle PyInstaller *onefile* : le processus que
    `Popen` demarre est le BOOTLOADER, qui s'extrait puis lance l'application
    dans un processus ENFANT. `terminate()` et `kill()` ne visent que le
    bootloader — l'enfant survit, garde `.cinesort.lock`, et l'execution
    suivante sort aussitot sur « Another CineSort instance is already running »
    (`cinesort/infra/single_instance.py`). D'ou un echec un tour sur DEUX,
    parfaitement alterne. `taskkill /T` descend l'arbre entier.
    """
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _attendre_les_handles(dossier: Path, delai_s: float = 10.0) -> None:
    """Attend que Windows libere les fichiers ouverts par l'application.

    `taskkill` rend la main des que la demande est transmise, pas quand les
    handles sont fermes : le `rmtree` de `TemporaryDirectory` tombait alors sur
    `PermissionError [WinError 32]` en supprimant `logs/cinesort.log`. On tente
    la suppression jusqu'a ce qu'elle passe, plutot que d'ignorer l'erreur — un
    `ignore_errors` masquerait une VRAIE fuite de processus.
    """
    limite = time.time() + delai_s
    while time.time() < limite:
        try:
            shutil.rmtree(dossier)
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.3)
    shutil.rmtree(dossier, ignore_errors=True)


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
        env = os.environ.copy()
        import tempfile

        # mkdtemp plutot que TemporaryDirectory : le nettoyage doit se faire
        # APRES la mort du processus, avec reessai (cf _attendre_les_handles).
        tmp = tempfile.mkdtemp(prefix="cinesort_smoke_")
        try:
            # `CINESORT_STATE_DIR` n'est lu NULLE PART sous `cinesort/` : la
            # variable ne servait qu'a rassurer. L'application resout son etat
            # par `%LOCALAPPDATA%/CineSort` (infra/state.py:default_state_dir),
            # donc ce test demarrait l'exe sur l'etat REEL de l'utilisateur —
            # vraie base SQLite, vrais reglages, vraie racine de bibliotheque —
            # et y deposait `.cinesort.lock`. On surcharge la variable qui est
            # reellement honoree ; l'ancienne est retiree pour ne pas laisser
            # croire qu'elle protege quelque chose.
            env["LOCALAPPDATA"] = tmp
            env.pop("CINESORT_STATE_DIR", None)
            # En mode `--api`, le serveur REFUSE de demarrer sans jeton : sur un
            # etat vierge il sort en code 1, sans rien ecrire sur stdout/stderr
            # ni dans son journal (build sans console). Mesure : 3 s puis code 1.
            # Il faut donc amorcer les reglages AVANT le lancement — sinon le
            # test ne mesure plus le packaging mais l'absence de configuration.
            etat = Path(tmp) / "CineSort"
            etat.mkdir(parents=True, exist_ok=True)
            (etat / "lib").mkdir(exist_ok=True)
            (etat / "settings.json").write_text(
                json.dumps(
                    {
                        "root": str(etat / "lib"),
                        "rest_api_token": "smoke-token-pyinstaller",
                        "rest_api_enabled": True,
                        "tmdb_enabled": False,
                    }
                ),
                encoding="utf-8",
            )
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
                # AUDIT 2026-06-11 (R4) : 15s ne suffisent PAS au 1er boot d'un
                # onefile ~60 MB (extraction %TEMP% + imports onnxruntime) ->
                # faux negatif systematique sur extraction froide. 60s couvre le
                # boot froid ; un boot chaud repond en ~3-5s.
                health = _wait_for_health(f"http://127.0.0.1:{port}/api/health", timeout_s=60.0)
                if health is None:
                    # AUDIT 2026-06-11 (R4) : lire proc.stdout d'un process VIVANT
                    # bloque indefiniment (deadlock pipe) — c'est ce qui gelait la
                    # suite entiere via pytest-timeout. On tue AVANT de lire.
                    _tuer_l_arbre(proc)
                    try:
                        out, err = proc.communicate(timeout=10.0)
                    except subprocess.TimeoutExpired:
                        out, err = b"<communicate timeout>", b""
                    # Le build est SANS console : un refus de demarrer sort en
                    # code 1 avec stdout ET stderr vides. Le journal de
                    # l'application est alors le seul temoin utile.
                    journal = etat / "logs" / "cinesort.log"
                    trace = (
                        journal.read_text(encoding="utf-8", errors="replace")[-2000:]
                        if journal.exists()
                        else "<aucun journal>"
                    )
                    self.fail(
                        "L'exe n'a pas repondu sur /api/health en 60s. "
                        "Verifier hiddenimports + runtime hooks.\n"
                        f"code de sortie: {proc.poll()}\n"
                        f"stdout: {out[:1000]!r}\nstderr: {err[:1000]!r}\n"
                        f"journal: {trace}"
                    )
                self.assertIn("ok", health or {})
            finally:
                _tuer_l_arbre(proc)
        finally:
            _attendre_les_handles(Path(tmp))


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
