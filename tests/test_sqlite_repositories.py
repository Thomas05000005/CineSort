"""Tests pour la composition Repository de SQLiteStore (issue #85)."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from cinesort.infra.db.repositories import (
    AnomalyRepository,
    ApplyRepository,
    PerceptualRepository,
    ProbeRepository,
    QualityRepository,
    RunRepository,
    ScanRepository,
    _BaseRepository,
)
from cinesort.infra.db.sqlite_store import SQLiteStore


class SQLiteStoreCompositionTests(unittest.TestCase):
    """Issue #85 : SQLiteStore expose 7 Repository via composition."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_repo_"))
        self.store = SQLiteStore(self._tmp / "test.sqlite")
        self.store.initialize()

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_store_exposes_apply_repository(self) -> None:
        self.assertIsInstance(self.store.apply, ApplyRepository)
        self.assertIsInstance(self.store.apply, _BaseRepository)

    def test_store_exposes_quality_repository(self) -> None:
        self.assertIsInstance(self.store.quality, QualityRepository)

    def test_store_exposes_run_repository(self) -> None:
        self.assertIsInstance(self.store.run, RunRepository)

    def test_store_exposes_anomaly_repository(self) -> None:
        self.assertIsInstance(self.store.anomaly, AnomalyRepository)

    def test_store_exposes_probe_repository(self) -> None:
        self.assertIsInstance(self.store.probe, ProbeRepository)

    def test_store_exposes_scan_repository(self) -> None:
        self.assertIsInstance(self.store.scan, ScanRepository)

    def test_store_exposes_perceptual_repository(self) -> None:
        self.assertIsInstance(self.store.perceptual, PerceptualRepository)


class RepositoryDelegationTests(unittest.TestCase):
    """Verifie que les Repository delegent correctement au store parent."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_repo_deleg_"))
        self.store = SQLiteStore(self._tmp / "test.sqlite")
        self.store.initialize()

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_repo_managed_conn_delegates_to_store(self) -> None:
        """ApplyRepository._managed_conn() delegue au store et retourne un context manager."""
        ctx = self.store.apply._managed_conn()
        # Doit etre un context manager utilisable
        with ctx as conn:
            self.assertIsNotNone(conn)
            cur = conn.execute("SELECT 1")
            self.assertEqual(cur.fetchone()[0], 1)

    def test_backward_compat_methods_still_work(self) -> None:
        """Les anciennes methodes store.X() restent fonctionnelles (heritage mixin)."""
        # get_quality_report retourne None pour un run/row inconnu
        self.assertIsNone(self.store.quality.get_quality_report(run_id="nope", row_id="nope"))
        # list_runs retourne une liste vide pour DB neuve
        self.assertEqual(self.store.run.list_runs(), [])

    def test_repository_method_matches_store_method(self) -> None:
        """store.quality.get_quality_report et store.get_quality_report sont identiques."""
        # Ce sont les MEMES methodes (heritage MRO via mixin), donc meme function ID
        self.assertEqual(
            self.store.quality.get_quality_report(run_id="x", row_id="y"),
            self.store.quality.get_quality_report(run_id="x", row_id="y"),
        )


class BaseRepositoryInjectionTests(unittest.TestCase):
    """Verifie qu'un Repository peut etre instancie avec un store stub (pour tests)."""

    def test_repo_constructible_with_stub_store(self) -> None:
        """Pattern attendu pour les tests unitaires futurs : injection d'un FakeStore."""

        class _FakeStore:
            def _connect(self):
                raise NotImplementedError

            def _managed_conn(self):
                raise NotImplementedError

            def _ensure_schema_group(self, name):
                pass

            def _decode_row_json(self, *args, **kwargs):
                return {}

            def _is_missing_table_error(self, exc, table_name):
                return False

        # Doit construire sans erreur
        repo = QualityRepository(_FakeStore())
        self.assertIs(repo._store.__class__.__name__, "_FakeStore")


#: Limite historique SQLITE_MAX_VARIABLE_NUMBER (SQLite < 3.32). On la force sur
#: les connexions du store pendant ces tests : le sqlite3 qui execute la suite est
#: souvent >= 3.32 (limite 32766), et le test serait alors un FAUX VERT — la clause
#: `NOT IN` non bornee d'avant le fix passerait sans lever. Doit rester > au lot de
#: purge (_PRUNE_CHUNK=500) + 1 parametre de root, sinon c'est le fix qu'on casse.
_SQLITE_LEGACY_VAR_LIMIT = 999

#: Nombre d'entrees seedees : doit depasser _SQLITE_LEGACY_VAR_LIMIT - 1 pour que
#: la clause `NOT IN` d'avant le fix (1 placeholder par entree conservee + le root)
#: franchisse effectivement la limite.
_PRUNE_SEED_COUNT = 1200


class PruneIncrementalCacheBoundsTests(unittest.TestCase):
    """Purge incrémentale : ne doit pas dépasser SQLITE_MAX_VARIABLE_NUMBER.

    Avant le fix, prune_incremental_row_cache / prune_incremental_scan_cache
    construisaient une clause NOT IN avec un placeholder par entrée conservée :
    au-delà de la limite SQLite (999 sur < 3.32), sqlite3.OperationalError
    "too many SQL variables", et le cache n'était alors jamais purgé.
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_prune_"))
        self.store = SQLiteStore(self._tmp / "test.sqlite")
        self.store.initialize()
        self.root = "R:/lib"
        self.videos = [f"{self.root}/f{i}/v{i}.mkv" for i in range(_PRUNE_SEED_COUNT)]
        self.folders = [f"{self.root}/f{i}" for i in range(_PRUNE_SEED_COUNT)]

        now = time.time()
        with self.store._managed_conn() as conn:
            conn.executemany(
                """
                INSERT INTO incremental_row_cache(
                  root_path, video_path, video_size, video_mtime_ns, video_hash,
                  folder_path, nfo_sig, cfg_sig, kind, row_json, updated_ts, last_run_id
                ) VALUES(?, ?, 1, 1, 'h', ?, NULL, 'c', 'single', '{}', ?, 'r1')
                """,
                [(self.root, v, f, now) for v, f in zip(self.videos, self.folders)],
            )
            conn.executemany(
                """
                INSERT INTO incremental_scan_cache(
                  root_path, folder_path, cfg_sig, folder_sig,
                  rows_json, stats_json, updated_ts, last_run_id
                ) VALUES(?, ?, 'c', 's', '[]', '{}', ?, 'r1')
                """,
                [(self.root, f, now) for f in self.folders],
            )

        # Faux-vert killer : sans ce bridage, le `NOT IN` non borne d'avant le fix
        # tient largement sous la limite 32766 des SQLite recents et le test passe
        # AUSSI sur le code bugge. On restaure la limite historique de 999.
        _real_connect = self.store._connect

        def _legacy_limit_connect() -> sqlite3.Connection:
            conn = _real_connect()
            conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, _SQLITE_LEGACY_VAR_LIMIT)
            return conn

        self.store._connect = _legacy_limit_connect  # type: ignore[method-assign]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_legacy_variable_limit_is_actually_enforced(self) -> None:
        """Garde-fou du garde-fou : prouve que le bridage de setUp mord vraiment.

        Si ce test devient vert sans lever, les deux tests "over_variable_limit"
        ci-dessous ne prouvent plus rien.
        """
        with self.store._managed_conn() as conn:
            self.assertEqual(
                conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER),
                _SQLITE_LEGACY_VAR_LIMIT,
            )
            placeholders = ",".join("?" for _ in range(_SQLITE_LEGACY_VAR_LIMIT + 1))
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute(f"SELECT 1 WHERE 1 IN ({placeholders})", tuple(range(1000)))

    def test_prune_row_cache_keeps_all_over_variable_limit(self) -> None:
        # keep = les 1200 vidéos -> la clause NOT IN d'avant le fix demandait
        # 1201 variables > 999 : OperationalError "too many SQL variables".
        # Ici : aucune obsolète, 0 supprimée, aucune exception.
        deleted = self.store.scan.prune_incremental_row_cache(root_path=self.root, keep_video_paths=list(self.videos))
        self.assertEqual(deleted, 0)
        self.assertEqual(self._count("incremental_row_cache"), _PRUNE_SEED_COUNT)

    def test_prune_scan_cache_keeps_all_over_variable_limit(self) -> None:
        # Même défaut, même correctif, sur le cache dossier (v1).
        deleted = self.store.scan.prune_incremental_scan_cache(root_path=self.root, keep_folders=list(self.folders))
        self.assertEqual(deleted, 0)
        self.assertEqual(self._count("incremental_scan_cache"), _PRUNE_SEED_COUNT)

    def test_prune_deletes_stale_entries(self) -> None:
        # Non-régression du contrat métier : reste vert des DEUX côtés de la
        # mutation (100 placeholders tiennent sous la limite). Prouve que le
        # découpage en lots supprime exactement les entrées obsolètes.
        deleted = self.store.scan.prune_incremental_row_cache(root_path=self.root, keep_video_paths=self.videos[:100])
        self.assertEqual(deleted, _PRUNE_SEED_COUNT - 100)
        self.assertEqual(self._count("incremental_row_cache"), 100)

    def test_prune_empty_keep_wipes_root(self) -> None:
        # Non-régression : keep vide == purge totale de ce root (sémantique
        # historique dont dépend plan_support_core).
        deleted = self.store.scan.prune_incremental_row_cache(root_path=self.root, keep_video_paths=[])
        self.assertEqual(deleted, _PRUNE_SEED_COUNT)
        self.assertEqual(self._count("incremental_row_cache"), 0)

    def _count(self, table: str) -> int:
        with self.store._managed_conn() as conn:
            cur = conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE root_path=?", (self.root,))
            return int(cur.fetchone()["n"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
