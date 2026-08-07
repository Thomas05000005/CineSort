"""Une cle API saisie puis enregistree ne doit pas disparaitre sans un mot.

`_apply_tmdb_key_persistence` deduit `remember_key` de l'EXISTANT :

    remember_key = to_bool(settings.get("remember_key"), bool(existing_tmdb_key))

Sur un profil NEUF, `existing_tmdb_key` est vide, donc le defaut est False. Un
payload qui apporte une cle sans porter `remember_key` la voit donc jetee —
`to_save["tmdb_api_key"] = ""` — au premier enregistrement, et sans que rien ne
le signale. L'utilisateur retrouve un champ vide et ne sait pas pourquoi.

La normalisation en LECTURE fait pourtant deja le raisonnement inverse
(`settings_support` : `payload.setdefault("remember_key", bool(tmdb_api_key))`) :
une cle presente vaut intention de la retenir. Les deux cotes divergeaient.

CE QUE LE CORRECTIF NE FAIT PAS : ecraser un choix EXPLICITE. Si le payload
porte `remember_key: false`, la cle est toujours jetee — c'est ce que
l'utilisateur a demande.
"""

from __future__ import annotations

import unittest

from cinesort.ui.api.settings_support import _apply_tmdb_key_persistence


def _persister(payload: dict, existant: dict) -> dict:
    to_save: dict = {}
    _apply_tmdb_key_persistence(to_save, payload, existant)
    return to_save


class ProfilNeufTests(unittest.TestCase):
    def test_une_cle_saisie_sur_un_profil_NEUF_est_conservee(self) -> None:
        """Le defaut. Avant : `tmdb_api_key` ressortait vide."""
        out = _persister({"tmdb_api_key": "CLE-DE-TEST-PAS-UN-SECRET"}, {})

        self.assertEqual(out["tmdb_api_key"], "CLE-DE-TEST-PAS-UN-SECRET")
        self.assertTrue(out["remember_key"])

    def test_un_profil_qui_a_DEJA_une_cle_est_inchange(self) -> None:
        """Non-regression du cas nominal (c'est lui qui marchait deja)."""
        out = _persister({"tmdb_api_key": "nouvelle"}, {"tmdb_api_key": "ancienne"})

        self.assertEqual(out["tmdb_api_key"], "nouvelle")
        self.assertTrue(out["remember_key"])


class LeChoixEXPLICITEGagneTests(unittest.TestCase):
    """Contre-epreuves : sans elles, un correctif qui force toujours
    `remember_key=True` passerait les tests ci-dessus."""

    def test_remember_key_FALSE_explicite_jette_toujours_la_cle(self) -> None:
        out = _persister({"tmdb_api_key": "CLE-DE-TEST", "remember_key": False}, {})

        self.assertEqual(out["tmdb_api_key"], "")
        self.assertFalse(out["remember_key"])

    def test_remember_key_FALSE_efface_aussi_une_cle_EXISTANTE(self) -> None:
        """« Ne plus retenir » doit rester une action effective."""
        out = _persister({"remember_key": False}, {"tmdb_api_key": "ancienne"})

        self.assertEqual(out["tmdb_api_key"], "")

    def test_un_payload_SANS_cle_ni_choix_ne_fabrique_rien(self) -> None:
        out = _persister({}, {})

        self.assertEqual(out["tmdb_api_key"], "")
        self.assertFalse(out["remember_key"])

    def test_une_cle_VIDE_ne_vaut_pas_intention_de_retenir(self) -> None:
        """Regle « sentinelle falsy » du depot : une chaine vide n'est pas une cle."""
        out = _persister({"tmdb_api_key": "   "}, {})

        self.assertFalse(out["remember_key"])
        self.assertEqual(out["tmdb_api_key"], "")


if __name__ == "__main__":
    unittest.main()
