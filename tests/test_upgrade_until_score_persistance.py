"""« Score d'arret des upgrades » : le reglage n'atteignait jamais la base.

LE DEFAUT. `validate_quality_profile` ne construit pas sa sortie depuis son
entree : elle part de `default_quality_profile()` et y recopie une liste FERMEE
de cles (`id`, `version`, `engine_version`, huit sections, `custom_rules`,
`tier_hierarchy`). `upgrade_until_score` n'y figurait pas, et n'existe pas dans
le profil par defaut — la cle etait donc SUPPRIMEE a chaque passage :

    set_upgrade_until_score(3000)
      profile_json["upgrade_until_score"] = 3000
      normalized = validate_quality_profile(profile_json)[2]   <- la cle disparait
      _save_active_quality_profile(normalized)                 <- la base n'en voit rien
      return {"ok": True, "upgrade_until_score": 3000}         <- annonce quand meme 3000

    get_upgrade_until_score()  ->  10000, toujours.

Les QUATRE chemins qui persistent un profil passent par ce validateur
(`set_upgrade_until_score`, `import_recyclarr_yaml`, `save_profile`,
`set_active_profile`), et `ensure_quality_profile` le rappelle a chaque LECTURE
du profil actif : la valeur ne pouvait survivre nulle part. Le repository, lui,
ne filtre rien (`json.dumps(profile_json)`).

POURQUOI PERSONNE NE L'A VU — les deux moities du trajet sont testees
separement, avec un mock exactement a l'endroit ou la valeur se perd
(`tests/test_quality_profiles_facade_extension.py`) :

    test_set_valid_score       api._save_active_quality_profile = MagicMock()
                               -> assert sur le RETOUR (5500), jamais sur ce qui
                                  a ete passe au mock ;
    test_get_custom_value_...  injecte 7777 DIRECTEMENT dans le payload stub
                               -> contourne le validateur.

Aucun test n'appelait `set` puis `get` sur la meme API. Et l'audit du
2026-08-31 a conclu « le reglage est bien persiste, mais rien ne s'en sert »
(docstring de `UpgradeUntilScoreSansExecutantTests`) : la moitie « persiste »
n'avait pas ete mesuree.

CE QUE CE FICHIER EPROUVE, ET DANS QUEL ORDRE. Les deux moities du correctif
sont couvertes par des tests DISTINCTS, pour qu'aucune ne puisse etre retiree
sans rougir :

  - `LeSeuilAtteintLaBaseTests` observe le STOCKAGE (`profile_json` relu du
    store), pas le payload : rouge tant que le validateur efface la cle, quel
    que soit l'etat des lecteurs ;
  - `UnSeuilAZeroEstUneConsigneTests` porte sur `0`, seule valeur que le
    correctif du validateur ne suffit PAS a faire remonter : il faut aussi que
    les lecteurs cessent de faire `x or 10000`. C'est la meme famille que
    `tests/test_sentinelle_falsy_or_defaut.py`, dont la regle grep-able ne
    couvre que cinq fichiers — et ne verrait de toute facon pas une constante
    nommee (`or DEFAULT_UPGRADE_UNTIL_SCORE`), son motif ne visant que les
    litteraux numeriques.
"""

from __future__ import annotations

import contextlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.domain.quality_score import (
    DEFAULT_UPGRADE_UNTIL_SCORE,
    UPGRADE_UNTIL_SCORE_MAX,
    default_quality_profile,
    validate_quality_profile,
)
from cinesort.infra.db.sqlite_store import SQLiteStore
from cinesort.ui.api.cinesort_api import CineSortApi
from cinesort.ui.api.profiles_support_import_export import _profile_to_recyclarr_dict


class _ApiSurStoreReel(unittest.TestCase):
    """Base commune : une CineSortApi branchee sur un store SQLite REEL.

    Le store est reel et non un double : c'est la seule facon d'observer si la
    valeur atteint le stockage. Un `MagicMock` a cet endroit est precisement ce
    qui a masque le defaut pendant toute la vie du reglage.
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_upgrade_until_"))
        self.store = SQLiteStore(self._tmp / "cinesort.sqlite")
        self.store.initialize()
        # Un profil actif connu : `ensure_quality_profile` n'a alors aucune
        # raison d'aller interroger les reglages de la machine.
        self.store.quality.save_quality_profile(
            profile_id="CinemaLux_v1",
            version=1,
            profile_json=default_quality_profile(),
            is_active=True,
        )
        self.api = CineSortApi()
        patcher = mock.patch.object(
            self.api,
            "_get_or_create_infra",
            return_value=(self.store, mock.MagicMock()),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        with contextlib.suppress(Exception):
            self.store.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _profil_stocke(self) -> dict:
        actif = self.store.quality.get_active_quality_profile() or {}
        profil = actif.get("profile_json")
        self.assertIsInstance(profil, dict, "le repository doit rendre un dict")
        assert isinstance(profil, dict)
        return profil


class LeSeuilAtteintLaBaseTests(_ApiSurStoreReel):
    """LE test : ce que la BASE contient apres l'enregistrement."""

    def test_la_valeur_enregistree_est_dans_le_stockage(self) -> None:
        """Rouge avant le correctif : la cle etait absente du profil persiste.

        On lit le store et non le payload de `get_upgrade_until_score` : une
        assertion sur le payload seul resterait verte si un lecteur fabriquait
        la valeur sans qu'elle soit ecrite nulle part.
        """
        res = self.api.quality.set_upgrade_until_score(3000)

        self.assertTrue(res.get("ok"), res)
        self.assertEqual(
            self._profil_stocke().get("upgrade_until_score"),
            3000,
            "le seuil annonce comme enregistre n'est pas dans le profil persiste",
        )

    def test_la_valeur_relue_est_celle_qui_a_ete_ecrite(self) -> None:
        """Le round-trip complet, celui que l'ecran fait a chaque rechargement."""
        self.api.quality.set_upgrade_until_score(3000)

        relu = self.api.quality.get_upgrade_until_score()

        self.assertTrue(relu.get("ok"), relu)
        self.assertEqual(relu.get("upgrade_until_score"), 3000)

    def test_ce_qui_est_annonce_est_ce_qui_est_relu(self) -> None:
        """Le triangle : l'annonce du setter et la relecture ne doivent pas diverger."""
        annonce = self.api.quality.set_upgrade_until_score(7500)
        relu = self.api.quality.get_upgrade_until_score()

        self.assertEqual(
            annonce.get("upgrade_until_score"),
            relu.get("upgrade_until_score"),
            "le setter annonce une valeur que la relecture ne retrouve pas",
        )

    def test_le_seuil_survit_a_une_seconde_lecture(self) -> None:
        """`ensure_quality_profile` repasse par le validateur a CHAQUE lecture.

        Sans la preservation, une valeur qui aurait ete ecrite par un autre
        chemin serait effacee au premier acces suivant.
        """
        self.api.quality.set_upgrade_until_score(4200)

        self.api.quality.get_upgrade_until_score()
        second = self.api.quality.get_upgrade_until_score()

        self.assertEqual(second.get("upgrade_until_score"), 4200)

    def test_un_profil_sans_la_cle_retombe_sur_le_defaut(self) -> None:
        """Non-regression : l'ABSENCE, elle, vaut toujours 10000."""
        relu = self.api.quality.get_upgrade_until_score()

        self.assertEqual(relu.get("upgrade_until_score"), DEFAULT_UPGRADE_UNTIL_SCORE)
        self.assertNotIn(
            "upgrade_until_score",
            self._profil_stocke(),
            "le validateur ne doit pas AJOUTER la cle aux profils qui ne la portent pas",
        )


class UnSeuilAZeroEstUneConsigneTests(_ApiSurStoreReel):
    """`0` = « n'upgrade jamais », l'exact oppose du defaut 10000.

    L'ecran (`min="0"`) comme le backend (borne `[0..UPGRADE_UNTIL_SCORE_MAX]`)
    l'acceptent explicitement. Ces tests restent ROUGES si l'on corrige la
    persistance sans corriger les lecteurs `x or DEFAUT` : c'est la seconde
    moitie du correctif, eprouvee separement.
    """

    def test_zero_est_accepte_et_persiste(self) -> None:
        res = self.api.quality.set_upgrade_until_score(0)

        self.assertTrue(res.get("ok"), res)
        self.assertEqual(self._profil_stocke().get("upgrade_until_score"), 0)

    def test_zero_relu_reste_zero(self) -> None:
        """Rouge avec `int(x or 10000)` : le seuil bascule sur son contraire."""
        self.api.quality.set_upgrade_until_score(0)

        relu = self.api.quality.get_upgrade_until_score()

        self.assertEqual(
            relu.get("upgrade_until_score"),
            0,
            "un seuil a 0 relu comme 10000 inverse la consigne de l'utilisateur",
        )

    def test_zero_traverse_le_row_de_profil(self) -> None:
        """`get_profiles` alimente la liste des profils de l'ecran."""
        self.api.quality.set_upgrade_until_score(0)

        res = self.api.settings.get_profiles()

        self.assertTrue(res.get("ok"), res)
        actifs = [p for p in res.get("profiles", []) if p.get("is_active")]
        for profil in actifs:
            with self.subTest(profile_id=profil.get("id")):
                self.assertEqual(profil.get("upgrade_until_score"), 0)

    def test_zero_part_dans_le_yaml_recyclarr(self) -> None:
        """La destination reelle du reglage : Radarr/Sonarr, via le YAML."""
        profil = default_quality_profile()
        profil["upgrade_until_score"] = 0

        rendu = _profile_to_recyclarr_dict(profil)

        self.assertEqual(rendu["quality_profiles"][0]["upgrade"]["until_score"], 0)


class LeValidateurPreserveLaCleTests(unittest.TestCase):
    """Le correctif au niveau du domaine, isole de toute persistance."""

    def test_la_cle_presente_est_preservee(self) -> None:
        entree = default_quality_profile()
        entree["upgrade_until_score"] = 6400

        ok, errs, normalise = validate_quality_profile(entree)

        self.assertTrue(ok, errs)
        self.assertEqual(normalise.get("upgrade_until_score"), 6400)

    def test_zero_est_preserve_et_non_confondu_avec_l_absence(self) -> None:
        entree = default_quality_profile()
        entree["upgrade_until_score"] = 0

        _ok, _errs, normalise = validate_quality_profile(entree)

        self.assertIn("upgrade_until_score", normalise)
        self.assertEqual(normalise["upgrade_until_score"], 0)

    def test_la_cle_absente_le_reste(self) -> None:
        """Non-regression : aucun profil existant ne gagne la cle."""
        _ok, _errs, normalise = validate_quality_profile(default_quality_profile())

        self.assertNotIn("upgrade_until_score", normalise)

    def test_une_valeur_hors_borne_est_clampee(self) -> None:
        """L'entree peut venir d'un YAML arbitraire : elle est bornee ici aussi."""
        for brut, attendu in ((-5, 0), (UPGRADE_UNTIL_SCORE_MAX + 1, UPGRADE_UNTIL_SCORE_MAX)):
            with self.subTest(brut=brut):
                entree = default_quality_profile()
                entree["upgrade_until_score"] = brut

                _ok, _errs, normalise = validate_quality_profile(entree)

                self.assertEqual(normalise.get("upgrade_until_score"), attendu)

    def test_une_valeur_illisible_nest_pas_ecrite(self) -> None:
        """On n'invente pas de nombre : le lecteur retombera sur son defaut."""
        for brut in ("beaucoup", [], {}, object()):
            with self.subTest(brut=brut):
                entree = default_quality_profile()
                entree["upgrade_until_score"] = brut

                _ok, _errs, normalise = validate_quality_profile(entree)

                self.assertNotIn("upgrade_until_score", normalise)

    def test_les_deux_autres_cles_hors_defaut_restent_preservees(self) -> None:
        """Non-regression de l'extraction : `custom_rules` et `tier_hierarchy`.

        Elles etaient recopiees en ligne dans `validate_quality_profile` ; le
        correctif les deplace dans `_preserver_cles_hors_defaut`. Ce test
        rougirait si le deplacement en avait perdu une.
        """
        entree = default_quality_profile()
        entree["custom_rules"] = [{"id": "r1"}]
        entree["tier_hierarchy"] = {"enabled": True}

        _ok, _errs, normalise = validate_quality_profile(entree)

        self.assertEqual(normalise.get("custom_rules"), [{"id": "r1"}])
        self.assertTrue(normalise.get("tier_hierarchy", {}).get("enabled"))


if __name__ == "__main__":
    unittest.main()
