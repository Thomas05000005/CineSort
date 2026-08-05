"""Un shell LENT ne doit pas etre diagnostique comme un probleme d'authentification.

La fixture `authenticated_page` attend le shell, puis — en cas de timeout —
tentait directement `wait_for_selector("#loginToken")`. Or le bypass
d'authentification localhost laisse ce champ dans le DOM mais CACHE. L'attente
echouait donc sur :

    TimeoutError: waiting for locator("#loginToken") to be visible
    20 x locator resolved to hidden <input id="loginToken" ...>

Un message qui designe le mauvais coupable : l'authentification n'etait pas en
cause, le shell etait seulement lent. Mesure du 2026-08-05 : cette erreur
apparait dans **4 des 8 derniers runs de CI en echec**, et bloque une vingtaine
de fichiers de tests runtime.

POURQUOI CE TEST FORCE LA CONDITION. En local le shell s'affiche en moins de 8 s,
donc le chemin de repli n'est jamais emprunte : muter la logique laisse tout au
VERT. Le defaut ne se manifeste que sous la charge d'un runner partage. On rend
donc la condition deterministe en ramenant le premier budget d'attente a 1 ms —
le premier `wait_for_selector` expire alors a coup sur, et c'est bien le chemin
de repli qui est mesure.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright requis")

pytest_plugins = ["tests.e2e_dashboard.conftest"]

from tests.e2e_dashboard import conftest as dashboard_conftest  # noqa: E402


@pytest.mark.runtime
def test_shell_lent_ne_tombe_pas_sur_le_champ_de_login_cache(page, e2e_server, monkeypatch) -> None:
    """Premiere attente forcee a l'echec : la fixture doit quand meme aboutir."""
    monkeypatch.setattr(dashboard_conftest, "_SHELL_TIMEOUT_MS", 1)

    # On rejoue la fixture elle-meme, pas une copie de sa logique : c'est le
    # code REEL qui doit etre exerce, sinon le test prouverait une reecriture.
    resultat = dashboard_conftest.authenticated_page.__wrapped__(page, e2e_server)

    assert resultat is page
    shell = page.locator("#app-shell")
    assert shell.count() > 0, "le shell n'est pas dans le DOM"
    assert "hidden" not in (shell.get_attribute("class") or ""), (
        "le shell est toujours cache : la fixture a rendu la main trop tot"
    )


@pytest.mark.runtime
def test_le_champ_de_login_est_bien_cache_en_bypass(page, e2e_server) -> None:
    """L'hypothese sur laquelle repose le correctif, verifiee explicitement.

    Si un jour le bypass cessait de laisser le champ dans le DOM, ou l'y
    laissait VISIBLE, la distinction faite par la fixture n'aurait plus de sens
    — et ce test le dirait, au lieu de laisser la fixture prendre la mauvaise
    branche en silence.
    """
    page.goto(e2e_server["dashboard_url"])
    page.wait_for_selector("#app-shell:not(.hidden)", timeout=30000)

    login = page.locator("#loginToken")
    assert login.count() > 0, "le champ de login a disparu du DOM"
    assert not login.is_visible(), "le champ de login est VISIBLE alors que le bypass est actif"
