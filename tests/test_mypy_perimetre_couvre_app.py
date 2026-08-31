# -*- coding: utf-8 -*-
"""`app.py` echappait au typage statique — le second des six controles.

Le defaut
---------
`mypy.yml` lancait `mypy cinesort/`. `app.py` — 1200 lignes, le point d'entree
de l'application, qui porte le boot desktop ET le passage du jeton REST sous
`?ntoken=` — n'etait donc pas type-checke.

Mesure du 2026-08-31, dans les conditions EXACTES du job (la commande de
reproduction est ecrite dans `mypy.yml`) :

    cinesort/ seul                        75 erreurs / 32 fichiers
    cinesort/ + app.py                    76 erreurs / 33 fichiers
    apres correction de l'unique erreur   75 erreurs / 32 fichiers

L'unique erreur etait un `type: ignore` qui nommait le MAUVAIS code
-------------------------------------------------------------------
`app.py:588` portait `[union-attr]` alors que mypy y leve `[attr-defined]` :
`splash_window` est type `object`, il n'a donc aucun attribut connu — ce qui
n'est pas une union. mypy le disait lui-meme :

    Error code "attr-defined" not covered by "type: ignore" comment

Un ignore qui vise le mauvais code ne couvre rien : il fait croire a une
exemption deliberee la ou l'erreur passe encore. Meme famille que la liste de
secrets qui masquait une cle fantome (`export_support._SECRET_KEYS`).

`app.py` entre donc dans le perimetre SANS COUT, plafond inchange a 75.

Pourquoi un test
----------------
Un perimetre est une valeur dans un fichier de configuration : il se retrecit
d'un coup d'editeur, sans erreur et sans bruit. Ce test constate que la cible
est declaree, et que le plafond reste borne.
"""

from __future__ import annotations

import io
import re
import unittest
from pathlib import Path

import yaml

_RACINE = Path(__file__).resolve().parents[1]
_WORKFLOW = _RACINE / ".github" / "workflows" / "mypy.yml"


def _invocation_mypy() -> str:
    """LA LIGNE `mypy ...` que le job execute — pas l'etape qui la contient.

    Une premiere version rendait l'etape `run:` ENTIERE. Or l'invocation reelle
    et la commande de reproduction citee en commentaire vivent dans la MEME
    etape : `assertIn("app.py", etape)` restait donc vrai apres avoir retire
    `app.py` de l'invocation. La mutation a survecu, et c'est elle qui l'a
    revele — le garde souffrait du defaut qu'il denonce, chercher une chaine
    dans un bloc trop large.
    """
    conf = yaml.safe_load(io.open(_WORKFLOW, encoding="utf-8").read())
    for job in (conf.get("jobs") or {}).values():
        for etape in job.get("steps") or []:
            for ligne in str(etape.get("run") or "").split("\n"):
                nue = ligne.strip()
                # `#` exclut les commentaires shell ; `uvx` exclut la commande de
                # reproduction, qui n'est pas ce que le job execute.
                if nue.startswith("mypy ") and not nue.startswith(("#", "uvx")):
                    return nue
    raise AssertionError("aucune invocation `mypy` trouvee dans le workflow")


class LeTypageCouvreLePointDEntreeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.commande = _invocation_mypy()
        self.source = io.open(_WORKFLOW, encoding="utf-8").read()

    def test_l_invocation_est_LISIBLE(self) -> None:
        """Garde anti-silence : si le parsing ne trouve plus la commande, les
        assertions suivantes porteraient sur une chaine vide."""
        self.assertIn("mypy ", self.commande)
        self.assertIn("cinesort/", self.commande)

    def test_app_py_est_TYPE_CHECKE(self) -> None:
        """Le cas qui a mordu : 1200 lignes, le boot et le jeton REST, hors mypy."""
        self.assertIn(
            "app.py",
            self.commande,
            "`app.py` porte le boot desktop et le passage du jeton REST, et n'etait type-checke par personne",
        )

    def test_la_commande_de_REPRODUCTION_suit_le_perimetre(self) -> None:
        """Le workflow documente comment reproduire son chiffre. Si cette
        commande reste sur l'ancien perimetre, quiconque la copie mesure autre
        chose que ce que le cliquet verifie — et conclut a une regression
        imaginaire, ou en manque une vraie."""
        repro = [
            ligne for ligne in self.source.split("\n") if "mypy cinesort/" in ligne and "--platform linux" in ligne
        ]
        self.assertTrue(repro, "commande de reproduction introuvable dans le commentaire")
        for ligne in repro:
            with self.subTest(ligne=ligne.strip()[:60]):
                self.assertIn("app.py", ligne)

    def test_le_PLAFOND_reste_borne(self) -> None:
        """Elargir sans remesurer ferait echouer la CI ; un plafond enorme le
        rendrait decoratif."""
        m = re.search(r"^\s*PLAFOND\s*=\s*(\d+)\s*$", self.source, re.MULTILINE)
        self.assertIsNotNone(m, "PLAFOND introuvable")
        plafond = int(m.group(1))
        self.assertGreater(plafond, 0)
        self.assertLess(plafond, 300, "un plafond aussi haut ne borne plus rien")

    def test_le_type_ignore_d_app_py_nomme_le_BON_code(self) -> None:
        """Contre-epreuve du correctif lui-meme.

        Remettre `[union-attr]` reintroduirait l'erreur — mypy passerait de 75 a
        76 et le cliquet rougirait. Ce test le dit sans lancer mypy, qui demande
        les deps de production et `--platform linux` pour rendre le bon chiffre."""
        app = io.open(_RACINE / "app.py", encoding="utf-8").read()
        self.assertIn("evaluate_js(  # type: ignore[attr-defined]", app)
        self.assertNotIn("evaluate_js(  # type: ignore[union-attr]", app)


if __name__ == "__main__":
    unittest.main()
