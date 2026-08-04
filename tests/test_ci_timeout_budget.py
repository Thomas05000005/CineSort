"""Le budget d'attente des helpers de test s'elargit sur un runner de CI.

Mesure du 2026-08-03 : `tests/test_apply_preview.py` construit son plan en ~5 s
en local et a mis 11 s sur un runner GitHub, au-dela du budget fixe de 10 s. Le
journal du run montrait `PLAN READY` atteint : aucun blocage reel, seulement un
parc lent. Deux tests tombaient au hasard, et un seul check requis rouge suffit
a empecher toute fusion — c'est ce qui a bloque 74 PR armees.

Le budget local n'est PAS releve : c'est lui qui attrape les vrais
interblocages en developpement.
"""

from __future__ import annotations

import unittest
from unittest import mock

from tests._helpers import _budget


class BudgetAdaptatifTests(unittest.TestCase):
    def test_local_le_budget_reste_serre(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(_budget(10.0), 10.0)
            self.assertEqual(_budget(5.0), 5.0)

    def test_sur_ci_le_budget_est_elargi(self) -> None:
        with mock.patch.dict("os.environ", {"CI": "true"}, clear=True):
            self.assertGreater(
                _budget(10.0),
                11.0,
                "le budget CI doit depasser les 11 s reellement mesurees sur un runner",
            )

    def test_la_variable_denvironnement_force_la_valeur(self) -> None:
        with mock.patch.dict("os.environ", {"CINESORT_TEST_TIMEOUT_S": "42"}, clear=True):
            self.assertEqual(_budget(10.0), 42.0)
        # Meme sous CI : la valeur forcee prime, pour reproduire un timeout.
        with mock.patch.dict("os.environ", {"CI": "true", "CINESORT_TEST_TIMEOUT_S": "1"}, clear=True):
            self.assertEqual(_budget(10.0), 1.0)

    def test_une_valeur_forcee_illisible_ne_casse_rien(self) -> None:
        with mock.patch.dict("os.environ", {"CINESORT_TEST_TIMEOUT_S": "pas-un-nombre"}, clear=True):
            self.assertEqual(_budget(10.0), 10.0)


if __name__ == "__main__":
    unittest.main()
