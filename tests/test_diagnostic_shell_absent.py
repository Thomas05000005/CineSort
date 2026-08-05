"""Le message d'echec doit permettre de TRANCHER a la premiere occurrence.

Issue #924. Un shell qui n'apparait pas apres 30 s en CI n'est pas « lent »,
c'est « jamais ». Trois enquetes successives ont ete menees par elimination,
sans jamais capturer l'etat AU MOMENT de la panne — donc sans jamais trancher
entre :

    application lente        -> le serveur repond, le DOM arrive, le shell tarde
    socket morte / epuisee   -> le serveur n'accepte plus de connexion

Le diagnostic ajoute repond exactement a cette question, et rien d'autre.

Il doit satisfaire deux exigences contradictoires en apparence :
  - donner le maximum d'information sur un runner qu'on ne peut pas inspecter ;
  - ne JAMAIS lever lui-meme — un diagnostic qui plante masquerait l'erreur
    qu'il est cense decrire, ce qui serait strictement pire que pas de
    diagnostic du tout.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright requis")

pytest_plugins = ["tests.e2e_dashboard.conftest"]

from tests.e2e_dashboard import conftest as dashboard_conftest  # noqa: E402


class _PageMuette:
    """Page dont TOUT echoue : le diagnostic doit survivre a chaque acces."""

    @property
    def url(self):
        raise RuntimeError("url indisponible")

    def locator(self, _sel):
        raise RuntimeError("locator indisponible")

    def title(self):
        raise RuntimeError("title indisponible")


@pytest.mark.runtime
def test_le_diagnostic_repond_a_la_question_qui_tranche(page, e2e_server) -> None:
    """Serveur VIVANT : le message doit le dire, donc ecarter la piste socket."""
    page.goto(e2e_server["dashboard_url"])
    page.wait_for_selector("#app-shell:not(.hidden)", timeout=30000)

    msg = dashboard_conftest._diagnostic_shell_absent(page, e2e_server, RuntimeError("timeout simule"))

    assert f"port du serveur de test : {e2e_server['port']}" in msg
    assert "le serveur ACCEPTE encore" in msg, f"le serveur repond mais le diagnostic ne le dit pas :\n{msg}"
    assert "#app-shell present=True" in msg
    assert "timeout simule" in msg, "l'erreur d'origine doit rester lisible"


@pytest.mark.runtime
def test_serveur_injoignable_est_nomme_comme_tel(page, e2e_server) -> None:
    """L'autre branche du verdict, sur un port certainement ferme."""
    ferme = dict(e2e_server)
    ferme["port"] = 1  # port privilegie, jamais ouvert par ce processus

    msg = dashboard_conftest._diagnostic_shell_absent(page, ferme, RuntimeError("x"))

    assert "serveur INJOIGNABLE" in msg, msg


@pytest.mark.runtime
def test_le_diagnostic_ne_leve_jamais() -> None:
    """Exigence non negociable : il ne doit pas masquer l'erreur qu'il decrit.

    On lui donne une page dont chaque acces leve, et un e2e_server sans port.
    """
    msg = dashboard_conftest._diagnostic_shell_absent(_PageMuette(), {}, RuntimeError("erreur d'origine a preserver"))

    assert isinstance(msg, str) and msg
    assert "erreur d'origine a preserver" in msg, "le diagnostic a perdu l'erreur d'origine, donc il masque le defaut"
