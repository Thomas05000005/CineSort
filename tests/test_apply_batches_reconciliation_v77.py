"""VN-E.2 — tests pour reconcile_pending_batches (cleanup PENDING-zombi).

Memoires :
- `feedback_sqlite_migration_test_existing_db` : on utilise la fixture
  mutualisee `existing_db_fixture(M-00)` pour creer une DB PRE-EXISTANTE
  arretee a v5 (apply_batches + apply_operations dispo), puis on insere
  des batches manuellement.
- Idempotence : 2 appels successifs ne changent rien apres le 1er.
- Pas de breaking change schema : on n'execute aucune migration custom,
  juste des INSERT/UPDATE sur les tables livrees par 005.

Couvre les 4 cas demandes :
1. 0 PENDING -> report vide
2. 1 PENDING jeune (<1h) -> ignore (pas touche)
3. 1 PENDING vieux complet (aucune op failed) -> COMPLETED_BY_BOOT_CLEANUP
4. 1 PENDING vieux incomplet (op avec error_message) -> ROLLED_BACK_BY_BOOT_CLEANUP
"""

from __future__ import annotations

import shutil
import sqlite3
import time
import unittest
from unittest.mock import MagicMock

from cinesort.app.apply_batches_reconciliation import (
    DEFAULT_MAX_AGE_HOURS,
    STATUS_COMPLETED_BY_BOOT,
    STATUS_ROLLED_BACK_BY_BOOT,
    reconcile_batches_at_boot,
    reconcile_pending_batches,
)
from tests._helpers import existing_db_fixture

# ---------------------------------------------------------------------------
# Shim store : expose `_managed_conn()` context-manager autour d'une sqlite3
# connection. C'est le seul attribut de SQLiteStore utilise par le module.
# ---------------------------------------------------------------------------


class _ConnCtx:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        return None


class _StoreShim:
    """Wrapper minimal autour d'une connexion sqlite3 pour mimer SQLiteStore."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _managed_conn(self) -> _ConnCtx:
        return _ConnCtx(self._conn)


def _insert_batch(
    conn: sqlite3.Connection,
    *,
    batch_id: str,
    run_id: str = "run-test",
    started_ts: float,
    status: str = "PENDING",
    dry_run: int = 0,
    summary_json: str = "{}",
) -> None:
    conn.execute(
        """
        INSERT INTO apply_batches(
          batch_id, run_id, started_ts, ended_ts, dry_run,
          quarantine_unapproved, status, summary_json, app_version
        )
        VALUES(?, ?, ?, NULL, ?, 0, ?, ?, 'test')
        """,
        (batch_id, run_id, started_ts, dry_run, status, summary_json),
    )
    conn.commit()


def _insert_op(
    conn: sqlite3.Connection,
    *,
    batch_id: str,
    op_index: int = 0,
    error_message: str | None = None,
    undo_status: str = "PENDING",
) -> None:
    conn.execute(
        """
        INSERT INTO apply_operations(
          batch_id, op_index, op_type, src_path, dst_path, reversible,
          undo_status, error_message, ts
        )
        VALUES(?, ?, 'MOVE', '/src', '/dst', 1, ?, ?, ?)
        """,
        (batch_id, op_index, undo_status, error_message, time.time()),
    )
    conn.commit()


def _get_batch_status(conn: sqlite3.Connection, batch_id: str) -> str:
    cur = conn.execute("SELECT status FROM apply_batches WHERE batch_id = ?", (batch_id,))
    row = cur.fetchone()
    return str(row[0]) if row else ""


class ReconcilePendingBatchesTests(unittest.TestCase):
    """Tests des 4 scenarios demandes + idempotence + None store."""

    def setUp(self) -> None:
        # M-00 : DB pre-existante a v5 (apply_batches + apply_operations dispo)
        self.db_path, self.conn = existing_db_fixture(5)
        self.addCleanup(shutil.rmtree, self.db_path.parent, ignore_errors=True)
        self.store = _StoreShim(self.conn)
        self.now = time.time()
        self.old_ts = self.now - (2.0 * 3600.0)  # 2h dans le passe -> zombi
        self.fresh_ts = self.now - 60.0  # 1 minute dans le passe -> pas zombi

    def tearDown(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    # ---- Cas 1 : 0 PENDING ----

    def test_no_pending_returns_empty_report(self) -> None:
        report = reconcile_pending_batches(self.store, now_ts=self.now)
        self.assertEqual(report["pending_found"], 0)
        self.assertEqual(report["completed"], 0)
        self.assertEqual(report["rolled_back"], 0)
        self.assertEqual(report["batches"], [])

    def test_only_done_batch_no_action(self) -> None:
        _insert_batch(self.conn, batch_id="b-done", started_ts=self.old_ts, status="DONE")
        report = reconcile_pending_batches(self.store, now_ts=self.now)
        self.assertEqual(report["pending_found"], 0)
        # Le DONE reste DONE
        self.assertEqual(_get_batch_status(self.conn, "b-done"), "DONE")

    # ---- Cas 2 : 1 PENDING jeune (<1h) -> ignore ----

    def test_young_pending_batch_ignored(self) -> None:
        _insert_batch(self.conn, batch_id="b-young", started_ts=self.fresh_ts, status="PENDING")
        report = reconcile_pending_batches(self.store, max_age_hours=1.0, now_ts=self.now)
        self.assertEqual(report["pending_found"], 0)
        # Toujours PENDING : pas touche
        self.assertEqual(_get_batch_status(self.conn, "b-young"), "PENDING")

    # ---- Cas 3 : 1 PENDING vieux complet (PROUVE via expected_ops) -> COMPLETED ----
    # AUDIT 2026-06-11 (R3e, gap[1]) : 'completed' exige desormais une preuve de
    # completude (expected_ops dans le summary ET total >= expected_ops).

    def test_old_pending_complete_marked_completed(self) -> None:
        _insert_batch(
            self.conn,
            batch_id="b-old-ok",
            started_ts=self.old_ts,
            status="PENDING",
            summary_json='{"expected_ops": 2}',  # preuve : 2 ops attendues
        )
        # 2 ops sans erreur ET 2 attendues -> verdict 'completed'
        _insert_op(self.conn, batch_id="b-old-ok", op_index=0)
        _insert_op(self.conn, batch_id="b-old-ok", op_index=1)

        report = reconcile_pending_batches(self.store, max_age_hours=1.0, now_ts=self.now)
        self.assertEqual(report["pending_found"], 1)
        self.assertEqual(report["completed"], 1)
        self.assertEqual(report["rolled_back"], 0)
        self.assertEqual(_get_batch_status(self.conn, "b-old-ok"), STATUS_COMPLETED_BY_BOOT)
        self.assertEqual(report["batches"][0]["verdict"], "completed")

    def test_old_pending_incomplete_ops_marked_rolled_back(self) -> None:
        """gap[1] coeur : moins d'ops enregistrees qu'attendu (crash mid-apply)
        -> ROLLED_BACK, PAS 'completed'. Avant le fix, total>0/failed=0 suffisait
        a tort a marquer 'completed' alors que des moves n'ont jamais eu lieu."""
        _insert_batch(
            self.conn,
            batch_id="b-old-partial",
            started_ts=self.old_ts,
            status="PENDING",
            summary_json='{"expected_ops": 5}',  # 5 attendues...
        )
        # ...mais seulement 2 enregistrees (kill mid-apply), aucune en erreur.
        _insert_op(self.conn, batch_id="b-old-partial", op_index=0)
        _insert_op(self.conn, batch_id="b-old-partial", op_index=1)

        report = reconcile_pending_batches(self.store, max_age_hours=1.0, now_ts=self.now)
        self.assertEqual(report["pending_found"], 1)
        self.assertEqual(report["completed"], 0)
        self.assertEqual(report["rolled_back"], 1)
        self.assertEqual(_get_batch_status(self.conn, "b-old-partial"), STATUS_ROLLED_BACK_BY_BOOT)

    def test_old_pending_without_expected_ops_marked_rolled_back(self) -> None:
        """Sans expected_ops dans le summary (cas reel : insert_apply_batch
        persiste summary={}), la completude n'est PAS prouvable -> defaut
        prudent ROLLED_BACK (contrat docstring L31-33)."""
        _insert_batch(
            self.conn,
            batch_id="b-old-noexp",
            started_ts=self.old_ts,
            status="PENDING",
            summary_json="{}",  # aucune preuve
        )
        _insert_op(self.conn, batch_id="b-old-noexp", op_index=0)
        _insert_op(self.conn, batch_id="b-old-noexp", op_index=1)

        report = reconcile_pending_batches(self.store, max_age_hours=1.0, now_ts=self.now)
        self.assertEqual(report["pending_found"], 1)
        self.assertEqual(report["completed"], 0)
        self.assertEqual(report["rolled_back"], 1)
        self.assertEqual(_get_batch_status(self.conn, "b-old-noexp"), STATUS_ROLLED_BACK_BY_BOOT)

    # ---- Cas 4 : 1 PENDING vieux incomplet -> ROLLED_BACK ----

    def test_old_pending_with_failed_op_marked_rolled_back(self) -> None:
        _insert_batch(self.conn, batch_id="b-old-ko", started_ts=self.old_ts, status="PENDING")
        # 1 op OK + 1 op avec erreur -> verdict 'rolled_back'
        _insert_op(self.conn, batch_id="b-old-ko", op_index=0)
        _insert_op(
            self.conn,
            batch_id="b-old-ko",
            op_index=1,
            error_message="disk full mid-move",
        )

        report = reconcile_pending_batches(self.store, max_age_hours=1.0, now_ts=self.now)
        self.assertEqual(report["pending_found"], 1)
        self.assertEqual(report["completed"], 0)
        self.assertEqual(report["rolled_back"], 1)
        self.assertEqual(_get_batch_status(self.conn, "b-old-ko"), STATUS_ROLLED_BACK_BY_BOOT)
        self.assertEqual(report["batches"][0]["verdict"], "rolled_back")

    def test_old_pending_with_no_ops_marked_rolled_back(self) -> None:
        """Batch PENDING sans aucune operation -> rollback (incoherent)."""
        _insert_batch(self.conn, batch_id="b-empty", started_ts=self.old_ts, status="PENDING")
        report = reconcile_pending_batches(self.store, max_age_hours=1.0, now_ts=self.now)
        self.assertEqual(report["pending_found"], 1)
        self.assertEqual(report["rolled_back"], 1)
        self.assertEqual(_get_batch_status(self.conn, "b-empty"), STATUS_ROLLED_BACK_BY_BOOT)

    def test_old_pending_with_undo_failed_op_marked_rolled_back(self) -> None:
        """undo_status='FAILED' compte aussi comme echec partiel."""
        _insert_batch(self.conn, batch_id="b-undo-failed", started_ts=self.old_ts, status="PENDING")
        _insert_op(
            self.conn,
            batch_id="b-undo-failed",
            op_index=0,
            undo_status="FAILED",
        )
        report = reconcile_pending_batches(self.store, max_age_hours=1.0, now_ts=self.now)
        self.assertEqual(report["rolled_back"], 1)

    # ---- Idempotence ----

    def test_idempotent_second_call_is_noop(self) -> None:
        _insert_batch(self.conn, batch_id="b-old-ok", started_ts=self.old_ts, status="PENDING")
        _insert_op(self.conn, batch_id="b-old-ok", op_index=0)

        # 1er passage : cleanup effectif
        r1 = reconcile_pending_batches(self.store, max_age_hours=1.0, now_ts=self.now)
        self.assertEqual(r1["pending_found"], 1)

        # 2e passage : plus rien a faire (batch n'est plus PENDING)
        r2 = reconcile_pending_batches(self.store, max_age_hours=1.0, now_ts=self.now + 10.0)
        self.assertEqual(r2["pending_found"], 0)
        self.assertEqual(r2["completed"], 0)
        self.assertEqual(r2["rolled_back"], 0)

    # ---- Mix : plusieurs batches ----

    def test_mixed_batches_processed_correctly(self) -> None:
        # 1 jeune ignore, 1 vieux complet, 1 vieux incomplet, 1 deja DONE
        _insert_batch(self.conn, batch_id="b-young", started_ts=self.fresh_ts, status="PENDING")
        _insert_batch(
            self.conn,
            batch_id="b-old-ok",
            started_ts=self.old_ts,
            status="PENDING",
            summary_json='{"expected_ops": 1}',  # preuve de completude (R3e gap[1])
        )
        _insert_op(self.conn, batch_id="b-old-ok", op_index=0)
        _insert_batch(self.conn, batch_id="b-old-ko", started_ts=self.old_ts, status="PENDING")
        _insert_op(
            self.conn,
            batch_id="b-old-ko",
            op_index=0,
            error_message="boom",
        )
        _insert_batch(self.conn, batch_id="b-done", started_ts=self.old_ts, status="DONE")

        report = reconcile_pending_batches(self.store, max_age_hours=1.0, now_ts=self.now)
        self.assertEqual(report["pending_found"], 2)
        self.assertEqual(report["completed"], 1)
        self.assertEqual(report["rolled_back"], 1)

        # Verifications individuelles
        self.assertEqual(_get_batch_status(self.conn, "b-young"), "PENDING")
        self.assertEqual(_get_batch_status(self.conn, "b-old-ok"), STATUS_COMPLETED_BY_BOOT)
        self.assertEqual(_get_batch_status(self.conn, "b-old-ko"), STATUS_ROLLED_BACK_BY_BOOT)
        self.assertEqual(_get_batch_status(self.conn, "b-done"), "DONE")

    # ---- Robustesse ----

    def test_none_store_returns_empty_report(self) -> None:
        report = reconcile_pending_batches(None, now_ts=self.now)
        self.assertEqual(report["pending_found"], 0)

    def test_default_max_age_is_one_hour(self) -> None:
        self.assertEqual(DEFAULT_MAX_AGE_HOURS, 1.0)


class ReconcileBatchesAtBootTests(unittest.TestCase):
    """Wrapper boot : tolere toutes les erreurs."""

    def test_boot_wrapper_passes_through(self) -> None:
        db_path, conn = existing_db_fixture(5)
        self.addCleanup(shutil.rmtree, db_path.parent, ignore_errors=True)
        store = _StoreShim(conn)
        try:
            report = reconcile_batches_at_boot(store)
            self.assertEqual(report["pending_found"], 0)
        finally:
            conn.close()

    def test_boot_wrapper_swallows_unexpected_errors(self) -> None:
        bad_store = MagicMock()
        bad_store._managed_conn.side_effect = RuntimeError("boom")
        report = reconcile_batches_at_boot(bad_store)
        # Pas d'exception remontee + report neutre
        self.assertEqual(report["pending_found"], 0)
        self.assertEqual(report["completed"], 0)
        self.assertEqual(report["rolled_back"], 0)


if __name__ == "__main__":
    unittest.main()
