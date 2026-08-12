"""Le profil qualite ACTIF doit etre celui qu'on exporte et qu'on calibre.

LE DEFAUT. Deux fonctions testaient `isinstance(actif.get("profile_json"), str)`
avant de deserialiser. Or le repository DECODE deja la colonne :

    quality.py:67  "profile_json": self._decode_row_json(..., expected_type=dict)

La condition etait donc TOUJOURS fausse, et les deux retombaient
systematiquement sur `default_quality_profile()`.

MESURE, sur un store REEL — profil personnalise enregistre puis relu :

    type rendu par le repository : dict
    isinstance(pj, str)          : False
    poids du profil par defaut   : resolution=None
    poids du profil utilisateur  : resolution=99.0

Deux consequences, silencieuses toutes les deux :

  - `export_shareable_profile` partageait le profil PAR DEFAUT sous le nom de
    l'utilisateur. Le partage communautaire de profil ne partageait rien ;
  - `get_calibration_report` calculait ses suggestions de poids sur un profil
    que l'utilisateur n'emploie pas — donc des conseils sans rapport avec son
    reglage.

POURQUOI PERSONNE NE L'A VU : LE TEST VERROUILLAIT LE DEFAUT. Il injectait
`{"profile_json": json.dumps(profil)}` — une CHAINE, forme que la production ne
produit jamais — et n'assertait ensuite que sur `author` et `description`, deux
valeurs qui viennent des ARGUMENTS du wrapper et non du profil. Le test restait
vert que le profil soit lu ou non.

Ce fichier assert donc sur le CONTENU du profil exporte, avec la forme REELLE
que rend le repository. C'est la seule facon d'observer la grandeur en cause.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.domain.quality_score import default_quality_profile
from cinesort.infra.db.sqlite_store import SQLiteStore
from cinesort.ui.api.cinesort_api import CineSortApi, _profil_actif_ou_defaut

#: Profil reconnaissable : si on le retrouve en sortie, il a bien ete lu.
_PROFIL_PERSO = {"weights": {"resolution": 99.0, "codec": 1.0}, "marqueur": "PROFIL_DE_L_UTILISATEUR"}


class LeRepositoryRendUnDICTPasUneChaineTests(unittest.TestCase):
    """La precondition du defaut, mesuree sur un store REEL.

    Sans ce test, la correction reposerait sur une lecture de code. Un double
    qui rendrait une chaine ferait passer l'ancien code pour correct.
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_d0_"))
        self.store = SQLiteStore(self._tmp / "c.sqlite")
        self.store.initialize()

    def tearDown(self) -> None:
        import contextlib

        with contextlib.suppress(Exception):
            self.store.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_profile_json_est_un_dict(self) -> None:
        self.store.quality.save_quality_profile(
            profile_id="perso", version=1, profile_json=_PROFIL_PERSO, is_active=True
        )

        actif = self.store.quality.get_active_quality_profile()

        self.assertIsInstance(
            actif["profile_json"],
            dict,
            "si le repository rendait une chaine, l'ancienne branche aurait ete correcte",
        )
        self.assertEqual(actif["profile_json"]["marqueur"], "PROFIL_DE_L_UTILISATEUR")


class LeProfilACTIFEstCELUIQuOnExporteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = CineSortApi()

    def _exporter(self, valeur_profile_json) -> dict:
        store = mock.MagicMock()
        store.quality.get_active_quality_profile.return_value = {"profile_json": valeur_profile_json}
        with mock.patch.object(self.api, "_get_or_create_infra", return_value=(store, mock.MagicMock())):
            return self.api._export_shareable_profile_impl(name="x", author="moi", description="d")

    def test_le_profil_de_l_utilisateur_se_retrouve_dans_l_export(self) -> None:
        """LE test. Il echoue avec l'ancienne branche `isinstance(..., str)`."""
        res = self._exporter(_PROFIL_PERSO)

        self.assertTrue(res["ok"])
        contenu = json.loads(res["content"])
        texte = json.dumps(contenu)
        self.assertIn(
            "PROFIL_DE_L_UTILISATEUR",
            texte,
            "le profil exporte n'est pas celui de l'utilisateur : le partage communautaire "
            "diffuse le profil PAR DEFAUT sous son nom.",
        )

    def test_une_forme_CHAINE_reste_toleree(self) -> None:
        """Compat : une base ancienne peut encore en produire une."""
        res = self._exporter(json.dumps(_PROFIL_PERSO))

        self.assertIn("PROFIL_DE_L_UTILISATEUR", json.dumps(json.loads(res["content"])))

    def test_un_profil_CORROMPU_retombe_sur_le_defaut_sans_lever(self) -> None:
        res = self._exporter("pas du json")

        self.assertTrue(res["ok"], "un profil illisible ne doit pas casser l'export")

    def test_sans_profil_actif_on_exporte_le_defaut(self) -> None:
        res = self._exporter(None)

        self.assertTrue(res["ok"])


class LaCALIBRATIONPorteSurLeProfilACTIFTests(unittest.TestCase):
    """Meme defaut, seconde fonction : les suggestions de poids se calculaient
    sur un profil que l'utilisateur n'emploie pas."""

    def test_le_helper_rend_les_poids_de_l_utilisateur(self) -> None:
        poids = _profil_actif_ou_defaut({"profile_json": _PROFIL_PERSO}).get("weights")

        self.assertEqual(poids, {"resolution": 99.0, "codec": 1.0})
        self.assertNotEqual(
            poids,
            default_quality_profile().get("weights"),
            "les suggestions de calibration porteraient sur le mauvais profil",
        )


class LeHelperTRAITELesQuatreFormesTests(unittest.TestCase):
    """Un helper partage par deux appelants doit etre sur sur les quatre entrees
    possibles : dict, chaine, corrompu, absent."""

    def test_dict(self) -> None:
        self.assertEqual(_profil_actif_ou_defaut({"profile_json": _PROFIL_PERSO}), _PROFIL_PERSO)

    def test_chaine(self) -> None:
        self.assertEqual(_profil_actif_ou_defaut({"profile_json": json.dumps(_PROFIL_PERSO)}), _PROFIL_PERSO)

    def test_corrompu(self) -> None:
        self.assertEqual(_profil_actif_ou_defaut({"profile_json": "{{{"}), default_quality_profile())

    def test_absent(self) -> None:
        self.assertEqual(_profil_actif_ou_defaut(None), default_quality_profile())

    def test_dict_VIDE_vaut_absence(self) -> None:
        """Un profil vide n'est pas un profil : l'exporter donnerait un fichier
        sans aucun poids, que le destinataire ne pourrait pas utiliser."""
        self.assertEqual(_profil_actif_ou_defaut({"profile_json": {}}), default_quality_profile())


if __name__ == "__main__":
    unittest.main()
