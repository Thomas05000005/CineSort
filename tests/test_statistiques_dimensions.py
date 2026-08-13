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

from cinesort.ui.api import library_support
from cinesort.ui.api.library_support import (
    SCORING_ROLLUP_DIMENSIONS,
    _classify_resolution,
    _extract_group_key,
)

_VUE = Path(__file__).resolve().parents[1] / "web" / "dashboard" / "views" / "statistiques.js"

#: Une row qui porte TOUS les signaux qu'une bibliotheque complete peut fournir.
#: Les cles sont celles que `_build_library_rows` construit reellement.
_ROW_COMPLETE: Dict[str, Any] = {
    "row_id": "r1",
    "title": "Dune",
    "year": 2024,
    "codec": "x265",
    # DERIVEE DE LA PRODUCTION, PAS ECRITE A LA MAIN. Cette valeur etait
    # « 2160p » — une chaine que `_classify_resolution` n'emet JAMAIS (elle rend
    # 4k / 1080p / 720p / sd / unknown). La fixture eprouvait donc une row que la
    # bibliotheque ne produit pas, et la « mesure » de la PR annoncait « 2160P »
    # la ou la vraie sortie est « 4K ».
    "resolution": _classify_resolution(3840, 2160),
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


class LesVALEURSDeLaFixtureViennentDeLaPRODUCTIONTests(unittest.TestCase):
    """UNE FIXTURE ECRITE A LA MAIN NE PROUVE QUE SA COHERENCE AVEC ELLE-MEME.

    Ce fichier a porte `resolution: "2160p"` — une chaine que
    `_classify_resolution` n'emet JAMAIS (elle rend 4k / 1080p / 720p / sd /
    unknown). La row eprouvee n'etait donc pas celle que la bibliotheque produit,
    et la « mesure » annoncait « 2160P » la ou la vraie sortie est « 4K ».

    Les valeurs classifiables sont desormais DERIVEES en appelant la fonction de
    production.

    CE QUI RESTE OUVERT, ET IL FAUT LE DIRE PLUTOT QUE DE LE MASQUER. Ce test
    verifie les VALEURS, pas les CLES : une dimension qui lirait une cle absente
    de `_build_library_rows` passerait encore, a condition qu'on ajoute cette cle
    a la fixture. Fermer cela demanderait de construire une row par le vrai
    constructeur, qui exige une `api` complete (`_build_library_rows(api, run_id)`)
    — un harnais qui n'a pas sa place dans un test unitaire de dimensions. Le
    garde reel contre cette famille reste le test de bout en bout de l'onglet.
    """

    def test_la_resolution_de_la_fixture_est_une_valeur_REELLE(self) -> None:
        emises = {
            _classify_resolution(3840, 2160),
            _classify_resolution(1920, 1080),
            _classify_resolution(1280, 720),
            _classify_resolution(720, 480),
        }
        self.assertIn(
            _ROW_COMPLETE["resolution"],
            emises,
            f"la fixture porte une resolution que la production n'emet jamais ; valeurs reelles : {sorted(emises)}",
        )

    def test_la_dimension_resolution_rend_bien_la_forme_ATTENDUE(self) -> None:
        """Et pas « 2160P » : c'est la sortie que l'utilisateur verra."""
        self.assertEqual(_extract_group_key(_ROW_COMPLETE, "resolution"), "4K")


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


class UneDimensionInconnueNeReconstruitPasLaBibliothequeTests(unittest.TestCase):
    """Constat de revue, verifie et retenu — mais pas le correctif propose.

    Le RESULTAT etait deja juste : `_extract_group_key` rend `None` pour toute
    dimension inconnue, donc aucun bucket, donc `groups: []`. Ce qui n'allait pas
    est le CHEMIN : on payait d'abord `_build_library_rows`, la reconstruction
    complete de la bibliotheque, pour n'en tirer aucun groupe.

    La sortie immediate suggeree rendait `{"groups": []}` — SANS `ok` ni `by`,
    que portent toutes les autres sorties de la fonction et que le front lit. La
    prendre telle quelle aurait echange un gaspillage contre une regression.
    """

    def setUp(self) -> None:
        self.appels: list[str] = []

    def test_une_dimension_inconnue_sort_AVANT_de_construire_les_rows(self) -> None:
        appels = self.appels
        vrai_build = library_support._build_library_rows
        vrai_resolve = library_support._resolve_run_id

        def _build(*_a, **_k):
            appels.append("_build_library_rows")
            return []

        def _resolve(*_a, **_k):
            appels.append("_resolve_run_id")
            return "run-1"

        library_support._build_library_rows = _build
        library_support._resolve_run_id = _resolve
        try:
            res = library_support.get_scoring_rollup(object(), by="director")
        finally:
            library_support._build_library_rows = vrai_build
            library_support._resolve_run_id = vrai_resolve

        self.assertNotIn(
            "_build_library_rows",
            appels,
            "la bibliotheque entiere est reconstruite pour une dimension qui ne peut rien grouper",
        )
        # ASSERTER LA FORME, PAS SEULEMENT LE RACCOURCI. C'est ce que le
        # correctif suggere cassait.
        self.assertEqual(res, {"ok": True, "by": "director", "groups": []})

    def test_une_dimension_SUPPORTEE_passe_toujours_par_les_rows(self) -> None:
        """LE CONTRE-TEST. Sans lui, une sortie immediate posee trop haut —
        avant toute dimension — satisferait le test precedent en cassant tout."""
        appels = self.appels
        vrai_build = library_support._build_library_rows
        vrai_resolve = library_support._resolve_run_id

        def _build(*_a, **_k):
            appels.append("_build_library_rows")
            return []

        def _resolve(*_a, **_k):
            return "run-1"

        library_support._build_library_rows = _build
        library_support._resolve_run_id = _resolve
        try:
            library_support.get_scoring_rollup(object(), by="decade")
        finally:
            library_support._build_library_rows = vrai_build
            library_support._resolve_run_id = vrai_resolve

        self.assertIn(
            "_build_library_rows",
            appels,
            "une dimension supportee ne construit plus les rows : la sortie immediate est trop large",
        )


if __name__ == "__main__":
    unittest.main()
