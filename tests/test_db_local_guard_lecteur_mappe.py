"""Un lecteur reseau MAPPE est du SMB, meme s'il s'ecrit comme un disque local.

`db_local_guard` refusait de poser la base SQLite sur un chemin UNC
(`\\\\serveur\\partage\\...`) â€” corruption silencieuse connue sur SMB, cf.
Sonarr #1886. Mais il ne testait QUE la FORME du chemin.

Or sous Windows, `net use Z: \\\\nas\\media` donne un `Z:\\` qui ressemble
exactement a un disque local et qui est le meme SMB en dessous. Le garde le
laissait donc passer, avec le meme risque et sans le moindre avertissement.

La detection existait deja dans le depot, juste a cote : `detect_storage_type`
(pragma_profile) interroge `GetDriveTypeW` et rend un profil `nas_*` sur
DRIVE_REMOTE. Elle n'etait pas branchee sur le garde. On la reutilise plutot que
d'en ecrire une seconde, qui finirait par diverger.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from cinesort.infra.db import nas_validation
from cinesort.infra.db.nas_validation import db_local_guard


class LecteurReseauMappeTests(unittest.TestCase):
    def _avec_type_detecte(self, valeur: str):
        return mock.patch(
            "cinesort.infra.db.nas_validation.detect_storage_type",
            return_value=valeur,
        )

    def test_un_lecteur_MAPPE_est_refuse(self) -> None:
        with self._avec_type_detecte("nas_smb"):
            with self.assertRaises(RuntimeError) as ctx:
                db_local_guard(Path("Z:/CineSort/db/cinesort.db"))

        self.assertIn("reseau mappe", str(ctx.exception), "le message ne dit pas de quoi il s'agit")

    def test_un_disque_LOCAL_reste_accepte(self) -> None:
        """Contre-epreuve : sans elle, un garde qui refuse tout passerait."""
        with self._avec_type_detecte("local_ssd"):
            db_local_guard(Path("C:/Users/x/AppData/Local/CineSort/db/cinesort.db"))

    def test_l_override_vaut_AUSSI_pour_un_lecteur_mappe(self) -> None:
        """Le bypass documente doit couvrir le nouveau cas, sinon on bloque un
        utilisateur qui avait deja fait son choix en connaissance de cause."""
        with self._avec_type_detecte("nas_smb"):
            db_local_guard(Path("Z:/CineSort/db/cinesort.db"), allow_unc=True)

    def test_un_echec_de_DETECTION_ne_bloque_pas_le_demarrage(self) -> None:
        """Sur ce point precis la detection est un bonus : une exception ctypes
        ou un environnement non-Windows ne doit pas empecher de demarrer."""
        with mock.patch(
            "cinesort.infra.db.nas_validation.detect_storage_type",
            side_effect=OSError("ctypes indisponible"),
        ):
            db_local_guard(Path("D:/CineSort/db/cinesort.db"))

    def test_le_chemin_UNC_reste_refuse_comme_avant(self) -> None:
        """Non-regression : le cas historique n'est pas remplace."""
        with self.assertRaises(RuntimeError) as ctx:
            db_local_guard(Path(r"\\nas\media\cinesort.db"))

        self.assertIn("UNC", str(ctx.exception))

    def test_la_detection_n_est_PAS_appelee_sur_un_chemin_UNC(self) -> None:
        """Le chemin UNC se decide sur la forme, sans appel systeme inutile."""
        with mock.patch("cinesort.infra.db.nas_validation.detect_storage_type") as detecte:
            with self.assertRaises(RuntimeError):
                db_local_guard(Path(r"\\nas\media\cinesort.db"))

        detecte.assert_not_called()

    def test_le_module_expose_toujours_son_garde(self) -> None:
        self.assertTrue(callable(nas_validation.db_local_guard))


if __name__ == "__main__":
    unittest.main()
