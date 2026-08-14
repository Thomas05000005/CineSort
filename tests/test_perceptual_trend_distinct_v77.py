"""GATE AUDIT 2026-06-14 (R7-15) — les compteurs perceptuels comptent des FILMS.

Re-scanner la meme bibliotheque cree un nouveau `run_id` avec les memes `row_id`.
Les compteurs de tendance et d'insight comptaient alors chaque film plusieurs
fois : « N films Reject ce mois » annoncait des re-analyses, pas des films.

CE FICHIER LISAIT LE SOURCE, ET C'ETAIT UN DEFAUT (2026-08-14) :

    self.assertIn("COUNT(DISTINCT row_id) as n", self.src)

Il verrouillait une IMPLEMENTATION, pas une propriete. Preuve : le correctif de
#1010-2 (moyenner PAR FILM avant d'agreger par jour) preserve exactement le
compte par film — le `COUNT(*)` porte desormais sur une sous-requete qui rend
une ligne par film et par jour — et ce test rougissait quand meme. Il aurait
pousse a reecrire le test au lieu du code, ou pire, a renoncer au correctif.

Symetriquement, il serait reste VERT si la chaine avait survecu dans une requete
devenue morte. Les deux reproches de `CLAUDE.md` a cette famille, sur le meme
fichier.

Les deux gates sont donc eprouves sur le COMPORTEMENT, avec le seul scenario qui
les distingue : un film analyse deux fois.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path

from cinesort.infra.db.sqlite_store import SQLiteStore, db_path_for_state_dir

_COLONNES = (
    "row_id, run_id, ts, global_tier_v2, global_score_v2, "
    "visual_score, audio_score, global_score, global_tier, metrics_json, settings_json"
)
_VALEURS = "?, ?, ?, 'reject', 40.0, 0.0, 0.0, 40.0, 'reject', '{}', '{}'"


class PerceptualTrendDistinctTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cs_trend_distinct_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        state = self.tmp / "state"
        state.mkdir()
        self.store = SQLiteStore(db_path_for_state_dir(state))
        self.store.initialize()
        self.store.perceptual._ensure_perceptual_tables()

        # UN film, DEUX analyses le meme jour : le seul scenario qui distingue
        # « compter des films » de « compter des rapports ». UNIQUE(run_id,
        # row_id) impose deux run_id — c'est bien le re-scan de production.
        self.base = time.time() - 3600.0
        with self.store._managed_conn() as conn:
            for run_id, decalage in (("run-1", 0.0), ("run-2", 60.0)):
                conn.execute(
                    f"INSERT INTO perceptual_reports ({_COLONNES}) VALUES ({_VALEURS})",  # noqa: S608
                    ("film_unique", run_id, self.base + decalage),
                )

    def test_trend_compte_des_films_pas_des_rapports(self) -> None:
        points = self.store.perceptual.get_global_score_v2_trend(since_ts=self.base - 86400.0)
        self.assertEqual(len(points), 1, f"un seul jour attendu : {points}")
        self.assertEqual(
            points[0]["count"],
            1,
            "un film analyse deux fois est compte deux fois : la tendance annonce des re-analyses, pas des films",
        )

    def test_tier_since_compte_des_films_pas_des_rapports(self) -> None:
        n = self.store.perceptual.count_v2_tier_since(tier="reject", since_ts=self.base - 86400.0)
        self.assertEqual(
            n,
            1,
            "l'insight « N films Reject » compte les rapports : un film re-scanne en vaut plusieurs",
        )


if __name__ == "__main__":
    unittest.main()
