"""tests/conftest.py — Fixtures pytest partagees pour la suite CineSort.

Cf issue #86 (audit-2026-05-12:h4i6) — phase 1 :
- Aucune migration des 19 fichiers existants dans cette PR (effort 10-14h estime).
- Cette fondation expose les fixtures les plus reutilisables pour que les
  futurs tests (et migrations progressives) puissent les utiliser sans
  redupliquer le boilerplate.

Helpers duplicates a migrer ulterieurement :
- `_create_file` : 8-19 fichiers
- `_wait_done`/`_wait_terminal` : 8-12 fichiers
- `_find_free_port` : 5 fichiers
- `_ConcurrencyBase setUp/tearDown` : ~10 fichiers

Pattern d'usage dans un nouveau test pytest :

    def test_foo(tmp_state_dir, create_movie_file):
        create_movie_file(tmp_state_dir.root / "Inception.2010" / "video.mkv")
        ...

Les tests existants en `unittest.TestCase` peuvent aussi consommer les
fixtures via la signature de la methode de test (pytest l'accepte) :

    class MyTests(unittest.TestCase):
        def test_x(self, tmp_state_dir):
            ...

Sinon, conserver les helpers methode `self._create_file(...)` actuels.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest


# -----------------------------------------------------------------------------
# Datastructures de support
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class TmpStateDirs:
    """Conteneur pour les paths de test : root (films sources), state_dir (BDD)."""

    base: Path
    root: Path
    state_dir: Path


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def tmp_state_dir(tmp_path: Path) -> TmpStateDirs:
    """Cree une paire (root, state_dir) sous le tmp_path pytest.

    Le cleanup est automatique (tmp_path est nettoye par pytest a la fin).
    Remplace le pattern repete dans tous les TestCase :

        self._tmp = tempfile.mkdtemp(prefix="cinesort_X_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir()
        self.state_dir.mkdir()
        # ... tearDown : shutil.rmtree(self._tmp)
    """
    root = tmp_path / "root"
    state_dir = tmp_path / "state"
    root.mkdir()
    state_dir.mkdir()
    return TmpStateDirs(base=tmp_path, root=root, state_dir=state_dir)


@pytest.fixture
def free_port() -> int:
    """Retourne un port TCP libre sur 127.0.0.1.

    Remplace le helper _find_free_port duplique dans 5 fichiers.
    NB : il y a une race condition entre l'obtention du port et l'utilisation
    par le test — pour les serveurs longs-running c'est ok, pour les ports
    "reserve a l'avance" envisager socketserver.TCPServer(0, ...).
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def create_movie_file() -> Callable[[Path, int], None]:
    """Retourne une factory pour creer un fichier video minimal.

    Usage :
        def test_x(tmp_state_dir, create_movie_file):
            create_movie_file(tmp_state_dir.root / "Inception.2010" / "v.mkv")

    Equivalent au _create_file duplique dans 19 fichiers. Defaut size=2048 bytes
    (> MIN_VIDEO_BYTES dans la plupart des configs de test).
    """

    def _factory(path: Path, size: int = 2048) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)

    return _factory


@pytest.fixture
def wait_run_terminal() -> Callable[..., dict]:
    """Retourne un helper pour attendre qu'un run atteigne un etat terminal.

    Usage :
        def test_x(wait_run_terminal):
            status = wait_run_terminal(api, run_id, timeout_s=8.0)
            assert status["status"] == "DONE"

    Remplace le pattern _wait_terminal / _wait_done duplique dans 12+ fichiers.
    Poll non-bloquant (sleep 30ms), fail explicit avec dernier status si timeout.
    """

    def _wait(api: Any, run_id: str, timeout_s: float = 10.0) -> dict:
        deadline = time.monotonic() + float(timeout_s)
        last: dict = {}
        while time.monotonic() < deadline:
            last = api.run.get_status(run_id, 0) or {}
            if last.get("done"):
                return last
            time.sleep(0.03)
        raise AssertionError(f"Timeout {timeout_s}s en attendant run_id={run_id}. Dernier status={last}")

    return _wait
