"""Un verrou pose sur le mauvais nom de champ REUSSIT et ne protege RIEN.

`set_field_lock(film_id, field_name, ...)` n'a AUCUNE liste blanche : n'importe
quelle chaine est acceptee, persistee, et rend `{ok: True}`. Le nom n'est
confronte a la realite qu'au moment du rematch, dans `merge_metadata`, qui
compare `locked_fields` aux CLES DE LA ROW.

Un nom qui ne correspond a aucune cle produit donc un verrou parfaitement
silencieux : l'utilisateur voit un cadenas ferme, et son titre est ecrase au
rescan suivant.

CE QUI REND LE PIEGE PROBABLE : la docstring de `set_field_lock` donne
`"title"` et `"year"` en exemple. MESURE (2026-08-07) :

    verrou sur 'proposed_title'  -> titre preserve : True
    verrou sur 'title'           -> titre preserve : FALSE   <- l'exemple !
    verrou sur 'PROPOSED_TITLE'  -> titre preserve : True    (insensible a la casse)

Cabler l'interface sur l'exemple de la docstring aurait livre une
fonctionnalite entierement inoperante, avec `ok: True` a chaque etape.

CE FICHIER FIXE LES NOMS QUI PROTEGENT. Toute interface de verrouillage doit
employer ceux-la, et ce test rougit si `merge_metadata` cesse de les honorer.
"""

from __future__ import annotations

import unittest

from cinesort.app.merge_metadata import merge_metadata

#: Les seuls noms qu'une UI de verrouillage doit poser, et la cle de row qu'ils
#: protegent. Ce sont des CLES DE PLAN ROW, pas des libelles d'affichage.
NOMS_QUI_PROTEGENT = ("proposed_title", "proposed_year")

#: Noms plausibles mais INOPERANTS — ils viennent des libelles de l'UI ou de la
#: docstring de `set_field_lock`.
NOMS_QUI_NE_PROTEGENT_PAS = ("title", "year", "titre", "annee")


def _rematch(verrous: tuple[str, ...] | list[str]) -> dict:
    """Rejoue ce que fait `_rematch_tmdb_and_update_plan` : la nouvelle row
    TMDb ecrase l'ancienne, sauf sur les champs verrouilles."""
    ancienne = {"proposed_title": "Le Bon la Brute et le Truand", "proposed_year": 1966, "row_id": "r1"}
    nouvelle = {"proposed_title": "The Good, the Bad and the Ugly", "proposed_year": 1970, "row_id": "r1"}
    return merge_metadata(source=nouvelle, target=ancienne, locked_fields=list(verrous), replace_data=True)


class LesNomsQuiPROTEGENTTests(unittest.TestCase):
    def test_proposed_title_preserve_la_correction_de_l_utilisateur(self) -> None:
        out = _rematch(["proposed_title"])

        self.assertEqual(out["proposed_title"], "Le Bon la Brute et le Truand")

    def test_proposed_year_preserve_l_annee_corrigee(self) -> None:
        out = _rematch(["proposed_year"])

        self.assertEqual(out["proposed_year"], 1966)

    def test_la_casse_n_a_pas_d_importance(self) -> None:
        """Documente par `merge_metadata` : une UI peut envoyer la casse qu'elle
        veut sans changer le resultat."""
        out = _rematch(["PROPOSED_TITLE"])

        self.assertEqual(out["proposed_title"], "Le Bon la Brute et le Truand")

    def test_tous_les_noms_de_la_liste_protegent_VRAIMENT(self) -> None:
        """Le garde : si `merge_metadata` cesse d'honorer l'un d'eux, ou si un
        nom est ajoute a la liste sans etre operant, ce test rougit."""
        for nom in NOMS_QUI_PROTEGENT:
            with self.subTest(champ=nom):
                avant = _rematch([])[nom]
                apres = _rematch([nom])[nom]
                self.assertNotEqual(
                    avant,
                    apres,
                    f"le verrou sur {nom!r} ne change RIEN : il est inoperant, "
                    f"et l'utilisateur verrait un cadenas qui ne protege pas",
                )


class LesNomsQuiNEProtegentPASTests(unittest.TestCase):
    """CONTRE-EPREUVE, et elle porte le sens du fichier.

    Sans elle, une implementation de `merge_metadata` qui preserverait TOUT
    passerait les tests ci-dessus.
    """

    def test_les_libelles_d_affichage_sont_INOPERANTS(self) -> None:
        for nom in NOMS_QUI_NE_PROTEGENT_PAS:
            with self.subTest(champ=nom):
                out = _rematch([nom])
                self.assertEqual(
                    out["proposed_title"],
                    "The Good, the Bad and the Ugly",
                    f"{nom!r} protege le titre : la liste NOMS_QUI_NE_PROTEGENT_PAS est perimee",
                )

    def test_SANS_verrou_le_rematch_ecrase_bien(self) -> None:
        """Contre-epreuve de la contre-epreuve : si le rematch n'ecrasait
        jamais rien, tout ce fichier serait vide de sens."""
        out = _rematch([])

        self.assertEqual(out["proposed_title"], "The Good, the Bad and the Ugly")
        self.assertEqual(out["proposed_year"], 1970)


if __name__ == "__main__":
    unittest.main()
