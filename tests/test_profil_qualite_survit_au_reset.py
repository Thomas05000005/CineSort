"""Le profil qualite de l'utilisateur doit survivre a une remise a zero de la base.

LE DEFAUT, EN CHAINE. `save_settings` construit ce qu'il ecrit : `to_save` part
de l'existant, puis chaque `_save_section_*` reclame SES cles. C'est une liste
blanche par omission — une cle qu'aucune section ne reclame n'est jamais
recopiee, et `save_settings` rend quand meme `ok: True`.

`custom_quality_profiles` et `active_quality_profile_id` n'etaient reclamees par
personne. MESURE, sur un `state_dir` neuf, en relisant le settings.json ECRIT :

    custom_quality_profiles   -> ABSENTE du fichier
    active_quality_profile_id -> ABSENTE du fichier
    locale (temoin)           -> "en", ecrite

Trois consequences, toutes silencieuses :

  1. `quality.save_profile` rendait `{"ok": true, "profile_id": "MonProfil"}` et
     ne persistait RIEN ;
  2. `quality.set_active_profile("MonProfil")` repondait ensuite
     « Profil inconnu » — pour le profil qu'on venait de « sauvegarder » ;
  3. `settings.reset_database` supprime le fichier SQLite entier. Le profil
     actif n'y ayant qu'une seule copie, il etait DETRUIT, et
     `ensure_quality_profile` reconstruisait le profil PAR DEFAUT sans un mot.
     Mesure de bout en bout : poids video **70 -> 60**, `ok: True`, aucun
     avertissement. Un utilisateur qui appuie sur « Reinitialiser la base » pour
     reparer un scan perdait son reglage au passage.

Ce n'etaient pas les lecteurs qui manquaient : `profiles_support_crud.py` et
`reset_support.py` lisent et ecrivent ces deux cles depuis toujours. C'est la
section d'ECRITURE qui n'existait pas.

CE QUE CES TESTS EPROUVENT, ET DANS QUEL SENS. La derniere classe est la plus
importante : un correctif qui rend un profil indestructible **eteindrait** la
reinitialisation VOULUE de la bibliotheque. Les deux sens sont verifies.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cinesort.domain.quality_score import default_quality_profile
from cinesort.ui.api.cinesort_api import CineSortApi
from cinesort.ui.api.quality_internal_support import profil_durable_des_reglages
from tests._helpers import cleanup_test_tree

#: Poids reconnaissable et VALIDE (la somme doit faire 100).
_POIDS_PERSO = {"video": 70, "audio": 20, "extras": 10}


def _profil_perso() -> dict:
    p = default_quality_profile()
    p["id"] = "MonProfil"
    p["label"] = "Mon profil"
    p["weights"] = dict(_POIDS_PERSO)
    return p


class _BaseApi(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_profil_reset_"))
        self.api = CineSortApi()
        self.api._state_dir = self._tmp / "state"  # type: ignore[attr-defined]
        self.api._state_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        cleanup_test_tree(self._tmp)

    # -- helpers de lecture, tous sur la sortie REELLE de l'application --

    def _biblio(self) -> tuple[list, str]:
        s = self.api.settings.get_settings() or {}
        return [e.get("id") for e in (s.get("custom_quality_profiles") or [])], str(
            s.get("active_quality_profile_id") or ""
        )

    def _poids_video_actif(self):
        q = self.api.quality.get_quality_profile() or {}
        pj = q.get("profile_json") or q.get("profile") or {}
        return (pj.get("weights") or {}).get("video")

    def _installer_le_profil(self) -> None:
        r = self.api.quality.save_profile(_profil_perso())
        self.assertTrue(r.get("ok"), f"save_profile a echoue : {r}")
        r2 = self.api.quality.set_active_profile("MonProfil")
        self.assertTrue(r2.get("ok"), f"set_active_profile a echoue : {r2}")


class LesReglagesCONSERVENTLeProfilTests(_BaseApi):
    """Le maillon 1 : sans persistance, tout le reste est sans objet."""

    def test_save_profile_ecrit_vraiment_sur_le_DISQUE(self) -> None:
        r = self.api.quality.save_profile(_profil_perso())

        self.assertTrue(r.get("ok"))
        fichier = self.api._get_state_dir() / "settings.json"
        d = json.loads(fichier.read_text(encoding="utf-8-sig"))
        self.assertIn(
            "custom_quality_profiles",
            d,
            "la cle n'est pas dans le fichier ecrit : save_settings l'a jetee en silence",
        )
        self.assertEqual([e.get("id") for e in d["custom_quality_profiles"]], ["MonProfil"])

    def test_le_profil_QU_ON_VIENT_DE_SAUVER_est_activable(self) -> None:
        """L'enchainement exact que faisait l'interface, et qui echouait."""
        self.assertTrue(self.api.quality.save_profile(_profil_perso()).get("ok"))

        r = self.api.quality.set_active_profile("MonProfil")

        self.assertTrue(
            r.get("ok"),
            f"le profil sauvegarde a l'instant est declare inconnu : {r.get('message') or r}",
        )
        self.assertEqual(self._biblio()[1], "MonProfil")


class UnRESETDeLaBASENeDetruitPasLeProfilTests(_BaseApi):
    """LE test de cette PR."""

    def test_le_profil_survit_a_reset_database(self) -> None:
        self._installer_le_profil()
        self.assertEqual(self._poids_video_actif(), 70, "precondition : le profil perso doit etre actif")

        self.api.settings.reset_database(dry_run=False)

        self.assertEqual(
            self._poids_video_actif(),
            70,
            "le profil de l'utilisateur a ete remplace par le profil PAR DEFAUT : "
            "« Reinitialiser la base » efface un reglage qu'on ne lui a pas demande d'effacer",
        )
        self.assertEqual(self._biblio(), (["MonProfil"], "MonProfil"))

    def test_la_bibliotheque_survit_meme_si_la_base_reste_vide(self) -> None:
        """Le materiau de la restauration est dans les REGLAGES, pas dans la base."""
        self._installer_le_profil()
        self.api.settings.reset_database(dry_run=False)

        durable = profil_durable_des_reglages(self.api)

        self.assertIsNotNone(durable)
        self.assertEqual((durable or {}).get("weights"), _POIDS_PERSO)


class UneSauvegardePARTIELLENEfaceRienTests(_BaseApi):
    """LA CLE ABSENTE EST UN SILENCE, PAS UN EFFACEMENT.

    CE QUE CETTE CLASSE A ATTRAPE, ET COMMENT. Une premiere version de
    `_save_section_quality_profiles` ecrivait les deux cles INCONDITIONNELLEMENT.
    Les 10 tests de ce fichier ne passaient alors que des charges utiles
    COMPLETES : ils etaient tous verts. La revue adversariale du LOT fusionne a
    nomme le trou, et la mesure l'a confirme :

        save_settings({"theme": "luxe"})  ->  ok: True
        custom_quality_profiles           ->  []      EFFACEE
        active_quality_profile_id         ->  ""      EFFACE

    LE SCENARIO N'ETAIT PAS THEORIQUE. L'ecran Parametres fige les reglages a son
    ouverture, puis les re-POSTe EN BLOC a chaque champ modifie (sauvegarde
    differee). Un profil cree depuis cet ecran disparaissait donc a la frappe
    suivante, sous un « Sauvegarde a HH:MM:SS ». Et tout client REST postant une
    charge utile partielle detruisait la bibliotheque.

    L'ironie vaut d'etre gardee : le MEME lot ajoutait `_chemin_demande`
    (probe_support.py) pour corriger exactement cette forme de defaut sur les
    chemins d'outils. Corriger un motif a un endroit ne le corrige pas ailleurs.
    """

    def test_une_sauvegarde_qui_ne_parle_QUE_d_un_autre_reglage_ne_touche_a_rien(self) -> None:
        self._installer_le_profil()
        self.assertEqual(self._biblio(), (["MonProfil"], "MonProfil"))

        r = self.api.settings.save_settings({"theme": "luxe"})

        self.assertTrue(r.get("ok"))
        self.assertEqual(
            self._biblio(),
            (["MonProfil"], "MonProfil"),
            "une sauvegarde partielle a efface la bibliotheque de profils",
        )

    def test_le_profil_survit_a_plusieurs_sauvegardes_partielles_successives(self) -> None:
        """Le cas reel : l'ecran Parametres sauvegarde a chaque champ touche."""
        self._installer_le_profil()

        for champ, valeur in (("theme", "luxe"), ("locale", "en"), ("expert_mode", True)):
            self.api.settings.save_settings({champ: valeur})

        self.assertEqual(self._biblio(), (["MonProfil"], "MonProfil"))

    def test_un_effacement_EXPLICITE_efface_quand_meme(self) -> None:
        """L'autre sens : la cle presente et vide reste une demande."""
        self._installer_le_profil()
        reglages = self.api.settings.get_settings() or {}
        reglages["custom_quality_profiles"] = []
        reglages["active_quality_profile_id"] = ""

        self.api.settings.save_settings(reglages)

        self.assertEqual(self._biblio(), ([], ""), "l'effacement demande n'a pas eu lieu")


class UnPRESETActifSurvitAussiTests(_BaseApi):
    """LES PRESETS COMPTENT AUTANT QUE LES PROFILS PERSONNALISES.

    Une premiere version ne cherchait l'id actif que dans
    `custom_quality_profiles`. Pour un PRESET, elle rendait `None`, la base
    repartait sur le profil par defaut — mais l'ecran continuait d'annoncer le
    preset choisi, parce que `get_profiles` prefere l'id des REGLAGES a celui de
    la base (`active_id_raw or db_active_id`).

    MESURE, apres `reset_database`, sur les trois presets testes :

        preset actif                base restauree   affiche a l'ecran
        CinemaLux_RemuxStrict_v1    CinemaLux_v1     CinemaLux_RemuxStrict_v1
        video 66 / extras 4         video 60 / 10
        Compact_v1                  CinemaLux_v1     Compact_v1
        video 50 / extras 20        video 60 / 10
        StreamingOptimal_v1         CinemaLux_v1     StreamingOptimal_v1
        video 55 / extras 20        video 60 / 10

    C'etait PIRE que le defaut d'origine : l'ecran mentait sur le profil qui
    score reellement la bibliotheque. Et c'est le fait de rendre l'id DURABLE
    qui a ouvert ce trou — avant, il n'etait jamais persiste, l'affichage
    retombait sur la base et restait coherent. Apres avoir rendu une valeur
    durable, il faut verifier TOUS ses lecteurs.
    """

    #: Trois presets aux poids DIFFERENTS du defaut : sans cela, un profil non
    #: restaure serait indiscernable d'un profil restaure.
    _PRESETS = ("CinemaLux_RemuxStrict_v1", "Compact_v1", "StreamingOptimal_v1")

    def _poids_actifs(self) -> dict:
        q = self.api.quality.get_quality_profile() or {}
        pj = q.get("profile_json") or q.get("profile") or {}
        return dict(pj.get("weights") or {})

    def _id_actif_en_base(self) -> str:
        q = self.api.quality.get_quality_profile() or {}
        pj = q.get("profile_json") or q.get("profile") or {}
        return str(pj.get("id") or "")

    def test_les_presets_sont_restaures_avec_LEURS_poids(self) -> None:
        defaut = default_quality_profile().get("weights")
        for pid in self._PRESETS:
            with self.subTest(preset=pid):
                self.assertTrue(self.api.quality.set_active_profile(pid).get("ok"))
                avant = self._poids_actifs()
                self.assertNotEqual(avant, defaut, f"{pid} a les memes poids que le defaut : il ne prouverait rien")

                self.api.settings.reset_database(dry_run=False)

                self.assertEqual(
                    self._poids_actifs(),
                    avant,
                    f"{pid} n'a pas ete restaure : la bibliotheque est desormais scoree avec un autre profil",
                )

    def test_l_ecran_et_la_BASE_disent_le_meme_profil(self) -> None:
        """La grandeur qui compte n'est pas « un profil existe » mais « c'est le
        MEME des deux cotes »."""
        for pid in self._PRESETS:
            with self.subTest(preset=pid):
                self.api.quality.set_active_profile(pid)
                self.api.settings.reset_database(dry_run=False)

                affiche = str((self.api.quality.get_profiles() or {}).get("active_profile_id") or "")

                self.assertEqual(
                    affiche,
                    self._id_actif_en_base(),
                    "l'ecran annonce un profil que la base n'a pas : le scoring tourne sur un autre",
                )


class LaREINITIALISATIONVOULUEMarcheTOUJOURSTests(_BaseApi):
    """L'AUTRE SENS, et c'est la moitie qu'on oublie.

    Un correctif qui rend le profil indestructible ETEINT la reinitialisation
    que l'utilisateur demande explicitement. « Le profil survit » et « le profil
    s'efface quand on le demande » doivent etre vrais tous les deux.
    """

    def test_le_scope_profils_qualite_vide_bien_la_bibliotheque(self) -> None:
        self._installer_le_profil()
        self.assertEqual(self._biblio(), (["MonProfil"], "MonProfil"))

        r = self.api.settings.reset_settings(scope="profils-qualite", dry_run=False)

        self.assertTrue(r.get("ok"))
        self.assertEqual(self._biblio(), ([], ""), "la reinitialisation demandee n'efface plus rien")

    def test_le_scope_all_vide_aussi_la_bibliotheque(self) -> None:
        self._installer_le_profil()

        self.assertTrue(self.api.settings.reset_settings(scope="all", dry_run=False).get("ok"))

        self.assertEqual(self._biblio(), ([], ""))


class UnProfilMALFORMENEmporteRienTests(_BaseApi):
    """Un profil abime ne doit pas emporter avec lui les ~118 autres reglages."""

    def test_une_entree_non_dict_est_ecartee_sans_faire_echouer_la_sauvegarde(self) -> None:
        s = self.api.settings.get_settings() or {}
        s["custom_quality_profiles"] = ["pas un profil", 42, _profil_perso()]
        s["locale"] = "en"  # temoin : un reglage voisin, qui doit survivre

        r = self.api.settings.save_settings(s)

        self.assertTrue(r.get("ok"))
        relu = self.api.settings.get_settings() or {}
        self.assertEqual([e.get("id") for e in relu["custom_quality_profiles"]], ["MonProfil"])
        self.assertEqual(relu.get("locale"), "en", "un profil malforme a emporte un reglage voisin")

    def test_un_profil_INVALIDE_laisse_la_main_au_defaut(self) -> None:
        """Schema durci entre deux versions : ne pas bloquer le demarrage.

        LE CAS D'INVALIDITE EST MESURE, PAS SUPPOSE. Une premiere version de ce
        test cassait la SOMME des poids (1/1/1 au lieu de 100) — et il est reste
        rouge, parce que `validate_quality_profile` **normalise** les poids au
        lieu de les refuser. Sonde sur les sept formes abimees plausibles : la
        seule qu'elle rejette est la hierarchie de tiers non decroissante.
        C'est donc la barriere reelle, et c'est elle qu'on eprouve.
        """
        s = self.api.settings.get_settings() or {}
        casse = _profil_perso()
        casse["tiers"] = {"platinum": 10, "gold": 60, "silver": 55, "bronze": 40}  # non decroissants
        s["custom_quality_profiles"] = [casse]
        s["active_quality_profile_id"] = "MonProfil"
        self.api.settings.save_settings(s)

        self.assertIsNone(profil_durable_des_reglages(self.api))


class LeHelperEstSURSesEntreesTests(_BaseApi):
    def test_aucun_profil_actif_nomme(self) -> None:
        self.assertIsNone(profil_durable_des_reglages(self.api))

    def test_un_id_actif_QUI_NE_CORRESPOND_A_RIEN(self) -> None:
        s = self.api.settings.get_settings() or {}
        s["custom_quality_profiles"] = [_profil_perso()]
        s["active_quality_profile_id"] = "UnAutreProfil"
        self.api.settings.save_settings(s)

        self.assertIsNone(profil_durable_des_reglages(self.api))


if __name__ == "__main__":
    unittest.main()
