"""Tests de migration depuis bases SQLite legacy (audit C12 P0 / sprint B7).

Contexte :
    Les tests `test_migration_chain.py` et `test_migration_021.py` couvrent
    deja la chaine complete sur DB fraiche et la transition v20 -> v21.
    En revanche, aucun test ne simule un utilisateur reel qui boot l'app sur
    une DB pre-existante d'une version anterieure (v1, v5, v10, etc.).

Risque adresse :
    Les migrations sont generalement testees "fresh" mais le scenario reel
    est `DB v1.0 existante -> upgrade v7.8` ou `DB v6.x existante -> upgrade
    v7.8`. Une regression sur un INSERT INTO new_table SELECT * FROM old
    ou un ALTER TABLE incompatible avec des donnees historiques ne serait
    pas detectee sans ce filet.

Strategie :
    1. Pour chaque point de depart legacy (v1, v5, v10, v22, v24) :
       a. Copier les fichiers de migration `001..N` dans un dossier temporaire.
       b. Appliquer ces migrations sur une DB neuve -> DB simule "v(N) legacy".
       c. Injecter quelques rows representatives dans les tables existantes.
       d. Pointer SQLiteStore vers le repertoire complet (toutes les migrations
          reelles) et appeler `initialize()` -> simule le boot reel.
       e. Verifier :
          - user_version atteint la latest_version().
          - Les rows seedees ont survecu (preservation des donnees).
          - PRAGMA integrity_check = "ok".
          - Les tables critiques sont presentes.
          - Cas particuliers :
            * v10 contient des tiers legacy 'Premium'/'Bon'/'Faible' qui doivent
              etre renommes par la migration 011 (Premium->Platinum, etc.).
            * v22 doit recreer la table runs en preservant les rows
              (migration 023 + flag @manager: disable_fk).

Couverture des points de depart (5 scenarios pour 3+ requis) :
    - v1  : genesis  -> minimum runs+errors uniquement.
    - v5  : ajout apply_batches/apply_operations (avant Undo v5 row_id).
    - v10 : avant le renommage des tiers (test la mig 011 sur donnees reelles).
    - v22 : juste avant la recreation de la table runs (mig 023).
    - v24 : v(N-1), juste avant 025 -- garantit qu'une DB tres recente migre OK.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from typing import List, Tuple

from cinesort.infra.db.connection import connect_sqlite
from cinesort.infra.db.migration_manager import MigrationManager
from cinesort.infra.db.sqlite_store import SQLiteStore


_REAL_MIG_DIR = Path("cinesort/infra/db/migrations")


def _copy_migrations_up_to(target_version: int, dest: Path) -> None:
    """Copie les fichiers de migration 001 -> target_version (inclus) dans dest."""
    dest.mkdir(parents=True, exist_ok=True)
    for f in sorted(_REAL_MIG_DIR.glob("*.sql")):
        try:
            version = int(f.stem.split("_")[0])
        except (ValueError, IndexError):
            continue
        if version <= int(target_version):
            shutil.copy(f, dest / f.name)


def _list_tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(r[0])
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _latest_real_version() -> int:
    """Lit la version la plus haute disponible dans le repertoire reel."""
    versions: List[int] = []
    for f in _REAL_MIG_DIR.glob("*.sql"):
        try:
            versions.append(int(f.stem.split("_")[0]))
        except (ValueError, IndexError):
            continue
    return max(versions) if versions else 0


class _LegacyMigrationBase(unittest.TestCase):
    """Mixin : prepare une DB legacy a une version donnee, puis fait migrer."""

    LEGACY_VERSION: int = 0

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix=f"cinesort_legacy_v{self.LEGACY_VERSION}_"))
        self.db_path = self._tmp / "cinesort.sqlite"
        self._legacy_mig_dir = self._tmp / "legacy_migrations"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _prepare_legacy_db(self) -> int:
        """Cree la DB et applique les migrations 001..LEGACY_VERSION."""
        _copy_migrations_up_to(self.LEGACY_VERSION, self._legacy_mig_dir)
        mgr = MigrationManager(self.db_path, self._legacy_mig_dir)
        v = mgr.apply()
        # Certaines migrations (ex: 001, 002, 003, 004) n'ecrivent pas
        # PRAGMA user_version a la fin (la convention demarre vraiment a 005).
        # Le manager ecrit lui-meme `PRAGMA user_version = <n>` apres chaque
        # migration appliquee, donc apply() retourne bien la version cible.
        self.assertEqual(
            v,
            self.LEGACY_VERSION,
            f"echec preparation DB legacy v{self.LEGACY_VERSION} (obtenu {v})",
        )
        return v

    def _boot_real_app(self) -> int:
        """Lance le boot de l'app sur la DB legacy via SQLiteStore.initialize()."""
        store = SQLiteStore(self.db_path, migrations_dir=_REAL_MIG_DIR, busy_timeout_ms=2000)
        return store.initialize()


# =============================================================================
# Scenario 1 : DB legacy v1 (genesis, runs + errors uniquement)
# =============================================================================
class MigrationFromV1Tests(_LegacyMigrationBase):
    """DB existante a v1 : seules `runs` et `errors` existent."""

    LEGACY_VERSION = 1

    def _seed_v1_data(self) -> None:
        ts = time.time()
        with closing(connect_sqlite(str(self.db_path))) as conn:
            # Table `runs` v1 : sans paused_at (ajoute par mig 023)
            conn.execute(
                "INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json) "
                "VALUES ('LEGACY_V1_R1', 'DONE', ?, '/old/root', '/old/state', '{}')",
                (ts,),
            )
            conn.execute(
                "INSERT INTO errors(run_id, ts, step, code, message) "
                "VALUES ('LEGACY_V1_R1', ?, 'scan', 'OLD-E1', 'legacy error msg')",
                (ts,),
            )
            conn.commit()

    def test_v1_db_migrates_to_latest_without_data_loss(self) -> None:
        self._prepare_legacy_db()
        # Verifie l'etat de depart minimal
        with closing(connect_sqlite(str(self.db_path))) as conn:
            tables_v1 = _list_tables(conn)
            self.assertIn("runs", tables_v1)
            self.assertIn("errors", tables_v1)
            self.assertNotIn("quality_reports", tables_v1)  # mig 003 pas encore
            self.assertNotIn("apply_batches", tables_v1)  # mig 005 pas encore

        self._seed_v1_data()

        # Boot app reel
        final_version = self._boot_real_app()
        self.assertGreaterEqual(final_version, _latest_real_version())

        # Verifications post-migration
        with closing(connect_sqlite(str(self.db_path))) as conn:
            self.assertEqual(_user_version(conn), _latest_real_version())
            # Les donnees v1 sont preservees
            row = conn.execute(
                "SELECT run_id, status, root, error_message FROM runs WHERE run_id='LEGACY_V1_R1'"
            ).fetchone()
            self.assertIsNotNone(row, "run legacy v1 perdu apres migration")
            self.assertEqual(row[0], "LEGACY_V1_R1")
            self.assertEqual(row[1], "DONE")
            self.assertEqual(row[2], "/old/root")
            err = conn.execute(
                "SELECT code, message FROM errors WHERE run_id='LEGACY_V1_R1'"
            ).fetchone()
            self.assertIsNotNone(err, "error legacy v1 perdue apres migration")
            self.assertEqual(err[0], "OLD-E1")
            # Integrity OK
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            # paused_at (colonne ajoutee par mig 023) doit etre presente
            cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
            self.assertIn("paused_at", cols, "colonne paused_at non ajoutee par mig 023")

    def test_v1_db_critical_tables_after_boot(self) -> None:
        self._prepare_legacy_db()
        self._boot_real_app()
        critical = {
            "runs",
            "errors",
            "quality_reports",
            "anomalies",
            "apply_batches",
            "apply_operations",
            "apply_pending_moves",
            "perceptual_reports",
            "probe_cache",
            "schema_migrations",
            "duplicate_decisions",
        }
        with closing(connect_sqlite(str(self.db_path))) as conn:
            tables = _list_tables(conn)
        missing = critical - tables
        self.assertFalse(missing, f"tables critiques manquantes apres migration v1: {missing}")


# =============================================================================
# Scenario 2 : DB legacy v5 (post apply_journal, avant Undo v5)
# =============================================================================
class MigrationFromV5Tests(_LegacyMigrationBase):
    """DB existante a v5 : runs, errors, probe_cache, quality_*, anomalies,
    apply_batches, apply_operations existent. Mais pas row_id (mig 007)."""

    LEGACY_VERSION = 5

    def _seed_v5_data(self) -> None:
        ts = time.time()
        with closing(connect_sqlite(str(self.db_path))) as conn:
            conn.execute(
                "INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json) "
                "VALUES ('LEGACY_V5_R1', 'DONE', ?, '/v5/root', '/v5/state', '{}')",
                (ts,),
            )
            # quality_reports avec un tier 'Bon' legacy (sera renomme par mig 011)
            conn.execute(
                "INSERT INTO quality_reports VALUES "
                "('LEGACY_V5_R1', 'row_v5_a', 75, 'Bon', '[]', '{}', 'p1', 1, ?)",
                (ts,),
            )
            # quality_reports avec tier 'Premium' legacy
            conn.execute(
                "INSERT INTO quality_reports VALUES "
                "('LEGACY_V5_R1', 'row_v5_b', 95, 'Premium', '[]', '{}', 'p1', 1, ?)",
                (ts,),
            )
            conn.execute(
                "INSERT INTO probe_cache(path, size, mtime, tool, raw_json, normalized_json, ts) "
                "VALUES ('/v5/film.mkv', 1000, 1.0, 'ffprobe', '{}', '{}', ?)",
                (ts,),
            )
            # apply_batches existe en v5
            conn.execute(
                "INSERT INTO apply_batches VALUES "
                "('LEGACY_V5_B1', 'LEGACY_V5_R1', ?, NULL, 0, 0, 'DONE', '{}', '7.2')",
                (ts,),
            )
            # apply_operations v5 : pas de row_id (ajoute mig 007), pas de src_sha1 (mig 013)
            conn.execute(
                "INSERT INTO apply_operations(batch_id, op_index, op_type, src_path, dst_path, "
                "reversible, undo_status, ts) "
                "VALUES ('LEGACY_V5_B1', 0, 'MOVE', '/v5/old', '/v5/new', 1, 'DONE', ?)",
                (ts,),
            )
            conn.commit()

    def test_v5_db_migrates_with_data_preservation(self) -> None:
        self._prepare_legacy_db()
        self._seed_v5_data()

        final_version = self._boot_real_app()
        self.assertGreaterEqual(final_version, _latest_real_version())

        with closing(connect_sqlite(str(self.db_path))) as conn:
            # Donnees runs preservees
            run = conn.execute(
                "SELECT run_id, root FROM runs WHERE run_id='LEGACY_V5_R1'"
            ).fetchone()
            self.assertIsNotNone(run)
            self.assertEqual(run[1], "/v5/root")

            # quality_reports preserves
            qr_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM quality_reports WHERE run_id='LEGACY_V5_R1'"
                ).fetchone()[0]
            )
            self.assertEqual(qr_count, 2)

            # Renommage de tiers verifiable : 'Bon' -> 'Gold', 'Premium' -> 'Platinum'
            tier_a = conn.execute(
                "SELECT tier FROM quality_reports WHERE row_id='row_v5_a'"
            ).fetchone()[0]
            self.assertEqual(tier_a, "Gold", "mig 011 n'a pas renomme 'Bon' -> 'Gold'")
            tier_b = conn.execute(
                "SELECT tier FROM quality_reports WHERE row_id='row_v5_b'"
            ).fetchone()[0]
            self.assertEqual(tier_b, "Platinum", "mig 011 n'a pas renomme 'Premium' -> 'Platinum'")

            # apply_operations preservees, avec colonnes ajoutees a NULL
            ops = conn.execute(
                "SELECT op_type, src_path, dst_path, row_id, src_sha1, src_size "
                "FROM apply_operations WHERE batch_id='LEGACY_V5_B1'"
            ).fetchall()
            self.assertEqual(len(ops), 1)
            self.assertEqual(ops[0][0], "MOVE")
            self.assertEqual(ops[0][1], "/v5/old")
            self.assertEqual(ops[0][2], "/v5/new")
            # row_id, src_sha1, src_size ajoutees plus tard => NULL
            self.assertIsNone(ops[0][3])
            self.assertIsNone(ops[0][4])
            self.assertIsNone(ops[0][5])

            # probe_cache preserve
            probe = conn.execute(
                "SELECT path FROM probe_cache WHERE path='/v5/film.mkv'"
            ).fetchone()
            self.assertIsNotNone(probe)

            # Integrity
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_v5_fk_cascade_works_after_migration(self) -> None:
        """Apres migration vers latest, les FK CASCADE doivent etre operationnelles
        meme sur les donnees seedees depuis v5."""
        self._prepare_legacy_db()
        self._seed_v5_data()
        self._boot_real_app()

        with closing(connect_sqlite(str(self.db_path))) as conn:
            # DELETE FROM runs doit cascader sur quality_reports (mig 021 a ajoute la FK)
            conn.execute("DELETE FROM runs WHERE run_id='LEGACY_V5_R1'")
            conn.commit()
            qr_after = int(
                conn.execute(
                    "SELECT COUNT(*) FROM quality_reports WHERE run_id='LEGACY_V5_R1'"
                ).fetchone()[0]
            )
            self.assertEqual(qr_after, 0, "FK CASCADE non operationnelle sur donnees legacy v5")


# =============================================================================
# Scenario 3 : DB legacy v10 (avant renommage tiers + schema_migrations)
# =============================================================================
class MigrationFromV10Tests(_LegacyMigrationBase):
    """DB existante a v10 : tiers legacy 'Premium'/'Bon'/'Moyen'/'Faible' encore
    presents, table schema_migrations pas encore creee (mig 012)."""

    LEGACY_VERSION = 10

    def _seed_v10_data(self) -> None:
        ts = time.time()
        with closing(connect_sqlite(str(self.db_path))) as conn:
            conn.execute(
                "INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json) "
                "VALUES ('LEGACY_V10_R1', 'DONE', ?, '/v10/root', '/v10/state', '{}')",
                (ts,),
            )
            # Tiers legacy variés pour tester tous les cas de la mig 011
            tier_seeds = [
                ("row_premium", 95, "Premium"),  # -> Platinum
                ("row_bon", 75, "Bon"),  # -> Gold
                ("row_moyen", 55, "Moyen"),  # -> Silver
                ("row_faible_high", 35, "Faible"),  # -> Bronze (score >= 30)
                ("row_faible_low", 20, "Faible"),  # -> Reject (score < 30)
                ("row_mauvais_low", 15, "Mauvais"),  # -> Reject (score < 30)
            ]
            for row_id, score, tier in tier_seeds:
                conn.execute(
                    "INSERT INTO quality_reports VALUES "
                    "(?, ?, ?, ?, '[]', '{}', 'p1', 1, ?)",
                    ("LEGACY_V10_R1", row_id, score, tier, ts),
                )
            # anomaly avec code, pour valider l'index ajoute par mig 010
            conn.execute(
                "INSERT INTO anomalies(run_id, severity, code, message, ts) "
                "VALUES ('LEGACY_V10_R1', 'ERROR', 'A_LEGACY', 'old anomaly', ?)",
                (ts,),
            )
            conn.commit()

    def test_v10_tier_renames_apply_correctly(self) -> None:
        self._prepare_legacy_db()
        # schema_migrations n'existe pas encore en v10
        with closing(connect_sqlite(str(self.db_path))) as conn:
            tables_v10 = _list_tables(conn)
            self.assertNotIn("schema_migrations", tables_v10)

        self._seed_v10_data()
        self._boot_real_app()

        expected_renames = {
            "row_premium": "Platinum",
            "row_bon": "Gold",
            "row_moyen": "Silver",
            "row_faible_high": "Bronze",
            "row_faible_low": "Reject",
            "row_mauvais_low": "Reject",
        }
        with closing(connect_sqlite(str(self.db_path))) as conn:
            for row_id, expected_tier in expected_renames.items():
                actual = conn.execute(
                    "SELECT tier FROM quality_reports WHERE row_id=?",
                    (row_id,),
                ).fetchone()
                self.assertIsNotNone(actual, f"row {row_id} perdue")
                self.assertEqual(
                    actual[0],
                    expected_tier,
                    f"mig 011 a mal renomme {row_id} (attendu {expected_tier}, obtenu {actual[0]})",
                )

    def test_v10_schema_migrations_created_and_tracks_post_v12(self) -> None:
        """Apres boot, schema_migrations doit exister et tracer les migrations >= 12."""
        self._prepare_legacy_db()
        self._seed_v10_data()
        self._boot_real_app()

        with closing(connect_sqlite(str(self.db_path))) as conn:
            tables = _list_tables(conn)
            self.assertIn("schema_migrations", tables)
            # Les migrations >= 12 (creation de schema_migrations) sont tracees
            tracked = [
                int(r[0])
                for r in conn.execute(
                    "SELECT version FROM schema_migrations ORDER BY version ASC"
                ).fetchall()
            ]
            # Au moins 12, 13, 14, ... jusqu'a latest
            self.assertIn(12, tracked)
            self.assertIn(_latest_real_version(), tracked)
            # Toutes les versions du tracking sont >= 12 (les < 12 ne sont pas tracees
            # car la table n'existait pas encore quand elles ont ete appliquees).
            for v in tracked:
                self.assertGreaterEqual(v, 12)

    def test_v10_anomalies_index_code_exists(self) -> None:
        """Mig 010 ajoute l'index idx_anomalies_code. Verifie qu'apres migration
        depuis v10 (donc avant l'index), il est bien present."""
        self._prepare_legacy_db()
        # En v10, l'index est deja la (cree par la mig 010 elle-meme)
        self._seed_v10_data()
        self._boot_real_app()

        with closing(connect_sqlite(str(self.db_path))) as conn:
            indexes = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='anomalies'"
                )
            }
            self.assertIn("idx_anomalies_code", indexes)


# =============================================================================
# Scenario 4 : DB legacy v22 (avant recreation table runs + duplicate_decisions)
# =============================================================================
class MigrationFromV22Tests(_LegacyMigrationBase):
    """DB existante a v22 : schema "moderne" mais sans paused_at sur runs
    (ajout mig 023) ni duplicate_decisions (mig 024). Test critique car la
    mig 023 recree la table runs avec @manager: disable_fk."""

    LEGACY_VERSION = 22

    def _seed_v22_data(self) -> None:
        ts = time.time()
        with closing(connect_sqlite(str(self.db_path))) as conn:
            # Run dans un etat "ancien" — PENDING, DONE, ... (avant ajout PAUSED/SAVED/AV)
            conn.execute(
                "INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json, "
                "stats_json, idx, total, current_folder, cancel_requested, error_message) "
                "VALUES ('LEGACY_V22_R1', 'DONE', ?, '/v22/root', '/v22/state', '{\"x\":1}', "
                "'{\"y\":2}', 42, 100, '/v22/cur', 0, NULL)",
                (ts,),
            )
            # Enfants : errors (FK CASCADE v21), quality_reports (FK CASCADE v21), anomalies
            conn.execute(
                "INSERT INTO errors(run_id, ts, step, code, message, context_json) "
                "VALUES ('LEGACY_V22_R1', ?, 'scan', 'E_V22', 'msg v22', '{\"info\": 1}')",
                (ts,),
            )
            conn.execute(
                "INSERT INTO quality_reports VALUES "
                "('LEGACY_V22_R1', 'row_v22', 80, 'Gold', '[]', '{}', 'p1', 1, ?)",
                (ts,),
            )
            conn.execute(
                "INSERT INTO anomalies(run_id, severity, code, message, ts) "
                "VALUES ('LEGACY_V22_R1', 'WARN', 'A_V22', 'anomaly v22', ?)",
                (ts,),
            )
            # apply chain
            conn.execute(
                "INSERT INTO apply_batches VALUES "
                "('LEGACY_V22_B1', 'LEGACY_V22_R1', ?, NULL, 0, 0, 'DONE', '{}', '7.7')",
                (ts,),
            )
            conn.execute(
                "INSERT INTO apply_operations(batch_id, op_index, op_type, src_path, dst_path, "
                "reversible, undo_status, ts, row_id, src_sha1, src_size) "
                "VALUES ('LEGACY_V22_B1', 0, 'MOVE', '/v22/a', '/v22/b', 1, 'DONE', ?, "
                "'row_v22', 'sha1abc', 12345)",
                (ts,),
            )
            conn.commit()

    def test_v22_runs_table_recreation_preserves_data(self) -> None:
        """Mig 023 fait DROP+CREATE+RENAME de runs avec @manager: disable_fk.
        Les enfants (errors, quality_reports, anomalies avec FK CASCADE) ne
        doivent PAS etre cascade-deleted pendant cette operation."""
        self._prepare_legacy_db()
        self._seed_v22_data()

        # Verifie l'etat de depart
        with closing(connect_sqlite(str(self.db_path))) as conn:
            self.assertEqual(_user_version(conn), 22)
            # paused_at n'existe pas encore en v22
            cols_v22 = {r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
            self.assertNotIn("paused_at", cols_v22)

        self._boot_real_app()

        with closing(connect_sqlite(str(self.db_path))) as conn:
            # Runs preserve avec ses metadonnees (DROP+CREATE+INSERT INTO ... SELECT)
            run = conn.execute(
                "SELECT run_id, status, root, idx, total, current_folder, paused_at, "
                "stats_json FROM runs WHERE run_id='LEGACY_V22_R1'"
            ).fetchone()
            self.assertIsNotNone(run, "run perdu apres recreation table v23")
            self.assertEqual(run[0], "LEGACY_V22_R1")
            self.assertEqual(run[1], "DONE")
            self.assertEqual(run[2], "/v22/root")
            self.assertEqual(run[3], 42)
            self.assertEqual(run[4], 100)
            self.assertEqual(run[5], "/v22/cur")
            self.assertIsNone(run[6])  # paused_at NULL pour les anciens runs
            self.assertEqual(run[7], '{"y":2}')

            # Verif critique : les enfants FK CASCADE ne doivent PAS avoir ete supprimes
            # par la recreation de runs (le marker @manager: disable_fk a fonctionne).
            err = conn.execute(
                "SELECT code FROM errors WHERE run_id='LEGACY_V22_R1'"
            ).fetchone()
            self.assertIsNotNone(err, "errors casacade-deleted pendant mig 023 — flag disable_fk casse !")
            self.assertEqual(err[0], "E_V22")

            qr = conn.execute(
                "SELECT score FROM quality_reports WHERE run_id='LEGACY_V22_R1'"
            ).fetchone()
            self.assertIsNotNone(qr, "quality_reports cascade-deleted pendant mig 023 !")
            self.assertEqual(qr[0], 80)

            anom = conn.execute(
                "SELECT code FROM anomalies WHERE run_id='LEGACY_V22_R1'"
            ).fetchone()
            self.assertIsNotNone(anom, "anomalies cascade-deleted pendant mig 023 !")
            self.assertEqual(anom[0], "A_V22")

            # apply chain preservee
            ops = conn.execute(
                "SELECT src_path, src_sha1 FROM apply_operations WHERE batch_id='LEGACY_V22_B1'"
            ).fetchone()
            self.assertIsNotNone(ops)
            self.assertEqual(ops[0], "/v22/a")
            self.assertEqual(ops[1], "sha1abc")

            # FK CASCADE toujours operationnelle apres recreation
            fks = list(conn.execute("PRAGMA foreign_key_list(errors)"))
            self.assertTrue(any(str(fk[6]).upper() == "CASCADE" for fk in fks),
                            "FK CASCADE perdue apres recreation runs")

            # PRAGMA foreign_keys = ON apres migration (le manager doit l'avoir restaure)
            self.assertEqual(int(conn.execute("PRAGMA foreign_keys").fetchone()[0]), 1)

            # Integrity
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_v22_status_check_extended_after_migration(self) -> None:
        """Mig 023 etend la contrainte CHECK sur runs.status pour accepter
        PAUSED, SAVED, AWAITING_VALIDATION. Verifie que c'est applique."""
        self._prepare_legacy_db()
        self._seed_v22_data()
        self._boot_real_app()

        with closing(connect_sqlite(str(self.db_path))) as conn:
            # Avant mig 023 : impossible d'inserer PAUSED. Apres : OK.
            conn.execute(
                "INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json) "
                "VALUES ('R_PAUSED_TEST', 'PAUSED', ?, '/r', '/s', '{}')",
                (time.time(),),
            )
            conn.execute(
                "INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json) "
                "VALUES ('R_SAVED_TEST', 'SAVED', ?, '/r', '/s', '{}')",
                (time.time(),),
            )
            conn.execute(
                "INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json) "
                "VALUES ('R_AV_TEST', 'AWAITING_VALIDATION', ?, '/r', '/s', '{}')",
                (time.time(),),
            )
            conn.commit()
            # Et un status invalide doit toujours echouer
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json) "
                    "VALUES ('R_BOGUS', 'INVALID_STATUS', ?, '/r', '/s', '{}')",
                    (time.time(),),
                )


# =============================================================================
# Scenario 5 : DB legacy v(N-1) (juste avant la derniere migration)
# =============================================================================
class MigrationFromVNMinus1Tests(_LegacyMigrationBase):
    """DB existante a v(N-1). Verifie que la derniere migration toute seule
    s'applique sans surprise sur une base "presque a jour"."""

    @classmethod
    def setUpClass(cls) -> None:
        latest = _latest_real_version()
        cls.LEGACY_VERSION = latest - 1

    def _seed_legacy_data(self) -> None:
        ts = time.time()
        with closing(connect_sqlite(str(self.db_path))) as conn:
            conn.execute(
                "INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json) "
                "VALUES ('LEGACY_VN1_R1', 'DONE', ?, '/vn1/root', '/vn1/state', '{}')",
                (ts,),
            )
            conn.execute(
                "INSERT INTO quality_reports VALUES "
                "('LEGACY_VN1_R1', 'row_vn1', 90, 'Platinum', '[]', '{}', 'p1', 1, ?)",
                (ts,),
            )
            conn.commit()

    def test_last_migration_applies_without_data_loss(self) -> None:
        latest = _latest_real_version()
        self.assertGreater(latest, 1)
        self._prepare_legacy_db()
        self._seed_legacy_data()

        final_version = self._boot_real_app()
        self.assertEqual(final_version, latest)

        with closing(connect_sqlite(str(self.db_path))) as conn:
            run = conn.execute(
                "SELECT run_id FROM runs WHERE run_id='LEGACY_VN1_R1'"
            ).fetchone()
            self.assertIsNotNone(run)
            qr = conn.execute(
                "SELECT score, tier FROM quality_reports WHERE row_id='row_vn1'"
            ).fetchone()
            self.assertIsNotNone(qr)
            self.assertEqual(qr[0], 90)
            self.assertEqual(qr[1], "Platinum")
            # Integrity
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")


# =============================================================================
# Cross-cutting : la liste de versions de depart est exhaustive
# =============================================================================
class LegacyVersionCoverageMetaTests(unittest.TestCase):
    """Sanity check : ce fichier couvre bien au moins 3 points de depart distincts
    et l'un d'entre eux est v(N-1)."""

    def test_at_least_three_legacy_versions_covered(self) -> None:
        legacy_classes: List[Tuple[str, int]] = [
            ("v1", MigrationFromV1Tests.LEGACY_VERSION),
            ("v5", MigrationFromV5Tests.LEGACY_VERSION),
            ("v10", MigrationFromV10Tests.LEGACY_VERSION),
            ("v22", MigrationFromV22Tests.LEGACY_VERSION),
            # v(N-1) calcule a la volee
        ]
        self.assertGreaterEqual(
            len({v for _, v in legacy_classes}), 3, "moins de 3 versions de depart distinctes"
        )

    def test_v_n_minus_1_is_strictly_below_latest(self) -> None:
        latest = _latest_real_version()
        n_minus_1 = MigrationFromVNMinus1Tests.LEGACY_VERSION if hasattr(
            MigrationFromVNMinus1Tests, "LEGACY_VERSION"
        ) else latest - 1
        self.assertEqual(n_minus_1, latest - 1)
        self.assertGreaterEqual(latest, 25)  # On a au moins 25 migrations


if __name__ == "__main__":
    unittest.main(verbosity=2)
