"""Issue #623 (volet 2) — la tolerance d'idempotence doit etre APPARIEE au statement.

`_is_idempotent_error` ne regardait que le MESSAGE de l'exception :

    _IDEMPOTENT_ERROR_FRAGMENTS = ("duplicate column name", "already exists")

`"already exists"` avale donc indifferemment `CREATE TABLE`, `CREATE INDEX`,
`CREATE TRIGGER`... mais aussi `CREATE VIEW` et `CREATE VIRTUAL TABLE ... USING
fts5`. Une migration de RESET d'un index FTS etait alors comptee « deja
appliquee » alors que l'objet survivant est justement celui qu'elle voulait
recreer, et la migration passait en vert avec un schema inchange.

Symetriquement, `"duplicate column name"` est legitime pour
`ALTER TABLE ... ADD COLUMN` (pas `IF NOT EXISTS`-able avant SQLite 3.35) mais
denonce une migration MAL ECRITE dans un `CREATE TABLE ... (a INT, a INT)` : le
taire laissait la table absente et faisait echouer plus loin, sans rapport
apparent, tout ce qui en depend.

DEUX chemins de boot appellent ce predicat et doivent bouger ensemble :
`MigrationManager.apply` (migration par migration) et
`SQLiteStore._bootstrap_schema_latest` (script concatene, filet self-healing).
Chaque classe ci-dessous couvre les DEUX.

Toutes les migrations sont jouees sur une base PRE-EXISTANTE (jamais seulement
fraiche) : c'est la seule situation ou ces erreurs peuvent survenir.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from cinesort.infra.db.migration_manager import MigrationManager, _is_idempotent_error
from cinesort.infra.db.sqlite_store import SQLiteStore


def _has_fts5() -> bool:
    with closing(sqlite3.connect(":memory:")) as conn:
        try:
            conn.execute("CREATE VIRTUAL TABLE probe_fts USING fts5(x)")
        except sqlite3.OperationalError:
            return False
    return True


class _MigrationHarness(unittest.TestCase):
    """Une base PRE-EXISTANTE + un dossier de migrations fabrique sur mesure."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_623_")
        self.root = Path(self._tmp.name)
        self.migrations = self.root / "migrations"
        self.migrations.mkdir()
        self.db_path = self.root / "cinesort.sqlite"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_migration(self, name: str, sql: str) -> None:
        (self.migrations / name).write_text(sql, encoding="utf-8")

    def seed_existing_db(self, statements: list[str], *, user_version: int) -> None:
        """Fabrique l'etat ANTERIEUR : c'est lui qui declenche l'erreur testee."""
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            for stmt in statements:
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {int(user_version)}")
            conn.commit()

    def manager(self) -> MigrationManager:
        return MigrationManager(self.db_path, self.migrations, busy_timeout_ms=8000)

    def store(self) -> SQLiteStore:
        return SQLiteStore(self.db_path, migrations_dir=self.migrations, busy_timeout_ms=8000)

    def user_version(self) -> int:
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            return int(conn.execute("PRAGMA user_version").fetchone()[0])

    def table_names(self) -> set[str]:
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            return {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}

    def columns(self, table: str) -> set[str]:
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


class ToleranceRestreinteAuxStatementsAttendus(_MigrationHarness):
    """Ce qui n'est PAS reconnu idempotent doit BLOQUER, pas passer en vert."""

    def test_create_view_deja_presente_bloque_la_migration(self) -> None:
        self.write_migration("001_base.sql", "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY);\n")
        self.write_migration("002_view.sql", "CREATE VIEW v_t AS SELECT id FROM t;\n")
        self.seed_existing_db(
            ["CREATE TABLE t (id INTEGER PRIMARY KEY)", "CREATE VIEW v_t AS SELECT id FROM t"],
            user_version=1,
        )

        with self.assertRaises(sqlite3.OperationalError) as ctx:
            self.manager().apply()
        self.assertIn("already exists", str(ctx.exception).lower())
        self.assertEqual(self.user_version(), 1, "la migration a ete comptee appliquee alors qu'elle a echoue")

    def test_create_view_deja_presente_bloque_aussi_le_bootstrap(self) -> None:
        """SECOND chemin de boot : le filet self-healing concatene.

        Sans cette ligne, un correctif pose uniquement sur `MigrationManager`
        laisserait `SQLiteStore._bootstrap_schema_latest` sur l'ancien
        comportement permissif — et c'est LUI qui tourne quand des tables
        critiques manquent, donc precisement sur une base deja abimee.
        """
        self.write_migration("001_base.sql", "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY);\n")
        self.write_migration("002_view.sql", "CREATE VIEW v_t AS SELECT id FROM t;\n")
        self.seed_existing_db(
            ["CREATE TABLE t (id INTEGER PRIMARY KEY)", "CREATE VIEW v_t AS SELECT id FROM t"],
            user_version=0,
        )

        with self.assertRaises(sqlite3.OperationalError) as ctx:
            self.store()._bootstrap_schema_latest()
        self.assertIn("already exists", str(ctx.exception).lower())

    @unittest.skipUnless(_has_fts5(), "SQLite compile sans FTS5")
    def test_reset_fts_deja_presente_bloque_la_migration(self) -> None:
        """Le scenario nomme par l'issue : une table virtuelle FTS survivante.

        Elle est justement celle que la migration de reset voulait recreer ;
        la « skipper » rendait un index de recherche potentiellement corrompu
        et une migration en vert.
        """
        self.write_migration("001_base.sql", "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY);\n")
        self.write_migration("002_fts.sql", "CREATE VIRTUAL TABLE films_fts USING fts5(title);\n")
        self.seed_existing_db(
            ["CREATE TABLE t (id INTEGER PRIMARY KEY)", "CREATE VIRTUAL TABLE films_fts USING fts5(title)"],
            user_version=1,
        )

        with self.assertRaises(sqlite3.OperationalError) as ctx:
            self.manager().apply()
        self.assertIn("already exists", str(ctx.exception).lower())
        self.assertEqual(self.user_version(), 1)

    def test_colonne_dupliquee_dans_un_create_table_bloque_la_migration(self) -> None:
        """`duplicate column name` hors d'un ALTER = migration mal ecrite.

        Avant, elle etait avalee : la table n'etait jamais creee et la
        migration etait comptee appliquee. Le defaut ressortait beaucoup plus
        loin, sous la forme d'un « no such table » sans rapport apparent.
        """
        self.write_migration("001_base.sql", "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY);\n")
        self.write_migration("002_bad.sql", "CREATE TABLE IF NOT EXISTS u (a INTEGER, a INTEGER);\n")
        self.seed_existing_db(["CREATE TABLE t (id INTEGER PRIMARY KEY)"], user_version=1)

        with self.assertRaises(sqlite3.OperationalError) as ctx:
            self.manager().apply()
        self.assertIn("duplicate column name", str(ctx.exception).lower())
        self.assertNotIn("u", self.table_names())
        self.assertEqual(self.user_version(), 1)


class ToleranceLegitimePreservee(_MigrationHarness):
    """Contrepartie : resserrer ne doit pas rendre le self-healing inerte.

    Ces cas etaient verts AVANT le correctif et doivent le rester — c'est ce
    qui separe un resserrement d'une regression de boot sur base existante.
    """

    def test_alter_table_add_column_deja_presente_reste_toleree(self) -> None:
        self.write_migration("001_base.sql", "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY);\n")
        self.write_migration("002_add.sql", "ALTER TABLE t ADD COLUMN extra TEXT;\n")
        self.seed_existing_db(["CREATE TABLE t (id INTEGER PRIMARY KEY, extra TEXT)"], user_version=1)

        self.assertEqual(self.manager().apply(), 2)
        self.assertEqual(self.user_version(), 2)
        self.assertIn("extra", self.columns("t"))

    def test_alter_table_add_column_deja_presente_reste_toleree_au_bootstrap(self) -> None:
        self.write_migration("001_base.sql", "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY);\n")
        self.write_migration("002_add.sql", "ALTER TABLE t ADD COLUMN extra TEXT;\n")
        self.seed_existing_db(["CREATE TABLE t (id INTEGER PRIMARY KEY, extra TEXT)"], user_version=0)

        self.assertEqual(self.store()._bootstrap_schema_latest(), 2)
        self.assertIn("extra", self.columns("t"))

    def test_create_table_sans_if_not_exists_reste_tolere(self) -> None:
        """Le motif `xxx_new` des migrations de reconstruction (021 / 025)."""
        self.write_migration("001_base.sql", "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY);\n")
        self.write_migration("002_new.sql", "CREATE TABLE t_new (id INTEGER PRIMARY KEY);\n")
        self.seed_existing_db(
            ["CREATE TABLE t (id INTEGER PRIMARY KEY)", "CREATE TABLE t_new (id INTEGER PRIMARY KEY)"],
            user_version=1,
        )

        self.assertEqual(self.manager().apply(), 2)
        self.assertEqual(self.user_version(), 2)

    def test_create_unique_index_deja_present_reste_tolere(self) -> None:
        """`CREATE UNIQUE INDEX` : le mot-cle s'intercale entre CREATE et INDEX."""
        self.write_migration("001_base.sql", "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY);\n")
        self.write_migration("002_ix.sql", "CREATE UNIQUE INDEX ix_t_id ON t(id);\n")
        self.seed_existing_db(
            ["CREATE TABLE t (id INTEGER PRIMARY KEY)", "CREATE UNIQUE INDEX ix_t_id ON t(id)"],
            user_version=1,
        )

        self.assertEqual(self.manager().apply(), 2)
        self.assertEqual(self.user_version(), 2)


class PredicatUnitaire(unittest.TestCase):
    """Le predicat lui-meme, hors contexte de migration."""

    def test_message_seul_ne_suffit_plus(self) -> None:
        exc = sqlite3.OperationalError("view v_t already exists")
        self.assertFalse(_is_idempotent_error(exc, "CREATE VIEW v_t AS SELECT 1"))
        self.assertFalse(_is_idempotent_error(exc, "CREATE VIRTUAL TABLE films_fts USING fts5(title)"))
        self.assertTrue(_is_idempotent_error(exc, "CREATE TABLE t (id INTEGER)"))

    def test_statement_seul_ne_suffit_pas_non_plus(self) -> None:
        """Un CREATE TABLE qui echoue pour une AUTRE raison doit remonter."""
        self.assertFalse(
            _is_idempotent_error(sqlite3.OperationalError("no such table: parent"), "CREATE TABLE t (id INTEGER)")
        )

    def test_duplicate_column_reste_reserve_a_alter_table(self) -> None:
        exc = sqlite3.OperationalError("duplicate column name: a")
        self.assertTrue(_is_idempotent_error(exc, "ALTER TABLE t ADD COLUMN a TEXT"))
        self.assertFalse(_is_idempotent_error(exc, "CREATE TABLE u (a INTEGER, a INTEGER)"))

    def test_indentation_et_retours_ligne_ne_trompent_pas_le_predicat(self) -> None:
        """`_split_sql_statements` rend des fragments qui commencent souvent
        par un saut de ligne : le motif doit les accepter."""
        exc = sqlite3.OperationalError("table t already exists")
        self.assertTrue(_is_idempotent_error(exc, "\n  create\n  table t (\n id INTEGER\n)"))

    def test_integrity_error_toujours_hors_perimetre(self) -> None:
        """R8-021 RETRACTE : ne jamais avaler une contrainte violee.

        Le predicat est type `OperationalError` et n'est appele que dans un
        `except sqlite3.OperationalError` ; on verrouille ici qu'aucun message
        de contrainte ne devient idempotent par accident.
        """
        for msg in ("UNIQUE constraint failed: t.id", "PRIMARY KEY must be unique", "NOT NULL constraint failed: t.a"):
            self.assertFalse(
                _is_idempotent_error(sqlite3.OperationalError(msg), "INSERT INTO t_new SELECT * FROM t"), msg
            )


if __name__ == "__main__":
    unittest.main()
