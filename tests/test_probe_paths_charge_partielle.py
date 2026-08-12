"""Une mise a jour PARTIELLE des chemins d'outils n'efface pas l'autre outil.

LE DEFAUT. `set_probe_tool_paths` lisait les deux chemins dans la seule charge
utile, puis les ecrivait tous les deux :

    ff_path = str(incoming.get("ffprobe_path") or "").strip()
    mi_path = str(incoming.get("mediainfo_path") or "").strip()
    ...
    merged["ffprobe_path"] = ff_path
    merged["mediainfo_path"] = mi_path

Un appel qui ne parlait que de ffprobe mettait donc `mediainfo_path` a "".
MESURE, sur un state_dir reel :

    AVANT  ffprobe   : C:\\outils\\ffprobe.exe
    AVANT  mediainfo : C:\\outils\\mediainfo.exe
    appel  {"ffprobe_path": ...}          -> ok: True
    APRES  mediainfo : ''                   <- EFFACE

L'endpoint est expose en REST. Une charge utile partielle — ce que produit
naturellement un formulaire a un seul champ — detruisait la configuration de
l'autre outil, et l'appel repondait `ok`.

CE QUE CES TESTS DISTINGUENT. « Absent » et « vide » ne veulent pas dire la meme
chose : la cle absente est un silence (on garde), la cle vide est une demande
(on efface). Un correctif qui rendrait le chemin ineffacable serait aussi faux
que celui d'origine — l'utilisateur doit pouvoir vider son champ.

Le validateur est une dependance INJECTEE par la signature de la fonction ; le
substituer n'est pas contourner la production, c'est utiliser la couture qu'elle
expose. Le defaut vit en aval de lui, dans la fusion.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.ui.api import probe_support
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import cleanup_test_tree

_FF = r"C:\outils\ffprobe.exe"
_MI = r"C:\outils\mediainfo.exe"


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_probe_partiel_"))
        self.api = CineSortApi()
        self.api._state_dir = self._tmp / "state"  # type: ignore[attr-defined]
        self.api._state_dir.mkdir(parents=True, exist_ok=True)
        s = self.api.settings.get_settings() or {}
        s["ffprobe_path"] = _FF
        s["mediainfo_path"] = _MI
        self.api.settings.save_settings(s)

    def tearDown(self) -> None:
        cleanup_test_tree(self._tmp)

    def _appeler(self, charge: dict) -> dict:
        with mock.patch.object(self.api, "_recheck_probe_tools_impl", return_value={"ok": True}):
            return probe_support.set_probe_tool_paths(
                self.api,
                charge,
                validate_tool_path_fn=lambda **_k: {"ok": True},
                detect_probe_tools_fn=lambda **_k: {"ok": True},
            )

    def _chemins(self) -> tuple[str, str]:
        s = self.api.settings.get_settings() or {}
        return str(s.get("ffprobe_path") or ""), str(s.get("mediainfo_path") or "")


class UneCleABSENTEPreserveLExistantTests(_Base):
    """LE test de cette correction."""

    def test_ne_parler_que_de_ffprobe_ne_touche_pas_a_mediainfo(self) -> None:
        r = self._appeler({"ffprobe_path": _FF})

        self.assertTrue(r.get("ok"))
        self.assertEqual(
            self._chemins(),
            (_FF, _MI),
            "une charge utile partielle a efface le chemin de l'autre outil",
        )

    def test_ne_parler_que_de_mediainfo_ne_touche_pas_a_ffprobe(self) -> None:
        """Le defaut est symetrique : les deux sens doivent etre couverts."""
        r = self._appeler({"mediainfo_path": _MI})

        self.assertTrue(r.get("ok"))
        self.assertEqual(self._chemins(), (_FF, _MI))

    def test_une_charge_utile_VIDE_ne_detruit_rien(self) -> None:
        """Un POST au corps vide est le cas le plus courant, et le plus couteux."""
        r = self._appeler({})

        self.assertTrue(r.get("ok"))
        self.assertEqual(self._chemins(), (_FF, _MI))


class LaPORTEPRINCIPALESuitLaMEMERegleTests(_Base):
    """`set_probe_tool_paths` n'est pas le seul chemin d'ecriture.

    CE QUE LA REVUE DU LOT A ATTRAPE. Corriger `set_probe_tool_paths` laissait
    intacte la PORTE PRINCIPALE : `_save_section_probe` ecrivait les deux chemins
    inconditionnellement. Mesure, sur un state_dir reel, apres enregistrement des
    deux outils :

        save_settings({"theme": "luxe"})  ->  ffprobe_path = ''
                                              mediainfo_path = ''

    Un client REST postant une charge utile partielle effacait donc la
    configuration des outils par la grande porte, pendant que la petite etait
    gardee. Corriger un motif a un endroit ne le corrige pas ailleurs.
    """

    def test_une_sauvegarde_qui_ne_parle_pas_des_outils_ne_les_touche_pas(self) -> None:
        self.assertEqual(self._chemins(), (_FF, _MI))

        self.api.settings.save_settings({"theme": "luxe"})

        self.assertEqual(
            self._chemins(),
            (_FF, _MI),
            "une sauvegarde partielle a efface la configuration des outils de sonde",
        )

    def test_une_sauvegarde_qui_VIDE_explicitement_efface_quand_meme(self) -> None:
        reglages = self.api.settings.get_settings() or {}
        reglages["ffprobe_path"] = ""
        reglages["mediainfo_path"] = ""

        self.api.settings.save_settings(reglages)

        self.assertEqual(self._chemins(), ("", ""))


class UneCleVIDEEfaceBienTests(_Base):
    """L'AUTRE SENS : un correctif qui rend le chemin ineffacable est aussi faux.

    L'utilisateur qui vide son champ demande explicitement l'effacement. Le
    distinguer du silence est tout l'objet de la correction.
    """

    def test_une_chaine_vide_EXPLICITE_efface(self) -> None:
        r = self._appeler({"mediainfo_path": ""})

        self.assertTrue(r.get("ok"))
        self.assertEqual(self._chemins(), (_FF, ""), "le champ vide de l'utilisateur n'a pas ete pris en compte")

    def test_les_deux_champs_vides_effacent_les_deux(self) -> None:
        self._appeler({"ffprobe_path": "", "mediainfo_path": ""})

        self.assertEqual(self._chemins(), ("", ""))


class LeCheminMODIFIEEstBienEcritTests(_Base):
    """La correction ne doit pas non plus figer les chemins."""

    def test_un_nouveau_chemin_remplace_l_ancien(self) -> None:
        nouveau = r"C:\autre\ffprobe.exe"

        self._appeler({"ffprobe_path": nouveau})

        self.assertEqual(self._chemins(), (nouveau, _MI))


if __name__ == "__main__":
    unittest.main()
