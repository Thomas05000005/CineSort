"""AUDIT F29 — auto-restore DB : iterer sur les backups au lieu du seul plus recent.

`_attempt_auto_restore` ne tentait QUE `backups[0]` et abandonnait en
"restore_failed" si celui-ci etait lui-meme corrompu, sans jamais essayer les
backups plus anciens et SAINS juste derriere.

Aggravation : apres l'abandon, `initialize()` appelait quand meme
`_backup_before_migrations`, qui poussait une copie de la DB CORROMPUE en tete
de backups/ a chaque boot. La rotation (DEFAULT_MAX_BACKUPS=5) evinçait alors le
backup sain en quelques boots -> perte definitive d'une bibliotheque qui etait
recuperable (aucun endpoint UI de restore manuel n'existe).

Les tests n'utilisent QUE sqlite3 pour juger de l'integrite des fichiers, jamais
les helpers de production, pour rester valides des deux cotes d'une mutation.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from typing import List, Optional

from cinesort.infra.db.backup import backup_db_with_rotation
from cinesort.infra.db.sqlite_store import SQLiteStore


def _raw_integrity(path: Path) -> str:
    """PRAGMA integrity_check independant du code de production."""
    try:
        with closing(sqlite3.connect(str(path))) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            return str(row[0]) if row else "unknown"
    except sqlite3.Error as exc:
        return f"error: {exc}"


def _corrupt(path: Path) -> None:
    """Ecrase la page 2 (offset 4096) — corruption detectee par integrity_check."""
    with open(path, "r+b") as fh:
        fh.seek(4096)
        fh.write(b"\xff" * 400)


class DbAutoRestoreIterationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_f29_"))
        self.db_path = self._tmp / "cinesort.sqlite"
        # DB de reference saine (fresh install : aucun backup cree)
        SQLiteStore(self.db_path).initialize()
        self.pristine = self._tmp / "pristine.sqlite"
        shutil.copy2(self.db_path, self.pristine)
        self.backup_dir = self._tmp / "backups"
        self.backup_dir.mkdir(exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ---- helpers ----

    def _add_backup(self, stamp: str, *, corrupt: bool, age_s: float, trigger: str = "pre_migration") -> Path:
        path = self.backup_dir / f"cinesort.{stamp}Z.{trigger}.bak"
        shutil.copy2(self.pristine, path)
        if corrupt:
            _corrupt(path)
        when = time.time() - age_s
        os.utime(path, (when, when))
        return path

    def _pre_migration_backups(self) -> List[Path]:
        return sorted(self.backup_dir.glob("*.pre_migration.bak"))

    @staticmethod
    def _initialize_tolerant(store: SQLiteStore) -> Optional[BaseException]:
        """initialize() peut lever sur une DB corrompue non restauree : on capture."""
        try:
            store.initialize()
        except BaseException as exc:  # noqa: BLE001 — on veut TOUTES les issues
            return exc
        return None

    # ---- preuve F29 ----

    def test_restore_ignore_le_backup_corrompu_et_prend_le_sain(self) -> None:
        """ROUGE avant : restore_failed sur le backup corrompu, le sain jamais tente."""
        healthy = self._add_backup("20260101-000000-000000", corrupt=False, age_s=3600)
        corrupt_backup = self._add_backup("20260202-000000-000000", corrupt=True, age_s=10)
        _corrupt(self.db_path)

        # Le decor est bien celui qu'on croit (verifie sans le code de prod)
        self.assertEqual(_raw_integrity(healthy), "ok")
        self.assertNotEqual(_raw_integrity(corrupt_backup), "ok")
        self.assertNotEqual(_raw_integrity(self.db_path), "ok")

        store = SQLiteStore(self.db_path)
        raised = self._initialize_tolerant(store)

        self.assertIsNone(raised, f"initialize() ne doit plus lever apres restore reussi: {raised!r}")
        self.assertEqual(store.integrity_status, "ok")
        event = store.integrity_event or {}
        self.assertEqual(event.get("status"), "restored")
        self.assertEqual(
            Path(str(event.get("backup_used"))).name,
            healthy.name,
            "le backup SAIN plus ancien doit avoir ete utilise, pas le corrompu plus recent",
        )
        self.assertEqual(_raw_integrity(self.db_path), "ok")

    def test_db_corrompue_jamais_backuppee(self) -> None:
        """ROUGE avant : +1 backup de la DB corrompue a chaque boot (evince les sains)."""
        self._add_backup("20260202-000000-000000", corrupt=True, age_s=10)
        _corrupt(self.db_path)
        before = len(self._pre_migration_backups())
        self.assertEqual(before, 1)

        store = SQLiteStore(self.db_path)
        self._initialize_tolerant(store)

        self.assertNotEqual(store.integrity_status, "ok")
        self.assertEqual(
            len(self._pre_migration_backups()),
            before,
            "une DB dont l'integrity_check echoue ne doit JAMAIS etre backuppee",
        )

    def test_boots_repetes_nevincent_aucun_backup_existant(self) -> None:
        """Mecanisme de la perte definitive : la rotation ne doit plus evincer.

        Fenetre de rotation pleine (DEFAULT_MAX_BACKUPS=5) + DB irrecuperable.
        Avant le fix, chaque boot poussait une copie de la DB CORROMPUE en tete
        et la rotation supprimait le plus ancien — au 4e boot le backup le plus
        ancien (celui qui aurait pu etre le seul sain) avait disparu.
        """
        for i in range(5):
            self._add_backup(f"2026020{i + 1}-000000-000000", corrupt=True, age_s=500 - i * 10)
        _corrupt(self.db_path)
        before = {p.name for p in self._pre_migration_backups()}
        self.assertEqual(len(before), 5)

        for _ in range(4):
            self._initialize_tolerant(SQLiteStore(self.db_path))

        self.assertEqual(
            {p.name for p in self._pre_migration_backups()},
            before,
            "des boots sur DB corrompue ont fait tourner la fenetre de backups",
        )

    # ---- non-regression (VERT des deux cotes de la mutation) ----

    def test_restore_depuis_lunique_backup_sain(self) -> None:
        healthy = self._add_backup("20260101-000000-000000", corrupt=False, age_s=60)
        _corrupt(self.db_path)

        store = SQLiteStore(self.db_path)
        raised = self._initialize_tolerant(store)

        self.assertIsNone(raised)
        self.assertEqual(store.integrity_status, "ok")
        event = store.integrity_event or {}
        self.assertEqual(event.get("status"), "restored")
        self.assertEqual(Path(str(event.get("backup_used"))).name, healthy.name)

    def test_corrupt_no_backup_contrat_inchange(self) -> None:
        _corrupt(self.db_path)

        store = SQLiteStore(self.db_path)
        self._initialize_tolerant(store)

        event = store.integrity_event or {}
        self.assertEqual(event.get("status"), "corrupt_no_backup")
        self.assertIsNone(event.get("backup_used"))

    def test_db_saine_boot_normal_inchange(self) -> None:
        store = SQLiteStore(self.db_path)
        raised = self._initialize_tolerant(store)

        self.assertIsNone(raised)
        self.assertEqual(store.integrity_status, "ok")
        self.assertIsNone(store.integrity_event)
        # Nuance N28 : un boot nominal (schema deja a jour) ne pousse plus de
        # backup — c'est ce qui evincait les backups riches par rotation.
        self.assertEqual(self._pre_migration_backups(), [])

    def test_db_saine_avec_migration_en_attente_backuppe(self) -> None:
        """Contrepartie de `test_db_saine_boot_normal_inchange` (nuance N28).

        Des qu'une migration est reellement en attente — l'etat d'une base
        apres une mise a jour de l'application — le backup pre_migration doit
        revenir : c'est le filet de `_restore_from_pre_migration_backup`.
        """
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            current = int(conn.execute("PRAGMA user_version").fetchone()[0])
            conn.execute(f"PRAGMA user_version = {max(0, current - 1)}")
            conn.commit()

        store = SQLiteStore(self.db_path)
        self.assertIsNone(self._initialize_tolerant(store))
        self.assertGreaterEqual(len(self._pre_migration_backups()), 1)


class DbAutoRestorePreScreenTests(unittest.TestCase):
    """REVUE R1 du correctif F29 — le pre-ecran de selection des backups.

    La revue adversaire a montre deux trous :
    - `PRAGMA integrity_check` ne distingue PAS une base VIDE d'une base saine :
      un fichier de 0 octet est un SQLite valide qui repond "ok". Or `backup_db`
      en laissait justement un dans backups/ quand la source etait corrompue ->
      l'auto-restore ecrasait la bibliotheque par une base VIDE en annoncant
      "Base de donnees restauree automatiquement".
    - AUCUN test n'exercait le pre-ecran (le neutraliser laissait les 6 tests
      verts) : seule l'iteration etait couverte.
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_f29r1_"))
        self.db_path = self._tmp / "cinesort.sqlite"
        SQLiteStore(self.db_path).initialize()
        self._seed_marker(self.db_path)
        self.pristine = self._tmp / "pristine.sqlite"
        shutil.copy2(self.db_path, self.pristine)
        self.backup_dir = self._tmp / "backups"
        self.backup_dir.mkdir(exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ---- helpers (sqlite3 pur : valides des deux cotes d'une mutation) ----

    @staticmethod
    def _seed_marker(path: Path) -> None:
        """Canari : une table applicative dont la survie prouve que la
        bibliotheque n'a pas ete remplacee par une base vide."""
        with closing(sqlite3.connect(str(path))) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS marker(x TEXT)")
            conn.execute("DELETE FROM marker")
            conn.execute("INSERT INTO marker VALUES ('MA_BIBLIOTHEQUE')")
            conn.commit()

    @staticmethod
    def _read_marker(path: Path) -> Optional[str]:
        try:
            with closing(sqlite3.connect(str(path))) as conn:
                row = conn.execute("SELECT x FROM marker").fetchone()
                return str(row[0]) if row else None
        except sqlite3.Error:
            return None

    def _add_healthy_backup(self, stamp: str, age_s: float, *, trigger: str = "pre_migration") -> Path:
        path = self.backup_dir / f"cinesort.{stamp}Z.{trigger}.bak"
        shutil.copy2(self.pristine, path)
        when = time.time() - age_s
        os.utime(path, (when, when))
        return path

    def _add_empty_backup(self, stamp: str, age_s: float, *, trigger: str = "pre_migration") -> Path:
        """Le .bak de 0 octet exactement tel que backup_db en laissait un."""
        path = self.backup_dir / f"cinesort.{stamp}Z.{trigger}.bak"
        path.write_bytes(b"")
        when = time.time() - age_s
        os.utime(path, (when, when))
        return path

    def _add_corrupt_backup(self, stamp: str, age_s: float, *, trigger: str = "post_apply") -> Path:
        path = self.backup_dir / f"cinesort.{stamp}Z.{trigger}.bak"
        shutil.copy2(self.pristine, path)
        _corrupt(path)
        when = time.time() - age_s
        os.utime(path, (when, when))
        return path

    def _guard_files(self) -> List[Path]:
        """Garde-fous {target}.before_restore.*.bak : leur presence PROUVE
        qu'un restore_backup a reellement ecrit sur la DB principale."""
        return sorted(self._tmp.glob("*before_restore*.bak"))

    @staticmethod
    def _boot(store: SQLiteStore) -> None:
        try:
            store.initialize()
        except BaseException:  # noqa: BLE001 — une DB corrompue peut faire lever
            pass

    # ---- preuve du pre-ecran ----

    def test_backup_vide_0_octet_ecarte_au_profit_du_backup_sain(self) -> None:
        """ROUGE sans pre-ecran : le .bak de 0 octet passe integrity_check "ok",
        il est restaure, l'event dit "restored" et la bibliotheque a disparu."""
        healthy = self._add_healthy_backup("20260101-000000-000000", age_s=3600)
        empty = self._add_empty_backup("20260202-000000-000000", age_s=10)
        _corrupt(self.db_path)

        # Le decor est bien celui qu'on croit, verifie SANS le code de prod :
        # un fichier de 0 octet est un SQLite valide qui repond "ok".
        self.assertEqual(empty.stat().st_size, 0)
        self.assertEqual(_raw_integrity(empty), "ok")
        self.assertEqual(_raw_integrity(healthy), "ok")

        store = SQLiteStore(self.db_path)
        self._boot(store)

        event = store.integrity_event or {}
        self.assertEqual(event.get("status"), "restored")
        self.assertEqual(
            Path(str(event.get("backup_used"))).name,
            healthy.name,
            "le backup de 0 octet a ete prefere au backup SAIN plus ancien",
        )
        self.assertEqual(
            self._read_marker(self.db_path),
            "MA_BIBLIOTHEQUE",
            "la bibliotheque a ete remplacee par une base VIDE",
        )

    def test_pre_ecran_necrase_jamais_la_db_avec_un_backup_inexploitable(self) -> None:
        """ROUGE sans pre-ecran : la DB est ecrasee par le backup corrompu
        (garde-fou before_restore cree) avant que l'integrity post ne le voie."""
        corrupt_backup = self._add_corrupt_backup("20260202-000000-000000", age_s=10)
        _corrupt(self.db_path)
        self.assertNotEqual(_raw_integrity(corrupt_backup), "ok")
        self.assertEqual(self._guard_files(), [])

        store = SQLiteStore(self.db_path)
        self._boot(store)

        self.assertEqual(
            self._guard_files(),
            [],
            "un restore a eu lieu depuis un backup deja connu comme corrompu",
        )
        event = store.integrity_event or {}
        self.assertEqual(event.get("status"), "restore_failed")
        self.assertIsNone(
            event.get("backup_used"),
            "backup_used doit designer un backup REELLEMENT restaure (None si aucun)",
        )
        self.assertEqual(event.get("backups_rejected"), 1)

    def test_backup_now_refuse_de_backupper_une_db_corrompue(self) -> None:
        """ROUGE sans la garde : backup_now (post_apply, appele apres CHAQUE
        apply reel) fabrique le candidat n°1 du prochain auto-restore."""
        _corrupt(self.db_path)
        store = SQLiteStore(self.db_path)
        self._boot(store)
        self.assertNotEqual(store.integrity_status, "ok")
        before = {p.name for p in self.backup_dir.glob("*.bak")}

        result = store.backup_now(trigger="post_apply")

        self.assertIsNone(result)
        self.assertEqual({p.name for p in self.backup_dir.glob("*.bak")}, before)

    def test_backup_echoue_sans_laisser_de_fichier_vide(self) -> None:
        """ROUGE sans le nettoyage : sqlite3.connect(dst) cree le .bak AVANT que
        src_conn.backup() ne leve -> un .bak de 0 octet reste dans backups/."""
        _corrupt(self.db_path)
        # On zeroe l'en-tete : `backup()` leve "file is not a database".
        with open(self.db_path, "r+b") as fh:
            fh.seek(0)
            fh.write(b"\x00" * 100)

        result = backup_db_with_rotation(self.db_path, self.backup_dir, trigger="pre_migration")

        self.assertIsNone(result)
        self.assertEqual(
            sorted(p.name for p in self.backup_dir.glob("*.bak")),
            [],
            "un .bak de 0 octet subsiste : il sera restaure au prochain boot",
        )

    # ---- non-regression (VERT des deux cotes de la mutation) ----

    def test_backup_sain_toujours_accepte(self) -> None:
        """Le pre-ecran ne doit pas devenir un refus systematique."""
        healthy = self._add_healthy_backup("20260101-000000-000000", age_s=60)
        _corrupt(self.db_path)

        store = SQLiteStore(self.db_path)
        self._boot(store)

        event = store.integrity_event or {}
        self.assertEqual(event.get("status"), "restored")
        self.assertEqual(Path(str(event.get("backup_used"))).name, healthy.name)
        self.assertEqual(self._read_marker(self.db_path), "MA_BIBLIOTHEQUE")

    def test_backup_now_inchange_sur_db_saine(self) -> None:
        """La garde ne doit pas bloquer le backup post_apply nominal."""
        store = SQLiteStore(self.db_path)
        store.initialize()

        result = store.backup_now(trigger="post_apply")

        self.assertIsNotNone(result)
        self.assertIn("post_apply", Path(str(result)).name)


if __name__ == "__main__":
    unittest.main()
