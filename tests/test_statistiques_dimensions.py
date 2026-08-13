"""Toute dimension proposee par l'ecran Statistiques doit pouvoir rendre un groupe.

POURQUOI CE FICHIER EXISTE. L'onglet « Scores » listait cinq dimensions, dont
« Realisateur ». Cote backend, `_extract_group_key(row, "director")` rend `None`
**quelle que soit la row** : le champ `director` n'existe sur aucune row de
`_build_library_rows`. Le bouton etait donc mort par construction — un clic, et
l'ecran repondait « Aucun groupe sur cette dimension », pour toujours.

Le commentaire de la vue disait pourtant « Dimensions REELLES de
`get_scoring_rollup` (library_support.py:2253-2268) » : l'inventaire avait ete
fait en lisant les branches `if dim == ...`, sans remarquer que l'une d'elles ne
faisait que renvoyer `None`. Enumerer les branches ne prouve pas qu'elles
produisent quelque chose.

CE QUE CES TESTS EPROUVENT.

1. Un test de COMPORTEMENT : pour chaque dimension declaree supportee, une row
   complete doit produire une cle de groupe non vide. C'est lui qui attrape une
   branche qui ne rend rien — une comparaison de chaine de code source, elle,
   resterait verte sur `return None`.
2. Un test de CONTRAT entre les deux bouts : la liste de boutons de la vue et la
   liste du backend sont derivees l'une de l'autre, pour qu'aucune des deux ne
   puisse deriver seule (meme famille que `tests/test_contract_ui_api.py`).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any, Dict, Set

from cinesort.ui.api.library_support import SCORING_ROLLUP_DIMENSIONS, _extract_group_key

_VUE = Path(__file__).resolve().parents[1] / "web" / "dashboard" / "views" / "statistiques.js"

#: Une row qui porte TOUS les signaux qu'une bibliotheque complete peut fournir.
#: Les cles sont celles que `_build_library_rows` construit reellement.
_ROW_COMPLETE: Dict[str, Any] = {
    "row_id": "r1",
    "title": "Dune",
    "year": 2024,
    "codec": "x265",
    "resolution": "2160p",
    "grain_era_v2": "modern_digital",
    "tmdb_collection_name": "Dune (collection)",
    "score_v2": 88.0,
    "display_tier": "gold",
}


def _dimensions_de_la_vue() -> Set[str]:
    """Les identifiants des boutons de dimension declares par la vue."""
    source = _VUE.read_text(encoding="utf-8")
    bloc = re.search(r"const DIMENSIONS\s*=\s*\[(.*?)\];", source, re.S)
    assert bloc is not None, "la vue Statistiques ne declare plus de liste DIMENSIONS"
    return set(re.findall(r'id:\s*"([a-z_]+)"', bloc.group(1)))


class ChaqueDimensionProposeeProduitUnGroupeTests(unittest.TestCase):
    def test_une_row_complete_rend_une_cle_pour_chaque_dimension_supportee(self) -> None:
        """LE test qui aurait attrape « Realisateur ».

        Une dimension qui ne sait rien extraire d'une row COMPLETE ne saura rien
        extraire d'aucune row : l'ecran est vide par construction, pas par
        manque de donnees.
        """
        for dim in SCORING_ROLLUP_DIMENSIONS:
            with self.subTest(dimension=dim):
                cle = _extract_group_key(_ROW_COMPLETE, dim)
                self.assertTrue(
                    cle,
                    f"la dimension « {dim} » ne rend aucune cle sur une row complete : "
                    "l'onglet Scores affichera « Aucun groupe » quoi que fasse l'utilisateur",
                )

    def test_la_vue_ne_propose_que_des_dimensions_supportees(self) -> None:
        vue = _dimensions_de_la_vue()
        mortes = sorted(vue - set(SCORING_ROLLUP_DIMENSIONS))
        self.assertEqual(
            mortes,
            [],
            f"la vue Statistiques propose {mortes}, que le backend ne sait pas grouper",
        )

    def test_la_vue_n_oublie_aucune_dimension_supportee(self) -> None:
        """Une dimension gratuite (la donnee est deja dans la row) mais absente de
        l'ecran, c'est du travail deja fait que l'utilisateur ne voit pas."""
        vue = _dimensions_de_la_vue()
        oubliees = sorted(set(SCORING_ROLLUP_DIMENSIONS) - vue)
        self.assertEqual(
            oubliees,
            [],
            f"le backend sait grouper par {oubliees}, la vue ne le propose pas",
        )


if __name__ == "__main__":
    unittest.main()
