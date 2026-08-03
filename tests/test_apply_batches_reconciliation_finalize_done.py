"""REVUE ADVERSAIRE PR#852 — la reconciliation au boot doit rendre l'undo.

Moitie manquante du finding F11 : quand `close_apply_batch(DONE)` echoue (base
verrouillee, disque plein, lecteur reseau tombe) APRES que tous les
deplacements ont ete faits, le batch reste `PENDING`. Or
`get_last_reversible_apply_batch` filtre `status='DONE'` et la reconciliation au
boot ne connaissait que `COMPLETED_BY_BOOT_CLEANUP` / `ROLLED_BACK_BY_BOOT_CLEANUP` :
l'apply devenait DEFINITIVEMENT non annulable.

La preuve utilisee ne peut pas vivre dans SQLite (c'est SQLite qui etait
indisponible) : c'est le marqueur `apply_end` du journal d'audit JSONL, ecrit
dans le run_dir a la toute fin de `_execute_apply`, donc apres le dernier
deplacement et avant la finalisation du journal.

Les tests couvrent les DEUX sens :
- marqueur present  -> `DONE`, undo re-arme (verifie via un vrai SQLiteStore) ;
- marqueur absent   -> comportement conservateur d'origine INCHANGE.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from cinesort.app.apply_batches_reconciliation import (
    STATUS_ROLLED_BACK_BY_BOOT,
    reconcile_batches_at_boot,
    reconcile_pending_batches,
    run_dir_for,
)
from cinesort.infra.db import SQLiteStore
from cinesort.infra.state import new_run

RUN_ID = "20260803_120000"
BATCH_ID = "batch-852"


def _write_audit_marker(
    state_dir: Path,
    *,
    run_id: str = RUN_ID,
    batch_id: str = BATCH_ID,
    event: str = "apply_end",
) -> Path:
    """Ecrit un `apply_audit.jsonl` contenant l'evenement demande."""
    run_dir = state_dir / "runs" / f"tri_films_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "apply_audit.jsonl"
    lines = [
        {"ts": 1.0, "run_id": run_id, "batch_id": batch_id, "event": "apply_start", "total_rows": 500},
        {"ts": 2.0, "run_id": run_id, "batch_id": batch_id, "event": event, "status": "DONE", "counts": {"moves": 500}},
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return path


class RunDirFormulaParityTests(unittest.TestCase):
    """`run_dir_for` duplique la formule de `infra.state.new_run` (contrat app/infra)."""

    def test_meme_chemin_que_new_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            expected = new_run(state_dir, RUN_ID).run_dir

            self.assertEqual(run_dir_for(state_dir, RUN_ID), expected)


class ReconcileFinalizesProvenBatchTests(unittest.TestCase):
    """Un batch PENDING prouve termine doit redevenir annulable."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self._tmp.name)
        self.store = SQLiteStore(self.state_dir / "cinesort.sqlite", busy_timeout_ms=5000)
        self.store.initialize()
        self.now = time.time()
        self.started = self.now - 60.0

    def tearDown(self) -> None:
        try:
            self.store.close()
        except Exception:
            pass
        try:
            self._tmp.cleanup()
        except Exception:
            pass

    def _seed_pending_batch(self, *, dry_run: bool = False, ops: int = 3) -> None:
        """Reproduit l'etat laisse par un apply dont la cloture DONE a echoue."""
        self.store.apply.insert_apply_batch(
            run_id=RUN_ID,
            dry_run=dry_run,
            quarantine_unapproved=False,
            status="PENDING",
            summary={},
            app_version="test",
            started_ts=self.started,
            batch_id=BATCH_ID,
        )
        for index in range(ops):
            self.store.apply.append_apply_operation(
                batch_id=BATCH_ID,
                op_index=index,
                op_type="MOVE",
                src_path=f"/src/{index}",
                dst_path=f"/dst/{index}",
                reversible=True,
            )

    def _status(self) -> str:
        with self.store._managed_conn() as conn:
            cur = conn.execute("SELECT status FROM apply_batches WHERE batch_id=?", (BATCH_ID,))
            row = cur.fetchone()
        return str(row["status"]) if row else ""

    def test_marqueur_present_remet_le_batch_en_done_et_rearme_l_undo(self) -> None:
        self._seed_pending_batch()
        _write_audit_marker(self.state_dir)

        report = reconcile_pending_batches(
            self.store,
            max_age_hours=0.0,
            now_ts=self.now,
            state_dir=self.state_dir,
        )

        self.assertEqual(report["finalized_done"], 1, f"rapport: {report}")
        self.assertEqual(self._status(), "DONE")
        batch = self.store.apply.get_last_reversible_apply_batch(RUN_ID)
        self.assertIsNotNone(batch, "l'undo doit etre re-arme : c'est tout l'objet du correctif")
        self.assertEqual(str((batch or {}).get("batch_id")), BATCH_ID)

    def test_summary_trace_la_raison_du_reamorcage(self) -> None:
        self._seed_pending_batch()
        _write_audit_marker(self.state_dir)

        reconcile_pending_batches(self.store, max_age_hours=0.0, now_ts=self.now, state_dir=self.state_dir)

        batch = self.store.apply.get_last_reversible_apply_batch(RUN_ID) or {}
        trace = (batch.get("summary") or {}).get("_boot_cleanup") or {}
        self.assertEqual(trace.get("reason"), "FINALIZED_BY_BOOT_APPLY_END_MARKER")
        self.assertEqual(trace.get("ops_count"), 3)

    def test_wrapper_boot_propage_state_dir(self) -> None:
        """`reconcile_batches_at_boot` est le point d'entree reel du boot."""
        self._seed_pending_batch()
        _write_audit_marker(self.state_dir)

        report = reconcile_batches_at_boot(self.store, max_age_hours=0.0, state_dir=self.state_dir)

        self.assertEqual(report.get("finalized_done"), 1, f"rapport: {report}")
        self.assertIsNotNone(self.store.apply.get_last_reversible_apply_batch(RUN_ID))

    # ---- NON-REGRESSION : rien ne doit devenir annulable sans preuve ----

    def test_sans_marqueur_le_batch_reste_non_annulable(self) -> None:
        """Apply tue en cours de route : pas de `apply_end` -> comportement d'origine."""
        self._seed_pending_batch()

        report = reconcile_pending_batches(
            self.store,
            max_age_hours=0.0,
            now_ts=self.now,
            state_dir=self.state_dir,
        )

        self.assertEqual(report["finalized_done"], 0)
        self.assertEqual(self._status(), STATUS_ROLLED_BACK_BY_BOOT)
        self.assertIsNone(self.store.apply.get_last_reversible_apply_batch(RUN_ID))

    def test_marqueur_apply_start_seul_ne_suffit_pas(self) -> None:
        """Un apply demarre puis tue laisse `apply_start` : ce n'est pas une preuve."""
        self._seed_pending_batch()
        _write_audit_marker(self.state_dir, event="op_move_file")

        report = reconcile_pending_batches(
            self.store,
            max_age_hours=0.0,
            now_ts=self.now,
            state_dir=self.state_dir,
        )

        self.assertEqual(report["finalized_done"], 0)
        self.assertEqual(self._status(), STATUS_ROLLED_BACK_BY_BOOT)

    def test_marqueur_d_un_autre_batch_ne_compte_pas(self) -> None:
        self._seed_pending_batch()
        _write_audit_marker(self.state_dir, batch_id="batch-d-un-autre-apply")

        report = reconcile_pending_batches(
            self.store,
            max_age_hours=0.0,
            now_ts=self.now,
            state_dir=self.state_dir,
        )

        self.assertEqual(report["finalized_done"], 0)
        self.assertEqual(self._status(), STATUS_ROLLED_BACK_BY_BOOT)

    def test_marqueur_sans_aucune_operation_journalisee_ne_suffit_pas(self) -> None:
        """Zero op = rien a annuler : marquer DONE serait un mensonge."""
        self._seed_pending_batch(ops=0)
        _write_audit_marker(self.state_dir)

        report = reconcile_pending_batches(
            self.store,
            max_age_hours=0.0,
            now_ts=self.now,
            state_dir=self.state_dir,
        )

        self.assertEqual(report["finalized_done"], 0)
        self.assertEqual(self._status(), STATUS_ROLLED_BACK_BY_BOOT)

    def test_sans_state_dir_le_comportement_historique_est_conserve(self) -> None:
        self._seed_pending_batch()
        _write_audit_marker(self.state_dir)

        report = reconcile_pending_batches(self.store, max_age_hours=0.0, now_ts=self.now)

        self.assertEqual(report["finalized_done"], 0)
        self.assertEqual(self._status(), STATUS_ROLLED_BACK_BY_BOOT)

    def test_idempotent(self) -> None:
        self._seed_pending_batch()
        _write_audit_marker(self.state_dir)

        first = reconcile_pending_batches(self.store, max_age_hours=0.0, now_ts=self.now, state_dir=self.state_dir)
        second = reconcile_pending_batches(
            self.store, max_age_hours=0.0, now_ts=self.now + 10.0, state_dir=self.state_dir
        )

        self.assertEqual(first["finalized_done"], 1)
        self.assertEqual(second["pending_found"], 0, "le batch n'est plus PENDING, rien a refaire")
        self.assertEqual(self._status(), "DONE")

    def test_journal_audit_illisible_ne_casse_pas_le_boot(self) -> None:
        self._seed_pending_batch()
        run_dir = self.state_dir / "runs" / f"tri_films_{RUN_ID}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "apply_audit.jsonl").write_text("{ceci n'est pas du JSON\n", encoding="utf-8")

        report = reconcile_pending_batches(
            self.store,
            max_age_hours=0.0,
            now_ts=self.now,
            state_dir=self.state_dir,
        )

        self.assertEqual(report["finalized_done"], 0)
        self.assertEqual(self._status(), STATUS_ROLLED_BACK_BY_BOOT)


class DryRunBatchNeverFinalizedTests(unittest.TestCase):
    """Un batch dry-run n'a rien deplace : le remettre DONE serait absurde."""

    def test_dry_run_ignore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            store = SQLiteStore(state_dir / "cinesort.sqlite", busy_timeout_ms=5000)
            store.initialize()
            now = time.time()
            try:
                store.apply.insert_apply_batch(
                    run_id=RUN_ID,
                    dry_run=True,
                    quarantine_unapproved=False,
                    status="PENDING",
                    summary={},
                    app_version="test",
                    started_ts=now - 60.0,
                    batch_id=BATCH_ID,
                )
                store.apply.append_apply_operation(
                    batch_id=BATCH_ID,
                    op_index=0,
                    op_type="MOVE",
                    src_path="/src/0",
                    dst_path="/dst/0",
                    reversible=True,
                )
                _write_audit_marker(state_dir)

                report = reconcile_pending_batches(store, max_age_hours=0.0, now_ts=now, state_dir=state_dir)

                self.assertEqual(report["finalized_done"], 0)
                with store._managed_conn() as conn:
                    cur = conn.execute("SELECT status FROM apply_batches WHERE batch_id=?", (BATCH_ID,))
                    row = cur.fetchone()
                self.assertEqual(str(row["status"]), STATUS_ROLLED_BACK_BY_BOOT)
            finally:
                try:
                    store.close()
                except (OSError, sqlite3.Error):
                    pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
