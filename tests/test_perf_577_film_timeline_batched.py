"""GATE #577 — `get_film_timeline` ne fait plus N+1 requetes SQLite.

Avant correctif, la timeline d'un film ouvrait, PAR RUN ou le film apparait :
1 requete `get_quality_report`, 1 `list_apply_batches_for_run`, puis 1
`list_apply_operations_by_row` par batch. Chaque appel de repository ouvre sa
PROPRE connexion SQLite (`SQLiteStore._managed_conn` -> `_connect`), et le
controle de schema en ouvre une seconde : le cout reel est double du nombre de
requetes.

Grandeur mesuree : le nombre de connexions SQLite ouvertes (deterministe).
Mesure sur DEUX tailles, avec 5 batches par run :

    runs | connexions avant | connexions apres
    -----+------------------+-----------------
      10 |              143 |                9
      40 |              563 |                9

Loi d'echelle constatee : avant = 14 x runs + 3 ; apres = constante.

Les tests ci-dessous utilisent un VRAI `SQLiteStore` (aucun faux repository) et
verifient d'abord le CONTENU de la timeline — un compteur de requetes seul ne
distinguerait pas "moins de requetes" de "plus rien ne remonte".
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cinesort.infra.db.repositories.apply as apply_repo_module
import cinesort.infra.db.repositories.quality as quality_repo_module
from cinesort.domain.film_history import get_film_timeline, list_films_overview
from cinesort.infra.db.sqlite_store import SQLiteStore

FILM_ID = "tmdb:27205"


class _ConnectionCounter:
    """Compte les connexions SQLite reellement ouvertes par le store."""

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        self.count = 0
        self._real = store._connect

    def __enter__(self) -> "_ConnectionCounter":
        def counting() -> Any:
            self.count += 1
            return self._real()

        self.store._connect = counting  # type: ignore[method-assign]
        return self

    def __exit__(self, *exc: Any) -> None:
        self.store._connect = self._real  # type: ignore[method-assign]


class _Fixture:
    """Bibliotheque de test : runs + plan.jsonl + rapports qualite + journal apply."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.state_dir = root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.store = SQLiteStore(self.state_dir / "cinesort.sqlite")
        self.store.initialize()

    def add_run(self, run_id: str, *, ts: float, rows: List[Dict[str, Any]]) -> None:
        run_dir = self.state_dir / "runs" / f"tri_films_{run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)
        with open(run_dir / "plan.jsonl", "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.store.run.insert_run_pending(
            run_id=run_id,
            root=str(self.root),
            state_dir=str(self.state_dir),
            config={},
            created_ts=ts,
        )
        self.store.run.mark_run_running(run_id, started_ts=ts)

    def add_quality(self, run_id: str, row_id: str, *, score: int, tier: str, ts: float) -> None:
        self.store.quality.upsert_quality_report(
            run_id=run_id,
            row_id=row_id,
            score=score,
            tier=tier,
            reasons=[],
            metrics={},
            profile_id="default",
            profile_version=1,
            ts=ts,
        )

    def add_batch(
        self,
        run_id: str,
        *,
        ts: float,
        dry_run: bool = False,
        ops: Tuple[Tuple[str, str, str, str], ...] = (),
    ) -> str:
        batch_id = self.store.apply.insert_apply_batch(
            run_id=run_id,
            dry_run=dry_run,
            quarantine_unapproved=False,
            started_ts=ts,
        )
        for index, (row_id, op_type, src, dst) in enumerate(ops):
            self.store.apply.append_apply_operation(
                batch_id=batch_id,
                op_index=index,
                op_type=op_type,
                src_path=src,
                dst_path=dst,
                reversible=True,
                row_id=row_id,
                ts=ts,
            )
        return str(batch_id)


def _plan_row(
    row_id: str,
    *,
    title: str = "Inception",
    year: int = 2010,
    confidence: int = 90,
    tmdb_id: int = 27205,
) -> Dict[str, Any]:
    return {
        "row_id": row_id,
        "proposed_title": title,
        "proposed_year": year,
        "candidates": [{"tmdb_id": tmdb_id}],
        "confidence": confidence,
        "proposed_source": "tmdb",
    }


class FilmTimelineContentTests(unittest.TestCase):
    """Le contenu de la timeline doit rester exact, y compris les cas d'exclusion."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_p577c_"))
        self.fx = _Fixture(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_timeline_complete_avec_exclusions(self) -> None:
        # run A : le film (row S|1), un rapport qualite, un batch reel avec 2 ops
        # sur ce row + un batch DRY-RUN qui doit etre ignore.
        self.fx.add_run(
            "runA",
            ts=1000.0,
            rows=[_plan_row("S|1"), _plan_row("S|9", title="Autre", year=1999, tmdb_id=111)],
        )
        self.fx.add_quality("runA", "S|1", score=70, tier="B", ts=1001.0)
        self.fx.add_batch(
            "runA",
            ts=1002.0,
            ops=(
                ("S|1", "MKDIR", "", "/lib/Inception (2010)"),
                ("S|1", "MOVE_DIR", "/dl/Inception.1080p", "/lib/Inception (2010)"),
            ),
        )
        self.fx.add_batch("runA", ts=1003.0, dry_run=True, ops=(("S|1", "MOVE_DIR", "/x", "/y"),))

        # run B : meme film mais AUTRE row_id, un batch dont les ops portent sur
        # un row_id different (aucun evenement apply attendu).
        self.fx.add_run("runB", ts=2000.0, rows=[_plan_row("S|2", confidence=95)])
        self.fx.add_quality("runB", "S|2", score=88, tier="A", ts=2001.0)
        self.fx.add_batch("runB", ts=2002.0, ops=(("S|7", "MOVE_DIR", "/a", "/b"),))

        # run C : le film est absent du plan -> aucun evenement.
        self.fx.add_run("runC", ts=3000.0, rows=[_plan_row("S|5", title="Interstellar", year=2014, tmdb_id=157336)])

        result = get_film_timeline(FILM_ID, self.fx.state_dir, self.fx.store)

        self.assertEqual(result["film_id"], FILM_ID)
        self.assertEqual(result["title"], "Inception")
        self.assertEqual(result["year"], 2010)
        self.assertEqual(result["scan_count"], 2, "runC ne contient pas le film")
        self.assertEqual(result["apply_count"], 1, "le batch dry-run et le batch d'un autre row sont exclus")
        self.assertEqual(result["current_score"], 88)

        types = [event["type"] for event in result["events"]]
        self.assertEqual(types, ["scan", "score", "apply", "scan", "score"])

        apply_event = result["events"][2]
        self.assertEqual(apply_event["run_id"], "runA")
        self.assertEqual(apply_event["ts"], 1002.0)
        self.assertEqual(
            apply_event["operations"],
            [
                {"op": "MKDIR", "from": "", "to": "/lib/Inception (2010)", "undo_status": "PENDING"},
                {
                    "op": "MOVE_DIR",
                    "from": "/dl/Inception.1080p",
                    "to": "/lib/Inception (2010)",
                    "undo_status": "PENDING",
                },
            ],
        )

        score_events = [event for event in result["events"] if event["type"] == "score"]
        self.assertEqual([event["score"] for event in score_events], [70, 88])
        self.assertEqual([event["delta"] for event in score_events], [0, 18])
        self.assertEqual([event["tier"] for event in score_events], ["B", "A"])

    def test_list_films_overview_conserve_scores_et_tiers(self) -> None:
        self.fx.add_run(
            "runA",
            ts=1000.0,
            rows=[
                _plan_row("S|1"),
                _plan_row("S|2", title="Interstellar", year=2014, tmdb_id=157336),
                _plan_row("S|3", title="Tenet", year=2020, tmdb_id=577922),
            ],
        )
        self.fx.store.run.mark_run_done("runA", stats={}, ended_ts=1500.0)
        self.fx.add_quality("runA", "S|1", score=70, tier="B", ts=1001.0)
        self.fx.add_quality("runA", "S|3", score=91, tier="A", ts=1002.0)

        films = list_films_overview(self.fx.state_dir, self.fx.store, limit=10)
        by_row = {film["row_id"]: film for film in films}
        self.assertEqual(by_row["S|1"]["score"], 70)
        self.assertEqual(by_row["S|1"]["tier"], "B")
        self.assertIsNone(by_row["S|2"]["score"], "un film sans rapport doit rester a None")
        self.assertEqual(by_row["S|2"]["tier"], "")
        self.assertEqual(by_row["S|3"]["score"], 91)
        self.assertEqual(by_row["S|3"]["tier"], "A")


class FilmTimelineQueryBudgetTests(unittest.TestCase):
    """Le nombre de connexions SQLite ne doit plus dependre du nombre de runs."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_p577q_"))

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _measure(self, runs: int, batches_per_run: int) -> Tuple[int, Dict[str, Any]]:
        root = self._tmp / f"lib_{runs}"
        fixture = _Fixture(root)
        for index in range(runs):
            run_id = f"run{index:03d}"
            row_id = f"S|{index}"
            ts = 1000.0 + index
            fixture.add_run(run_id, ts=ts, rows=[_plan_row(row_id)])
            fixture.add_quality(run_id, row_id, score=60 + index, tier="B", ts=ts)
            for batch in range(batches_per_run):
                fixture.add_batch(
                    run_id,
                    ts=ts + 0.1 * batch,
                    ops=((row_id, "MOVE_DIR", f"/src/{index}/{batch}", f"/dst/{index}/{batch}"),),
                )
        with _ConnectionCounter(fixture.store) as counter:
            result = get_film_timeline(FILM_ID, fixture.state_dir, fixture.store)
        return counter.count, result

    def test_connexions_constantes_sur_deux_tailles(self) -> None:
        small_conns, small_result = self._measure(4, 3)
        large_conns, large_result = self._measure(16, 3)

        # 1) La timeline grandit bien (sinon on mesurerait un budget de requetes
        #    sur une timeline vide, ce qui ne prouverait rien).
        self.assertEqual(small_result["scan_count"], 4)
        self.assertEqual(large_result["scan_count"], 16)
        self.assertEqual(small_result["apply_count"], 4 * 3)
        self.assertEqual(large_result["apply_count"], 16 * 3)

        # 2) Le cout DB, lui, ne bouge pas.
        self.assertEqual(
            small_conns,
            large_conns,
            f"le nombre de connexions doit etre constant ({small_conns} vs {large_conns})",
        )
        self.assertLessEqual(large_conns, 16, "budget de connexions attendu : une poignee, pas un multiple des runs")


class BatchedRepositoryEquivalenceTests(unittest.TestCase):
    """Les methodes groupees doivent rendre EXACTEMENT ce que rendaient les unitaires."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_p577e_"))
        self.fx = _Fixture(self._tmp)
        self.batch_ids: List[str] = []
        for index in range(3):
            run_id = f"run{index}"
            ts = 1000.0 + index
            self.fx.add_run(run_id, ts=ts, rows=[_plan_row(f"S|{index}")])
            self.fx.add_quality(run_id, f"S|{index}", score=50 + index, tier="C", ts=ts)
            for batch in range(2):
                self.batch_ids.append(
                    self.fx.add_batch(
                        run_id,
                        ts=ts + 0.1 * batch,
                        ops=((f"S|{index}", "MOVE_DIR", f"/s/{index}/{batch}", f"/d/{index}/{batch}"),),
                    )
                )

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_batches_groupes_identiques_aux_unitaires(self) -> None:
        run_ids = [f"run{index}" for index in range(3)]
        grouped = self.fx.store.apply.list_apply_batches_for_runs(run_ids=run_ids, limit_per_run=10)
        for run_id in run_ids:
            expected = self.fx.store.apply.list_apply_batches_for_run(run_id=run_id, limit=10)
            self.assertEqual(grouped.get(run_id), expected, f"divergence sur {run_id}")

    def test_batches_groupes_respectent_la_borne_par_run(self) -> None:
        run_ids = [f"run{index}" for index in range(3)]
        grouped = self.fx.store.apply.list_apply_batches_for_runs(run_ids=run_ids, limit_per_run=1)
        for run_id in run_ids:
            expected = self.fx.store.apply.list_apply_batches_for_run(run_id=run_id, limit=1)
            self.assertEqual(len(grouped.get(run_id) or []), 1)
            self.assertEqual(grouped.get(run_id), expected)

    def test_operations_groupees_identiques_aux_unitaires(self) -> None:
        row_ids = [f"S|{index}" for index in range(3)]
        grouped = self.fx.store.apply.list_apply_operations_for_rows(batch_ids=self.batch_ids, row_ids=row_ids)
        found = 0
        for batch_id in self.batch_ids:
            for row_id in row_ids:
                expected = self.fx.store.apply.list_apply_operations_by_row(batch_id=batch_id, row_id=row_id)
                self.assertEqual(grouped.get((batch_id, row_id), []), expected)
                found += len(expected)
        self.assertEqual(found, len(self.batch_ids), "chaque batch porte exactement une operation")

    def test_operations_groupees_gerent_le_sentinelle_legacy(self) -> None:
        legacy_batch = self.fx.add_batch("run0", ts=1500.0)
        self.fx.store.apply.append_apply_operation(
            batch_id=legacy_batch,
            op_index=0,
            op_type="MOVE_DIR",
            src_path="/legacy/src",
            dst_path="/legacy/dst",
            reversible=True,
            row_id=None,
            ts=1500.0,
        )
        grouped = self.fx.store.apply.list_apply_operations_for_rows(
            batch_ids=[legacy_batch],
            row_ids=["__legacy__"],
        )
        expected = self.fx.store.apply.list_apply_operations_by_row(batch_id=legacy_batch, row_id="__legacy__")
        self.assertEqual(grouped.get((legacy_batch, "__legacy__")), expected)
        self.assertEqual(len(expected), 1)

    def test_rapports_qualite_groupes_identiques_aux_unitaires(self) -> None:
        pairs = [(f"run{index}", f"S|{index}") for index in range(3)]
        pairs.append(("run0", "S|inconnu"))
        grouped = self.fx.store.quality.get_quality_reports_for_pairs(pairs=pairs)
        for run_id, row_id in pairs:
            expected = self.fx.store.quality.get_quality_report(run_id=run_id, row_id=row_id)
            self.assertEqual(grouped.get((run_id, row_id)), expected)
        self.assertNotIn(("run0", "S|inconnu"), grouped)

    def test_resultats_identiques_quand_le_decoupage_force_plusieurs_paquets(self) -> None:
        """Le chemin multi-paquet doit rendre le meme resultat que le paquet unique.

        Les jeux reels (<= 100 runs) tiennent dans un seul paquet : sans ce test,
        la boucle de decoupage ne serait jamais exercee au-dela de la 1re
        iteration, et une erreur d'indice y resterait invisible.
        """
        run_ids = [f"run{index}" for index in range(3)]
        row_ids = [f"S|{index}" for index in range(3)]
        pairs = [(f"run{index}", f"S|{index}") for index in range(3)]

        reference_batches = self.fx.store.apply.list_apply_batches_for_runs(run_ids=run_ids)
        reference_ops = self.fx.store.apply.list_apply_operations_for_rows(
            batch_ids=self.batch_ids, row_ids=row_ids
        )
        reference_reports = self.fx.store.quality.get_quality_reports_for_pairs(pairs=pairs)

        original_chunk = apply_repo_module._SQL_CHUNK
        original_pair_chunk = quality_repo_module._SQL_PAIR_CHUNK
        apply_repo_module._SQL_CHUNK = 1
        quality_repo_module._SQL_PAIR_CHUNK = 1
        try:
            self.assertEqual(self.fx.store.apply.list_apply_batches_for_runs(run_ids=run_ids), reference_batches)
            self.assertEqual(
                self.fx.store.apply.list_apply_operations_for_rows(batch_ids=self.batch_ids, row_ids=row_ids),
                reference_ops,
            )
            self.assertEqual(self.fx.store.quality.get_quality_reports_for_pairs(pairs=pairs), reference_reports)
        finally:
            apply_repo_module._SQL_CHUNK = original_chunk
            quality_repo_module._SQL_PAIR_CHUNK = original_pair_chunk

        # Le jeu de reference doit etre non vide, sinon l'egalite serait triviale.
        self.assertEqual(len(reference_batches), 3)
        self.assertEqual(len(reference_ops), len(self.batch_ids))
        self.assertEqual(len(reference_reports), 3)

    def test_methodes_groupees_sur_entrees_vides(self) -> None:
        self.assertEqual(self.fx.store.apply.list_apply_batches_for_runs(run_ids=[]), {})
        self.assertEqual(self.fx.store.apply.list_apply_operations_for_rows(batch_ids=[], row_ids=["S|0"]), {})
        self.assertEqual(
            self.fx.store.apply.list_apply_operations_for_rows(batch_ids=self.batch_ids, row_ids=[]),
            {},
        )
        self.assertEqual(self.fx.store.quality.get_quality_reports_for_pairs(pairs=[]), {})


if __name__ == "__main__":
    unittest.main()
