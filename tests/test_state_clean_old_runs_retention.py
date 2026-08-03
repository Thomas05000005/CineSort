"""Gardes unitaires de la retention-runs `infra.state.clean_old_runs`.

Trois invariants, chacun avec son test dedie (mutation individuelle possible) :

1. issue #609 (PERTE DE DONNEES) — le classement « les N plus recents a garder »
   se fait sur la DATE DE MODIFICATION, pas sur le NOM du run_dir. Les run_dirs
   s'appellent `tri_films_{run_id}` et `run_id` a deux formats acceptes par
   `normalize_or_generate_run_id` : `YYYYMMDD_HHMMSS_NNN` et le fallback
   `uuid4().hex`. Des que les deux coexistent, l'ordre lexicographique n'est
   plus chronologique et la retention supprime des runs RECENTS.

2. un run_dir qui disparait entre `iterdir()` et `stat()` (course reelle : un
   autre process purge en meme temps) ne doit pas faire exploser tout le
   nettoyage — l'entree vaut `0.0` et la purge continue.

3. R8-002 (PERTE DE DONNEES) — `runs/_preserved_review/` est le coffre des
   quarantaines NON REVUES sauvees de la retention : il est exclu du classement
   et n'est donc JAMAIS lui-meme candidat a la purge.

Ces tests n'inspectent aucune chaine de code source : ils appellent la vraie
fonction sur une arborescence jetable et observent ce qui reste sur disque.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from cinesort.infra import state as state_mod

# Un instant de reference stable, puis des offsets explicites : aucun test ne
# depend de la resolution mtime du systeme de fichiers ni de l'ordre de creation.
_BASE_MTIME = 1_700_000_000.0


def _make_run(runs: Path, name: str, *, age_seconds: float) -> Path:
    """Cree `runs/<name>` avec une mtime deterministe (`age_seconds` dans le passe)."""
    d = runs / name
    d.mkdir(parents=True, exist_ok=True)
    ts = _BASE_MTIME - age_seconds
    os.utime(d, (ts, ts))
    return d


def test_clean_old_runs_keeps_newest_by_mtime_when_names_sort_the_other_way(
    tmp_path: Path,
) -> None:
    """Issue #609 : formats mixtes -> le nom ment, la mtime dit vrai.

    `f3a9...` (uuid4().hex) trie APRES `20260803_...` en lexicographique
    decroissant, alors qu'il est BEAUCOUP plus vieux. Un tri par nom garderait
    l'uuid et detruirait les runs frais.
    """
    state_dir = tmp_path / "state"
    runs = state_dir / "runs"
    runs.mkdir(parents=True)

    # Vieux runs au format uuid4().hex, dont le premier caractere est une lettre
    # (> tout chiffre en ASCII), donc premiers d'un tri par nom decroissant.
    stale_uuid_a = _make_run(runs, "tri_films_f3a9c1d2e4b5a6978817263544556677", age_seconds=90_000)
    stale_uuid_b = _make_run(runs, "tri_films_e1b2c3d4e5f60718293a4b5c6d7e8f90", age_seconds=80_000)
    # Runs recents au format horodate, qui commencent par un chiffre.
    fresh_ts_a = _make_run(runs, "tri_films_20260803_101500_001", age_seconds=20)
    fresh_ts_b = _make_run(runs, "tri_films_20260803_101500_002", age_seconds=10)

    state_mod.clean_old_runs(state_dir, keep_last=2)

    assert fresh_ts_a.is_dir(), "run recent supprime : la retention n'a pas trie par mtime"
    assert fresh_ts_b.is_dir(), "run recent supprime : la retention n'a pas trie par mtime"
    assert not stale_uuid_a.exists(), "vieux run uuid conserve a la place d'un run recent"
    assert not stale_uuid_b.exists(), "vieux run uuid conserve a la place d'un run recent"


def test_clean_old_runs_survives_run_dir_vanishing_between_iterdir_and_stat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Course reelle : un run_dir disparait apres le filtrage, avant le `stat()`.

    On reproduit la fenetre TOCTOU en supprimant le dossier au moment exact ou
    `clean_old_runs` verifie `d.is_dir()` — donc avant que la cle de tri ne
    l'interroge. Sans le repli `OSError -> 0.0`, l'exception remonte de la
    fonction de tri et AUCUN vieux run n'est purge.
    """
    state_dir = tmp_path / "state"
    runs = state_dir / "runs"
    runs.mkdir(parents=True)

    vanishing = _make_run(runs, "tri_films_20260803_090000_001", age_seconds=50_000)
    stale = _make_run(runs, "tri_films_20260803_093000_002", age_seconds=40_000)
    fresh = _make_run(runs, "tri_films_20260803_100000_003", age_seconds=10)

    real_is_dir = Path.is_dir

    def _is_dir_then_vanish(self: Path, *args: object, **kwargs: object) -> bool:
        result = real_is_dir(self, *args, **kwargs)  # type: ignore[arg-type]
        if result and os.fspath(self) == os.fspath(vanishing):
            shutil.rmtree(vanishing, ignore_errors=True)
        return result

    monkeypatch.setattr(Path, "is_dir", _is_dir_then_vanish)

    state_mod.clean_old_runs(state_dir, keep_last=1)

    monkeypatch.undo()

    assert fresh.is_dir(), "le run le plus recent doit survivre a la course"
    assert not stale.exists(), "la purge s'est arretee sur le run_dir disparu"
    assert not vanishing.exists()


def test_clean_old_runs_never_purges_the_preserved_review_vault(tmp_path: Path) -> None:
    """R8-002 : `runs/_preserved_review/` est hors retention, quelle que soit sa mtime.

    On lui donne volontairement la mtime la PLUS ANCIENNE : s'il entrait dans le
    classement, il serait le premier candidat a `shutil.rmtree` et les originaux
    quarantines non revus seraient perdus.
    """
    state_dir = tmp_path / "state"
    runs = state_dir / "runs"
    runs.mkdir(parents=True)

    vault = _make_run(runs, state_mod._PRESERVED_REVIEW_DIRNAME, age_seconds=999_999)
    hostage = vault / "tri_films_20260101_000000_001" / "conflict"
    hostage.mkdir(parents=True)
    (hostage / "Inception.2010.mkv").write_text("original quarantine", encoding="utf-8")
    os.utime(vault, (_BASE_MTIME - 999_999, _BASE_MTIME - 999_999))

    stale = _make_run(runs, "tri_films_20260803_090000_001", age_seconds=50_000)
    fresh = _make_run(runs, "tri_films_20260803_100000_002", age_seconds=10)

    state_mod.clean_old_runs(state_dir, keep_last=1)

    assert vault.is_dir(), "le coffre _preserved_review a ete purge (R8-002 perdu)"
    assert (hostage / "Inception.2010.mkv").is_file(), "original quarantine detruit"
    assert fresh.is_dir(), "le coffre a consomme un slot de retention"
    assert not stale.exists()


def test_clean_old_runs_moves_unreviewed_quarantine_before_deleting_the_run(
    tmp_path: Path,
) -> None:
    """R8-002 : un `<run_dir>/_review` non vide est RELOCALISE, jamais detruit."""
    state_dir = tmp_path / "state"
    runs = state_dir / "runs"
    runs.mkdir(parents=True)

    doomed = _make_run(runs, "tri_films_20260803_090000_001", age_seconds=50_000)
    original = doomed / "_review" / "duplicate" / "Heat.1995.mkv"
    original.parent.mkdir(parents=True)
    original.write_text("original quarantine", encoding="utf-8")
    # Ecrire dans le run_dir a rafraichi sa mtime : on la repositionne dans le passe.
    os.utime(doomed, (_BASE_MTIME - 50_000, _BASE_MTIME - 50_000))
    fresh = _make_run(runs, "tri_films_20260803_100000_002", age_seconds=10)

    state_mod.clean_old_runs(state_dir, keep_last=1)

    assert fresh.is_dir()
    assert not doomed.exists()
    rescued = runs / state_mod._PRESERVED_REVIEW_DIRNAME / doomed.name / "duplicate" / "Heat.1995.mkv"
    assert rescued.is_file(), "quarantine non revue detruite par la retention"
    assert rescued.read_text(encoding="utf-8") == "original quarantine"
