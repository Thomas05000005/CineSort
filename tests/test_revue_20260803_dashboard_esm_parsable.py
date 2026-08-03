"""Revue post-merge 2026-08-03 — garde d'outillage : tout module du dashboard
doit se parser en MODULE ES, pas seulement en script CommonJS.

Piege rencontre pendant cette revue : une backquote glissee dans un commentaire
HTML place *a l'interieur d'un template literal* (views/historique.js) fermait
la chaine prematurement. `node --check historique.js` retournait rc=0 — parce
que l'extension .js le fait parser en mode SCRIPT — alors que le meme contenu en
.mjs levait `SyntaxError: Unexpected identifier`. Le dashboard est integralement
charge en ESM par le navigateur : c'est le parse module qui fait foi, et il
n'etait verifie nulle part. Un fichier casse serait passe en CI et aurait produit
un ecran blanc en production.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, esm_syntax_error, require_node

DASHBOARD = ROOT / "web" / "dashboard"


class DashboardModulesParsentEnEsmTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def test_tous_les_modules_du_dashboard_parsent_en_esm(self):
        files = sorted(DASHBOARD.rglob("*.js"))
        self.assertGreater(len(files), 20, "inventaire suspect : le dashboard compte des dizaines de modules")
        failures = []
        for js in files:
            err = esm_syntax_error(js)
            if err:
                failures.append(f"{js.relative_to(ROOT).as_posix()} :: {err.splitlines()[0] if err else ''}")
        self.assertEqual(failures, [], "modules non parsables en ESM :\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
