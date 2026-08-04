"""R8-081 / F-TEST-01 — preuve de FALSIFIABILITE rejouable du test repare.

Le test `tests/test_auto_install.py::TestGetToolsDir::test_creates_dir` verifie que
`get_tools_dir()` CREE le dossier tools/ retourne (assertTrue(d.exists())). L'ancienne
assertion `assertTrue(d.exists() or True)` etait tautologique (toujours vraie).

Ce script prouve, SANS editer le code de prod, que la NOUVELLE assertion est falsifiable :
  ETAT 1 (vert honnete)  : get_tools_dir reel -> dossier cree -> d.exists() True  -> PASS
  ETAT 2 (rouge si bug)  : get_tools_dir bugge (pas de mkdir, chemin frais) -> d.exists() False -> l'assert LEVE
  ETAT 3 (vert apres fix): on restaure -> PASS

(En complement, la preuve "live" a aussi ete faite en plantant/revertant la vraie
ligne auto_install.py:169 ; cf docs/internal/r8/R8_CORRECTIONS.md, etats capturés.)

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_081_falsifiability.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import cinesort.infra.probe.auto_install as ai

REAL = ai.get_tools_dir


def assert_creates_dir() -> None:
    """Replique exacte de l'assertion du test repare (intention reelle)."""
    d = ai.get_tools_dir()
    assert d.exists(), "get_tools_dir() doit creer le dossier tools/"


def bugged_get_tools_dir() -> Path:
    """Bug simule : retourne un dossier frais SANS le creer (mkdir supprime)."""
    return Path(tempfile.gettempdir()) / "tools_R8PLANT_inexistant_xyz"


def run() -> None:
    results = {}

    # ETAT 1 : vert honnete (get_tools_dir reel)
    try:
        assert_creates_dir()
        results["etat1_vert_honnete"] = "PASS"
    except AssertionError as e:
        results["etat1_vert_honnete"] = f"FAIL (inattendu) : {e}"

    # ETAT 2 : rouge sur bug plante (creation supprimee)
    ai.get_tools_dir = bugged_get_tools_dir
    try:
        assert_creates_dir()
        results["etat2_rouge_sur_bug"] = "PASS (PROBLEME: le test ne detecte PAS le bug -> non falsifiable)"
    except AssertionError as e:
        results["etat2_rouge_sur_bug"] = f"RED OK (assertion levee) : {e}"
    finally:
        ai.get_tools_dir = REAL

    # ETAT 3 : vert apres restauration
    try:
        assert_creates_dir()
        results["etat3_vert_apres_revert"] = "PASS"
    except AssertionError as e:
        results["etat3_vert_apres_revert"] = f"FAIL (inattendu) : {e}"

    print("=== R8-081 FALSIFIABILITE (rejouable, sans edit prod) ===")
    for k, v in results.items():
        print(f"  {k:24s}: {v}")

    falsifiable = (
        results["etat1_vert_honnete"] == "PASS"
        and results["etat2_rouge_sur_bug"].startswith("RED OK")
        and results["etat3_vert_apres_revert"] == "PASS"
    )
    print(
        f"\nVERDICT : {'FALSIFIABLE PROUVEE (vert/rouge/vert)' if falsifiable else 'NON falsifiable -> instrument suspect'}"
    )


if __name__ == "__main__":
    run()
