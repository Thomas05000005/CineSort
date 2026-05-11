"""CR-1 audit QA 20260429 — tests d'atomicite des moves apply.

Couvre :
- Helper journaled_move : INSERT pending avant move, DELETE apres succes,
  laisse l'entree si exception dans le with.
- Wrapper RecordOpWithJournal : drop-in autour de record_op qui porte
  store + batch_id pour permettre atomic_move.
- Helper atomic_move : utilise journal si record_op porte journal_store,
  sinon fallback shutil.move direct.
- reconcile_pending_moves : 4 verdicts (completed, rolled_back, duplicated,
  lost) + cleanup de l'entree dans tous les cas.
- Mixin _apply_mixin : insert/delete/list/count pending moves.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from cinesort.app.move_journal import (
    RecordOpWithJournal,
    atomic_move,
    journaled_move,
)
from cinesort.app.move_reconciliation import (
    _classify_pending,
    reconcile_at_boot,
    reconcile_pending_moves,
)
from cinesort.infra.db.sqlite_store import SQLiteStore


def _make_store() -> tuple[SQLiteStore, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="cinesort_atomicity_"))
    store = SQLiteStore(tmp / "test.sqlite", busy_timeout_ms=5000)
    store.initialize()
    return store, tmp


class JournaledMoveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store, self._tmp = _make_store()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_journaled_move_clean_path(self) -> None:
        """Sortie OK du with → entree DELETE apres yield, table vide."""
        with journaled_move(
            self.store,
            src="C:/src.mkv",
            dst="C:/dst.mkv",
            op_type="MOVE_FILE",
            batch_id="batch1",
        ) as pending_id:
            self.assertIsNotNone(pending_id)
            # Pendant le with, l'entree existe
            pending = self.store.list_pending_moves()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["op_type"], "MOVE_FILE")

        # Apres le with sans exception : l'entree est supprimee
        self.assertEqual(self.store.count_pending_moves(), 0)

    def test_journaled_move_with_exception_leaves_entry(self) -> None:
        """Exception dans le with → entree reste pour reconciliation."""
        with (
            self.assertRaises(RuntimeError),
            journaled_move(
                self.store,
                src="C:/src.mkv",
                dst="C:/dst.mkv",
                op_type="MOVE_FILE",
            ),
        ):
            raise RuntimeError("simulated crash mid-move")

        # L'entree pending est restee (sera traitee par reconciliation au boot)
        pending = self.store.list_pending_moves()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["src_path"], "C:/src.mkv")

    def test_journaled_move_no_store_is_noop(self) -> None:
        """store=None → pas d'erreur, pas de journal."""
        with journaled_move(
            None,
            src="C:/src.mkv",
            dst="C:/dst.mkv",
            op_type="MOVE_FILE",
        ) as pending_id:
            self.assertIsNone(pending_id)

    def test_journaled_move_persists_metadata(self) -> None:
        """src_sha1, src_size, row_id sont bien persistes."""
        with journaled_move(
            self.store,
            src="C:/film.mkv",
            dst="D:/films/film.mkv",
            op_type="MOVE_FILE",
            batch_id="b42",
            src_sha1="deadbeef",
            src_size=123456,
            row_id="row_007",
        ):
            pass  # no-op
        # Apres le with, l'entree est supprimee — on doit re-INSERT pour verifier
        with journaled_move(
            self.store,
            src="C:/film2.mkv",
            dst="D:/films/film2.mkv",
            op_type="MOVE_DIR",
            batch_id="b42",
            src_sha1="cafebabe",
            src_size=999,
            row_id="row_008",
        ):
            pending = self.store.list_pending_moves()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["src_sha1"], "cafebabe")
            self.assertEqual(pending[0]["src_size"], 999)
            self.assertEqual(pending[0]["row_id"], "row_008")
            self.assertEqual(pending[0]["batch_id"], "b42")

    def test_journaled_move_filter_by_batch_id(self) -> None:
        """list_pending_moves(batch_id=...) filtre correctement."""
        # Inserer 2 entrees dans 2 batches differents — manuellement, sans
        # cleanup automatique (on simule des entrees orphelines).
        self.store.insert_pending_move(op_type="MOVE_FILE", src_path="a", dst_path="b", batch_id="b1")
        self.store.insert_pending_move(op_type="MOVE_FILE", src_path="c", dst_path="d", batch_id="b2")

        all_pending = self.store.list_pending_moves()
        self.assertEqual(len(all_pending), 2)

        b1_pending = self.store.list_pending_moves(batch_id="b1")
        self.assertEqual(len(b1_pending), 1)
        self.assertEqual(b1_pending[0]["src_path"], "a")


class AtomicMoveTests(unittest.TestCase):
    """Tests du helper atomic_move : journaled si record_op a journal_store."""

    def setUp(self) -> None:
        self.store, self._tmp = _make_store()
        self.src = self._tmp / "source.mkv"
        self.dst = self._tmp / "subdir" / "dest.mkv"
        self.src.write_bytes(b"video data")
        self.dst.parent.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_atomic_move_with_record_op_with_journal(self) -> None:
        """RecordOpWithJournal → atomic_move utilise le journal."""
        record_op_calls = []
        plain_record = lambda payload: record_op_calls.append(payload)
        wrapped = RecordOpWithJournal(plain_record, store=self.store, batch_id="batch_x")

        atomic_move(wrapped, src=self.src, dst=self.dst, op_type="MOVE_FILE")

        # Move s'est bien fait
        self.assertFalse(self.src.exists())
        self.assertTrue(self.dst.exists())
        # Journal pending vide (DELETE apres succes)
        self.assertEqual(self.store.count_pending_moves(), 0)

    def test_atomic_move_with_plain_record_op_falls_back(self) -> None:
        """record_op simple (function) → atomic_move fait shutil.move direct."""
        record_op_calls = []
        plain_record = lambda payload: record_op_calls.append(payload)

        atomic_move(plain_record, src=self.src, dst=self.dst, op_type="MOVE_FILE")

        self.assertFalse(self.src.exists())
        self.assertTrue(self.dst.exists())
        self.assertEqual(self.store.count_pending_moves(), 0)

    def test_atomic_move_with_none_record_op(self) -> None:
        """record_op=None → atomic_move fait shutil.move direct."""
        atomic_move(None, src=self.src, dst=self.dst, op_type="MOVE_FILE")
        self.assertFalse(self.src.exists())
        self.assertTrue(self.dst.exists())

    def test_record_op_with_journal_is_callable(self) -> None:
        """RecordOpWithJournal proxie l'appel vers le record_op original."""
        record_op_calls = []
        plain_record = lambda payload: record_op_calls.append(payload)
        wrapped = RecordOpWithJournal(plain_record, store=self.store)

        wrapped({"op_type": "TEST"})
        self.assertEqual(len(record_op_calls), 1)
        self.assertEqual(record_op_calls[0]["op_type"], "TEST")

    def test_record_op_with_journal_handles_none_callable(self) -> None:
        """Si callable_fn=None, __call__ ne plante pas."""
        wrapped = RecordOpWithJournal(None, store=self.store)
        self.assertIsNone(wrapped({"op_type": "TEST"}))


class ReconcilePendingMovesTests(unittest.TestCase):
    """Tests de reconcile_pending_moves : 4 verdicts + cleanup."""

    def setUp(self) -> None:
        self.store, self._tmp = _make_store()
        self.src = self._tmp / "src.mkv"
        self.dst = self._tmp / "dst.mkv"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_pending_entry(self, src_exists: bool, dst_exists: bool) -> dict:
        if src_exists:
            self.src.write_bytes(b"src")
        if dst_exists:
            self.dst.write_bytes(b"dst")
        return {
            "id": 1,
            "src_path": str(self.src),
            "dst_path": str(self.dst),
            "op_type": "MOVE_FILE",
        }

    def test_classify_completed(self) -> None:
        """src absent + dst present → completed (le DELETE pending a juste rate)."""
        entry = self._make_pending_entry(src_exists=False, dst_exists=True)
        self.assertEqual(_classify_pending(entry), "completed")

    def test_classify_rolled_back(self) -> None:
        """src present + dst absent → rolled_back (move pas commence)."""
        entry = self._make_pending_entry(src_exists=True, dst_exists=False)
        self.assertEqual(_classify_pending(entry), "rolled_back")

    def test_classify_duplicated(self) -> None:
        """src present + dst present → duplicated (CONFLIT critique)."""
        entry = self._make_pending_entry(src_exists=True, dst_exists=True)
        self.assertEqual(_classify_pending(entry), "duplicated")

    def test_classify_lost(self) -> None:
        """src absent + dst absent → lost (CRITIQUE, fichier perdu)."""
        entry = self._make_pending_entry(src_exists=False, dst_exists=False)
        self.assertEqual(_classify_pending(entry), "lost")

    def test_reconcile_empty_returns_empty_report(self) -> None:
        """Pas d'entrees pending → rapport vide, pas d'effet."""
        report = reconcile_pending_moves(self.store)
        self.assertEqual(report["examined"], 0)
        self.assertEqual(report["completed"], 0)
        self.assertEqual(report["rolled_back"], 0)
        self.assertEqual(report["duplicated"], [])
        self.assertEqual(report["lost"], [])

    def test_reconcile_completed_cleanup(self) -> None:
        """completed → entree supprimee, pas de message warning."""
        # Move termine : src absent, dst present
        self.dst.write_bytes(b"dst data")
        self.store.insert_pending_move(
            op_type="MOVE_FILE",
            src_path=str(self.src),
            dst_path=str(self.dst),
        )
        report = reconcile_pending_moves(self.store)
        self.assertEqual(report["examined"], 1)
        self.assertEqual(report["completed"], 1)
        self.assertEqual(self.store.count_pending_moves(), 0)
        # Pas de warning critique
        self.assertEqual(report["duplicated"], [])
        self.assertEqual(report["lost"], [])

    def test_reconcile_duplicated_warning(self) -> None:
        """duplicated → message warning + entree supprimee."""
        self.src.write_bytes(b"src")
        self.dst.write_bytes(b"dst")
        self.store.insert_pending_move(
            op_type="MOVE_FILE",
            src_path=str(self.src),
            dst_path=str(self.dst),
        )
        report = reconcile_pending_moves(self.store)
        self.assertEqual(len(report["duplicated"]), 1)
        # Au moins un message warning + un message d'entete
        self.assertTrue(any("CONFLIT" in m for m in report["messages"]))
        self.assertEqual(self.store.count_pending_moves(), 0)

    def test_reconcile_lost_warning(self) -> None:
        """lost → message critique + entree supprimee."""
        self.store.insert_pending_move(
            op_type="MOVE_FILE",
            src_path=str(self.src),
            dst_path=str(self.dst),
        )
        report = reconcile_pending_moves(self.store)
        self.assertEqual(len(report["lost"]), 1)
        self.assertTrue(any("FICHIER PERDU" in m for m in report["messages"]))
        self.assertEqual(self.store.count_pending_moves(), 0)

    def test_reconcile_with_none_store_returns_empty(self) -> None:
        """store=None → no-op, rapport vide, pas d'erreur."""
        report = reconcile_pending_moves(None)
        self.assertEqual(report["examined"], 0)


class ReconcileAtBootTests(unittest.TestCase):
    """Tests de reconcile_at_boot : variante avec notification UI."""

    def setUp(self) -> None:
        self.store, self._tmp = _make_store()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_reconcile_at_boot_no_conflicts_no_notify(self) -> None:
        """Pas de conflits → notify pas appele."""
        notify = MagicMock()
        notify.notify = MagicMock()
        # Une entree completed (sans warning)
        dst = self._tmp / "ok.mkv"
        dst.write_bytes(b"data")
        self.store.insert_pending_move(
            op_type="MOVE_FILE",
            src_path=str(self._tmp / "missing.mkv"),
            dst_path=str(dst),
        )
        report = reconcile_at_boot(self.store, notify=notify)
        self.assertEqual(report["completed"], 1)
        notify.notify.assert_not_called()

    def test_reconcile_at_boot_with_conflicts_notifies(self) -> None:
        """Conflits → notify.notify appele avec event 'error'."""
        notify = MagicMock()
        notify.notify = MagicMock()
        # Entree duplicated (les 2 fichiers existent)
        src = self._tmp / "src.mkv"
        dst = self._tmp / "dst.mkv"
        src.write_bytes(b"a")
        dst.write_bytes(b"b")
        self.store.insert_pending_move(
            op_type="MOVE_FILE",
            src_path=str(src),
            dst_path=str(dst),
        )
        report = reconcile_at_boot(self.store, notify=notify)
        self.assertEqual(len(report["duplicated"]), 1)
        notify.notify.assert_called_once()
        args, kwargs = notify.notify.call_args
        self.assertEqual(args[0], "error")  # event = "error"

    def test_reconcile_at_boot_notify_failure_does_not_crash(self) -> None:
        """Si notify.notify lance, le boot continue (rapport quand meme retourne)."""
        notify = MagicMock()
        notify.notify = MagicMock(side_effect=RuntimeError("notify down"))
        # Entree lost
        self.store.insert_pending_move(
            op_type="MOVE_FILE",
            src_path=str(self._tmp / "ghost1.mkv"),
            dst_path=str(self._tmp / "ghost2.mkv"),
        )
        report = reconcile_at_boot(self.store, notify=notify)
        self.assertEqual(len(report["lost"]), 1)


if __name__ == "__main__":
    unittest.main()
