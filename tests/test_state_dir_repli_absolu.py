"""Le repli de `default_state_dir()` ne doit JAMAIS etre relatif.

Il valait `"."`, donc `./CineSort` quand `LOCALAPPDATA` est absent. La base, les
runs et les journaux suivaient alors le REPERTOIRE COURANT : lancer
l'application depuis un autre dossier ouvrait silencieusement une AUTRE base —
ni erreur, ni migration, juste une bibliotheque qui a l'air neuve.

`LOCALAPPDATA` est toujours pose sur un poste Windows interactif, mais pas
necessairement dans un service, une tache planifiee ou un conteneur. Et cette
fonction a **133 sites d'appel** : c'est la racine de tout l'etat.

Ce fichier eprouve la PROPRIETE (« absolu, et stable quel que soit le repertoire
de lancement »), pas la valeur exacte du repli — un test qui figerait `~/CineSort`
rougirait au premier changement de politique sans rien prouver de plus.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.infra.state import default_state_dir


class LeRepliEstABSOLUTests(unittest.TestCase):
    def test_sans_LOCALAPPDATA_le_chemin_reste_absolu(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LOCALAPPDATA", None)
            chemin = default_state_dir()
        self.assertTrue(
            chemin.is_absolute(),
            f"le repli est RELATIF ({chemin}) : la base suivrait le repertoire de lancement",
        )

    def test_le_repli_ne_DEPEND_PAS_du_repertoire_courant(self) -> None:
        """LA propriete qui compte. Un `Path('.')` est deja « resolu » en absolu
        par `Path.cwd()` chez certains appelants : seule la STABILITE entre deux
        repertoires de lancement distingue le repli sain du repli fautif."""
        depart = Path.cwd()
        with tempfile.TemporaryDirectory(prefix="cs_cwd_a_") as a, tempfile.TemporaryDirectory(prefix="cs_cwd_b_") as b:
            try:
                with mock.patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("LOCALAPPDATA", None)
                    os.chdir(a)
                    depuis_a = default_state_dir().resolve()
                    os.chdir(b)
                    depuis_b = default_state_dir().resolve()
            finally:
                os.chdir(depart)

        self.assertEqual(
            depuis_a,
            depuis_b,
            f"le repertoire d'etat CHANGE avec le repertoire de lancement : {depuis_a} vs {depuis_b}",
        )

    def test_avec_LOCALAPPDATA_rien_ne_change(self) -> None:
        """CONTRE-EPREUVE : le chemin nominal — celui de 100 % des postes
        Windows interactifs — doit rester exactement le meme."""
        with tempfile.TemporaryDirectory(prefix="cs_lad_") as tmp:
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                self.assertEqual(default_state_dir(), Path(tmp) / "CineSort")


if __name__ == "__main__":
    unittest.main()
