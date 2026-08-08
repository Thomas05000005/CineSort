"""Poser un verrou sur un nom de champ INCONNU doit ECHOUER, pas reussir a vide.

LE DEFAUT. `set_field_lock` n'avait aucune liste blanche : n'importe quelle
chaine etait acceptee, persistee, et rendait `{ok: True}`. Le nom n'est confronte
a la realite qu'au rematch, dans `merge_metadata`, qui le compare aux CLES de la
nouvelle plan row. Un nom hors de ces cles donne donc un verrou parfaitement
inoperant : cadenas ferme a l'ecran, titre ecrase au rescan suivant.

C'est un ECHEC PRESENTE COMME UN SUCCES, et sur un chemin qui perd de la donnee.

CE QUI RENDAIT LE PIEGE PROBABLE, ET DURABLE :

  - la docstring donnait `"title"` et `"year"` en exemple -- deux noms qui ne
    protegent rien (mesure du 2026-08-07) ;
  - `tests/test_vp_g_field_locks_ui_endpoints.py` posait ces memes noms en
    **douze** endroits et assertait `ok: True`. La batterie VERROUILLAIT donc le
    defaut : cabler l'interface sur son exemple aurait livre une fonctionnalite
    entierement vide, verte de bout en bout.

LA LISTE BLANCHE EST DERIVEE, PAS RECOPIEE. Mesure du 2026-08-08 :
`plan_row_to_jsonable` preserve exactement les 31 noms de champs de `PlanRow`
-- zero cle ajoutee, zero perdue. Ces champs sont donc la source de verite, et
une liste ecrite a la main divergerait au premier champ ajoute au dataclass.
"""

from __future__ import annotations

import dataclasses
import unittest

from cinesort.domain import core
from cinesort.ui.api import library_support
from cinesort.ui.api.library_support import _CHAMPS_VERROUILLABLES
from tests.test_vp_g_field_locks_ui_endpoints import _FakeApi

#: Noms plausibles mais INOPERANTS : libelles d'affichage, ou l'ancien exemple
#: de la docstring.
NOMS_QUI_NE_PROTEGENT_PAS = ("title", "year", "titre", "annee", "Title", "n_importe_quoi")

#: Cles de plan row reellement honorees par `merge_metadata`.
NOMS_QUI_PROTEGENT = ("proposed_title", "proposed_year")


class UnNomInconnuEstREFUSETests(unittest.TestCase):
    def test_chaque_nom_inoperant_est_rejete(self) -> None:
        for nom in NOMS_QUI_NE_PROTEGENT_PAS:
            with self.subTest(nom=nom):
                api = _FakeApi()

                res = library_support.set_field_lock(api, film_id="tmdb:1", field_name=nom, locked_value="x")

                self.assertFalse(
                    res["ok"],
                    f"« {nom} » a ete accepte : le verrou serait pose, visible, et ne protegerait RIEN.",
                )

    def test_rien_n_est_PERSISTE_quand_le_nom_est_refuse(self) -> None:
        """Un refus qui ecrit quand meme laisserait le cadenas a l'ecran."""
        api = _FakeApi()

        library_support.set_field_lock(api, film_id="tmdb:1", field_name="title", locked_value="x")

        self.assertEqual(
            len(api._store.field_locks.calls),
            0,
            "le repo a ete appele malgre le refus",
        )

    def test_les_noms_OPERANTS_passent_toujours(self) -> None:
        """Contre-epreuve : la garde ne doit pas tout fermer."""
        for nom in NOMS_QUI_PROTEGENT:
            with self.subTest(nom=nom):
                api = _FakeApi()

                res = library_support.set_field_lock(api, film_id="tmdb:1", field_name=nom, locked_value="x")

                self.assertTrue(res["ok"], f"« {nom} » protege reellement et doit etre accepte")

    def test_la_casse_n_a_pas_d_importance(self) -> None:
        """`merge_metadata` compare en minuscules ; la garde doit s'aligner."""
        api = _FakeApi()

        res = library_support.set_field_lock(api, film_id="tmdb:1", field_name="PROPOSED_TITLE", locked_value="x")

        self.assertTrue(res["ok"])


class UnVerrouFANTOMEResteEFFACABLETests(unittest.TestCase):
    """La restriction va sur le chemin qui CREE, jamais sur celui qui NETTOIE.

    Des verrous poses avant l'existence de la garde dorment dans les bases
    existantes. Valider aussi a la suppression les rendrait INEFFACABLES :
    l'utilisateur verrait un cadenas qu'aucun geste ne peut retirer.
    """

    def test_clear_accepte_un_nom_hors_liste_blanche(self) -> None:
        api = _FakeApi()

        res = library_support.clear_field_lock(api, "tmdb:1", "title")

        self.assertTrue(
            res["ok"],
            "un verrou fantome deja en base doit rester supprimable",
        )

    def test_clear_atteint_REELLEMENT_le_repo(self) -> None:
        """Un `ok: True` sans appel au repo serait le meme defaut a l'envers."""
        api = _FakeApi()

        library_support.clear_field_lock(api, "tmdb:1", "year")

        self.assertTrue(
            any(c[0] == "clear_lock" for c in api._store.field_locks.calls),
            f"aucun clear_lock transmis au repo : {api._store.field_locks.calls}",
        )


class LaListeBlancheEstDERIVEETests(unittest.TestCase):
    def test_elle_vaut_exactement_les_champs_de_PlanRow(self) -> None:
        """Si elle etait recopiee a la main, elle divergerait en silence."""
        attendu = {f.name.lower() for f in dataclasses.fields(core.PlanRow)}

        self.assertEqual(set(_CHAMPS_VERROUILLABLES), attendu)

    def test_elle_contient_les_deux_noms_que_l_UI_doit_poser(self) -> None:
        for nom in NOMS_QUI_PROTEGENT:
            self.assertIn(nom, _CHAMPS_VERROUILLABLES)

    def test_elle_ne_contient_AUCUN_libelle_d_affichage(self) -> None:
        for nom in ("title", "year", "titre", "annee"):
            self.assertNotIn(nom, _CHAMPS_VERROUILLABLES)


if __name__ == "__main__":
    unittest.main()
