"""Aucun caractere cyrillique ou grec dans le code de PRODUCTION.

POURQUOI CE GARDE, ALORS QUE LE CAS TROUVE ETAIT COSMETIQUE. Deux commentaires
portaient `delibere` avec un `е` CYRILLIQUE (U+0435) au lieu du `e` latin — le
meme mot aux deux endroits, donc un copier-coller. Sans effet a l'execution,
puisque ce sont des commentaires.

Mais c'est la meme sequence d'octets qui, dans un identifiant, une cle de
dictionnaire ou une comparaison de chaine, produit un defaut indiscernable a
l'oeil : deux noms qui s'affichent pareil et ne sont pas egaux. Le cout de la
garde est nul ; celui d'une occurrence dans du code executable ne l'est pas.

PERIMETRE : `cinesort/` SEULEMENT, et c'est deliberé.

  - `tests/test_unicode_filenames.py` porte des noms de fichiers cyrilliques
    VOLONTAIREMENT — c'est son sujet ;
  - `web/` porte des `Δ` (U+0394) qui sont des deltas affiches a l'utilisateur.

Restreindre a `cinesort/` donne donc un cliquet a **ZERO exemption** : toute
occurrence y est un defaut, sans liste a maintenir. Une liste d'exemptions qui
enfle finit par etre la mesure au lieu de la garder.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1] / "cinesort"

#: Cyrillique (U+0400-U+04FF) et grec (U+0370-U+03FF) : les deux blocs qui
#: contiennent des homoglyphes des lettres latines (е, а, о, р, с, х, ο, ν...).
_HOMOGLYPHES = re.compile("[Ѐ-ӿͰ-Ͽ]")


class AucunHomoglypheDansLeCodeDeProductionTests(unittest.TestCase):
    def test_aucun_caractere_cyrillique_ou_grec(self) -> None:
        trouves: list[str] = []
        fichiers = 0
        for chemin in RACINE.rglob("*.py"):
            fichiers += 1
            for numero, ligne in enumerate(chemin.read_text(encoding="utf-8").splitlines(), 1):
                for m in _HOMOGLYPHES.finditer(ligne):
                    rel = chemin.relative_to(RACINE.parent).as_posix()
                    trouves.append(f"{rel}:{numero} U+{ord(m.group()):04X}")

        self.assertGreater(fichiers, 100, "la sonde ne lit presque aucun fichier : elle est cassee")
        self.assertEqual(
            trouves,
            [],
            "caractere(s) cyrillique(s)/grec(s) dans le code de production — "
            f"probable homoglyphe d'une lettre latine : {trouves}",
        )


if __name__ == "__main__":
    unittest.main()
