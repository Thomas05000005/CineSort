"""VO-A backend -- tests pragma_profile.py.

Couvre :
  * Integrite des 4 profils (cles obligatoires + valeurs critiques NAS).
  * detect_storage_type sur chemins locaux + UNC.
  * apply_pragmas roundtrip via snapshot readback.
  * connect_sqlite backward compat (signature `connect_sqlite(db_path)`).
  * Override explicite via `profile=...` puis via `SQLiteStore(pragma_profile_name=...)`.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, ".")

from cinesort.infra.db.connection import connect_sqlite, get_mmap_size
from cinesort.infra.db.pragma_profile import (
    PROFILES,
    apply_pragmas,
    detect_storage_type,
    get_pragma_snapshot,
    is_unc_path,
    resolve_profile,
)


class ProfilesIntegrityTests(unittest.TestCase):
    """PROFILES doit exposer les 4 profils attendus avec les invariants critiques."""

    EXPECTED_PROFILES = {"local_ssd", "local_hdd", "nas_smb", "nas_smb_slow"}
    REQUIRED_KEYS = {
        "journal_mode",
        "synchronous",
        "busy_timeout",
        "mmap_size",
        "cache_size",
        "wal_autocheckpoint",
    }

    def test_all_expected_profiles_present(self):
        self.assertEqual(set(PROFILES.keys()), self.EXPECTED_PROFILES)

    def test_every_profile_has_required_keys(self):
        for name, profile in PROFILES.items():
            with self.subTest(profile=name):
                missing = self.REQUIRED_KEYS - set(profile.keys())
                self.assertFalse(missing, f"Profil {name} : cles manquantes {missing}")

    def test_all_profiles_use_wal(self):
        # WAL est requis pour la robustesse multi-process de CineSort.
        for name, profile in PROFILES.items():
            with self.subTest(profile=name):
                self.assertEqual(profile["journal_mode"], "WAL")

    def test_nas_profiles_disable_mmap(self):
        # mmap_size > 0 sur SMB -> corruption silencieuse confirmee.
        self.assertEqual(PROFILES["nas_smb"]["mmap_size"], 0)
        self.assertEqual(PROFILES["nas_smb_slow"]["mmap_size"], 0)

    def test_nas_profiles_use_synchronous_full(self):
        # synchronous=FULL est l'unique garantie de durabilite sur SMB
        # (Sonarr #1886 : corruption silencieuse sur NORMAL).
        self.assertEqual(PROFILES["nas_smb"]["synchronous"], "FULL")
        self.assertEqual(PROFILES["nas_smb_slow"]["synchronous"], "FULL")

    def test_local_profiles_use_synchronous_normal(self):
        # NORMAL est canonique avec WAL : ~30% gain perf sans perte de durabilite
        # significative entre checkpoints.
        self.assertEqual(PROFILES["local_ssd"]["synchronous"], "NORMAL")
        self.assertEqual(PROFILES["local_hdd"]["synchronous"], "NORMAL")

    def test_busy_timeout_monotonic(self):
        # Plus le stockage est lent, plus le busy_timeout doit etre eleve.
        ssd = int(PROFILES["local_ssd"]["busy_timeout"])
        hdd = int(PROFILES["local_hdd"]["busy_timeout"])
        nas = int(PROFILES["nas_smb"]["busy_timeout"])
        nas_slow = int(PROFILES["nas_smb_slow"]["busy_timeout"])
        self.assertLess(ssd, hdd)
        self.assertLess(hdd, nas)
        self.assertLess(nas, nas_slow)

    def test_nas_wal_autocheckpoint_more_frequent(self):
        # Sur NAS on veut fermer le WAL plus souvent (limite la fenetre
        # de corruption en cas de coupure reseau).
        local = int(PROFILES["local_ssd"]["wal_autocheckpoint"])
        nas = int(PROFILES["nas_smb"]["wal_autocheckpoint"])
        nas_slow = int(PROFILES["nas_smb_slow"]["wal_autocheckpoint"])
        self.assertLess(nas, local)
        self.assertLess(nas_slow, nas)


class DetectStorageTypeTests(unittest.TestCase):
    """detect_storage_type doit reconnaitre UNC et fallback raisonnable."""

    def test_unc_path_double_backslash(self):
        # Chemin UNC litteral : `\\nas01\media\db.sqlite`.
        unc = chr(92) * 2 + "nas01" + chr(92) + "media" + chr(92) + "db.sqlite"
        self.assertEqual(detect_storage_type(unc), "nas_smb")

    def test_unc_path_pathlib_object(self):
        unc = chr(92) * 2 + "server" + chr(92) + "share" + chr(92) + "cine.db"
        self.assertEqual(detect_storage_type(Path(unc)), "nas_smb")

    def test_local_temp_path_not_nas(self):
        # tempfile garantit un chemin local OS-friendly.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            kind = detect_storage_type(str(db_path))
            # Sur Windows local : 'local_ssd' ou 'local_hdd' (jamais nas_*).
            # Sur Linux/macOS : fallback 'local_ssd'.
            self.assertNotIn(kind, {"nas_smb", "nas_smb_slow"})
            self.assertIn(kind, PROFILES)

    def test_unknown_path_falls_back_to_local_ssd(self):
        # Chemin sans drive : fallback safe.
        kind = detect_storage_type("relative/path.db")
        self.assertEqual(kind, "local_ssd")


class IsUncPathTests(unittest.TestCase):
    def test_double_backslash_prefix(self):
        unc = chr(92) * 2 + "nas01" + chr(92) + "share" + chr(92) + "x.db"
        self.assertTrue(is_unc_path(unc))

    def test_local_temp_not_unc(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(is_unc_path(str(Path(tmp) / "x.db")))

    def test_relative_not_unc(self):
        self.assertFalse(is_unc_path("rel/path.db"))


class ResolveProfileTests(unittest.TestCase):
    def test_explicit_profile_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "x.db")
            self.assertEqual(
                resolve_profile(db_path, explicit_profile="nas_smb_slow"),
                "nas_smb_slow",
            )

    def test_explicit_unknown_raises(self):
        with self.assertRaises(ValueError):
            resolve_profile("any.db", explicit_profile="totally_made_up")

    def test_auto_resolution_returns_valid_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "x.db")
            self.assertIn(resolve_profile(db_path), PROFILES)


class ApplyPragmasRoundtripTests(unittest.TestCase):
    """Verifie que apply_pragmas applique reellement + retourne un snapshot."""

    def test_apply_local_ssd_sets_wal_and_normal(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ssd.db"
            conn = sqlite3.connect(str(db_path))
            try:
                snap = apply_pragmas(conn, "local_ssd")
                # journal_mode est case-insensitive en readback : SQLite renvoie
                # 'wal' apres ecriture 'WAL'.
                self.assertEqual(str(snap["journal_mode"]).lower(), "wal")
                # synchronous renvoye sous forme numerique : NORMAL = 1.
                self.assertEqual(int(snap["synchronous"]), 1)
                self.assertEqual(int(snap["busy_timeout"]), 5000)
            finally:
                conn.close()

    def test_apply_nas_smb_sets_full_sync_and_zero_mmap(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "nas.db"
            conn = sqlite3.connect(str(db_path))
            try:
                snap = apply_pragmas(conn, "nas_smb")
                self.assertEqual(str(snap["journal_mode"]).lower(), "wal")
                # synchronous=FULL -> 2.
                self.assertEqual(int(snap["synchronous"]), 2)
                self.assertEqual(int(snap["busy_timeout"]), 30000)
                # mmap_size doit etre 0 sur NAS SMB (memo Sonarr #1886).
                self.assertEqual(int(snap["mmap_size"]), 0)
            finally:
                conn.close()

    def test_apply_unknown_profile_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "x.db"
            conn = sqlite3.connect(str(db_path))
            try:
                with self.assertRaises(ValueError):
                    apply_pragmas(conn, "wrong_profile_name")
            finally:
                conn.close()

    def test_get_pragma_snapshot_returns_all_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "snap.db"
            conn = sqlite3.connect(str(db_path))
            try:
                snap = get_pragma_snapshot(conn)
                expected = {
                    "journal_mode",
                    "synchronous",
                    "busy_timeout",
                    "mmap_size",
                    "cache_size",
                    "wal_autocheckpoint",
                }
                self.assertEqual(set(snap.keys()), expected)
            finally:
                conn.close()


class ConnectSqliteBackwardCompatTests(unittest.TestCase):
    """La refacto VO-A ne doit PAS casser les call sites historiques."""

    def test_call_without_kwargs_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "compat.db"
            conn = connect_sqlite(str(db_path))
            try:
                # Foreign keys ON est un invariant non negociable.
                row = conn.execute("PRAGMA foreign_keys").fetchone()
                self.assertEqual(int(row[0]), 1)
                # journal_mode applique via profil autodetect (local_*).
                row = conn.execute("PRAGMA journal_mode").fetchone()
                self.assertEqual(str(row[0]).lower(), "wal")
            finally:
                conn.close()

    def test_busy_timeout_kwarg_still_honored(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "bt.db"
            # busy_timeout_ms forme le timeout Python-level ; le PRAGMA effectif
            # vient du profil mais l'appel ne doit pas lever.
            conn = connect_sqlite(str(db_path), busy_timeout_ms=12345)
            try:
                self.assertIsInstance(conn, sqlite3.Connection)
            finally:
                conn.close()

    def test_explicit_profile_nas_smb_applies_full_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "force_nas.db"
            conn = connect_sqlite(str(db_path), profile="nas_smb")
            try:
                row = conn.execute("PRAGMA synchronous").fetchone()
                self.assertEqual(int(row[0]), 2)  # FULL
                row = conn.execute("PRAGMA mmap_size").fetchone()
                self.assertEqual(int(row[0]), 0)
            finally:
                conn.close()

    def test_explicit_profile_unknown_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "bad.db"
            with self.assertRaises(ValueError):
                connect_sqlite(str(db_path), profile="not_a_profile")

    def test_get_mmap_size_helper_still_works(self):
        # Helper existant V3-11 : la refacto ne doit pas le casser.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "mmap.db"
            conn = connect_sqlite(str(db_path))
            try:
                size = get_mmap_size(conn)
                self.assertIsInstance(size, int)
                self.assertGreaterEqual(size, 0)
            finally:
                conn.close()


class SQLiteStorePragmaProfileTests(unittest.TestCase):
    """SQLiteStore doit honorer le kwarg pragma_profile_name."""

    def test_default_profile_is_none_autodetect(self):
        from cinesort.infra.db.sqlite_store import SQLiteStore

        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(Path(tmp) / "db" / "store.sqlite")
            self.assertIsNone(store.pragma_profile_name)

    def test_explicit_profile_stored(self):
        from cinesort.infra.db.sqlite_store import SQLiteStore

        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(
                Path(tmp) / "db" / "store.sqlite",
                pragma_profile_name="nas_smb_slow",
            )
            self.assertEqual(store.pragma_profile_name, "nas_smb_slow")


if __name__ == "__main__":
    unittest.main()
