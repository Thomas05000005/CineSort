"""Migration 021 (V1-02 polish v7.7.0) — ON DELETE CASCADE sur 4 FK.

Source : audit R5-DB-1, PLAN_RESTE_A_FAIRE.md section 1.2.

Couvre :
1. Fresh DB : les 4 FK sont creees avec CASCADE, indexes preserves.
2. DB existante (v20 -> v21) : donnees preservees apres migration.
3. CASCADE fonctionnel : DELETE FROM runs supprime errors/quality_reports/anomalies.
4. CASCADE fonctionnel : DELETE FROM apply_batches supprime apply_operations.
5. Idempotence : rejouer la migration sur DB v21 = no-op.
6. Filtrage des rows orphelines : si quality_reports/anomalies referencent un
   run inexistant, la migration les filtre au lieu d'echouer.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, ".")

from cinesort.infra.db.connection import connect_sqlite
from cinesort.infra.db.migration_manager import MigrationManager
from cinesort.infra.db.sqlite_store import SQLiteStore

_REAL_MIG_DIR = Path("cinesort/infra/db/migrations")


def _fk_actions(conn: sqlite3.Connection, table: str) -> list[tuple[str, str, str, str]]:
    """Retourne [(table_parente, col_local, col_parente, on_delete)] pour la table."""
    out = []
    for row in conn.execute(f"PRAGMA foreign_key_list({table})"):
        out.append((str(row[2]), str(row[3]), str(row[4]), str(row[6])))
    return out


def _index_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
            (table,),
        )
    }


class FreshMigration021Tests(unittest.TestCase):
    """Sur fresh DB, les 4 FK doivent avoir ON DELETE CASCADE."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_mig021_fresh_")
        self.db_path = Path(self._tmp) / "t.db"
        SQLiteStore(self.db_path).initialize()
        self.conn = sqlite3.connect(str(self.db_path))

    def tearDown(self) -> None:
        self.conn.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_user_version_at_least_21(self) -> None:
        v = self.conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertGreaterEqual(int(v), 21)

    def test_errors_fk_cascade(self) -> None:
        fks = _fk_actions(self.conn, "errors")
        self.assertEqual(len(fks), 1)
        self.assertEqual(fks[0], ("runs", "run_id", "run_id", "CASCADE"))

    def test_quality_reports_fk_cascade(self) -> None:
        fks = _fk_actions(self.conn, "quality_reports")
        self.assertEqual(len(fks), 1)
        self.assertEqual(fks[0], ("runs", "run_id", "run_id", "CASCADE"))

    def test_anomalies_fk_cascade(self) -> None:
        fks = _fk_actions(self.conn, "anomalies")
        self.assertEqual(len(fks), 1)
        self.assertEqual(fks[0], ("runs", "run_id", "run_id", "CASCADE"))

    def test_apply_operations_fk_cascade(self) -> None:
        fks = _fk_actions(self.conn, "apply_operations")
        self.assertEqual(len(fks), 1)
        self.assertEqual(fks[0], ("apply_batches", "batch_id", "batch_id", "CASCADE"))

    def test_indexes_preserved_errors(self) -> None:
        self.assertIn("idx_errors_run_id", _index_names(self.conn, "errors"))

    def test_indexes_preserved_quality_reports(self) -> None:
        names = _index_names(self.conn, "quality_reports")
        # Migration 022 drop idx_quality_reports_run (redondant avec PK
        # composite run_id,row_id, cf issue #77). Les autres indexes
        # restent utiles (tier/score filtrent independamment).
        self.assertIn("idx_quality_reports_tier", names)
        self.assertIn("idx_quality_reports_score", names)

    def test_indexes_preserved_anomalies(self) -> None:
        names = _index_names(self.conn, "anomalies")
        self.assertIn("idx_anomalies_run_id", names)
        self.assertIn("idx_anomalies_severity", names)
        self.assertIn("idx_anomalies_code", names)

    def test_indexes_preserved_apply_operations(self) -> None:
        names = _index_names(self.conn, "apply_operations")
        self.assertIn("idx_apply_ops_batch_opindex", names)
        self.assertIn("idx_apply_ops_batch", names)
        self.assertIn("idx_apply_ops_reversible", names)
        self.assertIn("idx_apply_ops_row_id", names)


class CascadeBehaviorTests(unittest.TestCase):
    """Verifie que DELETE cascade correctement les enfants."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_mig021_cascade_")
        self.db_path = Path(self._tmp) / "t.db"
        SQLiteStore(self.db_path).initialize()
        self.conn = connect_sqlite(str(self.db_path))
        self._seed()

    def tearDown(self) -> None:
        self.conn.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _seed(self) -> None:
        ts = time.time()
        # 2 runs avec enfants
        for run_id in ("R1", "R2"):
            self.conn.execute(
                "INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json) "
                "VALUES (?, 'DONE', ?, '/r', '/s', '{}')",
                (run_id, ts),
            )
            self.conn.execute(
                "INSERT INTO errors(run_id, ts, step, code, message) VALUES (?, ?, 'scan', 'E1', 'm')",
                (run_id, ts),
            )
            self.conn.execute(
                "INSERT INTO quality_reports(run_id, row_id, score, tier, reasons_json, "
                "metrics_json, profile_id, profile_version, ts) "
                "VALUES (?, 'row1', 80, 'Gold', '[]', '{}', 'p1', 1, ?)",
                (run_id, ts),
            )
            self.conn.execute(
                "INSERT INTO anomalies(run_id, severity, code, message, ts) VALUES (?, 'WARN', 'A1', 'm', ?)",
                (run_id, ts),
            )
        # 1 batch attache a R1 + 2 ops
        self.conn.execute(
            "INSERT INTO apply_batches VALUES ('B1', 'R1', ?, NULL, 0, 0, 'DONE', '{}', '7.7')",
            (ts,),
        )
        for idx in (0, 1):
            self.conn.execute(
                "INSERT INTO apply_operations(batch_id, op_index, op_type, src_path, dst_path, "
                "reversible, undo_status, ts) "
                "VALUES ('B1', ?, 'MOVE', '/a', '/b', 1, 'DONE', ?)",
                (idx, ts),
            )
        self.conn.commit()

    def _count(self, table: str, where: str = "") -> int:
        sql = f"SELECT COUNT(*) FROM {table}"
        if where:
            sql += f" WHERE {where}"
        return int(self.conn.execute(sql).fetchone()[0])

    def test_delete_run_cascades_errors(self) -> None:
        self.conn.execute("DELETE FROM runs WHERE run_id = 'R1'")
        self.conn.commit()
        self.assertEqual(self._count("errors", "run_id='R1'"), 0)
        self.assertEqual(self._count("errors", "run_id='R2'"), 1)

    def test_delete_run_cascades_quality_reports(self) -> None:
        self.conn.execute("DELETE FROM runs WHERE run_id = 'R1'")
        self.conn.commit()
        self.assertEqual(self._count("quality_reports", "run_id='R1'"), 0)
        self.assertEqual(self._count("quality_reports", "run_id='R2'"), 1)

    def test_delete_run_cascades_anomalies(self) -> None:
        self.conn.execute("DELETE FROM runs WHERE run_id = 'R1'")
        self.conn.commit()
        self.assertEqual(self._count("anomalies", "run_id='R1'"), 0)
        self.assertEqual(self._count("anomalies", "run_id='R2'"), 1)

    def test_delete_batch_cascades_apply_operations(self) -> None:
        self.assertEqual(self._count("apply_operations", "batch_id='B1'"), 2)
        self.conn.execute("DELETE FROM apply_batches WHERE batch_id = 'B1'")
        self.conn.commit()
        self.assertEqual(self._count("apply_operations", "batch_id='B1'"), 0)

    def test_delete_run_cascades_to_apply_chain(self) -> None:
        """Une suppression de run doit aussi cascader sur ses errors/quality/anomalies,
        mais PAS automatiquement sur apply_batches/apply_operations (apply_batches
        n'a pas de FK ON DELETE CASCADE vers runs — c'est volontaire car les batches
        portent leur propre cycle de vie via apply_journal).
        Ce test documente le comportement attendu : delete run -> orphelins batches OK.
        """
        self.conn.execute("DELETE FROM runs WHERE run_id = 'R1'")
        self.conn.commit()
        # apply_batches survit (pas de FK sur runs)
        self.assertEqual(self._count("apply_batches", "batch_id='B1'"), 1)
        self.assertEqual(self._count("apply_operations", "batch_id='B1'"), 2)


class ExistingDbMigrationTests(unittest.TestCase):
    """v20 -> v21 sur DB existante avec donnees : aucune perte de donnees legitimes."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_mig021_existing_")
        self.db_path = Path(self._tmp) / "t.db"
        # Repertoire de migrations limite a 1-20
        self._mig_v20 = Path(self._tmp) / "mig_v20"
        self._mig_v20.mkdir()
        for f in sorted(_REAL_MIG_DIR.glob("*.sql")):
            try:
                version = int(f.stem.split("_")[0])
            except ValueError:
                continue
            if version <= 20:
                shutil.copy(f, self._mig_v20 / f.name)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_v20_to_v21_preserves_data(self) -> None:
        """Apres migration v20 -> v21, toutes les donnees legitimes sont preservees."""
        # 1) DB initialisee a v20
        mgr = MigrationManager(self.db_path, self._mig_v20)
        v = mgr.apply()
        self.assertEqual(v, 20)

        ts = time.time()
        with closing(connect_sqlite(str(self.db_path))) as conn:
            conn.execute(
                "INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json) "
                "VALUES ('RX', 'DONE', ?, '/r', '/s', '{}')",
                (ts,),
            )
            conn.execute(
                "INSERT INTO errors(run_id, ts, step, code, message, context_json) "
                "VALUES ('RX', ?, 'scan', 'E1', 'msg', '{}')",
                (ts,),
            )
            conn.execute(
                "INSERT INTO quality_reports VALUES ('RX', 'row1', 75, 'Gold', '[]', '{}', 'p1', 1, ?)",
                (ts,),
            )
            conn.execute(
                "INSERT INTO anomalies(run_id, severity, code, message, ts) VALUES ('RX', 'WARN', 'A1', 'm', ?)",
                (ts,),
            )
            conn.execute(
                "INSERT INTO apply_batches VALUES ('BX', 'RX', ?, NULL, 0, 0, 'DONE', '{}', '7.6')",
                (ts,),
            )
            conn.execute(
                "INSERT INTO apply_operations(batch_id, op_index, op_type, src_path, dst_path, "
                "reversible, undo_status, ts) "
                "VALUES ('BX', 0, 'MOVE', '/a', '/b', 1, 'DONE', ?)",
                (ts,),
            )
            conn.commit()

        # 2) Migre vers v21 (avec le repertoire reel qui inclut 021)
        mgr_v21 = MigrationManager(self.db_path, _REAL_MIG_DIR)
        v = mgr_v21.apply()
        # Migration 022 ajoutee (drop indexes redondants) -> on attend >= 21
        # plutot que strict 21 pour rester robuste aux futures migrations.
        self.assertGreaterEqual(v, 21)

        # 3) Toutes les donnees legitimes preservees
        with closing(connect_sqlite(str(self.db_path))) as conn:
            self.assertEqual(int(conn.execute("SELECT COUNT(*) FROM runs WHERE run_id='RX'").fetchone()[0]), 1)
            self.assertEqual(int(conn.execute("SELECT COUNT(*) FROM errors WHERE run_id='RX'").fetchone()[0]), 1)
            self.assertEqual(
                int(conn.execute("SELECT COUNT(*) FROM quality_reports WHERE run_id='RX'").fetchone()[0]), 1
            )
            self.assertEqual(int(conn.execute("SELECT COUNT(*) FROM anomalies WHERE run_id='RX'").fetchone()[0]), 1)
            self.assertEqual(
                int(conn.execute("SELECT COUNT(*) FROM apply_batches WHERE batch_id='BX'").fetchone()[0]), 1
            )
            self.assertEqual(
                int(conn.execute("SELECT COUNT(*) FROM apply_operations WHERE batch_id='BX'").fetchone()[0]), 1
            )

    def test_v20_to_v21_filters_orphan_quality_reports(self) -> None:
        """Si quality_reports contient des rows orphelines (run_id sans parent),
        la migration les filtre au lieu d'echouer (FK integrite).
        """
        mgr = MigrationManager(self.db_path, self._mig_v20)
        mgr.apply()

        ts = time.time()
        with closing(connect_sqlite(str(self.db_path))) as conn:
            # 1 run legitime
            conn.execute(
                "INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json) "
                "VALUES ('R-OK', 'DONE', ?, '/r', '/s', '{}')",
                (ts,),
            )
            # 1 quality_report legitime + 1 orphelin
            conn.execute(
                "INSERT INTO quality_reports VALUES ('R-OK', 'row1', 80, 'Gold', '[]', '{}', 'p1', 1, ?)",
                (ts,),
            )
            conn.execute(
                "INSERT INTO quality_reports VALUES ('GHOST', 'row1', 60, 'Silver', '[]', '{}', 'p1', 1, ?)",
                (ts,),
            )
            # 1 anomaly orpheline
            conn.execute(
                "INSERT INTO anomalies(run_id, severity, code, message, ts) VALUES ('GHOST', 'WARN', 'A1', 'm', ?)",
                (ts,),
            )
            conn.commit()

        mgr_v21 = MigrationManager(self.db_path, _REAL_MIG_DIR)
        v = mgr_v21.apply()
        # Migration 022 ajoutee (drop indexes redondants) -> on attend >= 21
        # plutot que strict 21 pour rester robuste aux futures migrations.
        self.assertGreaterEqual(v, 21)

        with closing(connect_sqlite(str(self.db_path))) as conn:
            # Le legitime est preserve
            self.assertEqual(
                int(conn.execute("SELECT COUNT(*) FROM quality_reports WHERE run_id='R-OK'").fetchone()[0]), 1
            )
            # L'orphelin est filtre
            self.assertEqual(
                int(conn.execute("SELECT COUNT(*) FROM quality_reports WHERE run_id='GHOST'").fetchone()[0]), 0
            )
            self.assertEqual(int(conn.execute("SELECT COUNT(*) FROM anomalies WHERE run_id='GHOST'").fetchone()[0]), 0)

    def _seed_v20_avec_orpheline(self) -> None:
        """Base en v20 : une `errors` legitime, une orpheline.

        Pourquoi ce cas manquait au test ci-dessus : `connect_sqlite` pose
        `PRAGMA foreign_keys = ON`, et `errors` est la SEULE des quatre tables
        qui avait deja une FK en v20. Une orpheline y est donc impossible a
        creer par le chemin qu'utilisait le test — l'angle mort etait dans le
        harnais. En vrai elle arrive sans rien faire d'exotique : `foreign_keys`
        vaut OFF par DEFAUT dans SQLite, donc tout ecrivain qui ne pose pas le
        pragma (version anterieure, outil externe, script de maintenance) laisse
        ses `errors` derriere un run supprime.
        """
        MigrationManager(self.db_path, self._mig_v20).apply()
        ts = time.time()
        with closing(connect_sqlite(str(self.db_path))) as conn:
            conn.execute(
                "INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json) "
                "VALUES ('R-OK', 'DONE', ?, '/r', '/s', '{}')",
                (ts,),
            )
            conn.execute(
                "INSERT INTO errors(run_id, ts, step, code, message) VALUES ('R-OK', ?, 'scan', 'E1', 'legitime')",
                (ts,),
            )
            # Le commit n'est pas cosmetique : `PRAGMA foreign_keys` est un no-op
            # SILENCIEUX dans une transaction ouverte.
            conn.commit()
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                "INSERT INTO errors(run_id, ts, step, code, message) VALUES ('GHOST', ?, 'scan', 'E2', 'orpheline')",
                (ts,),
            )
            conn.commit()

    def test_v20_to_v21_ne_bloque_pas_sur_une_errors_orpheline(self) -> None:
        """MESURE avant correctif, base reelle en v20, UNE seule orpheline :

            essai 1 : IntegrityError: FOREIGN KEY constraint failed -> v20
            essai 2 : IntegrityError: FOREIGN KEY constraint failed -> v20

        Deterministe et rejoue a chaque ouverture : la base ne s'ouvre plus
        jamais, et rien dans l'application ne repare la ligne fautive.
        """
        self._seed_v20_avec_orpheline()

        version = MigrationManager(self.db_path, _REAL_MIG_DIR).apply()

        self.assertGreaterEqual(version, 21, "la migration a echoue : la base reste bloquee a v20")

    def test_l_orpheline_SURVIT_a_la_migration(self) -> None:
        """Contre-epreuve du correctif ecarte.

        Le premier correctif tente ici etait le filtre `WHERE EXISTS` des trois
        sections soeurs. Il debloque bien le demarrage — et DETRUIT le journal
        d'erreurs, ce que la passe adversaire N26 avait deja refuse. Le meme SQL
        etant rejoue par `_bootstrap_schema_latest` a chaque auto-reparation, le
        filtre aurait supprime ces lignes sur le chemin le PLUS frequent des
        deux (mesure : 2 tests de N26 passes au rouge).

        Le correctif retenu (marqueur `disable_fk`) n'enleve rien : il aligne
        seulement le chemin migration sur le chemin bootstrap, qui tournait deja
        FK a OFF.
        """
        self._seed_v20_avec_orpheline()

        MigrationManager(self.db_path, _REAL_MIG_DIR).apply()

        with closing(connect_sqlite(str(self.db_path))) as conn:
            codes = sorted(str(r[0]) for r in conn.execute("SELECT code FROM errors"))
        self.assertEqual(codes, ["E1", "E2"], "le journal d'erreurs a ete ampute par la migration")

    def test_l_orpheline_reste_DIAGNOSTIQUABLE(self) -> None:
        """Survivre ne suffit pas : l'incoherence doit rester visible.

        `PRAGMA integrity_check` repond « ok » sur une base pleine d'orphelines —
        c'est tout l'objet du diagnostic N26. Si la migration laissait passer la
        ligne SANS qu'elle soit detectable, on aurait echange un blocage bruyant
        contre une incoherence muette.
        """
        self._seed_v20_avec_orpheline()
        MigrationManager(self.db_path, _REAL_MIG_DIR).apply()

        with closing(connect_sqlite(str(self.db_path))) as conn:
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()

        tables = {str(row[0]) for row in violations}
        self.assertIn("errors", tables, f"l'orpheline n'est signalee par aucun diagnostic : {violations}")

    def test_une_orpheline_ne_bloque_pas_le_demarrage_SUIVANT(self) -> None:
        """Le vrai symptome n'est pas « la migration echoue », c'est qu'elle
        echoue A CHAQUE FOIS. Un echec transitoire se rattrape au reboot ; celui-ci
        non."""
        self._seed_v20_avec_orpheline()

        versions = [MigrationManager(self.db_path, _REAL_MIG_DIR).apply() for _ in range(2)]

        self.assertTrue(
            all(v >= 21 for v in versions),
            f"la base reste bloquee au redemarrage : versions obtenues {versions}",
        )

    def test_l_apply_operation_orpheline_SURVIT_aussi(self) -> None:
        """Section 4 : le journal d'undo, la table la plus consequente des quatre.

        Chacune de ses lignes est le seul enregistrement d'un deplacement DEJA
        FAIT sur disque. Elle n'avait NI garde d'execution NI test : son filtre
        `WHERE EXISTS` etait presente comme une protection d'integrite, alors que
        sous `disable_fk` il ne fait plus que supprimer. MESURE : filtre retire
        et rien d'autre change, la migration aboutit ET la ligne est preservee.
        """
        MigrationManager(self.db_path, self._mig_v20).apply()
        ts = time.time()
        with closing(connect_sqlite(str(self.db_path))) as conn:
            conn.execute(
                "INSERT INTO apply_batches VALUES ('B-OK', 'R', ?, NULL, 0, 0, 'DONE', '{}', '7.6')",
                (ts,),
            )
            conn.execute(
                "INSERT INTO apply_operations(batch_id, op_index, op_type, src_path, dst_path, "
                "reversible, undo_status, ts) VALUES ('B-OK', 1, 'MOVE', '/a', '/b', 1, 'PENDING', ?)",
                (ts,),
            )
            conn.commit()
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                "INSERT INTO apply_operations(batch_id, op_index, op_type, src_path, dst_path, "
                "reversible, undo_status, ts) VALUES ('B-DISPARU', 1, 'MOVE', '/c', '/d', 1, 'PENDING', ?)",
                (ts,),
            )
            conn.commit()

        MigrationManager(self.db_path, _REAL_MIG_DIR).apply()

        with closing(connect_sqlite(str(self.db_path))) as conn:
            batches = sorted(str(r[0]) for r in conn.execute("SELECT batch_id FROM apply_operations"))
        self.assertEqual(
            batches,
            ["B-DISPARU", "B-OK"],
            "le journal d'undo a ete ampute : ces lignes tracent des deplacements deja faits sur disque",
        )

    def test_les_sorties_RECALCULABLES_restent_filtrees(self) -> None:
        """Garde anti-sur-correction : ne pas etendre la clemence a tout.

        `quality_reports` et `anomalies` sont des sorties qu'un nouveau scan
        reproduit. Les conserver orphelines n'apporterait rien et laisserait du
        bruit dans une base que la retention ne sait pas purger (leur run n'existe
        plus, donc aucun chemin de nettoyage ne les atteint).
        """
        MigrationManager(self.db_path, self._mig_v20).apply()
        ts = time.time()
        with closing(connect_sqlite(str(self.db_path))) as conn:
            conn.execute(
                "INSERT INTO quality_reports VALUES ('GHOST', 'row1', 60, 'Silver', '[]', '{}', 'p1', 1, ?)",
                (ts,),
            )
            conn.execute(
                "INSERT INTO anomalies(run_id, severity, code, message, ts) VALUES ('GHOST', 'WARN', 'A1', 'm', ?)",
                (ts,),
            )
            conn.commit()

        MigrationManager(self.db_path, _REAL_MIG_DIR).apply()

        with closing(connect_sqlite(str(self.db_path))) as conn:
            self.assertEqual(int(conn.execute("SELECT COUNT(*) FROM quality_reports").fetchone()[0]), 0)
            self.assertEqual(int(conn.execute("SELECT COUNT(*) FROM anomalies").fetchone()[0]), 0)

    def test_le_marqueur_disable_fk_est_PRESENT_et_strictement_formate(self) -> None:
        """Le marqueur est un contrat textuel, matche par `line.strip().startswith`.

        Deux lecteurs independants l'interpretent (`migration_manager.apply` et
        `SQLiteStore._bootstrap_schema_latest`) et tous deux exigent une ligne
        qui COMMENCE par le marqueur apres trim. Le noyer dans une phrase le
        desactiverait sans que rien ne rougisse.
        """
        sql = (_REAL_MIG_DIR / "021_fk_cascade.sql").read_text(encoding="utf-8")

        lignes_marqueur = [ln for ln in sql.splitlines() if ln.strip().startswith("-- @manager: disable_fk")]

        self.assertEqual(len(lignes_marqueur), 1, f"marqueur absent ou duplique : {lignes_marqueur}")


class IdempotenceTests(unittest.TestCase):
    """Rejouer la migration apres son application = no-op."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_mig021_idem_")
        self.db_path = Path(self._tmp) / "t.db"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_double_apply_is_noop(self) -> None:
        # 1ere application
        mgr = MigrationManager(self.db_path, _REAL_MIG_DIR)
        v1 = mgr.apply()
        self.assertGreaterEqual(v1, 21)

        # On insere quelques donnees
        ts = time.time()
        with closing(connect_sqlite(str(self.db_path))) as conn:
            conn.execute(
                "INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json) "
                "VALUES ('RZ', 'DONE', ?, '/r', '/s', '{}')",
                (ts,),
            )
            conn.execute(
                "INSERT INTO errors(run_id, ts, step, code, message) VALUES ('RZ', ?, 'scan', 'E1', 'm')",
                (ts,),
            )
            conn.commit()

        # 2eme application : ne touche rien (user_version >= 21)
        v2 = mgr.apply()
        self.assertEqual(v1, v2)

        # Donnees toujours la
        with closing(connect_sqlite(str(self.db_path))) as conn:
            self.assertEqual(int(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]), 1)
            self.assertEqual(int(conn.execute("SELECT COUNT(*) FROM errors").fetchone()[0]), 1)
            # FK toujours CASCADE
            fks = _fk_actions(conn, "errors")
            self.assertEqual(fks[0][3], "CASCADE")


if __name__ == "__main__":
    unittest.main()
