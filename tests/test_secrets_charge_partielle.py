"""Une sauvegarde de reglages PARTIELLE n'efface plus les secrets qu'elle ne nomme pas.

LE DEFAUT. `_save_settings_payload_locked` part de l'existant (merge
read-modify-write) puis chaque `_save_section_*` ecrase ce qu'elle reclame. Cinq
sections ecrivaient leur secret INCONDITIONNELLEMENT :

    "plex_token":          str(payload.get("plex_token") or "").strip()
    "radarr_api_key":      ...
    "omdb_api_key":        ...
    "email_smtp_password": ...
    "rest_api_token":      ...

Une sauvegarde qui ne nommait pas le secret le remplacait donc par "". Et
`write_settings` n'ecrit AUCUNE enveloppe chiffree pour une valeur vide : le
secret est perdu, sans copie ailleurs.

    save_settings({"theme": "luxe"})  ->  ok: True
      plex_token / radarr_api_key / omdb_api_key
      email_smtp_password / rest_api_token        -> ''   EFFACES
      tmdb_api_key / jellyfin_api_key             -> conserves

L'ASYMETRIE EST CE QUI REND LE DIAGNOSTIC UNIVOQUE. Les deux survivants ont un
helper dedie — `_apply_tmdb_key_persistence`, `_apply_jellyfin_key_persistence` —
qui tourne APRES les sections et reporte l'existant quand le payload est muet.
Cinq secrets sur sept avaient manque cette politique.

C'est le meme motif, dans le meme fichier, que `_save_section_probe` (chemins
d'outils, cf. `test_probe_paths_charge_partielle.py`) et
`_save_section_quality_profiles` : « cle ABSENTE = silence (on garde), cle
presente et VIDE = demande (on efface) ». Un correctif qui rendrait le secret
ineffacable serait aussi faux que l'original — l'utilisateur doit pouvoir vider
son champ. Les deux sens sont donc couverts ici.

CE QUE L'ECRAN NE DECLENCHE PAS. `parametres.js` poste son instantane complet
(moins les 4 cles de `_CLES_POSSEDEES_AILLEURS`), secrets au masque, que
`_unmask_secrets_for_save` restaure : l'utilisateur de l'interface n'etait pas
touche. La portee est celle d'un client REST postant une charge utile partielle —
exactement celle que le dépôt a déjà jugée reelle en corrigeant les chemins
d'outils, dont la « porte principale » etait cette meme fonction.

POURQUOI LE JETON REST PORTE LES TESTS DE BOUT EN BOUT. Les quatre autres
secrets ne sont persistes que si DPAPI repond (`protection_available()`), donc
jamais sur le runner Linux de la CI : un test de bout en bout les concernant
serait VACANT ailleurs que sous Windows. `rest_api_token` a, lui, un repli en
clair assume pour les plateformes non-Windows (`write_settings`) — il est donc
verifiable partout, et c'est aussi celui dont la perte coute le plus cher. Les
quatre autres sont couverts au niveau des sections (plateforme-independant) et
par le cliquet de couverture en fin de fichier.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import List

from cinesort.ui.api import settings_support
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import cleanup_test_tree

# Valeur deliberement NON aleatoire : >= MIN_LAN_TOKEN_LENGTH (32) pour ne pas
# croiser la garde anti-degradation du hot-swap, mais d'entropie assez faible
# pour ne pas ressembler a un `token_urlsafe` aux yeux du scan de secrets.
_JETON = "JETON-DE-TEST-NON-SECRET-000000000"
_AUTRE_JETON = "AUTRE-JETON-DE-TEST-NON-SECRET-000"


class _FauxServeurRest:
    """Enregistre les hot-swaps demandes, sans ouvrir de socket."""

    def __init__(self) -> None:
        self.swaps: List[str] = []

    def update_auth_token(self, new_token: str) -> None:
        self.swaps.append(str(new_token))


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_secrets_partiel_"))
        self.api = CineSortApi()
        self.api._state_dir = self._tmp / "state"  # type: ignore[attr-defined]
        self.api._state_dir.mkdir(parents=True, exist_ok=True)
        # Le jeton est pose EXPLICITEMENT, comme le fait le boot
        # (`app.py` : `save_settings({**s, "rest_api_token": token})`) : un GET
        # seul le genere en memoire mais ne le persiste pas.
        reglages = self.api.settings.get_settings() or {}
        reglages["rest_api_token"] = _JETON
        self.api.settings.save_settings(reglages)
        # ANCRAGE. Sans cette assertion le fichier entier serait vacant : si le
        # jeton n'etait pas persiste, « il n'a pas ete efface » ne prouverait rien.
        self.assertEqual(self._jeton_sur_disque(), _JETON, "le jeton de depart n'a pas ete persiste")

    def tearDown(self) -> None:
        cleanup_test_tree(self._tmp)

    def _jeton_sur_disque(self) -> str:
        """Relit par le code de PRODUCTION (dechiffre l'enveloppe le cas echeant)."""
        return str(settings_support.read_settings(self.api._get_state_dir()).get("rest_api_token") or "")


class UneCleABSENTEPreserveLeSecretTests(_Base):
    """LE test de cette correction."""

    def test_une_sauvegarde_qui_ne_parle_pas_du_jeton_ne_l_efface_pas(self) -> None:
        resultat = self.api.settings.save_settings({"theme": "luxe"})

        self.assertTrue(resultat.get("ok"))
        self.assertEqual(
            self._jeton_sur_disque(),
            _JETON,
            "une sauvegarde partielle a efface le jeton de l'API REST",
        )

    def test_une_charge_utile_sans_aucun_reglage_connu_ne_detruit_rien(self) -> None:
        """Un POST au corps quasi vide est le cas le plus courant, et le plus couteux."""
        resultat = self.api.settings.save_settings({"expert_mode": True})

        self.assertTrue(resultat.get("ok"))
        self.assertEqual(self._jeton_sur_disque(), _JETON)

    def test_le_temoin_non_secret_change_bien(self) -> None:
        """Contre-test : la sauvegarde partielle doit tout de meme AGIR.

        Sans lui, un `save_settings` devenu inoperant ferait passer les deux
        tests ci-dessus pour des succes.
        """
        self.api.settings.save_settings({"theme": "cinema"})

        reglages = settings_support.read_settings(self.api._get_state_dir())
        self.assertEqual(reglages.get("theme"), "cinema")


class UneCleVIDEEfaceBienTests(_Base):
    """L'AUTRE SENS : un correctif qui rend le secret ineffacable est aussi faux.

    Le jeton vide est un kill-switch assume (rotation apres compromission) :
    `rest_server.update_auth_token` l'autorise explicitement, meme en bind
    0.0.0.0. Il doit rester atteignable.
    """

    def test_un_jeton_explicitement_VIDE_efface(self) -> None:
        self.api.settings.save_settings({"rest_api_token": ""})

        self.assertEqual(self._jeton_sur_disque(), "", "l'effacement explicite du jeton n'a pas ete honore")

    def test_un_nouveau_jeton_remplace_l_ancien(self) -> None:
        """La correction ne doit pas non plus FIGER le secret."""
        self.api.settings.save_settings({"rest_api_token": _AUTRE_JETON})

        self.assertEqual(self._jeton_sur_disque(), _AUTRE_JETON)


class LeHotSwapNePartPasSurUneChargePartielleTests(_Base):
    """LE SECOND SITE, et il fallait les deux.

    Corriger la seule PERSISTANCE laissait le serveur vivant sans jeton :
    `_save_settings_impl` comparait un `new_token` vide a l'ancien, donc
    different, et appelait `update_auth_token("")`. Le controle d'auth etant
    fail-closed (`if not self.auth_token: return False`), tout client recevait
    401 jusqu'au redemarrage — tableau de bord compris.
    """

    def test_une_sauvegarde_partielle_ne_touche_pas_au_jeton_du_serveur(self) -> None:
        serveur = _FauxServeurRest()
        self.api._rest_server = serveur  # type: ignore[attr-defined]

        self.api.settings.save_settings({"theme": "luxe"})

        self.assertEqual(serveur.swaps, [], "le hot-swap a coupe l'authentification du serveur REST")

    def test_un_changement_de_jeton_declenche_TOUJOURS_le_hot_swap(self) -> None:
        """Contre-test : la garde ne doit pas eteindre le hot-swap legitime.

        C'est tout l'objet de `update_auth_token` — sans lui, `settings.json`
        porte le nouveau jeton et le handler valide encore avec l'ancien.
        """
        serveur = _FauxServeurRest()
        self.api._rest_server = serveur  # type: ignore[attr-defined]

        self.api.settings.save_settings({"rest_api_token": _AUTRE_JETON})

        self.assertEqual(serveur.swaps, [_AUTRE_JETON])

    def test_un_effacement_EXPLICITE_atteint_encore_le_kill_switch(self) -> None:
        serveur = _FauxServeurRest()
        self.api._rest_server = serveur  # type: ignore[attr-defined]

        self.api.settings.save_settings({"rest_api_token": ""})

        self.assertEqual(serveur.swaps, [""])


class LesSectionsNEcriventPlusUnSecretAbsentTests(unittest.TestCase):
    """Les quatre autres secrets, au niveau ou la plateforme n'intervient pas.

    Leur persistance depend de DPAPI, donc un test de bout en bout serait vacant
    hors Windows (cf. l'en-tete du module). La DECISION, elle, se verifie partout.
    """

    def test_section_plex_omet_le_jeton_absent(self) -> None:
        self.assertNotIn("plex_token", settings_support._save_section_plex({}))

    def test_section_radarr_omet_la_cle_absente(self) -> None:
        self.assertNotIn("radarr_api_key", settings_support._save_section_radarr({}))

    def test_section_omdb_omet_la_cle_absente(self) -> None:
        self.assertNotIn("omdb_api_key", settings_support._save_section_omdb({}))

    def test_section_email_omet_le_mot_de_passe_absent(self) -> None:
        self.assertNotIn("email_smtp_password", settings_support._save_section_email({}))

    def test_section_rest_api_omet_le_jeton_absent(self) -> None:
        self.assertNotIn("rest_api_token", settings_support._save_section_rest_api({}))

    def test_un_mot_de_passe_FOURNI_n_est_pas_strippe(self) -> None:
        """Un espace de tete ou de fin peut faire partie du secret SMTP."""
        rendu = settings_support._save_section_email({"email_smtp_password": "  pa ss  "})

        self.assertEqual(rendu["email_smtp_password"], "  pa ss  ")

    def test_les_autres_secrets_FOURNIS_sont_strippes(self) -> None:
        self.assertEqual(settings_support._save_section_plex({"plex_token": " t "})["plex_token"], "t")
        self.assertEqual(settings_support._save_section_radarr({"radarr_api_key": " r "})["radarr_api_key"], "r")
        self.assertEqual(settings_support._save_section_omdb({"omdb_api_key": " o "})["omdb_api_key"], "o")


class AucunSecretNEstReecritParUnPayloadMuetTests(unittest.TestCase):
    """CLIQUET DE COUVERTURE, marge zero, et il eprouve le COMPORTEMENT.

    Le defaut corrige ici est un OUBLI : cinq secrets avaient manque la politique
    que deux autres appliquaient. Un huitieme secret ajoute demain la manquerait
    de la meme facon, en silence.

    Une premiere version de ce cliquet comparait deux LISTES — `_SECRET_FIELDS`
    contre la table de politique. Elle serait restee verte sur une entree
    declaree que plus aucune section n'applique : elle mesurait une intention,
    pas un effet. On interroge donc le dispatcher REEL avec un payload muet, et
    on exige qu'il ne pose AUCUN secret. Toute section future qui ecrirait son
    secret inconditionnellement rougit ici, qu'elle soit declaree ou non.
    """

    def _sections_sur_payload_muet(self) -> dict:
        to_save: dict = {}
        settings_support._appliquer_les_sections(
            to_save,
            {},
            default_collection_folder_name="_Collection",
            default_empty_folders_folder_name="_Vide",
            default_residual_cleanup_folder_name="_Dossier Nettoyage",
            default_probe_backend="auto",
            debug_enabled=False,
        )
        return to_save

    def test_le_dispatcher_ne_pose_aucun_secret_sur_un_payload_muet(self) -> None:
        reecrits = sorted(set(settings_support._SECRET_FIELDS) & set(self._sections_sur_payload_muet()))

        self.assertEqual(
            reecrits,
            [],
            "ces secrets sont ecrases par une sauvegarde qui ne les nomme pas ; "
            "declarez-les dans _SECRETS_NON_EFFACABLES_PAR_OMISSION et appelez "
            "_reprendre_le_secret_si_fourni dans leur section",
        )

    def test_le_dispatcher_AGIT_bien_sur_un_payload_muet(self) -> None:
        """ANCRAGE. Sans lui, un dispatcher devenu inerte rendrait le test ci-dessus vert."""
        rendu = self._sections_sur_payload_muet()

        self.assertEqual(rendu.get("theme"), "luxe")
        self.assertEqual(rendu.get("plex_enabled"), False)

    def test_la_table_ne_declare_pas_de_secret_inconnu(self) -> None:
        """Une entree perimee ferait croire a une politique encore utile.

        Un secret retire de `_SECRET_FIELDS` doit l'etre aussi de la table —
        sinon `_reprendre_le_secret_si_fourni` garde une entree sans objet.
        """
        declares = set(settings_support._SECRETS_NON_EFFACABLES_PAR_OMISSION)

        self.assertEqual(sorted(declares - set(settings_support._SECRET_FIELDS)), [])


if __name__ == "__main__":
    unittest.main()
