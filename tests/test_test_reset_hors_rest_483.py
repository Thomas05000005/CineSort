"""`test_reset` ne doit JAMAIS devenir une route REST (#483).

Elle remet l'application dans un etat propre — elle efface les runs en memoire.
Aujourd'hui elle n'a aucune route : la Pass 1 du dispatcher (methodes directes
de `CineSortApi`) est desactivee par defaut, et `test_reset` n'est sur aucune
facade. Rien ne le GARANTISSAIT pour autant.

MESURE qui motive ce fichier : poser les trois methodes publiques residuelles de
`CineSortApi` sur une facade — ce que #483 recommande — creait exactement UNE
route, `runtime/test_reset`. Les deux autres (`open_path`, `log_api_exception`)
etaient deja dans `_EXCLUDED_METHODS`, que la Pass 2 consulte aussi ;
`test_reset` ne l'etait pas, parce qu'elle n'en avait jamais eu besoin.

Suivre la recommandation de l'issue telle quelle aurait donc ouvert un endpoint
de remise a zero — le motif exact de #944, ou un chemin destructif etait
joignable sans aucune des garanties de la regle n3.

Les E2E ne sont pas concernes : ils appellent `test_reset` directement sur
l'objet Python (`tests/e2e/conftest.py`) ou via le pont pywebview
(`window.pywebview.api.test_reset`), qui ne passe pas par ce dispatcher —
exactement comme `open_path`, exclu ici et pourtant utilise par l'UI desktop.
"""

from __future__ import annotations

import unittest

from cinesort.infra.rest_server import _EXCLUDED_METHODS, _get_api_methods
from cinesort.ui.api.cinesort_api import CineSortApi
from cinesort.ui.api.facades.runtime_facade import RuntimeFacade


class TestResetResteHorsDeLApiRestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_aucune_route_ne_mene_a_test_reset(self) -> None:
        routes = _get_api_methods(self.api)
        fautives = sorted(r for r in routes if r.endswith("test_reset"))
        self.assertEqual(fautives, [], f"routes exposant une remise a zero : {fautives}")

    def test_la_facade_isation_ne_l_exposerait_PAS(self) -> None:
        """Le scenario que #483 recommande, joue pour de vrai.

        Sans l'exclusion, ce test rougit : la Pass 2 du dispatcher decouvre
        toute methode publique d'une facade, et `test_reset` en deviendrait une.
        """
        avant = set(_get_api_methods(self.api))
        original = getattr(RuntimeFacade, "test_reset", None)
        self.addCleanup(
            lambda: (
                setattr(RuntimeFacade, "test_reset", original)
                if original is not None
                else RuntimeFacade.__dict__.get("test_reset") and delattr(RuntimeFacade, "test_reset")
            )
        )
        RuntimeFacade.test_reset = lambda self, *a, **k: None  # type: ignore[attr-defined]

        apres = set(_get_api_methods(CineSortApi()))

        self.assertEqual(
            sorted(apres - avant),
            [],
            "poser `test_reset` sur une facade cree une route REST de remise a zero : "
            "elle doit rester dans `_EXCLUDED_METHODS`.",
        )

    def test_l_exclusion_est_bien_declaree(self) -> None:
        """Le « pourquoi » vit dans le commentaire de la liste ; ici on ancre le « quoi ».

        Ce test seul serait une tautologie — c'est celui d'au-dessus qui porte la
        preuve. Il existe pour que l'echec nomme la cause en une ligne.
        """
        self.assertIn("test_reset", _EXCLUDED_METHODS)

    def test_les_deux_autres_residuelles_restent_exclues(self) -> None:
        """`open_path` prend un chemin arbitraire, `log_api_exception` est un helper.

        Elles etaient deja exclues ; le verifier ici evite qu'un nettoyage de la
        liste emporte l'une des trois en croyant n'en toucher qu'une.
        """
        for methode in ("open_path", "log_api_exception"):
            self.assertIn(methode, _EXCLUDED_METHODS)


if __name__ == "__main__":
    unittest.main()
