"""Vague P / VP-D : Decisions tri-etat (accepted/rejected/deferred).

AC-1 : migration 031 testee sur fixture v30 reelle (post-VP-C) — voir
       test_existing_db_fixture_v77.py.
AC-2 : signature API `save_validation()` retourne `{ok:bool}` sur appel
       legacy — voir test_save_validation_backward_compat.py.
AC-3 : transition `deferred -> accepted` respecte les `field_locks` de VP-C.
AC-4 : `dangerConfirmModal` "Rejeter Tout > 50 items" countdown 3s — UI.
AC-5 : coexistence apply_atomic (VP-A) sans collision kwargs.

Memoire `feedback_sqlite_migration_test_existing_db` : la migration 031
DOIT etre testee sur une DB pre-existante a v30 (post-VP-C field_locks),
pas seulement sur fresh DB.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path

sys.path.insert(0, ".")

from cinesort.infra.db.migration_manager import _split_sql_statements
from cinesort.infra.db.repositories.decisions import (
    DECISION_ACCEPTED,
    DECISION_DEFERRED,
    DECISION_REJECTED,
    DecisionsRepository,
    from_legacy_ok_bool,
    to_legacy_ok_bool,
)
from cinesort.infra.db.repositories.field_locks import FieldLocksRepository
from tests._helpers import _project_migrations_dir


def _apply_migration(conn: sqlite3.Connection, version: int) -> None:
    fname = {
        30: "030_field_locks.sql",
        31: "031_tri_etat_decisions.sql",
    }[version]
    sql = (_project_migrations_dir() / fname).read_text(encoding="utf-8")
    for stmt in _split_sql_statements(sql):
        conn.execute(stmt)
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()


class _FakeStore:
    """Stub SQLiteStore minimal pour DecisionsRepository et FieldLocksRepository."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _managed_conn(self):
        @contextmanager
        def _ctx():
            with closing(self._connect()) as conn, conn:
                yield conn

        return _ctx()

    def _ensure_schema_group(self, group_name, *, min_user_version=None):
        # Migrations deja appliquees dans setUp.
        return None


# ---------------------------------------------------------------------------
# Helpers backward compat (to_legacy_ok_bool / from_legacy_ok_bool)
# ---------------------------------------------------------------------------


class LegacyOkBoolHelperTests(unittest.TestCase):
    """Tests purs de la projection backward compat tri-etat <-> ok:bool."""

    def test_to_legacy_ok_bool_accepted_returns_true(self):
        self.assertTrue(to_legacy_ok_bool("accepted"))

    def test_to_legacy_ok_bool_rejected_returns_false(self):
        self.assertFalse(to_legacy_ok_bool("rejected"))

    def test_to_legacy_ok_bool_deferred_returns_false(self):
        """Un film 'reporte' n'est PAS approuve pour apply — backward compat."""
        self.assertFalse(to_legacy_ok_bool("deferred"))

    def test_to_legacy_ok_bool_none_returns_false(self):
        self.assertFalse(to_legacy_ok_bool(None))

    def test_to_legacy_ok_bool_unknown_returns_false(self):
        """Toute valeur non reconnue projette a False (safe default)."""
        self.assertFalse(to_legacy_ok_bool("garbage"))
        self.assertFalse(to_legacy_ok_bool(""))
        self.assertFalse(to_legacy_ok_bool(42))

    def test_to_legacy_ok_bool_case_insensitive(self):
        self.assertTrue(to_legacy_ok_bool("ACCEPTED"))
        self.assertTrue(to_legacy_ok_bool("Accepted"))

    def test_from_legacy_ok_bool_true_returns_accepted(self):
        self.assertEqual(from_legacy_ok_bool(True), DECISION_ACCEPTED)

    def test_from_legacy_ok_bool_false_returns_rejected(self):
        self.assertEqual(from_legacy_ok_bool(False), DECISION_REJECTED)

    def test_from_legacy_ok_bool_none_returns_rejected(self):
        self.assertEqual(from_legacy_ok_bool(None), DECISION_REJECTED)


# ---------------------------------------------------------------------------
# Repository CRUD : set / get / clear / list
# ---------------------------------------------------------------------------


class DecisionsRepositoryCrudTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_root = Path(tempfile.mkdtemp(prefix="cinesort_decisions_"))
        self.db_path = self.tmp_root / "store.sqlite3"
        conn = sqlite3.connect(str(self.db_path))
        try:
            _apply_migration(conn, 31)
        finally:
            conn.close()
        self.repo = DecisionsRepository(_FakeStore(self.db_path))

    def test_set_decision_accepted(self):
        res = self.repo.set_decision("tmdb:603", "run-1", DECISION_ACCEPTED)
        self.assertTrue(res["ok"])
        self.assertEqual(res["decision"], DECISION_ACCEPTED)
        self.assertGreater(res["decided_at"], 0)

    def test_set_decision_deferred(self):
        res = self.repo.set_decision("tmdb:603", "run-1", DECISION_DEFERRED)
        self.assertTrue(res["ok"])
        self.assertEqual(res["decision"], DECISION_DEFERRED)

    def test_set_decision_rejected(self):
        res = self.repo.set_decision("tmdb:603", "run-1", DECISION_REJECTED)
        self.assertTrue(res["ok"])

    def test_set_decision_invalid_value_rejected(self):
        """Une decision hors {accepted, rejected, deferred} doit echouer."""
        res = self.repo.set_decision("tmdb:603", "run-1", "garbage")
        self.assertFalse(res["ok"])
        self.assertIn("decision invalide", res["reason"])

    def test_set_decision_empty_film_id_rejected(self):
        res = self.repo.set_decision("", "run-1", DECISION_ACCEPTED)
        self.assertFalse(res["ok"])

    def test_get_decision_returns_none_if_absent(self):
        self.assertIsNone(self.repo.get_decision("tmdb:999", "run-x"))

    def test_get_decision_returns_full_payload(self):
        self.repo.set_decision(
            "tmdb:603",
            "run-1",
            DECISION_DEFERRED,
            row_id="r-7",
            decided_by="user",
            reason="hesitation",
        )
        got = self.repo.get_decision("tmdb:603", "run-1")
        self.assertIsNotNone(got)
        self.assertEqual(got["decision"], DECISION_DEFERRED)
        self.assertEqual(got["decided_by"], "user")
        self.assertEqual(got["reason"], "hesitation")
        self.assertEqual(got["row_id"], "r-7")

    def test_set_decision_upsert_replaces_previous(self):
        """Re-poser une decision sur (film_id, run_id) UNIQUE doit ecraser."""
        self.repo.set_decision("tmdb:603", "run-1", DECISION_DEFERRED)
        self.repo.set_decision("tmdb:603", "run-1", DECISION_ACCEPTED)
        got = self.repo.get_decision("tmdb:603", "run-1")
        self.assertEqual(got["decision"], DECISION_ACCEPTED)
        # Une seule ligne en DB
        conn = sqlite3.connect(str(self.db_path))
        try:
            cur = conn.execute(
                "SELECT COUNT(*) FROM film_decisions_v2 WHERE film_id=? AND run_id=?",
                ("tmdb:603", "run-1"),
            )
            self.assertEqual(int(cur.fetchone()[0]), 1)
        finally:
            conn.close()

    def test_clear_decision_removes_row(self):
        self.repo.set_decision("tmdb:603", "run-1", DECISION_ACCEPTED)
        res = self.repo.clear_decision("tmdb:603", "run-1")
        self.assertTrue(res["ok"])
        self.assertTrue(res["removed"])
        self.assertIsNone(self.repo.get_decision("tmdb:603", "run-1"))

    def test_clear_decision_returns_removed_false_if_absent(self):
        res = self.repo.clear_decision("tmdb:999", "run-x")
        self.assertTrue(res["ok"])
        self.assertFalse(res["removed"])

    def test_list_decisions_for_run(self):
        self.repo.set_decision("tmdb:1", "run-1", DECISION_ACCEPTED)
        self.repo.set_decision("tmdb:2", "run-1", DECISION_REJECTED)
        self.repo.set_decision("tmdb:3", "run-1", DECISION_DEFERRED)
        self.repo.set_decision("tmdb:99", "run-2", DECISION_ACCEPTED)  # autre run

        items = self.repo.list_decisions_for_run("run-1")
        self.assertEqual(len(items), 3)

    def test_list_decisions_for_run_filter(self):
        self.repo.set_decision("tmdb:1", "run-1", DECISION_ACCEPTED)
        self.repo.set_decision("tmdb:2", "run-1", DECISION_DEFERRED)
        self.repo.set_decision("tmdb:3", "run-1", DECISION_DEFERRED)

        deferred_only = self.repo.list_decisions_for_run("run-1", decision_filter=DECISION_DEFERRED)
        self.assertEqual(len(deferred_only), 2)
        for entry in deferred_only:
            self.assertEqual(entry["decision"], DECISION_DEFERRED)

    def test_list_decisions_for_film(self):
        self.repo.set_decision("tmdb:603", "run-1", DECISION_DEFERRED)
        self.repo.set_decision("tmdb:603", "run-2", DECISION_ACCEPTED)
        self.repo.set_decision("tmdb:42", "run-1", DECISION_REJECTED)

        items = self.repo.list_decisions_for_film("tmdb:603")
        self.assertEqual(len(items), 2)


# ---------------------------------------------------------------------------
# AC-3 : transitions deferred -> accepted respectent VP-C field_locks
# ---------------------------------------------------------------------------


class TransitionDeferredToAcceptedTests(unittest.TestCase):
    """AC-3 : upgrade deferred->accepted consulte les field_locks VP-C."""

    def setUp(self) -> None:
        self.tmp_root = Path(tempfile.mkdtemp(prefix="cinesort_transitions_"))
        self.db_path = self.tmp_root / "store.sqlite3"
        # On a besoin des 2 tables : field_locks (030) ET decisions (031).
        conn = sqlite3.connect(str(self.db_path))
        try:
            _apply_migration(conn, 30)
            _apply_migration(conn, 31)
        finally:
            conn.close()

        store = _FakeStore(self.db_path)
        self.decisions_repo = DecisionsRepository(store)
        self.locks_repo = FieldLocksRepository(store)

    def test_upgrade_deferred_to_accepted_basic(self):
        # Etape 1 : decision deferred
        self.decisions_repo.set_decision("tmdb:603", "run-1", DECISION_DEFERRED)
        # Etape 2 : aucun lock pose
        locks = self.locks_repo.list_locks("tmdb:603")
        locked_fields = [lk["field_name"] for lk in locks]

        # Etape 3 : upgrade
        res = self.decisions_repo.upgrade_deferred_to_accepted("tmdb:603", "run-1", locked_fields=locked_fields)
        self.assertTrue(res["ok"])
        self.assertEqual(res["previous_decision"], DECISION_DEFERRED)
        self.assertEqual(res["new_decision"], DECISION_ACCEPTED)
        self.assertEqual(res["respected_locks"], [])
        self.assertIsNone(res["warning"])

    def test_upgrade_deferred_to_accepted_with_locks(self):
        """AC-3 : si des champs sont verrouilles, ils sont remontes par la repo."""
        # 1. Poser des locks
        self.locks_repo.set_lock("tmdb:603", "title", "Matrix manuel")
        self.locks_repo.set_lock("tmdb:603", "year", 1999)

        # 2. Decision deferred
        self.decisions_repo.set_decision("tmdb:603", "run-1", DECISION_DEFERRED)

        # 3. Caller consulte locks puis upgrade
        locks = self.locks_repo.list_locks("tmdb:603")
        locked_fields = [lk["field_name"] for lk in locks]
        self.assertCountEqual(locked_fields, ["title", "year"])

        res = self.decisions_repo.upgrade_deferred_to_accepted("tmdb:603", "run-1", locked_fields=locked_fields)
        self.assertTrue(res["ok"])
        self.assertCountEqual(res["respected_locks"], ["title", "year"])

        # La decision est bien stockee comme accepted
        got = self.decisions_repo.get_decision("tmdb:603", "run-1")
        self.assertEqual(got["decision"], DECISION_ACCEPTED)

    def test_upgrade_warns_if_locks_not_consulted(self):
        """Si le caller passe locked_fields=None, on log un warning."""
        self.decisions_repo.set_decision("tmdb:603", "run-1", DECISION_DEFERRED)
        res = self.decisions_repo.upgrade_deferred_to_accepted("tmdb:603", "run-1", locked_fields=None)
        self.assertTrue(res["ok"])
        self.assertIsNotNone(res["warning"])
        self.assertIn("field_locks", res["warning"])

    def test_upgrade_without_previous_decision(self):
        """Upgrade sans decision prealable doit creer accepted (idempotent)."""
        res = self.decisions_repo.upgrade_deferred_to_accepted("tmdb:603", "run-1", locked_fields=[])
        self.assertTrue(res["ok"])
        self.assertIsNone(res["previous_decision"])
        self.assertEqual(res["new_decision"], DECISION_ACCEPTED)


# ---------------------------------------------------------------------------
# AC-5 : coexistence apply_atomic (VP-A) sans collision kwargs
# ---------------------------------------------------------------------------


class ApplyAtomicCoexistenceTests(unittest.TestCase):
    """AC-5 : aucune collision kwargs entre `apply_atomic` (VP-A) et `decision` (VP-D).

    `apply_atomic` est un kwarg sur `apply()` (run_facade), pas sur
    `save_validation()`. La signature de chaque endpoint reste distincte.
    """

    def test_save_validation_signature_does_not_have_apply_atomic(self):
        """La signature de `save_validation` n'expose PAS apply_atomic."""
        import inspect

        from cinesort.ui.api.facades.run_facade import RunFacade

        sig = inspect.signature(RunFacade.save_validation)
        params = set(sig.parameters.keys())
        # `apply_atomic` est reserve a apply(), pas a save_validation().
        self.assertNotIn("apply_atomic", params)
        # `decisions` est bien present (legacy)
        self.assertIn("decisions", params)

    def test_apply_signature_has_apply_atomic(self):
        """La signature de `apply` continue d'avoir apply_atomic (VP-A)."""
        import inspect

        from cinesort.ui.api.facades.run_facade import RunFacade

        sig = inspect.signature(RunFacade.apply)
        params = set(sig.parameters.keys())
        self.assertIn("apply_atomic", params)
        # Default False (opt-in)
        self.assertEqual(sig.parameters["apply_atomic"].default, False)

    def test_decisions_repo_does_not_consume_apply_atomic(self):
        """La repo decisions n'accepte pas apply_atomic en kwargs."""
        import inspect

        sig = inspect.signature(DecisionsRepository.set_decision)
        params = set(sig.parameters.keys())
        self.assertNotIn("apply_atomic", params)


# ---------------------------------------------------------------------------
# Persistance (close/reopen) — analogue Jellyfin #15549
# ---------------------------------------------------------------------------


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_root = Path(tempfile.mkdtemp(prefix="cinesort_decisions_persist_"))
        self.db_path = self.tmp_root / "store.sqlite3"
        conn = sqlite3.connect(str(self.db_path))
        try:
            _apply_migration(conn, 31)
        finally:
            conn.close()

    def _build_repo(self) -> DecisionsRepository:
        return DecisionsRepository(_FakeStore(self.db_path))

    def test_decision_persists_after_close_reopen(self):
        repo = self._build_repo()
        repo.set_decision("tmdb:603", "run-1", DECISION_DEFERRED, reason="hesitation")

        # Nouveau repo = nouveau handle SQLite.
        repo2 = self._build_repo()
        got = repo2.get_decision("tmdb:603", "run-1")
        self.assertIsNotNone(got)
        self.assertEqual(got["decision"], DECISION_DEFERRED)
        self.assertEqual(got["reason"], "hesitation")


if __name__ == "__main__":
    unittest.main()
