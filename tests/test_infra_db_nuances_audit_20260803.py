"""Nuances infra/db de l'ultra-audit 2026-08-03 (N06, N21, N23, N26, N27, N28).

Chaque classe couvre UN finding et n'observe que du COMPORTEMENT (nombre de
connexions ouvertes, fichiers presents, statut renvoye, exception levee, log
emis) — jamais une chaine de code source.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing, contextmanager, suppress
from pathlib import Path
from typing import Iterator, List, Optional
from unittest import mock

from cinesort.infra.db import connection as connection_module
from cinesort.infra.db import sqlite_store as sqlite_store_module
from cinesort.infra.db.repositories.apply import ApplyBatchStateError
from cinesort.infra.db.sqlite_store import REQUIRED_SCHEMA_TABLES, SCHEMA_GROUPS, SQLiteStore

_STORE_LOGGER = "cinesort.infra.db.sqlite_store"


@contextmanager
def _capture_store_logs() -> Iterator[List[logging.LogRecord]]:
    """Capture les records du logger du store, y compris quand il n'y en a AUCUN.

    `assertLogs` echoue quand rien n'est logue, ce qui est precisement l'issue
    attendue de la moitie des tests de diagnostic ci-dessous.
    """
    records: List[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Collector()
    store_logger = logging.getLogger(_STORE_LOGGER)
    previous_level = store_logger.level
    store_logger.addHandler(handler)
    store_logger.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        store_logger.setLevel(previous_level)
        store_logger.removeHandler(handler)


class _ConnectionCounter:
    """Compte les ouvertures reelles de connexion SQLite faites par le store."""

    def __init__(self) -> None:
        self.count = 0
        self._real = connection_module.connect_sqlite

    def __enter__(self) -> "_ConnectionCounter":
        def counting(*args, **kwargs):
            self.count += 1
            return self._real(*args, **kwargs)

        self._patch = mock.patch.object(sqlite_store_module, "connect_sqlite", counting)
        self._patch.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._patch.stop()


class _TmpDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_nuance_db_"))
        self.db_path = self._tmp / "db" / "cinesort.sqlite"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _backups(self, pattern: str = "*.bak") -> List[Path]:
        backup_dir = self.db_path.parent / "backups"
        if not backup_dir.is_dir():
            return []
        return sorted(backup_dir.glob(pattern))


# ---------------------------------------------------------------------------
# N21 (HIGH) — memoisation des verifications de schema
# ---------------------------------------------------------------------------


class SchemaCheckMemoTests(_TmpDbTestCase):
    """N21 : chaque appel de repository ouvrait 1 a 2 connexions parasites.

    Mesure de reference sur ce meme harnais AVANT correctif : 2 connexions pour
    `film_modal.get_tmdb_override`, 3 pour `field_locks.list_locks` (le
    `min_user_version` ajoutait un `get_user_version()`). Apres : 1, celle du
    travail utile.
    """

    def test_repeated_repository_calls_open_one_connection_each(self) -> None:
        store = SQLiteStore(self.db_path)
        store.initialize()
        store.film_modal.get_tmdb_override(run_id="R1", row_id="row0")  # amorce le memo

        with _ConnectionCounter() as counter:
            for i in range(20):
                store.film_modal.get_tmdb_override(run_id="R1", row_id=f"row{i}")

        self.assertEqual(
            counter.count,
            20,
            f"{counter.count} connexions pour 20 appels : la verification de schema n'est pas memoisee",
        )

    def test_min_user_version_group_is_memoized_too(self) -> None:
        """Le groupe avec `min_user_version` ouvrait UNE connexion de plus."""
        store = SQLiteStore(self.db_path)
        store.initialize()
        store.field_locks.list_locks("film-1")

        with _ConnectionCounter() as counter:
            for _ in range(10):
                store.field_locks.list_locks("film-1")

        self.assertEqual(counter.count, 10, f"{counter.count} connexions pour 10 appels")

    def test_memo_does_not_survive_deletion_of_the_db_file(self) -> None:
        """Le memo ne doit pas survivre a une suppression du fichier de base.

        `reset_database` (UI Parametres) supprime le .sqlite sans remplacer
        l'instance de store, et docs/TROUBLESHOOTING.md recommande la meme
        suppression manuelle en dernier recours. Un memo non invalide rendrait
        le store inutilisable jusqu'au redemarrage.
        """
        store = SQLiteStore(self.db_path)
        store.initialize()
        store.film_modal.get_tmdb_override(run_id="R1", row_id="row0")

        self.db_path.unlink()
        for suffix in ("-wal", "-shm"):
            Path(str(self.db_path) + suffix).unlink(missing_ok=True)

        # Doit se self-healer, pas lever "no such table".
        self.assertIsNone(store.film_modal.get_tmdb_override(run_id="R1", row_id="row0"))
        self.assertTrue(self.db_path.is_file())

    def test_no_memo_when_filesystem_exposes_no_inode(self) -> None:
        """Sans numero d'inode exploitable, on ne memoise pas du tout.

        Un `st_ino` a 0 (certains montages reseau) rendrait impossible de
        distinguer un fichier supprime puis recree : on repasse alors au
        comportement d'origine plutot que de risquer un memo perime.
        """
        store = SQLiteStore(self.db_path)
        store.initialize()
        real_stat = Path.stat

        class _NoInodeStat:
            def __init__(self, wrapped) -> None:
                self._w = wrapped
                self.st_ino = 0

            def __getattr__(self, name):
                return getattr(self._w, name)

        def fake_stat(self, *args, **kwargs):
            return _NoInodeStat(real_stat(self, *args, **kwargs))

        with mock.patch.object(Path, "stat", fake_stat):
            store.film_modal.get_tmdb_override(run_id="R1", row_id="row0")
            with _ConnectionCounter() as counter:
                store.film_modal.get_tmdb_override(run_id="R1", row_id="row1")
            self.assertGreater(
                counter.count,
                1,
                "sans identite de fichier fiable, la verification de schema doit etre refaite",
            )

    def test_memo_does_not_survive_a_db_file_replaced_by_another(self) -> None:
        """Le memo doit tomber quand le .sqtile est remplace par un AUTRE fichier.

        C'est la garde que le seul `stat()`-echoue-donc-None ne couvre pas : ici
        le fichier existe toujours au moment du controle, seule son identite a
        change. Sans comparaison d'inode, le store ferait confiance a un memo
        pris sur un fichier qui n'existe plus.
        """
        store = SQLiteStore(self.db_path)
        store.initialize()
        store.film_modal.get_tmdb_override(run_id="R1", row_id="row0")

        self.db_path.unlink()
        for suffix in ("-wal", "-shm"):
            Path(str(self.db_path) + suffix).unlink(missing_ok=True)
        # Un autre fichier SQLite valide, SANS le schema CineSort, prend la place.
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.execute("CREATE TABLE zz(x)")
            conn.commit()

        self.assertIsNone(store.film_modal.get_tmdb_override(run_id="R1", row_id="row0"))

    def test_memo_does_not_survive_an_initialize_that_rolled_the_db_back(self) -> None:
        """initialize() peut faire RECULER le contenu de la base, en place.

        `restore_backup` ecrit via l'API de sauvegarde SQLite dans le fichier
        existant : l'inode ne change pas, seul le CONTENU recule. Un memo pris
        avant ce rollback serait donc a la fois obsolete et indetectable par
        l'identite du fichier — d'ou le vidage du memo en tete d'initialize().
        """
        store = SQLiteStore(self.db_path)
        store.initialize()
        store.field_locks.list_locks("film-1")  # memoise le groupe field_locks

        # Backup "d'avant la feature" : meme base, mais sans film_field_locks.
        backup_dir = self.db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        old_backup = backup_dir / "cinesort.20260101-000000-000000Z.pre_migration.bak"
        shutil.copy2(self.db_path, old_backup)
        with closing(sqlite3.connect(str(old_backup))) as conn:
            conn.execute("DROP TABLE film_field_locks")
            conn.execute("PRAGMA user_version = 29")
            conn.commit()

        def _boom(_self) -> int:
            raise sqlite3.DatabaseError("migration boom (test)")

        with mock.patch.object(SQLiteStore, "_apply_schema_migrations", _boom):
            with self.assertRaises(RuntimeError):
                store.initialize()

        with closing(sqlite3.connect(str(self.db_path))) as conn:
            names = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("film_field_locks", names, "le rollback pre_migration n'a pas eu lieu")

        # Le store doit re-verifier et se reparer, pas faire confiance a son memo.
        self.assertEqual(store.field_locks.list_locks("film-1"), [])


# ---------------------------------------------------------------------------
# N27 (MEDIUM) — user_quality_feedback absente du registre self-heal
# ---------------------------------------------------------------------------


class RequiredSchemaTablesCoverageTests(_TmpDbTestCase):
    """N27 : la seule table de SCHEMA_GROUPS hors REQUIRED_SCHEMA_TABLES."""

    def test_every_schema_group_table_is_self_healable(self) -> None:
        """Invariant unidirectionnel : REQUIRED peut contenir plus, pas moins."""
        grouped = {name for tables in SCHEMA_GROUPS.values() for name in tables}
        self.assertEqual(
            sorted(grouped - set(REQUIRED_SCHEMA_TABLES)),
            [],
            "une table exposee par un groupe de schema n'est pas dans le filet self-heal",
        )

    def test_dropped_user_quality_feedback_is_recreated(self) -> None:
        store = SQLiteStore(self.db_path)
        store.initialize()
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.execute("DROP TABLE user_quality_feedback")
            conn.commit()

        store2 = SQLiteStore(self.db_path)
        store2.quality.insert_user_quality_feedback(
            run_id="R1",
            row_id="row1",
            computed_score=80,
            computed_tier="good",
            user_tier="excellent",
            tier_delta=1,
        )

        with closing(sqlite3.connect(str(self.db_path))) as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM user_quality_feedback").fetchone()[0])
        self.assertEqual(total, 1)

    def test_five_feedback_submissions_on_a_broken_db_all_succeed(self) -> None:
        """Le scenario decrit par la passe adversaire, bout en bout.

        Base abimee hors-bande (uqf seule manquante) + 5 envois de feedback :
        avant, les 5 levaient `no such table` et chaque tentative poussait un
        backup de plus. Apres, la premiere repare la base et les 5 aboutissent.
        """
        store = SQLiteStore(self.db_path)
        store.initialize()
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.execute("DROP TABLE user_quality_feedback")
            conn.commit()

        store2 = SQLiteStore(self.db_path)
        for i in range(5):
            store2.quality.insert_user_quality_feedback(
                run_id="R1",
                row_id=f"row{i}",
                computed_score=80,
                computed_tier="good",
                user_tier="excellent",
                tier_delta=1,
            )

        with closing(sqlite3.connect(str(self.db_path))) as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM user_quality_feedback").fetchone()[0])
        self.assertEqual(total, 5)
        self.assertLessEqual(
            len(self._backups("*.pre_migration.bak")),
            1,
            "une base reparee une fois ne doit pas continuer a pousser des backups",
        )


# ---------------------------------------------------------------------------
# N28 (MEDIUM) — un backup pre_migration a CHAQUE boot evince les backups riches
# ---------------------------------------------------------------------------


class PreMigrationBackupFrequencyTests(_TmpDbTestCase):
    """N28 : rotation par mtime seule + backup inconditionnel = eviction."""

    def _seed_marker(self, path: Path, value: str) -> None:
        with closing(sqlite3.connect(str(path))) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS marker(x TEXT)")
            conn.execute("DELETE FROM marker")
            conn.execute("INSERT INTO marker VALUES (?)", (value,))
            conn.commit()

    @staticmethod
    def _read_marker(path: Path) -> Optional[str]:
        try:
            with closing(sqlite3.connect(str(path))) as conn:
                row = conn.execute("SELECT x FROM marker").fetchone()
                return str(row[0]) if row else None
        except sqlite3.Error:
            return None

    def test_no_backup_when_schema_is_already_up_to_date(self) -> None:
        SQLiteStore(self.db_path).initialize()
        SQLiteStore(self.db_path).initialize()
        self.assertEqual(
            [p.name for p in self._backups("*.pre_migration.bak")],
            [],
            "un boot sans migration en attente ne doit plus pousser de backup",
        )

    def test_backup_still_created_when_a_migration_is_pending(self) -> None:
        SQLiteStore(self.db_path).initialize()
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.execute("PRAGMA user_version = 20")
            conn.commit()

        SQLiteStore(self.db_path).initialize()

        self.assertGreaterEqual(
            len(self._backups("*.pre_migration.bak")),
            1,
            "une migration reellement en attente doit toujours etre precedee d'un backup",
        )

    def test_backup_still_created_when_a_required_table_is_missing(self) -> None:
        SQLiteStore(self.db_path).initialize()
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.execute("DROP TABLE film_field_locks")
            conn.commit()

        SQLiteStore(self.db_path).initialize()

        self.assertGreaterEqual(
            len(self._backups("*.pre_migration.bak")),
            1,
            "le bootstrap self-heal reecrit le schema : il doit rester precede d'un backup",
        )

    def test_rich_backups_survive_repeated_boots_after_db_wipe(self) -> None:
        """Scenario reproduit par la passe adversaire, bout en bout.

        Base riche -> 5 backups riches -> l'utilisateur supprime le .sqlite
        (procedure docs/TROUBLESHOOTING.md) -> l'app recree une base vierge et
        est relancee 6 fois. Avant le correctif il ne restait aucun backup riche.
        """
        SQLiteStore(self.db_path).initialize()
        self._seed_marker(self.db_path, "MA_BIBLIOTHEQUE")

        backup_dir = self.db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        rich_names = []
        for i in range(5):
            dst = backup_dir / f"cinesort.2026010{i + 1}-000000-000000Z.pre_migration.bak"
            shutil.copy2(self.db_path, dst)
            when = time.time() - (500 - i * 10)
            os.utime(dst, (when, when))
            rich_names.append(dst.name)

        self.db_path.unlink()
        for suffix in ("-wal", "-shm"):
            Path(str(self.db_path) + suffix).unlink(missing_ok=True)

        for _ in range(6):
            SQLiteStore(self.db_path).initialize()

        survivors = {p.name for p in self._backups("cinesort.*.bak")}
        self.assertEqual(
            sorted(survivors),
            sorted(rich_names),
            "les backups riches ont ete evinces par des copies de la base vierge",
        )
        for name in rich_names:
            self.assertEqual(self._read_marker(backup_dir / name), "MA_BIBLIOTHEQUE")


# ---------------------------------------------------------------------------
# N23 (LOW, defense en profondeur) — "illisible" n'est pas "corrompu"
# ---------------------------------------------------------------------------


class UnreadableVsCorruptTests(_TmpDbTestCase):
    """N23 : requalifie LOW (aucune perte de donnees prouvee par l'adversaire).

    Le correctif se borne donc a ne plus presumer la corruption quand l'unique
    symptome est "l'OS a refuse d'ouvrir le fichier". Le chemin de corruption
    REELLE doit rester strictement inchange, d'ou le second test.
    """

    def _make_backup(self, name: str) -> Path:
        backup_dir = self.db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        dst = backup_dir / name
        shutil.copy2(self.db_path, dst)
        return dst

    def test_unopenable_db_does_not_trigger_auto_restore(self) -> None:
        SQLiteStore(self.db_path).initialize()
        self._make_backup("cinesort.20260101-000000-000000Z.pre_migration.bak")
        store = SQLiteStore(self.db_path)

        failure = sqlite3.OperationalError("unable to open database file")
        with mock.patch.object(store, "_connect", side_effect=failure):
            with mock.patch.object(store, "_attempt_auto_restore") as restore:
                # Le reste du boot echoue forcement (plus aucune connexion du
                # store n'aboutit) ; seule la decision de restaurer nous occupe.
                with suppress(sqlite3.Error):
                    store.initialize()

        self.assertFalse(restore.called, "un fichier illisible ne doit pas declencher l'auto-restore")
        self.assertTrue(
            store.integrity_status.startswith("unreadable: "),
            f"statut inattendu: {store.integrity_status!r}",
        )
        self.assertEqual((store.integrity_event or {}).get("status"), "unreadable")

    def test_real_corruption_still_triggers_auto_restore(self) -> None:
        """Garde-fou : le chemin de corruption REELLE reste inchange."""
        SQLiteStore(self.db_path).initialize()
        healthy = self._make_backup("cinesort.20260101-000000-000000Z.pre_migration.bak")
        with open(self.db_path, "r+b") as fh:
            fh.seek(4096)
            fh.write(b"\xff" * 400)

        store = SQLiteStore(self.db_path)
        store.initialize()

        event = store.integrity_event or {}
        self.assertEqual(event.get("status"), "restored")
        self.assertEqual(Path(str(event.get("backup_used"))).name, healthy.name)


# ---------------------------------------------------------------------------
# N26 (LOW) — lignes orphelines laissees par les migrations de rebuild
# ---------------------------------------------------------------------------


class ForeignKeyViolationDiagnosticTests(_TmpDbTestCase):
    """N26 : la passe adversaire REJETTE le correctif "filtrer les orphelines".

    Filtrer `errors` comme ses trois tables soeurs supprimerait silencieusement
    le journal d'erreurs de l'utilisateur — exactement ce que le fix BUG-001 a
    ete ecrit pour eviter (cf le commentaire de `_bootstrap_schema_latest`).
    Seule la moitie DIAGNOSTIQUE du correctif est retenue ici : `PRAGMA
    foreign_key_check` n'etait execute NULLE PART dans le produit, donc
    l'incoherence etait totalement muette (`integrity_check` repond "ok").

    Scenario reproduit tel que decrit par la passe adversaire : perte
    hors-bande de la table `runs`, puis self-heal au boot. Le bootstrap tourne
    sous `PRAGMA foreign_keys = OFF` (fix BUG-001), donc la ligne `errors`
    survit a la reconstruction et devient orpheline.
    """

    def _seed_orphaned_error(self) -> None:
        SQLiteStore(self.db_path).initialize()
        ts = time.time()
        with closing(sqlite3.connect(str(self.db_path))) as raw:
            raw.execute(
                "INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json) "
                "VALUES ('R-OK', 'DONE', ?, '/r', '/s', '{}')",
                (ts,),
            )
            raw.execute(
                "INSERT INTO errors(run_id, ts, step, code, message) VALUES ('R-OK', ?, 'scan', 'E1', 'm')",
                (ts,),
            )
            raw.commit()
            raw.execute("DROP TABLE runs")
            raw.commit()

    def test_orphan_rows_are_logged_after_a_schema_rebuild(self) -> None:
        self._seed_orphaned_error()

        store = SQLiteStore(self.db_path)
        with _capture_store_logs() as records:
            store.initialize()

        fk_logs = [rec.getMessage() for rec in records if "foreign_key_check" in rec.getMessage()]
        self.assertTrue(fk_logs, "aucun diagnostic FK emis apres le self-heal")
        self.assertIn("errors -> runs", fk_logs[0])
        # L'incoherence est bien invisible du seul check deja execute au boot.
        self.assertEqual(store.integrity_status, "ok")

    def test_orphan_rows_are_never_deleted_by_the_diagnostic(self) -> None:
        """Le diagnostic ne doit RIEN supprimer : le journal d'erreurs survit."""
        self._seed_orphaned_error()

        SQLiteStore(self.db_path).initialize()

        with closing(sqlite3.connect(str(self.db_path))) as conn:
            codes = sorted(str(r[0]) for r in conn.execute("SELECT code FROM errors"))
        self.assertEqual(codes, ["E1"])

    def test_healthy_db_emits_no_diagnostic(self) -> None:
        """Pas de faux positif : un self-heal sur base coherente ne logue rien."""
        SQLiteStore(self.db_path).initialize()
        with closing(sqlite3.connect(str(self.db_path))) as raw:
            raw.execute("DROP TABLE film_field_locks")
            raw.commit()

        store = SQLiteStore(self.db_path)
        with _capture_store_logs() as records:
            store.initialize()

        self.assertEqual([rec.getMessage() for rec in records if "foreign_key_check" in rec.getMessage()], [])

    def test_nominal_boot_does_not_run_the_check(self) -> None:
        """Le diagnostic est gate sur un changement de schema effectif.

        Une base deja reparee, meme durablement incoherente, ne doit pas payer
        un `foreign_key_check` a chaque lancement.
        """
        self._seed_orphaned_error()
        SQLiteStore(self.db_path).initialize()  # le self-heal a lieu ici

        store = SQLiteStore(self.db_path)
        with _capture_store_logs() as records:
            store.initialize()

        self.assertEqual([rec.getMessage() for rec in records if "foreign_key_check" in rec.getMessage()], [])


# ---------------------------------------------------------------------------
# N06 (LOW) — transitions d'etat manquantes apres le boot-cleanup
# ---------------------------------------------------------------------------


class BootCleanupUndoTransitionTests(_TmpDbTestCase):
    """N06 : finaliser un undo apres un boot-cleanup levait ApplyBatchStateError."""

    def _batch_in_status(self, store: SQLiteStore, status: str) -> str:
        batch_id = store.apply.insert_apply_batch(run_id="R1", dry_run=False, quarantine_unapproved=False)
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.execute("UPDATE apply_batches SET status=? WHERE batch_id=?", (status, batch_id))
            conn.commit()
        return batch_id

    def _status_of(self, batch_id: str) -> str:
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            row = conn.execute("SELECT status FROM apply_batches WHERE batch_id=?", (batch_id,)).fetchone()
        return str(row[0])

    def test_rolled_back_by_boot_cleanup_can_be_finalized_as_undone(self) -> None:
        store = SQLiteStore(self.db_path)
        store.initialize()
        batch_id = self._batch_in_status(store, "ROLLED_BACK_BY_BOOT_CLEANUP")

        store.apply.close_apply_batch(batch_id=batch_id, status="UNDONE_DONE", summary={"undo_selective": True})

        self.assertEqual(self._status_of(batch_id), "UNDONE_DONE")

    def test_completed_by_boot_cleanup_can_be_finalized_as_partial(self) -> None:
        store = SQLiteStore(self.db_path)
        store.initialize()
        batch_id = self._batch_in_status(store, "COMPLETED_BY_BOOT_CLEANUP")

        store.apply.close_apply_batch(batch_id=batch_id, status="UNDONE_PARTIAL", summary={})

        self.assertEqual(self._status_of(batch_id), "UNDONE_PARTIAL")

    def test_boot_cleanup_batch_cannot_go_back_to_done(self) -> None:
        """Invariant H14 preserve : aucun retour vers un etat reversible."""
        store = SQLiteStore(self.db_path)
        store.initialize()
        batch_id = self._batch_in_status(store, "ROLLED_BACK_BY_BOOT_CLEANUP")

        with self.assertRaises(ApplyBatchStateError):
            store.apply.close_apply_batch(batch_id=batch_id, status="DONE", summary={})
        self.assertEqual(self._status_of(batch_id), "ROLLED_BACK_BY_BOOT_CLEANUP")


if __name__ == "__main__":
    unittest.main()
