"""VP-A rollback_forward integration tests.

Couvre l'AC-3 (rollback FS+DB atomique) du plan VP-A :
- Rollback `MOVE_FILE` : fichier deja deplace est replace dans src.
- Rollback `MOVE_DIR` : dossier deplace est replace dans src.
- Rollback partiel (5 sur 10 ops echouent -> tous annules avec status='PARTIAL'
  ou 'DONE' selon le cas).
- Si DB rollback echoue (mock), FS revert est quand meme tente + log d'audit.
- Coordination avec undo classique : rollback_status='ROLLED_BACK_BY_ATOMIC'
  est SEPARE de undo_status (memo plan VP-A open question #5).

Tests non couverts ici (cf. test_apply_atomic_mode_v77 pour migrations + repo
unit tests, et integration full apply_changes au niveau test_apply_undo_*).
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, ".")

from cinesort.app.apply_rollback import (
    ROLLBACK_DONE,
    ROLLBACK_FAILED,
    ROLLBACK_PARTIAL,
    rollback_forward,
)
from cinesort.infra.db.sqlite_store import SQLiteStore


def _make_store() -> tuple[SQLiteStore, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="cinesort_atomic_rb_"))
    store = SQLiteStore(tmp / "test.sqlite", busy_timeout_ms=5000)
    store.initialize()
    return store, tmp


def _create_file(path: Path, size: int = 64) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


class RollbackForwardEmptyBatchTests(unittest.TestCase):
    """Edge cases : batch_id vide, batch sans ops, etc."""

    def setUp(self) -> None:
        self.store, self._tmp = _make_store()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_empty_batch_id_returns_failed(self) -> None:
        result = rollback_forward(self.store, "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["rollback_status"], ROLLBACK_FAILED)

    def test_batch_with_no_ops_returns_done(self) -> None:
        """Batch existe mais aucune op journalisee : rollback success no-op."""
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1", dry_run=False, quarantine_unapproved=False,
        )
        self.store.apply.upsert_atomic_mode(batch_id, True)

        result = rollback_forward(self.store, batch_id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["rollback_status"], ROLLBACK_DONE)
        self.assertEqual(result["counts"]["done"], 0)


class RollbackForwardMoveFileTests(unittest.TestCase):
    """Rollback FS : fichiers deja deplaces sont restaures dans src."""

    def setUp(self) -> None:
        self.store, self._tmp = _make_store()
        self.src_root = self._tmp / "src"
        self.dst_root = self._tmp / "dst"
        self.src_root.mkdir(parents=True, exist_ok=True)
        self.dst_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_rollback_reverts_move_file(self) -> None:
        """AC-3 : fichier au dst doit revenir au src apres rollback."""
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1", dry_run=False, quarantine_unapproved=False,
        )
        self.store.apply.upsert_atomic_mode(batch_id, True)

        src = self.src_root / "movie1.mkv"
        dst = self.dst_root / "movie1.mkv"
        # Simuler un MOVE_FILE deja execute : fichier present a dst, absent a src
        _create_file(dst, size=128)
        self.assertFalse(src.exists())

        # Journaliser l'op
        self.store.apply.append_apply_operation(
            batch_id=batch_id,
            op_index=1,
            op_type="MOVE_FILE",
            src_path=str(src),
            dst_path=str(dst),
            reversible=True,
        )

        result = rollback_forward(self.store, batch_id)
        self.assertTrue(result["ok"], f"Rollback should succeed, got {result}")
        self.assertEqual(result["rollback_status"], ROLLBACK_DONE)
        self.assertEqual(result["counts"]["done"], 1)
        self.assertEqual(result["counts"]["failed"], 0)
        # FS : fichier revenu au src
        self.assertTrue(src.exists())
        self.assertFalse(dst.exists())

        # DB : status final marque
        mode = self.store.apply.get_atomic_mode(batch_id)
        self.assertEqual(mode["rollback_status"], ROLLBACK_DONE)

    def test_rollback_skips_irreversible_ops(self) -> None:
        """Op avec reversible=False : skipped, pas FS touch."""
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1", dry_run=False, quarantine_unapproved=False,
        )
        src = self.src_root / "irr.mkv"
        dst = self.dst_root / "irr.mkv"
        _create_file(dst)
        self.store.apply.append_apply_operation(
            batch_id=batch_id,
            op_index=1,
            op_type="MOVE_FILE",
            src_path=str(src),
            dst_path=str(dst),
            reversible=False,
        )

        result = rollback_forward(self.store, batch_id)
        self.assertEqual(result["counts"]["skipped"], 1)
        self.assertEqual(result["counts"]["done"], 0)
        # FS inchange : fichier reste au dst
        self.assertTrue(dst.exists())
        self.assertFalse(src.exists())

    def test_rollback_skips_when_dst_missing(self) -> None:
        """Si le fichier a dst a disparu (manuel, cleanup), skip + log audit."""
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1", dry_run=False, quarantine_unapproved=False,
        )
        src = self.src_root / "ghost.mkv"
        dst = self.dst_root / "ghost.mkv"
        # On NE CREE PAS dst — il est manquant
        self.store.apply.append_apply_operation(
            batch_id=batch_id,
            op_index=1,
            op_type="MOVE_FILE",
            src_path=str(src),
            dst_path=str(dst),
            reversible=True,
        )

        audit_calls = []
        def audit_fn(level, msg):
            audit_calls.append((level, msg))

        result = rollback_forward(self.store, batch_id, audit_fn=audit_fn)
        self.assertEqual(result["counts"]["skipped"], 1)
        self.assertEqual(result["counts"]["done"], 0)
        # Log d'audit emis
        self.assertTrue(any("dst manquant" in msg for _, msg in audit_calls))

    def test_rollback_skips_when_src_already_exists(self) -> None:
        """Si src existe deja (collision), skip + log."""
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1", dry_run=False, quarantine_unapproved=False,
        )
        src = self.src_root / "exists.mkv"
        dst = self.dst_root / "exists.mkv"
        _create_file(src)
        _create_file(dst)
        self.store.apply.append_apply_operation(
            batch_id=batch_id,
            op_index=1,
            op_type="MOVE_FILE",
            src_path=str(src),
            dst_path=str(dst),
            reversible=True,
        )

        result = rollback_forward(self.store, batch_id)
        self.assertEqual(result["counts"]["skipped"], 1)
        # Les 2 fichiers restent en place
        self.assertTrue(src.exists())
        self.assertTrue(dst.exists())


class RollbackForwardMixedBatchTests(unittest.TestCase):
    """Plusieurs ops dans un meme batch : reverse order + partial status."""

    def setUp(self) -> None:
        self.store, self._tmp = _make_store()
        self.src_root = self._tmp / "src"
        self.dst_root = self._tmp / "dst"
        self.src_root.mkdir(parents=True, exist_ok=True)
        self.dst_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_rollback_5_of_10_partial(self) -> None:
        """Plan VP-A test integration : 5 sur 10 deplacements echouent.

        On simule 10 ops : 5 sont revertables (dst present), 5 sont skipped
        (dst manquant). Le rollback final est DONE (aucun FAILED) avec 5
        done + 5 skipped.
        """
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1", dry_run=False, quarantine_unapproved=False,
        )
        self.store.apply.upsert_atomic_mode(batch_id, True)

        for i in range(10):
            src = self.src_root / f"movie{i}.mkv"
            dst = self.dst_root / f"movie{i}.mkv"
            if i < 5:
                _create_file(dst)  # revert-able
            # i >= 5 : dst manquant -> skip
            self.store.apply.append_apply_operation(
                batch_id=batch_id,
                op_index=i + 1,
                op_type="MOVE_FILE",
                src_path=str(src),
                dst_path=str(dst),
                reversible=True,
            )

        result = rollback_forward(self.store, batch_id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["counts"]["done"], 5)
        self.assertEqual(result["counts"]["skipped"], 5)
        self.assertEqual(result["counts"]["failed"], 0)
        self.assertEqual(result["rollback_status"], ROLLBACK_DONE)

        # Verifier que les 5 fichiers reverted sont au src
        for i in range(5):
            self.assertTrue((self.src_root / f"movie{i}.mkv").exists())
            self.assertFalse((self.dst_root / f"movie{i}.mkv").exists())

    def test_rollback_reverse_order_execution(self) -> None:
        """Les ops sont revertes dans l'ordre inverse (LIFO) du journal."""
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1", dry_run=False, quarantine_unapproved=False,
        )
        order_seen = []

        for i in range(3):
            src = self.src_root / f"m{i}.mkv"
            dst = self.dst_root / f"m{i}.mkv"
            _create_file(dst)
            self.store.apply.append_apply_operation(
                batch_id=batch_id,
                op_index=i + 1,
                op_type="MOVE_FILE",
                src_path=str(src),
                dst_path=str(dst),
                reversible=True,
            )

        result = rollback_forward(self.store, batch_id)
        # On verifie via le tableau details : op_index doit etre decroissant
        op_indices = [d["op_index"] for d in result["details"]]
        self.assertEqual(op_indices, [3, 2, 1], "Rollback en ordre inverse (LIFO)")


class RollbackForwardDbFailureTests(unittest.TestCase):
    """AC-3 : si DB rollback echoue, FS revert tente + audit log."""

    def setUp(self) -> None:
        self.store, self._tmp = _make_store()
        self.src_root = self._tmp / "src"
        self.dst_root = self._tmp / "dst"
        self.src_root.mkdir(parents=True, exist_ok=True)
        self.dst_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_db_mark_failure_degrades_to_partial(self) -> None:
        """Si mark_rollback_status final echoue, on retourne ROLLBACK_PARTIAL
        avec FS revert deja effectue (audit log emis)."""
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1", dry_run=False, quarantine_unapproved=False,
        )
        src = self.src_root / "m.mkv"
        dst = self.dst_root / "m.mkv"
        _create_file(dst)
        self.store.apply.append_apply_operation(
            batch_id=batch_id,
            op_index=1,
            op_type="MOVE_FILE",
            src_path=str(src),
            dst_path=str(dst),
            reversible=True,
        )

        original_mark = self.store.apply.mark_rollback_status
        call_count = {"n": 0}

        def flaky_mark(*args, **kwargs):
            call_count["n"] += 1
            # Premier appel (IN_PROGRESS) OK ; deuxieme (final) leve
            if call_count["n"] >= 2:
                raise sqlite3.OperationalError("DB locked simulated")
            return original_mark(*args, **kwargs)

        audit_calls = []
        def audit_fn(level, msg):
            audit_calls.append((level, msg))

        with patch.object(
            self.store.apply, "mark_rollback_status", side_effect=flaky_mark
        ):
            result = rollback_forward(self.store, batch_id, audit_fn=audit_fn)

        # FS revert a quand meme eu lieu
        self.assertTrue(src.exists())
        self.assertFalse(dst.exists())
        # Statut degrade en PARTIAL (DB tracking failed)
        self.assertEqual(result["rollback_status"], ROLLBACK_PARTIAL)
        # Audit log emis sur l'echec DB
        self.assertTrue(any("FAILED" in msg for _, msg in audit_calls))


class RollbackForwardCoordinationUndoTests(unittest.TestCase):
    """Plan VP-A open question #5 : rollback_status SEPARE de undo_status.

    Verifie que rollback_forward NE TOUCHE PAS aux flags undo_status
    existants sur apply_operations. La chaine undo manuelle
    (`get_last_reversible_apply_batch` + `mark_apply_operation_undo_status`)
    reste autorite, et rollback_status est dans la table apply_batch_modes.
    """

    def setUp(self) -> None:
        self.store, self._tmp = _make_store()
        self.src_root = self._tmp / "src"
        self.dst_root = self._tmp / "dst"
        self.src_root.mkdir(parents=True, exist_ok=True)
        self.dst_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_rollback_does_not_change_undo_status(self) -> None:
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1", dry_run=False, quarantine_unapproved=False,
        )
        src = self.src_root / "m.mkv"
        dst = self.dst_root / "m.mkv"
        _create_file(dst)
        self.store.apply.append_apply_operation(
            batch_id=batch_id,
            op_index=1,
            op_type="MOVE_FILE",
            src_path=str(src),
            dst_path=str(dst),
            reversible=True,
        )

        rollback_forward(self.store, batch_id)

        ops = self.store.apply.list_apply_operations(batch_id=batch_id)
        # undo_status n'a PAS ete touche par rollback_forward (reste 'PENDING')
        self.assertEqual(ops[0]["undo_status"], "PENDING")

        # rollback_status SEPARE dans apply_batch_modes
        mode = self.store.apply.get_atomic_mode(batch_id)
        self.assertEqual(mode["rollback_status"], ROLLBACK_DONE)

    def test_get_last_reversible_apply_batch_not_impacted(self) -> None:
        """`get_last_reversible_apply_batch` se base sur status='DONE'.
        Un batch rollback-atomique (status='FAILED') ne doit PAS apparaitre.
        """
        batch_id = self.store.apply.insert_apply_batch(
            run_id="r1", dry_run=False, quarantine_unapproved=False,
        )
        # Le batch reste PENDING -> get_last_reversible doit NE PAS le voir
        result = self.store.apply.get_last_reversible_apply_batch("r1")
        self.assertIsNone(result)

        # Apres rollback atomique (qui ne change pas status='DONE'), idem.
        self.store.apply.upsert_atomic_mode(batch_id, True)
        rollback_forward(self.store, batch_id)

        result_after = self.store.apply.get_last_reversible_apply_batch("r1")
        # Toujours None (batch n'est jamais passe a DONE)
        self.assertIsNone(result_after)


class ApplyChangesBackwardCompatTests(unittest.TestCase):
    """AC-1 : signature `apply_changes(apply_atomic=...)` retourne {ok: bool}."""

    def test_signature_accepts_apply_atomic_kwarg(self) -> None:
        """`apply_atomic` est un kwarg accepte par apply_changes."""
        import inspect

        from cinesort.ui.api import apply_support

        sig = inspect.signature(apply_support.apply_changes)
        self.assertIn("apply_atomic", sig.parameters)
        # Default = False (opt-in strict)
        self.assertFalse(sig.parameters["apply_atomic"].default)

    def test_signature_run_facade_apply_accepts_atomic(self) -> None:
        import inspect

        from cinesort.ui.api.facades.run_facade import RunFacade

        sig = inspect.signature(RunFacade.apply)
        self.assertIn("apply_atomic", sig.parameters)
        self.assertFalse(sig.parameters["apply_atomic"].default)

    def test_signature_apply_impl_accepts_atomic(self) -> None:
        import inspect

        from cinesort.ui.api.cinesort_api import CineSortApi

        sig = inspect.signature(CineSortApi._apply_impl)
        self.assertIn("apply_atomic", sig.parameters)
        self.assertFalse(sig.parameters["apply_atomic"].default)


if __name__ == "__main__":
    unittest.main()
