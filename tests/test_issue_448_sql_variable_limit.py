"""Issue #448 — aucune clause `IN (...)` ne depend plus de la taille de l'entree.

SQLite borne le nombre de parametres lies (`SQLITE_MAX_VARIABLE_NUMBER`) : 999
avant 3.32.0, 32766 depuis. Une clause construite avec un placeholder par
element ne DEGRADE pas au-dela de cette borne, elle ECHOUE
(`sqlite3.OperationalError: too many SQL variables`) des la preparation.

La borne n'est pas supposee : elle est LUE sur l'interpreteur qui execute le
test (`Connection.getlimit`), et chaque cas verifie explicitement que son entree
la depasse — sinon le test passerait sans jamais emprunter le chemin qu'il
pretend couvrir.

Deux proprietes par site, la seconde etant la plus importante :

1. l'appel ne leve plus ;
2. le resultat est INCHANGE. Un decoupage qui repare le crash mais change une
   agregation serait un bug, pas un correctif. Les cas de doublons visent
   specifiquement les deux agregations qui CUMULENT (`+=`) : un `IN` unique
   dedoublonnait implicitement les run_id repetes, un decoupage naif les
   compterait une fois par paquet.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any, List

import cinesort.infra.db.repositories.apply as apply_repo_module
from cinesort.infra.db.repositories._sql import SQL_CHUNK
from cinesort.infra.db.sqlite_store import SQLiteStore


def _sqlite_variable_limit() -> int:
    """Borne REELLE de la version de SQLite embarquee (mesuree, pas supposee)."""
    conn = sqlite3.connect(":memory:")
    try:
        return int(conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER))
    finally:
        conn.close()


VAR_LIMIT = _sqlite_variable_limit()
#: Marge volontairement courte : le test doit depasser la borne, pas la pulveriser.
OVER_LIMIT = VAR_LIMIT + 500

REAL_RUNS = ("runA", "runB", "runC")


class _Library:
    """Petite bibliotheque reelle : 3 runs, avec erreurs, anomalies, qualite,
    rapports perceptuels et journal apply."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.state_dir = root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.store = SQLiteStore(self.state_dir / "cinesort.sqlite")
        self.store.initialize()
        self.batch_ids: List[str] = []
        for index, run_id in enumerate(REAL_RUNS):
            self._seed_run(run_id, index)

    def _seed_run(self, run_id: str, index: int) -> None:
        store = self.store
        store.run.insert_run_pending(
            run_id=run_id,
            root=str(self.root),
            state_dir=str(self.state_dir),
            config={},
            created_ts=1000.0 + index,
        )
        store.run.mark_run_running(run_id, started_ts=1000.0 + index)

        for err in range(index + 1):
            store.run.insert_error(
                run_id=run_id,
                step="scan",
                code=f"E{err}",
                message="boum",
                ts=1000.0 + index,
            )

        with store._managed_conn() as conn:
            for anomaly in range(index + 2):
                conn.execute(
                    "INSERT INTO anomalies(run_id, row_id, severity, code, message, ts) VALUES(?,?,?,?,?,?)",
                    (run_id, f"S|{anomaly}", "warning", "A1", "anomalie", 1000.0),
                )

        tiers = ("platinum", "gold", "silver")
        for row in range(index + 1):
            row_id = f"S|{row}"
            store.quality.upsert_quality_report(
                run_id=run_id,
                row_id=row_id,
                score=70 + row,
                tier=tiers[row % len(tiers)],
                reasons=[],
                metrics={},
                profile_id="default",
                profile_version=1,
                ts=1000.0 + index,
            )
            store.perceptual.upsert_perceptual_report(
                run_id=run_id,
                row_id=row_id,
                visual_score=80,
                audio_score=80,
                global_score=80,
                global_tier="gold",
                metrics={},
                settings_used={},
                global_score_v2=80.0,
                global_tier_v2=tiers[row % len(tiers)],
                global_score_v2_payload={"warnings": ["dnr_partial"]} if row == 0 else {"warnings": []},
                ts=1000.0 + index,
            )

        batch_id = store.apply.insert_apply_batch(
            run_id=run_id,
            dry_run=False,
            quarantine_unapproved=False,
            started_ts=2000.0 + index,
        )
        store.apply.append_apply_operation(
            batch_id=batch_id,
            op_index=0,
            op_type="MOVE_DIR",
            src_path=f"/src/{run_id}",
            dst_path=f"/dst/{run_id}",
            reversible=True,
            row_id="S|0",
            ts=2000.0 + index,
        )
        store.apply.append_apply_operation(
            batch_id=batch_id,
            op_index=1,
            op_type="MOVE_DIR",
            src_path=f"/src/{run_id}/legacy",
            dst_path=f"/dst/{run_id}/legacy",
            reversible=True,
            row_id=None,
            ts=2000.0 + index,
        )
        store.apply.close_apply_batch(
            batch_id=batch_id,
            status="DONE",
            summary={"applied_count": 10 + index},
        )
        self.batch_ids.append(batch_id)


def _padded(values: Any) -> List[str]:
    """`values` suivi d'assez d'identifiants INEXISTANTS pour depasser la borne.

    Les identifiants ajoutes ne correspondent a aucune ligne : le resultat
    attendu est donc STRICTEMENT celui de `values` seul.
    """
    filler = [f"absent-{index:07d}" for index in range(OVER_LIMIT - len(list(values)))]
    return [*values, *filler]


def _repeated_across_chunks(values: Any) -> List[str]:
    """`values` repete EN DEBUT ET EN FIN d'une liste plus longue qu'un paquet.

    Repeter simplement `values * 3` ne prouve RIEN : les trois copies tiennent
    dans le meme paquet, ou le `IN` de SQLite dedoublonne de lui-meme. Il faut
    que la meme valeur retombe dans DEUX paquets differents pour qu'une
    agregation cumulative la compte deux fois — d'ou l'intercalage d'un
    remplissage plus long que `SQL_CHUNK`, lu depuis le module (et non recopie)
    pour que le test suive la constante si elle change.
    """
    head = list(values)
    filler = [f"absent-{index:07d}" for index in range(OVER_LIMIT - 2 * len(head))]
    out = [*head, *filler, *head]
    assert len(filler) > SQL_CHUNK, "remplissage trop court : les doublons resteraient dans un paquet"
    return out


class SqlVariableLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.mkdtemp(prefix="issue448_")
        cls.lib = _Library(Path(cls._tmp))
        cls.store = cls.lib.store

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self) -> None:
        # Sans cette garde, une future version de SQLite dont la borne monterait
        # au-dessus de OVER_LIMIT rendrait toute la classe vacante en silence.
        self.assertGreater(len(_padded(REAL_RUNS)), VAR_LIMIT)

    # --- Les six agregations par run --------------------------------------

    def test_compteurs_erreurs_identiques_au_dela_de_la_borne(self) -> None:
        reference = self.store.run.get_error_counts_for_runs(list(REAL_RUNS))
        self.assertEqual(reference, {"runA": 1, "runB": 2, "runC": 3})
        self.assertEqual(self.store.run.get_error_counts_for_runs(_padded(REAL_RUNS)), reference)

    def test_compteurs_anomalies_identiques_au_dela_de_la_borne(self) -> None:
        reference = self.store.anomaly.get_anomaly_counts_for_runs(list(REAL_RUNS))
        self.assertEqual(reference, {"runA": 2, "runB": 3, "runC": 4})
        self.assertEqual(self.store.anomaly.get_anomaly_counts_for_runs(_padded(REAL_RUNS)), reference)

    def test_compteurs_appliques_identiques_au_dela_de_la_borne(self) -> None:
        reference = self.store.apply.get_applied_counts_for_runs(list(REAL_RUNS))
        self.assertEqual(reference, {"runA": 10, "runB": 11, "runC": 12})
        self.assertEqual(self.store.apply.get_applied_counts_for_runs(_padded(REAL_RUNS)), reference)

    def test_compteurs_qualite_identiques_au_dela_de_la_borne(self) -> None:
        reference = self.store.quality.get_quality_counts_for_runs(list(REAL_RUNS))
        self.assertEqual(sorted(reference), ["runA", "runB", "runC"])
        self.assertEqual(reference["runC"]["scored_movies"], 3)
        self.assertEqual(self.store.quality.get_quality_counts_for_runs(_padded(REAL_RUNS)), reference)

    def test_distribution_tiers_v2_identique_au_dela_de_la_borne(self) -> None:
        reference = self.store.perceptual.get_global_tier_v2_distribution(run_ids=list(REAL_RUNS))
        self.assertEqual(reference["platinum"], 3)
        self.assertEqual(sum(reference.values()), 6)
        self.assertEqual(
            self.store.perceptual.get_global_tier_v2_distribution(run_ids=_padded(REAL_RUNS)),
            reference,
        )

    def test_compte_warnings_v2_identique_au_dela_de_la_borne(self) -> None:
        reference = self.store.perceptual.count_v2_warnings_flag(flag="dnr_partial", run_ids=list(REAL_RUNS))
        self.assertEqual(reference, 3)
        self.assertEqual(
            self.store.perceptual.count_v2_warnings_flag(flag="dnr_partial", run_ids=_padded(REAL_RUNS)),
            reference,
        )

    # --- Les deux agregations qui CUMULENT : invariance aux doublons -------

    def test_distribution_tiers_v2_insensible_aux_run_ids_repetes(self) -> None:
        """Un `IN` unique dedoublonnait ; un decoupage sans dedup compterait 2x."""
        reference = self.store.perceptual.get_global_tier_v2_distribution(run_ids=list(REAL_RUNS))
        repete = self.store.perceptual.get_global_tier_v2_distribution(run_ids=_repeated_across_chunks(REAL_RUNS))
        self.assertEqual(repete, reference)

    def test_compte_warnings_v2_insensible_aux_run_ids_repetes(self) -> None:
        reference = self.store.perceptual.count_v2_warnings_flag(flag="dnr_partial", run_ids=list(REAL_RUNS))
        repete = self.store.perceptual.count_v2_warnings_flag(
            flag="dnr_partial", run_ids=_repeated_across_chunks(REAL_RUNS)
        )
        self.assertEqual(repete, reference)

    # --- Le journal apply : DEUX dimensions a decouper ---------------------

    def test_operations_par_ligne_identiques_au_dela_de_la_borne(self) -> None:
        row_ids = ["S|0", "S|1", "S|2", "__legacy__"]
        reference = self.store.apply.list_apply_operations_for_rows(
            batch_ids=self.lib.batch_ids,
            row_ids=row_ids,
        )
        self.assertEqual(len(reference), len(self.lib.batch_ids) * 2)
        # `batch_ids` etait deja decoupe ; c'est `row_ids` qui ne l'etait pas.
        self.assertEqual(
            self.store.apply.list_apply_operations_for_rows(
                batch_ids=self.lib.batch_ids,
                row_ids=_padded(row_ids),
            ),
            reference,
        )

    def test_operations_legacy_non_dupliquees_sur_plusieurs_paquets(self) -> None:
        """`row_id IS NULL` doit former SON PROPRE paquet.

        Repete dans le predicat de chaque paquet de lignes, il ferait remonter
        les operations legacy autant de fois qu'il y a de paquets — un
        `_SQL_CHUNK` reduit rend cette duplication visible, la valeur de
        production (200) ne l'aurait jamais montree.
        """
        row_ids = ["S|0", "S|1", "S|2", "__legacy__"]
        reference = self.store.apply.list_apply_operations_for_rows(
            batch_ids=self.lib.batch_ids,
            row_ids=row_ids,
        )
        legacy_key = (self.lib.batch_ids[0], "__legacy__")
        self.assertEqual(len(reference[legacy_key]), 1)

        original = apply_repo_module._SQL_CHUNK
        apply_repo_module._SQL_CHUNK = 1
        try:
            decoupe = self.store.apply.list_apply_operations_for_rows(
                batch_ids=self.lib.batch_ids,
                row_ids=row_ids,
            )
        finally:
            apply_repo_module._SQL_CHUNK = original
        self.assertEqual(decoupe, reference)
        self.assertEqual(len(decoupe[legacy_key]), 1)

    # --- Le chemin destructif ---------------------------------------------

    def test_suppression_de_run_avec_plus_de_batches_que_la_borne(self) -> None:
        """`delete_run` listait les batch_id puis les rejouait en parametres."""
        tmp = tempfile.mkdtemp(prefix="issue448_del_")
        try:
            store = SQLiteStore(Path(tmp) / "cinesort.sqlite")
            store.initialize()
            store.run.insert_run_pending(run_id="R", root=tmp, state_dir=tmp, config={}, created_ts=1.0)
            seed_batch = store.apply.insert_apply_batch(
                run_id="R", dry_run=False, quarantine_unapproved=False, started_ts=1.0
            )
            store.apply.append_apply_operation(
                batch_id=seed_batch,
                op_index=0,
                op_type="MOVE_DIR",
                src_path="/a",
                dst_path="/b",
                reversible=True,
                row_id="S|0",
                ts=1.0,
            )
            extra = OVER_LIMIT
            with store._managed_conn() as conn:
                conn.executemany(
                    "INSERT INTO apply_batches(batch_id, run_id, started_ts, dry_run,"
                    " quarantine_unapproved, status, summary_json, app_version)"
                    " VALUES(?,?,1.0,0,0,'DONE','{}','test')",
                    [(f"b{index:07d}", "R") for index in range(extra)],
                )
                seeded = conn.execute("SELECT COUNT(*) FROM apply_batches WHERE run_id=?", ("R",)).fetchone()[0]
            # Sans cette garde, un INSERT rejete silencieusement rendrait le test
            # vacant : il ne depasserait jamais la borne.
            self.assertEqual(seeded, extra + 1)
            self.assertGreater(seeded, VAR_LIMIT)

            # 1 run + 1 operation + (extra + 1) batches.
            self.assertEqual(store.run.delete_run("R"), extra + 3)
            with store._managed_conn() as conn:
                reste = conn.execute("SELECT COUNT(*) FROM apply_batches WHERE run_id=?", ("R",)).fetchone()[0]
                orphelines = conn.execute("SELECT COUNT(*) FROM apply_operations").fetchone()[0]
            self.assertEqual(reste, 0)
            self.assertEqual(orphelines, 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class SqlChunkHelperTests(unittest.TestCase):
    def test_decoupage_couvre_tout_sans_paquet_vide(self) -> None:
        from cinesort.infra.db.repositories._sql import chunked

        values = [str(index) for index in range(7)]
        paquets = list(chunked(values, 3))
        self.assertEqual(paquets, [["0", "1", "2"], ["3", "4", "5"], ["6"]])
        self.assertEqual([item for paquet in paquets for item in paquet], values)
        self.assertEqual(list(chunked([], 3)), [])
        # Une taille absurde ne doit pas boucler indefiniment.
        self.assertEqual(list(chunked(values, 0)), [[value] for value in values])


if __name__ == "__main__":
    unittest.main()
