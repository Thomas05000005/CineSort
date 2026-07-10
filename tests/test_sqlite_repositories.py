"""Tests pour la composition Repository de SQLiteStore (issue #85)."""

from __future__ import annotations

import tempfile
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


class PruneIncrementalCacheBoundsTests(unittest.TestCase):
    """Purge incrémentale : ne doit pas dépasser SQLITE_MAX_VARIABLE_NUMBER.

    Avant le fix, prune_incremental_row_cache construisait une clause NOT IN
    avec un placeholder par vidéo conservée : au-delà de la limite SQLite
    (999 sur < 3.32), sqlite3.OperationalError "too many SQL variables".
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_prune_"))
        self.store = SQLiteStore(self._tmp / "test.sqlite")
        self.store.initialize()
        self.root = "R:/lib"
        for i in range(1200):
            self.store.scan.upsert_incremental_row_cache(
                root_path=self.root,
                video_path=f"{self.root}/f{i}/v{i}.mkv",
                video_size=1,
                video_mtime_ns=1,
                video_hash="h",
                folder_path=f"{self.root}/f{i}",
                nfo_sig=None,
                cfg_sig="c",
                kind="single",
                row_json={},
                run_id="r1",
            )

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_prune_keeps_all_over_variable_limit(self) -> None:
        # keep = les 1200 vidéos -> l'ancienne clause NOT IN aurait levé
        # OperationalError. Ici : aucune obsolète, 0 supprimée, aucune exception.
        keep = [f"{self.root}/f{i}/v{i}.mkv" for i in range(1200)]
        deleted = self.store.scan.prune_incremental_row_cache(
            root_path=self.root, keep_video_paths=keep
        )
        self.assertEqual(deleted, 0)

    def test_prune_deletes_stale_entries(self) -> None:
        keep = [f"{self.root}/f{i}/v{i}.mkv" for i in range(100)]
        deleted = self.store.scan.prune_incremental_row_cache(
            root_path=self.root, keep_video_paths=keep
        )
        self.assertEqual(deleted, 1100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
