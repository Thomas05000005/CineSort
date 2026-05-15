"""Tests pour les fixtures partagees dans tests/conftest.py (issue #86 phase 1).

Verifie que les fixtures se chargent et fonctionnent comme attendu. Permet aussi
de servir de documentation executable pour les futurs migrators.
"""

from __future__ import annotations

from pathlib import Path


def test_tmp_state_dir_provides_root_and_state_dir(tmp_state_dir) -> None:
    """tmp_state_dir cree 2 dirs et expose les paths."""
    assert tmp_state_dir.base.is_dir()
    assert tmp_state_dir.root.is_dir()
    assert tmp_state_dir.state_dir.is_dir()
    # base est le parent de root et state_dir
    assert tmp_state_dir.root.parent == tmp_state_dir.base
    assert tmp_state_dir.state_dir.parent == tmp_state_dir.base


def test_tmp_state_dir_isolated_per_test(tmp_state_dir, tmp_path: Path) -> None:
    """Chaque test recoit un tmp_path/tmp_state_dir different."""
    assert tmp_state_dir.base == tmp_path


def test_free_port_returns_int(free_port: int) -> None:
    """free_port retourne un port TCP libre [1024, 65535]."""
    assert isinstance(free_port, int)
    assert 1024 <= free_port <= 65535


def test_create_movie_file_writes_video(tmp_state_dir, create_movie_file) -> None:
    """create_movie_file cree les dirs parents et ecrit la taille demandee."""
    p = tmp_state_dir.root / "Inception.2010" / "Inception.2010.mkv"
    create_movie_file(p, size=4096)
    assert p.is_file()
    assert p.stat().st_size == 4096


def test_create_movie_file_default_size(tmp_state_dir, create_movie_file) -> None:
    """Defaut size=2048 bytes."""
    p = tmp_state_dir.root / "Matrix.1999" / "v.mkv"
    create_movie_file(p)
    assert p.stat().st_size == 2048


def test_wait_run_terminal_returns_status_dict(wait_run_terminal) -> None:
    """wait_run_terminal accepte un api-like object et un run_id, poll get_status.

    Issue #84 PR 10 : la fixture utilise maintenant api.run.get_status (facade).
    Le FakeApi expose un faux attribut .run avec get_status pour respecter ce contrat.
    """

    class FakeRunFacade:
        def __init__(self, parent):
            self._parent = parent

        def get_status(self, run_id, idx):
            self._parent.calls += 1
            if self._parent.calls < 3:
                return {"done": False, "status": "RUNNING"}
            return {"done": True, "status": "DONE", "run_id": run_id}

    class FakeApi:
        def __init__(self) -> None:
            self.calls = 0
            self.run = FakeRunFacade(self)

    api = FakeApi()
    out = wait_run_terminal(api, "test-run-id", timeout_s=2.0)
    assert out["done"] is True
    assert out["status"] == "DONE"
    assert out["run_id"] == "test-run-id"
    # Au moins 3 polls (False, False, True)
    assert api.calls >= 3


def test_wait_run_terminal_raises_on_timeout(wait_run_terminal) -> None:
    """Si done ne devient jamais True, AssertionError avec dernier status."""

    class StuckRunFacade:
        def get_status(self, run_id, idx):
            return {"done": False, "status": "STUCK"}

    class StuckApi:
        def __init__(self) -> None:
            self.run = StuckRunFacade()

    import pytest

    with pytest.raises(AssertionError, match="Timeout"):
        wait_run_terminal(StuckApi(), "r", timeout_s=0.1)
