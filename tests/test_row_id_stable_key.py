"""Non-regression [HIGH-20] : le row_id est la cle des operations DESTRUCTIVES.

Le row_id sert de cle a `by_row` dans apply_core (deplacement des films marques
pour suppression, losers de doublons) et a la table `decisions`. Deux films
distincts partageant un row_id -> l'operation destructive frappe le MAUVAIS film.

L'implementation historique etait `hash((str(folder), video.name)) & 0xFFFFFFFF` :
  - randomisee par PYTHONHASHSEED (non reproductible d'un process a l'autre) ;
  - tronquee a 32 bits -> ~0,3 % de collision anniversaire sur 5 000 films.

Ces tests verrouillent les deux proprietes de la cle : deterministe et pleine
largeur (64 bits). NB : seules les fonctions de production `_plan_item` /
`_plan_tv_episode` sont importees au niveau module — le helper est resolu
paresseusement pour que ces tests ECHOUENT (au lieu de casser a la collecte) sur
le code pre-fix.
"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from cinesort.app.plan_support_replan import _plan_item, _plan_tv_episode

# Nombre de hex chars attendus pour la partie digest : 64 bits = 16.
_EXPECTED_HEX_LEN = 16


def _row_id(prefix: str, folder: Path, video_name: str) -> str:
    """Calcule un row_id via le helper de production (echoue clairement si absent)."""
    import cinesort.app.plan_support_replan as mod

    fn = getattr(mod, "_compute_row_id", None)
    if fn is None:
        pytest.fail(
            "plan_support_replan n'expose pas de calcul de row_id stable "
            "(_compute_row_id) : la cle des operations destructives est encore "
            "un hash() builtin randomise et tronque a 32 bits."
        )
    return fn(prefix, folder, video_name)


def _digest_of(row_id: str) -> str:
    prefix, sep, digest = row_id.partition("|")
    assert prefix and sep, f"row_id sans prefixe : {row_id!r}"
    return digest


def test_row_id_digest_is_full_width_64_bits() -> None:
    """La cle doit exposer 64 bits, pas 32 (troncature = collisions)."""
    digest = _digest_of(_row_id("S", Path("C:/Films/Star Wars (1977)"), "a.mkv"))

    assert len(digest) == _EXPECTED_HEX_LEN, (
        f"digest de {len(digest) * 4} bits ({digest!r}) : une cle d'operation "
        "destructive tronquee collisionne (~0,3 % sur 5 000 films)"
    )
    int(digest, 16)  # doit rester du hex


@pytest.mark.parametrize("prefix", ["S", "C", "T"])
def test_row_id_stable_across_processes(prefix: str) -> None:
    """Deterministe malgre PYTHONHASHSEED : `hash()` builtin ne l'etait pas."""
    prog = textwrap.dedent(
        f"""
        from pathlib import Path
        from cinesort.app.plan_support_replan import _compute_row_id
        print(_compute_row_id({prefix!r}, Path("C:/Films/Star Wars (1977)"), "a.mkv"))
        """
    )
    repo_root = Path(__file__).resolve().parents[1]

    outputs = set()
    for seed in ("0", "1", "7", "random"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        res = subprocess.run(
            [sys.executable, "-c", prog],
            cwd=str(repo_root),
            env=env,
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            pytest.fail(
                "impossible de calculer un row_id stable dans un sous-process "
                f"(PYTHONHASHSEED={seed}) : {res.stderr.strip()[-400:]}"
            )
        outputs.add(res.stdout.strip())

    assert len(outputs) == 1, (
        f"row_id instable d'un process a l'autre : {sorted(outputs)} — les cles "
        "figees dans plan.jsonl ne seraient plus recalculables."
    )


def test_row_id_unique_over_large_library() -> None:
    """Aucune collision sur une bibliotheque realiste (le cas 32 bits en produit)."""
    root = Path("C:/Films")
    seen: dict[str, tuple[str, str]] = {}
    collisions: list[tuple[tuple[str, str], tuple[str, str]]] = []

    for i in range(50_000):
        folder = root / f"Film {i} (2020)"
        name = "movie.mkv"
        rid = _row_id("S", folder, name)
        key = (str(folder), name)
        if rid in seen:
            collisions.append((seen[rid], key))
        seen[rid] = key

    assert not collisions, f"row_id partage par deux films distincts : {collisions[:3]}"


def test_row_id_distinguishes_folder_and_filename_boundary() -> None:
    """Le separateur empeche ('ab','c') et ('a','bc') de coller sur la meme cle."""
    a = _row_id("S", Path("C:/Films/ab"), "c.mkv")
    b = _row_id("S", Path("C:/Films/a"), "bc.mkv")
    assert a != b


def test_row_id_varies_with_prefix_folder_and_name() -> None:
    base = _row_id("S", Path("C:/Films/A (2020)"), "a.mkv")
    assert base != _row_id("C", Path("C:/Films/A (2020)"), "a.mkv")
    assert base != _row_id("S", Path("C:/Films/B (2020)"), "a.mkv")
    assert base != _row_id("S", Path("C:/Films/A (2020)"), "b.mkv")


@pytest.mark.parametrize("fn", [_plan_item, _plan_tv_episode], ids=["film", "tv"])
def test_plan_sites_use_the_stable_key(fn) -> None:
    """Les DEUX sites de calcul passent par le helper, aucun `hash()` tronque."""
    src = inspect.getsource(fn)
    assert "0xFFFFFFFF" not in src, f"{fn.__name__} tronque encore le row_id a 32 bits"
    assert "hash((" not in src, f"{fn.__name__} utilise encore le hash() builtin randomise"
    assert "_compute_row_id(" in src, f"{fn.__name__} ne construit plus le row_id via le helper"
