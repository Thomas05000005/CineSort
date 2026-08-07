"""Le gate d'accessibilite ne doit pas auditer des pages qui n'existent pas.

MESURE 2026-08-06 : sur les six routes visees par `tests/test_axe_dashboard.py`,
`/validation` n'etait enregistree par AUCUN `registerRoute` de
`web/dashboard/app.js`. L'audit portait donc sur une page vide — sans que rien
ne le signale, puisque axe-core ne trouve aucune violation sur une page vide.

C'est la forme la plus discrete de gate neutralise : il tourne, il ne rougit
jamais, et il ne mesure rien. Ce test-ci est statique et tourne dans le
perimetre CI ordinaire — contrairement au gate lui-meme, qui exige un navigateur
et un jeton.

NB : les DEUX autres neutralisations du gate ne sont pas couvertes ici (assertion
dure commentee, et `CINESORT_API_TOKEN` defini par aucun workflow). Elles
demandent de faire tourner le dashboard et de traiter les violations reelles.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_APP_JS = Path("web/dashboard/app.js")
_AXE_TEST = Path("tests/test_axe_dashboard.py")


def _routes_enregistrees() -> set[str]:
    source = _APP_JS.read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r'registerRoute\(\s*"([^"]+)"', source)}


def _routes_auditees() -> list[str]:
    source = _AXE_TEST.read_text(encoding="utf-8")
    m = re.search(r"^ROUTES\s*=\s*\[(.*?)\]", source, re.MULTILINE | re.DOTALL)
    assert m, "ROUTES introuvable dans le gate d'accessibilite"
    return re.findall(r'"([^"]+)"', m.group(1))


class RoutesDuGateA11yTests(unittest.TestCase):
    def test_le_routeur_expose_bien_des_routes(self) -> None:
        """Sans ca, une regex cassee rendrait le test complaisant : un ensemble
        vide fait passer n'importe quelle inclusion."""
        self.assertGreater(len(_routes_enregistrees()), 5)

    def test_le_gate_liste_bien_des_routes(self) -> None:
        self.assertGreater(len(_routes_auditees()), 0)

    def test_CHAQUE_route_auditee_existe_dans_le_routeur(self) -> None:
        enregistrees = _routes_enregistrees()
        manquantes = [r for r in _routes_auditees() if r not in enregistrees]

        self.assertEqual(
            manquantes,
            [],
            f"le gate d'accessibilite audite des pages inexistantes : {manquantes}. "
            "Une page vide ne produit aucune violation — le gate passe sans rien mesurer.",
        )

    def test_aucun_doublon_dans_la_liste_auditee(self) -> None:
        auditees = _routes_auditees()
        self.assertEqual(len(auditees), len(set(auditees)), f"routes en double : {auditees}")


if __name__ == "__main__":
    unittest.main()
