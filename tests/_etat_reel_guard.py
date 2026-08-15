"""Garde-fou : la suite ne doit JAMAIS toucher l'etat reel de l'utilisateur.

POURQUOI. `CineSortApi()` sans `state_dir` resout l'etat par
`%LOCALAPPDATA%/CineSort` (`cinesort/infra/state.py:default_state_dir`). C'est
le comportement correct de l'APPLICATION — et un defaut dans un TEST : la vraie
base SQLite de l'utilisateur est ouverte, avec ses vrais reglages et sa vraie
racine de bibliotheque.

MESURE (2026-08-15, sentinelle posee sur le perimetre CI complet). Trois tests
modifiaient l'horodatage de la base reelle a chaque execution :

    tests/test_api_bridge_lot3.py::...::test_apply_logs_warn_if_close_failed...
    tests/test_calibration.py::SubmitFeedbackIntegrationTests::test_invalid_run_id
    tests/test_run_report_export.py::...::test_export_run_report_requires_existing_run

Tous les trois sont des tests de CHEMIN D'ERREUR : ils passent la validation
d'entree, atteignent la couche de persistance, et faute d'etat isole tombent sur
celui de l'utilisateur. Les tests sains du meme fichier passent `state_dir` dans
la charge utile ; ceux-la appellent une methode qui n'en prend pas.

PORTEE. Le depot compte **338** appels `CineSortApi()` nus dans **144** fichiers.
Corriger trois sites laisserait la famille revenir au premier test suivant. La
redirection est donc posee une fois pour toute la session.

CE QUE CE MODULE NE FAIT PAS. Il ne masque pas la dette : il ATTRIBUE. A la fin
de la session il nomme les tests qui ont reellement ecrit dans le bac a sable,
c'est-a-dire ceux qui auraient ecrit chez l'utilisateur. C'est le meme parti que
`tests/_temp_leak_guard.py`, qui redirige `%TEMP%` et COMPTE au lieu d'interdire.

REGLAGE :
  CINESORT_ETAT_GUARD=0   desactive la redirection (pour deboguer le garde
                          lui-meme ; a n'utiliser que sur une machine dont
                          l'etat reel est jetable).
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest

GUARD_ENV = "CINESORT_ETAT_GUARD"
VAR = "LOCALAPPDATA"

_actif = os.environ.get(GUARD_ENV, "1") != "0"
_ancienne_valeur = os.environ.get(VAR)
_bac: Path | None = None
# nodeid -> nombre d'entrees creees dans le bac par ce test
_attribution: dict[str, int] = {}


def _compter(dossier: Path) -> int:
    try:
        return sum(1 for _ in dossier.rglob("*"))
    except OSError:
        return 0


def _demonter() -> None:
    """Restaure la variable et supprime le bac. Idempotent."""
    global _bac
    if _ancienne_valeur is None:
        os.environ.pop(VAR, None)
    else:
        os.environ[VAR] = _ancienne_valeur
    if _bac is not None:
        shutil.rmtree(_bac, ignore_errors=True)
        _bac = None


def _preserver_playwright() -> None:
    """Playwright range ses navigateurs SOUS `%LOCALAPPDATA%\\ms-playwright`.

    Rediriger `LOCALAPPDATA` sans precaution les rend introuvables. Mesure sur
    le perimetre CI complet : **52 tests `[chromium]` en ERROR at setup**, et
    rien d'autre — 9071 passed au lieu de 9121, l'ecart etant exactement ces
    tests. C'est aussi la famille que CLAUDE.md signale comme invisible dans un
    grep `FAILED`, puisque ce sont des erreurs de SETUP.

    On fige donc le chemin reel dans la variable officielle avant de rediriger.
    """
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    if _ancienne_valeur:
        navigateurs = Path(_ancienne_valeur) / "ms-playwright"
        if navigateurs.is_dir():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(navigateurs)


if _actif:
    _preserver_playwright()
    _bac = Path(tempfile.mkdtemp(prefix="cinesort_etat_bac_"))
    os.environ[VAR] = str(_bac)
    # Filet : si pytest meurt sans passer par le hook de fin de session, le bac
    # ne doit pas rester dans %TEMP% et gonfler le compteur de fuite (#960).
    atexit.register(_demonter)


@pytest.fixture(autouse=True)
def _etat_reel_attribution(request: pytest.FixtureRequest):
    """Note quel test a materialise quelque chose dans le bac a sable."""
    if not _actif or _bac is None:
        yield
        return
    avant = _compter(_bac)
    yield
    apres = _compter(_bac)
    if apres > avant:
        _attribution[request.node.nodeid] = apres - avant


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:  # noqa: ANN001, ARG001
    """Nomme les tests qui auraient ecrit dans l'etat REEL sans ce garde."""
    if not _actif:
        terminalreporter.write_line(
            f"[etat-reel] garde DESACTIVE ({GUARD_ENV}=0) : la suite a pu ecrire dans l'etat reel de l'utilisateur."
        )
        return
    if not _attribution:
        return
    terminalreporter.write_line("")
    terminalreporter.write_line(
        f"[etat-reel] {len(_attribution)} test(s) ont ecrit dans l'etat applicatif. "
        "Sans ce garde, c'est la base REELLE de l'utilisateur qui etait ouverte :"
    )
    for nodeid, n in sorted(_attribution.items(), key=lambda x: -x[1])[:20]:
        terminalreporter.write_line(f"[etat-reel]   {n:>4} entree(s)  {nodeid}")


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001, ARG001
    _demonter()
