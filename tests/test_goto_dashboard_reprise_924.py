"""`page.goto` reprend sur une penurie de ports ephemeres (#924).

Le correctif keep-alive de #924 a fait passer le serveur de **26 sockets a 1**
pour 6 serveurs x 4 requetes, et la frequence de `net::ERR_NO_BUFFER_SPACE`
s'est effondree — mais pas a zero : une occurrence sur ~25 executions de `main`
(run 31086285725, `tests/test_runtime_contrast_wcag.py`).

Deux choses ont ete apprises de cette occurrence :

1. elle frappe au **`goto`**, pas a l'attente du shell. Le diagnostic ajoute a
   l'epoque vit plus bas, dans l'attente de `#app-shell` : il ne se declenche
   donc pas, la page n'etant jamais chargee. L'instrument etait sur la mauvaise
   ligne, et l'occurrence n'a rien appris de plus que la precedente ;
2. `ERR_NO_BUFFER_SPACE` est par nature TRANSITOIRE — c'est une penurie de
   ports ephemeres, pas une panne du serveur.

Ces tests n'ont pas besoin d'un navigateur : ils eprouvent la logique de
reprise sur une page factice, ce qui les rend deterministes. La mesure de
frequence, elle, est statistique et ne peut pas vivre en CI.
"""

from __future__ import annotations

import unittest

from tests.e2e_dashboard.conftest import _PALIERS_GOTO_S, _aller_au_dashboard


class _PageFactice:
    """Page qui echoue les N premiers `goto`, puis reussit."""

    def __init__(self, echecs: int, message: str) -> None:
        self._restants = echecs
        self._message = message
        self.appels = 0

    def goto(self, url: str) -> None:
        self.appels += 1
        if self._restants > 0:
            self._restants -= 1
            raise RuntimeError(self._message)

    # Le diagnostic interroge ces trois-la ; il doit survivre a leur absence.
    @property
    def url(self) -> str:
        raise RuntimeError("url indisponible")

    def locator(self, _sel):  # noqa: ANN001, ANN201
        raise RuntimeError("locator indisponible")

    def title(self) -> str:
        raise RuntimeError("title indisponible")


_SERVEUR = {"dashboard_url": "http://127.0.0.1:1/dashboard/", "port": 1}


class GotoAvecRepriseTests(unittest.TestCase):
    def test_une_penurie_passagere_ne_fait_plus_echouer_le_test(self) -> None:
        page = _PageFactice(echecs=1, message="Page.goto: net::ERR_NO_BUFFER_SPACE at http://x/")

        _aller_au_dashboard(page, _SERVEUR)

        self.assertEqual(page.appels, 2, "le goto aurait du etre rejoue exactement une fois")

    def test_le_chemin_nominal_ne_coute_rien(self) -> None:
        page = _PageFactice(echecs=0, message="")
        _aller_au_dashboard(page, _SERVEUR)
        self.assertEqual(page.appels, 1)
        self.assertEqual(_PALIERS_GOTO_S[0], 0.0, "le premier essai doit etre immediat")

    def test_une_penurie_PERSISTANTE_echoue_toujours(self) -> None:
        """La reprise ne doit jamais transformer une panne reelle en succes."""
        page = _PageFactice(echecs=99, message="Page.goto: net::ERR_NO_BUFFER_SPACE at http://x/")

        with self.assertRaises(RuntimeError) as ctx:
            _aller_au_dashboard(page, _SERVEUR)

        self.assertEqual(page.appels, len(_PALIERS_GOTO_S))
        message = str(ctx.exception)
        # L'echec final doit porter le DIAGNOSTIC, sinon l'occurrence suivante
        # n'apprendra toujours rien.
        self.assertIn("port du serveur de test", message)
        self.assertIn("ERR_NO_BUFFER_SPACE", message, "l'erreur d'origine doit rester lisible")

    def test_une_erreur_qui_n_est_PAS_une_penurie_remonte_au_premier_essai(self) -> None:
        """Reessayer un refus de connexion retarderait un diagnostic juste."""
        page = _PageFactice(echecs=99, message="Page.goto: net::ERR_CONNECTION_REFUSED at http://x/")

        with self.assertRaises(RuntimeError):
            _aller_au_dashboard(page, _SERVEUR)

        self.assertEqual(page.appels, 1, "une erreur non transitoire ne doit pas etre rejouee")

    def test_le_budget_de_reprise_reste_negligeable(self) -> None:
        """Il precede une attente de 8 s : il ne doit pas peser dans la balance."""
        self.assertLess(sum(_PALIERS_GOTO_S), 2.0)


if __name__ == "__main__":
    unittest.main()
