"""La courbe Qualite moyenne PAR FILM, comme le compte affiche a cote.

Constat 2 de l'audit du 2026-08-08 (#1010). Le compte etait deja dedoublonne
(`COUNT(DISTINCT row_id)`, R7-15) mais la moyenne portait sur TOUTES les lignes :
un film analyse plusieurs fois le meme jour pesait autant de fois dans la courbe
et une seule dans le nombre affiche a cote. Les deux colonnes d'une meme ligne
decrivaient deux ensembles differents.

SCENARIO DISCRIMINANT — c'est lui qui compte, pas le nombre de tests :

    film_A : analyse 3 fois le meme jour, scores 10, 10, 10
    film_B : analyse 1 fois,               score  90

    moyenne par RAPPORT : (10+10+10+90) / 4 = 30,0     <- l'ancien calcul
    moyenne par FILM    : (10 + 90) / 2     = 50,0     <- la population du compte

L'ecart n'est pas cosmetique : 30 est Bronze, 50 est Silver.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path

from cinesort.infra.db.sqlite_store import SQLiteStore, db_path_for_state_dir

#: Requete LITTERALE. Elle etait composee par f-string depuis deux
#: constantes : les valeurs interpolees etaient constantes, donc sans
#: risque d'injection, mais il fallait porter une suppression `S608` que
#: l'analyse statique du depot signalait quand meme. Une chaine
#: litterale n'a besoin d'aucune suppression, et se lit mieux.
_INSERT = (
    "INSERT INTO perceptual_reports ("
    "row_id, run_id, ts, global_tier_v2, global_score_v2, "
    "visual_score, audio_score, global_score, global_tier, metrics_json, settings_json"
    ") VALUES (?, ?, ?, 'bronze', ?, 0.0, 0.0, 10.0, 'bronze', '{}', '{}')"
)


class LaMoyenneEstPARFILMTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cs_moy_film_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        state = self.tmp / "state"
        state.mkdir()
        self.store = SQLiteStore(db_path_for_state_dir(state))
        self.store.initialize()
        self.store.perceptual._ensure_perceptual_tables()

        # Tout le meme JOUR : c'est le regroupement par date qui est en cause.
        # UNIQUE(run_id, row_id) impose un run distinct par analyse d'un meme film.
        base = time.time() - 3600.0
        lignes = [
            ("film_A", "run-1", base, 10.0),
            ("film_A", "run-2", base + 60, 10.0),
            ("film_A", "run-3", base + 120, 10.0),
            ("film_B", "run-1", base + 180, 90.0),
        ]
        with self.store._managed_conn() as conn:
            for row_id, run_id, ts, score in lignes:
                conn.execute(
                    _INSERT,
                    (row_id, run_id, ts, score),
                )
        self.depuis = base - 86400.0

    def _points(self) -> list:
        return self.store.perceptual.get_global_score_v2_trend(since_ts=self.depuis)

    def test_un_film_analyse_trois_fois_ne_pese_pas_trois_fois(self) -> None:
        points = self._points()
        self.assertEqual(len(points), 1, f"un seul jour attendu : {points}")
        self.assertEqual(
            points[0]["avg_score"],
            50.0,
            "la moyenne est ponderee par le nombre d'analyses : "
            f"{points[0]['avg_score']} au lieu de 50,0 (elle vaut 30,0 par rapport)",
        )

    def test_le_compte_reste_celui_des_FILMS(self) -> None:
        """CONTRE-EPREUVE. Le passage a une sous-requete change la forme du
        `COUNT` : il ne doit pas se remettre a compter les rapports."""
        points = self._points()
        self.assertEqual(points[0]["count"], 2, "le compte n'est plus celui des films distincts")

    def test_sans_re_analyse_rien_ne_change(self) -> None:
        """CONTRE-EPREUVE : sur une base sans doublon d'analyse, les deux
        semantiques coincident — le correctif ne doit rien deplacer."""
        state2 = self.tmp / "state2"
        state2.mkdir()
        store2 = SQLiteStore(db_path_for_state_dir(state2))
        store2.initialize()
        store2.perceptual._ensure_perceptual_tables()
        base = time.time() - 3600.0
        with store2._managed_conn() as conn:
            for i, score in enumerate((10.0, 90.0)):
                conn.execute(
                    _INSERT,
                    (f"film_{i}", "run-1", base + i, score),
                )
        points = store2.perceptual.get_global_score_v2_trend(since_ts=base - 86400.0)
        self.assertEqual(points[0]["avg_score"], 50.0)
        self.assertEqual(points[0]["count"], 2)


if __name__ == "__main__":
    unittest.main()
