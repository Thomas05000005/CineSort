"""`get_film_full` doit exposer le `film_id` : sans lui, l'UI ne peut nommer le film.

POURQUOI CE CHAMP EXISTE. Les trois endpoints de verrous (`set_field_lock`,
`list_field_locks`, `clear_field_lock`) exigent un `film_id` de la forme
`tmdb:<id>` ou `path:<sha1(folder|video)>`.

La seconde forme n'est PAS calculable dans un navigateur — elle demande un SHA-1
du chemin. Le front n'avait donc AUCUN moyen de designer le film, et la
fonctionnalite de verrous restait inatteignable depuis l'interface :
`grep -rn "set_field_lock" web/` ne rendait rien avant cette vague.

CE QUE CE TEST VERROUILLE, ET CE QU'IL NE VERROUILLE PAS. Il exige que le champ
soit present et NON VIDE, et surtout qu'il vaille exactement ce que
`compute_film_id` rend sur la meme row — c'est-a-dire l'identite sous laquelle
`_rematch_tmdb_and_update_plan` cherche les verrous. Un `film_id` present mais
calcule autrement rendrait les verrous invisibles au re-match tout en donnant
une interface d'apparence fonctionnelle.
"""

from __future__ import annotations

import unittest
from unittest import mock

from cinesort.domain.film_identity import compute_film_id
from cinesort.ui.api import film_support


def _row(**extra):
    base = {
        "row_id": "r1",
        "folder": "D:/Films/Heat (1995)",
        "video": "Heat.1995.mkv",
        "proposed_title": "Heat",
        "proposed_year": 1995,
        "candidates": [],
    }
    base.update(extra)
    return base


def _appeler(row):
    """Execute `get_film_full` en neutralisant tout ce qui touche au disque et a TMDb.

    LE STORE N'EST PAS UN `MagicMock` NU, ET C'EST IMPORTANT. Un MagicMock rend
    un objet TRUTHY a `get_tmdb_override(...)`, donc la branche d'override
    s'execute ; et `int(MagicMock())` vaut **1** en Python, si bien que la row
    repartait avec `tmdb_id = 1` et une identite `tmdb:1` sortie de nulle part.
    Le double fabriquait un etat que la production ne produit jamais.
    """
    store = mock.MagicMock()
    store.film_modal.get_tmdb_override.return_value = None
    api = mock.MagicMock()
    api.settings.get_settings.return_value = {"state_dir": "X"}
    api._get_or_create_infra.return_value = (store, mock.MagicMock())
    with (
        mock.patch.object(film_support, "_resolve_run_id", return_value="run-1"),
        mock.patch.object(film_support, "_find_plan_row", return_value=row),
        mock.patch.object(film_support, "_fetch_poster_url", return_value=None),
        mock.patch.object(film_support, "_fetch_tmdb_extras", return_value={}),
        mock.patch.object(film_support.film_history_support, "get_film_history", return_value={"ok": True}),
    ):
        return film_support.get_film_full(api, "run-1", "r1")


class LIdentiteDuFilmEstEXPOSEETests(unittest.TestCase):
    def test_le_champ_est_present_et_non_vide(self) -> None:
        res = _appeler(_row())

        self.assertIn("film_id", res, "sans ce champ, l'UI ne peut nommer le film")
        self.assertTrue(res["film_id"], "identite vide : les endpoints de verrous refuseraient l'appel")

    def test_elle_vaut_EXACTEMENT_compute_film_id(self) -> None:
        """Une identite calculee autrement rendrait les verrous invisibles au
        re-match, tout en donnant une interface d'apparence fonctionnelle."""
        row = _row()

        res = _appeler(row)

        self.assertEqual(res["film_id"], compute_film_id(row))

    def test_un_film_sans_tmdb_id_recoit_une_identite_de_CHEMIN(self) -> None:
        """C'est le cas majoritaire, et celui que le navigateur ne peut pas
        calculer : `path:<sha1>`."""
        res = _appeler(_row())

        self.assertTrue(
            str(res["film_id"]).startswith("path:"),
            f"attendu une identite de chemin, obtenu {res['film_id']!r}",
        )

    def test_un_film_AVEC_tmdb_id_recoit_l_identite_tmdb(self) -> None:
        res = _appeler(_row(tmdb_id=603))

        self.assertEqual(res["film_id"], "tmdb:603")


if __name__ == "__main__":
    unittest.main()
