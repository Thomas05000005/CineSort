"""#669 + #468 — restauration ATOMIQUE de la base principale.

Les deux defauts vivaient dans la meme fonction, `infra/db/backup.py:restore_backup` :

- **#669** : la restauration ecrivait DIRECTEMENT dans la base vive
  (`src_conn.backup(dst_conn)` avec `dst_conn` ouverte sur la cible), et l'echec
  du garde-fou `before_restore.bak` n'etait qu'un `warning` suivi du restore
  destructif. Un `.bak` dont l'en-tete a survecu mais dont des pages internes
  sont perdues se copie SANS lever : la bibliotheque etait remplacee par une
  image malformee et la fonction retournait un succes.
- **#468** : les sidecars `-wal`/`-shm` de la cible n'etaient pas purges. Ils
  appartiennent a la GENERATION du fichier principal ; en survivre a son
  remplacement revient a rejouer les pages d'une autre base par-dessus celle
  qu'on vient de restaurer.

Mesures qui ont motive ces tests (code d'avant correctif) :

    restore_backup(bak_partiel, live)  -> aucune exception
    live : (4000 lignes, quick_check ok) -> "database disk image is malformed"

    SQLiteStore.initialize() sur migration ratee, avec un .bak pre_migration
    partiel : base vive SAINE remplacee par l'image malformee, et l'utilisateur
    recoit "DB restauree depuis backup pre_migration".

    restore_backup avec un `-wal` orphelin de page_size differente
    -> OperationalError("attempt to write a readonly database") ET contenu de
    la base vive remplace par celui de la generation etrangere.

Chaque test nomme la garde qu'il protege (cf. la matrice de mutation en tete de
la PR) : mutee seule, cette garde fait rougir le ou les tests cites.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from typing import List, Optional
from unittest import mock

from cinesort.infra.db import backup as backup_module
from cinesort.infra.db.backup import backup_db, list_backups, restore_backup
from cinesort.infra.db.sqlite_store import SQLiteStore

PAGE = 4096
_REAL_MIGRATIONS = Path(backup_module.__file__).resolve().parent / "migrations"


# --------------------------------------------------------------------------- #
# Helpers — sqlite3 pur, donc valides des DEUX cotes d'une mutation du module   #
# teste (ils ne peuvent pas devenir complaisants avec le code de production).   #
# --------------------------------------------------------------------------- #


# Un PRAGMA n'accepte pas de parametre lie : on passe donc par des instructions
# ECRITES EN DUR plutot que par une interpolation (rien d'interpole ne part vers
# SQLite, et l'analyse statique n'a pas a deviner que la valeur est sure).
_PAGE_SIZE_SQL = {4096: "PRAGMA page_size=4096", 16384: "PRAGMA page_size=16384"}
_JOURNAL_SQL = {True: "PRAGMA journal_mode=WAL", False: "PRAGMA journal_mode=DELETE"}
# Recul de `user_version` utilise pour rendre une migration reellement en
# attente (cf `_rendre_une_migration_en_attente`). Valeur ecrite en dur pour la
# meme raison que les deux dictionnaires ci-dessus, et volontairement basse :
# elle reste sous la derniere migration meme si le schema avance.
_RECUL_VERSION = 20
_RECUL_SQL = "PRAGMA user_version = 20"


def _seed(path: Path, marker: str, rows: int, *, wal: bool = False, page_size: Optional[int] = None) -> None:
    with closing(sqlite3.connect(str(path))) as conn:
        if page_size:
            conn.execute(_PAGE_SIZE_SQL[page_size])
        conn.execute(_JOURNAL_SQL[wal])
        conn.execute("CREATE TABLE films (id INTEGER PRIMARY KEY, titre TEXT)")
        conn.executemany(
            "INSERT INTO films (titre) VALUES (?)",
            [(f"{marker}-{index}",) for index in range(rows)],
        )
        conn.commit()


def _rows(path: Path) -> Optional[tuple]:
    """(nombre de lignes, plus petit titre) ou None si la base est illisible."""
    try:
        with closing(sqlite3.connect(str(path))) as conn:
            return conn.execute("SELECT COUNT(*), MIN(titre) FROM films").fetchone()
    except sqlite3.Error:
        return None


def _quick_check(path: Path) -> str:
    try:
        with closing(sqlite3.connect(str(path))) as conn:
            row = conn.execute("PRAGMA quick_check").fetchone()
            return str(row[0]) if row else "unknown"
    except sqlite3.Error as exc:
        return f"error: {exc}"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _blank_pages(path: Path, first: int, last: int) -> None:
    """Perd les pages [first, last[ d'une base SQLite en gardant sa taille.

    C'est la forme exacte du `.bak` PARTIEL que le nettoyage AUDIT F29 ne
    couvre pas : le fichier n'est pas vide, `list_backups` le liste toujours et
    il reste selectionnable comme source de restauration.
    """
    raw = bytearray(path.read_bytes())
    raw[first * PAGE : last * PAGE] = b"\x00" * ((last - first) * PAGE)
    path.write_bytes(bytes(raw))


# Liste ECRITE EN DUR : la lire depuis `backup_module.SQLITE_SIDECAR_SUFFIXES`
# rendrait ces tests complices du module teste — retirer un suffixe de la
# constante retirerait AUSSI l'assertion correspondante, et la mutation
# resterait verte (mesure faite : elle l'etait).
_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def _sidecars(db_path: Path) -> List[str]:
    return sorted(
        db_path.name + suffix for suffix in _SIDECAR_SUFFIXES if db_path.with_name(db_path.name + suffix).exists()
    )


class _RestoreCaseMixin(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_restore_atomique_"))
        self.live = self._tmp / "cinesort.sqlite"
        self.bak = self._tmp / "cinesort.20260101-000000-000000Z.manual.bak"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _tmp_leftovers(self) -> List[str]:
        return sorted(p.name for p in self._tmp.iterdir() if p.name.endswith(".tmp"))


# --------------------------------------------------------------------------- #
# GARDE 1 : publication atomique  +  GARDE 2 : validation avant publication     #
# --------------------------------------------------------------------------- #


class RestoreDepuisUnBackupPartielTests(_RestoreCaseMixin):
    def setUp(self) -> None:
        super().setUp()
        _seed(self.live, "BIBLIOTHEQUE", 4000)
        _seed(self.bak, "BACKUP", 4000)
        _blank_pages(self.bak, 5, 9)

    def test_le_bak_partiel_est_bien_le_piege_attendu(self) -> None:
        """Decor verifie SANS le code de production : le `.bak` n'est ni vide ni
        detectable a la taille — il ouvre, mais son image est malformee."""
        self.assertGreater(self.bak.stat().st_size, 0)
        self.assertNotEqual(_quick_check(self.bak), "ok")
        self.assertEqual(list_backups(self._tmp), [self.bak], "le .bak partiel reste un candidat de restauration")

    def test_restore_partiel_laisse_la_base_vive_octet_pour_octet(self) -> None:
        """GARDE 1 + GARDE 2 — le coeur de #669.

        Avant correctif : aucune exception, et la bibliotheque (4000 lignes,
        quick_check ok) devenait "database disk image is malformed".
        """
        avant = _sha(self.live)

        with self.assertRaises(sqlite3.DatabaseError):
            restore_backup(self.bak, self.live)

        self.assertEqual(_sha(self.live), avant, "la base vive a ete modifiee par une restauration refusee")
        self.assertEqual(_quick_check(self.live), "ok")
        self.assertEqual(_rows(self.live), (4000, "BIBLIOTHEQUE-0"))

    def test_restore_refuse_ne_laisse_aucun_fichier_de_travail(self) -> None:
        """GARDE 5 — le `.tmp` abandonne serait un fichier mort a cote de la base."""
        with self.assertRaises(sqlite3.DatabaseError):
            restore_backup(self.bak, self.live)

        self.assertEqual(self._tmp_leftovers(), [])
        self.assertEqual(_sidecars(self.live), [])

    def test_restore_nominal_publie_bien_le_contenu_du_backup(self) -> None:
        """Contre-epreuve : la garde ne doit pas devenir un refus systematique."""
        sain = self._tmp / "cinesort.20260102-000000-000000Z.manual.bak"
        _seed(sain, "BACKUP", 30)

        self.assertEqual(restore_backup(sain, self.live), self.live)

        self.assertEqual(_rows(self.live), (30, "BACKUP-0"))
        self.assertEqual(_quick_check(self.live), "ok")
        self.assertEqual(self._tmp_leftovers(), [])


# --------------------------------------------------------------------------- #
# GARDE 3 : l'echec du garde-fou ARRETE le restore quand la cible est saine     #
# --------------------------------------------------------------------------- #


class GardeFouImpossibleTests(_RestoreCaseMixin):
    """Le garde-fou `before_restore.bak` echouait en silence (`warning`) et le
    restore destructif continuait — un disque plein faisait donc perdre la base
    principale SANS filet.

    La regle appliquee est verifiee positivement sur la cible (et non devinee
    depuis le type d'exception : un disque plein remonte en
    `sqlite3.OperationalError`, PAS en `OSError`).
    """

    DISQUE_PLEIN = sqlite3.OperationalError("database or disk is full")

    def _guards(self) -> List[Path]:
        return sorted(self._tmp.glob("*before_restore*.bak"))

    def test_cible_saine_non_sauvegardable_le_restore_est_refuse(self) -> None:
        """GARDE 3 — sens restrictif : mieux vaut ne pas restaurer que detruire
        sans filet une base encore recuperable."""
        _seed(self.live, "BIBLIOTHEQUE", 500)
        _seed(self.bak, "BACKUP", 30)
        avant = _sha(self.live)

        with mock.patch.object(backup_module, "backup_db", side_effect=self.DISQUE_PLEIN):
            with self.assertRaises(sqlite3.OperationalError):
                restore_backup(self.bak, self.live)

        self.assertEqual(_sha(self.live), avant, "la base vive a ete ecrasee alors qu'elle n'etait pas sauvegardable")
        self.assertEqual(_rows(self.live), (500, "BIBLIOTHEQUE-0"))
        self.assertEqual(self._guards(), [])
        self.assertEqual(self._tmp_leftovers(), [])

    def test_cible_inexploitable_non_sauvegardable_le_restore_a_lieu(self) -> None:
        """Contre-epreuve indispensable : le garde-fou echoue precisement quand
        la cible est ILLISIBLE, c'est-a-dire dans le cas ou l'auto-restore au
        boot est le plus utile. Refuser la aussi rendrait la reparation
        impossible."""
        _seed(self.live, "BIBLIOTHEQUE", 4000)
        _blank_pages(self.live, 5, 9)
        _seed(self.bak, "BACKUP", 30)
        self.assertNotEqual(_quick_check(self.live), "ok")

        with mock.patch.object(backup_module, "backup_db", side_effect=self.DISQUE_PLEIN):
            restore_backup(self.bak, self.live)

        self.assertEqual(_rows(self.live), (30, "BACKUP-0"))
        self.assertEqual(_quick_check(self.live), "ok")


# --------------------------------------------------------------------------- #
# GARDE 4 : purge des sidecars de la generation precedente (#468)               #
# --------------------------------------------------------------------------- #


class SidecarsOrphelinsTests(_RestoreCaseMixin):
    """Un `-wal` orphelin est celui d'une AUTRE generation : le fichier
    principal a ete remplace, pas lui.

    Avec la publication atomique, la cible n'est plus ouverte par
    `restore_backup` : le `-wal` n'est donc plus consomme au passage et
    SURVIVRAIT au remplacement — SQLite le rejouerait par-dessus l'image
    fraichement restauree au boot suivant. La purge n'est pas un confort, c'est
    la contrepartie obligatoire de la GARDE 1.
    """

    def _wal_etranger(self, *, page_size: int = PAGE) -> bytes:
        """`-wal` non checkpointe d'une base sans aucun rapport avec la cible."""
        source = self._tmp / "autre_generation.sqlite"
        conn = sqlite3.connect(str(source))
        try:
            conn.execute(_PAGE_SIZE_SQL[page_size])
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA wal_autocheckpoint=0")
            conn.execute("CREATE TABLE films (id INTEGER PRIMARY KEY, titre TEXT)")
            conn.executemany(
                "INSERT INTO films (titre) VALUES (?)",
                [(f"ETRANGERE-{index}",) for index in range(3000)],
            )
            conn.commit()
            frames = Path(str(source) + "-wal").read_bytes()
        finally:
            conn.close()
        source.unlink(missing_ok=True)
        Path(str(source) + "-wal").unlink(missing_ok=True)
        Path(str(source) + "-shm").unlink(missing_ok=True)
        self.assertGreater(len(frames), 0)
        return frames

    def test_sidecars_orphelins_de_la_cible_disparue_sont_tous_purges(self) -> None:
        """GARDE 4 — la forme ou la purge est SEULE a pouvoir agir.

        Le fichier principal a disparu (crash, suppression, copie partielle
        depuis une sauvegarde externe) mais ses sidecars sont restes. Comme il
        n'y a rien a sauvegarder, aucun garde-fou n'est pris et PERSONNE
        n'ouvre la cible : SQLite ne peut donc pas consommer ces sidecars au
        passage comme il le fait d'habitude. Sans purge explicite ils survivent
        au remplacement, et le `-wal` etranger est rejoue a la premiere
        ouverture — la base "restauree" contient alors la generation etrangere.
        """
        frames = self._wal_etranger()
        _seed(self.bak, "BACKUP", 30)
        Path(str(self.live) + "-wal").write_bytes(frames)
        Path(str(self.live) + "-shm").write_bytes(b"\x00" * 32768)
        Path(str(self.live) + "-journal").write_bytes(b"\xd9\xd5\x05\xf9\x20\xa1\x63\xd7" + b"\x00" * 500)
        self.assertFalse(self.live.exists())
        self.assertEqual(len(_sidecars(self.live)), 3)

        restore_backup(self.bak, self.live)

        self.assertEqual(_sidecars(self.live), [], "un sidecar de la generation precedente a survecu au restore")
        # Premiere ouverture APRES restore : c'est elle qui rejouerait le -wal.
        self.assertEqual(_rows(self.live), (30, "BACKUP-0"))
        self.assertEqual(_quick_check(self.live), "ok")

    def test_sidecars_orphelins_avec_cible_presente_ne_rejouent_pas(self) -> None:
        """Meme contrat par l'autre chemin : quand la cible existe, le garde-fou
        l'ouvre et SQLite consomme lui-meme une partie des sidecars. Le resultat
        observable doit etre identique — contenu du BACKUP, aucun sidecar."""
        frames = self._wal_etranger()
        _seed(self.live, "BIBLIOTHEQUE", 40)
        _seed(self.bak, "BACKUP", 30)
        Path(str(self.live) + "-wal").write_bytes(frames)
        Path(str(self.live) + "-shm").write_bytes(b"\x00" * 32768)

        restore_backup(self.bak, self.live)

        self.assertEqual(_sidecars(self.live), [])
        self.assertEqual(_rows(self.live), (30, "BACKUP-0"))
        self.assertEqual(_quick_check(self.live), "ok")

    def test_wal_orphelin_de_page_size_differente_nempeche_plus_le_restore(self) -> None:
        """GARDE 1 + GARDE 4 — avant correctif : `OperationalError("attempt to
        write a readonly database")`, restauration IMPOSSIBLE, et le contenu de
        la base vive remplace par celui de la generation etrangere."""
        frames = self._wal_etranger(page_size=16384)
        _seed(self.live, "BIBLIOTHEQUE", 40)
        _seed(self.bak, "BACKUP", 30)
        Path(str(self.live) + "-wal").write_bytes(frames)

        restore_backup(self.bak, self.live)

        self.assertEqual(_sidecars(self.live), [])
        self.assertEqual(_rows(self.live), (30, "BACKUP-0"))


# --------------------------------------------------------------------------- #
# GARDE 6 : le garde-fou ne s'ecrase plus lui-meme                              #
# --------------------------------------------------------------------------- #


class GardeFouUniqueTests(_RestoreCaseMixin):
    def test_deux_restores_dans_la_meme_tranche_de_temps_gardent_deux_filets(self) -> None:
        """GARDE 6 — `_format_backup_name` formate des microsecondes, mais le
        timer Windows a une granularite d'environ 15 ms : deux restores
        rapproches produisaient le meme nom, et le second garde-fou ECRASAIT le
        premier (l'etat pre-restore le plus ancien etait perdu).

        On fige le nom formate pour rendre la collision certaine plutot que
        dependante de la charge machine (patcher `time.time` la provoquerait
        aussi, mais en figeant l'horloge de tout le processus).
        """
        _seed(self.live, "BIBLIOTHEQUE", 40)
        _seed(self.bak, "BACKUP", 30)
        fige = "cinesort.20260101-000000-000000Z.before_restore.bak"

        with mock.patch.object(backup_module, "_format_backup_name", return_value=fige):
            restore_backup(self.bak, self.live)
            restore_backup(self.bak, self.live)

        guards = sorted(self._tmp.glob("*before_restore*.bak"))
        self.assertEqual(len(guards), 2, f"un garde-fou a ete ecrase par l'autre: {[p.name for p in guards]}")


# --------------------------------------------------------------------------- #
# GARDE 7 : backup_db publie sa destination en une fois (#669, probleme 2)      #
# --------------------------------------------------------------------------- #


_ENFANT = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from cinesort.infra.db.backup import backup_db
backup_db(Path(sys.argv[2]), Path(sys.argv[3]))
print("TERMINE")
"""


class BackupInterrompuTests(unittest.TestCase):
    """`backup_db` ouvrait `sqlite3.connect(dst)`, ce qui CREE la destination
    avant la moindre page copiee : un kill pendant la copie laissait un `.bak`
    PARTIEL dans backups/. Le nettoyage AUDIT F29 ne couvre que `st_size == 0`,
    donc ce fichier restait liste par `list_backups` et selectionnable comme
    source de restauration.
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_backup_kill_"))
        self.src = self._tmp / "cinesort.sqlite"
        self.bdir = self._tmp / "backups"
        self.bdir.mkdir()
        # Assez gros pour que la copie dure quelques dizaines de millisecondes.
        with closing(sqlite3.connect(str(self.src))) as conn:
            conn.execute("CREATE TABLE films (id INTEGER PRIMARY KEY, titre TEXT, jaquette BLOB)")
            conn.executemany(
                "INSERT INTO films (titre, jaquette) VALUES (?, ?)",
                [(f"FILM-{index}", bytes([index % 251]) * 8192) for index in range(700)],
            )
            conn.commit()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_un_kill_pendant_la_copie_ne_laisse_aucun_bak_partiel(self) -> None:
        """GARDE 7 — interruption reelle : le processus est TUE pendant la copie
        (aucun `finally`, aucun nettoyage applicatif ne tourne)."""
        dst = self.bdir / "cinesort.20260101-000000-000000Z.pre_migration.bak"
        repo_root = str(Path(backup_module.__file__).resolve().parents[3])
        proc = subprocess.Popen(
            [sys.executable, "-c", _ENFANT, repo_root, str(self.src), str(dst)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 60.0
            tue = False
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                # Le fichier destination (ou le fichier de travail) apparait des
                # l'ouverture de la connexion, donc bien AVANT la fin de la copie.
                if any(self.bdir.iterdir()):
                    proc.kill()
                    tue = True
                    break
                time.sleep(0.001)
            _, err = proc.communicate(timeout=60)
        finally:
            if proc.poll() is None:  # pragma: no cover — filet de securite
                proc.kill()
                proc.wait(timeout=10)
        self.assertTrue(
            tue,
            f"la copie n'a jamais commence, interruption non obtenue (rc={proc.returncode}): {err.decode(errors='replace')[-400:]}",
        )
        self.assertNotEqual(proc.returncode, 0, "le processus a termine sa copie, il n'a pas ete interrompu")

        restants = list_backups(self.bdir)
        self.assertEqual(
            [p.name for p in restants],
            [],
            "un .bak partiel survit a l'interruption et sera propose comme source de restauration",
        )

    def test_backup_nominal_publie_la_destination_et_ne_laisse_pas_de_tmp(self) -> None:
        """Contre-epreuve : la publication differee ne casse pas le cas normal."""
        dst = self.bdir / "cinesort.20260101-000000-000000Z.manual.bak"

        self.assertEqual(backup_db(self.src, dst), dst)

        self.assertEqual([p.name for p in list_backups(self.bdir)], [dst.name])
        self.assertEqual(sorted(p.name for p in self.bdir.iterdir()), [dst.name])
        self.assertEqual(_quick_check(dst), "ok")

    def test_un_backup_qui_echoue_nabime_pas_le_bak_deja_present(self) -> None:
        """Un backup rate ne doit jamais entamer un backup precedent SAIN."""
        dst = self.bdir / "cinesort.20260101-000000-000000Z.manual.bak"
        _seed(dst, "BACKUP_PRECEDENT_SAIN", 300)
        avant = _sha(dst)
        with open(self.src, "r+b") as handle:  # source illisible
            handle.seek(0)
            handle.write(b"\x00" * 100)

        with self.assertRaises(sqlite3.DatabaseError):
            backup_db(self.src, dst)

        self.assertEqual(_sha(dst), avant)
        self.assertEqual(sorted(p.name for p in self.bdir.iterdir()), [dst.name])


# --------------------------------------------------------------------------- #
# FACADE DE PRODUCTION — le chemin qui detruisait vraiment la base              #
# --------------------------------------------------------------------------- #


class RestoreParLaFacadeSQLiteStoreTests(unittest.TestCase):
    """`SQLiteStore.initialize()` restaure depuis le backup `pre_migration`
    quand une migration echoue (`_restore_from_pre_migration_backup`). Ce
    chemin-la, contrairement a l'auto-restore, n'a AUCUN pre-ecran de selection
    du backup : c'est par la que la base principale se faisait detruire.

    Mesure avant correctif : base vive SAINE (`quick_check` ok, marqueurs
    AVANT_BACKUP + APRES_BACKUP) remplacee par l'image malformee du `.bak`
    partiel, avec le message rassurant "DB restauree depuis backup
    pre_migration".
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_facade_restore_"))
        self.db_path = self._tmp / "db" / "cinesort.sqlite"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _marqueurs(self) -> Optional[List[str]]:
        try:
            with closing(sqlite3.connect(str(self.db_path))) as conn:
                return [str(row[0]) for row in conn.execute("SELECT v FROM films_marqueur ORDER BY v")]
        except sqlite3.Error:
            return None

    def _migrations_qui_echouent(self) -> Path:
        mig_dir = self._tmp / "migrations_ko"
        shutil.copytree(_REAL_MIGRATIONS, mig_dir)
        (mig_dir / "9999_migration_qui_echoue.sql").write_text("CREATE TABLE boom (;", encoding="utf-8")
        return mig_dir

    def _rendre_une_migration_en_attente(self) -> None:
        """Recule `user_version` pour que le prochain `initialize()` ait une
        migration REELLEMENT en attente, et pousse donc son `.pre_migration.bak`.

        Necessaire depuis la nuance N28 (ultra-audit 2026-08-03, sur `main`) :
        `_backup_before_migrations` ne pousse plus de backup a chaque boot mais
        uniquement quand le schema va bouger. Sans ce recul, un simple
        `initialize()` ne cree plus aucun backup et ce test perdait son decor
        (`IndexError` sur une liste vide) — c'est l'INSTRUMENT qui est perime,
        pas la regle verifiee. On passe par la condition que `main` teste
        elle-meme comme declencheur legitime du backup
        (`test_backup_still_created_when_a_migration_is_pending`), plutot que
        de fabriquer le `.bak` a la main hors du chemin de production.

        La verification qui suit interdit que ce decor redevienne muet : si le
        backup n'est pas cree, l'echec nomme la cause au lieu d'un `IndexError`.
        """
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            avant = int(conn.execute("PRAGMA user_version").fetchone()[0])
            conn.execute(_RECUL_SQL)
            conn.commit()
        self.assertGreater(avant, _RECUL_VERSION, "aucune migration ne serait en attente apres le recul")

    def test_migration_ratee_avec_backup_partiel_ne_detruit_pas_la_bibliotheque(self) -> None:
        SQLiteStore(self.db_path, busy_timeout_ms=5000).initialize()
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.execute("CREATE TABLE films_marqueur (v TEXT)")
            conn.execute("INSERT INTO films_marqueur VALUES ('AVANT_BACKUP')")
            conn.commit()

        self._rendre_une_migration_en_attente()
        store = SQLiteStore(self.db_path, busy_timeout_ms=5000)
        store.initialize()  # cree le backup pre_migration
        bak = [p for p in store.list_db_backups() if ".pre_migration." in p.name][0]

        # Le backup devient PARTIEL (pages perdues, taille inchangee, non vide)
        _blank_pages(bak, 3, 6)
        # ... et reste le pre_migration le plus recent malgre les boots suivants
        futur = time.time() + 86_400
        os.utime(bak, (futur, futur))
        self.assertNotEqual(_quick_check(bak), "ok")

        # La bibliotheque continue de vivre APRES ce backup
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.execute("INSERT INTO films_marqueur VALUES ('APRES_BACKUP')")
            conn.commit()
        self.assertEqual(_quick_check(self.db_path), "ok")

        store_ko = SQLiteStore(self.db_path, busy_timeout_ms=5000, migrations_dir=self._migrations_qui_echouent())
        with self.assertRaises(Exception) as ctx:
            store_ko.initialize()

        self.assertNotIn(
            "DB restauree depuis backup pre_migration",
            str(ctx.exception),
            "l'utilisateur est rassure alors que la base a ete remplacee par une image malformee",
        )
        self.assertEqual(_quick_check(self.db_path), "ok", "la base principale a ete detruite par le restore")
        self.assertEqual(self._marqueurs(), ["APRES_BACKUP", "AVANT_BACKUP"])

    def test_migration_ratee_avec_backup_sain_restaure_toujours(self) -> None:
        """Contre-epreuve : le rollback de migration doit continuer de marcher."""
        SQLiteStore(self.db_path, busy_timeout_ms=5000).initialize()
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.execute("CREATE TABLE films_marqueur (v TEXT)")
            conn.execute("INSERT INTO films_marqueur VALUES ('AVANT_BACKUP')")
            conn.commit()

        SQLiteStore(self.db_path, busy_timeout_ms=5000).initialize()  # backup pre_migration sain
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.execute("INSERT INTO films_marqueur VALUES ('APRES_BACKUP')")
            conn.commit()

        store_ko = SQLiteStore(self.db_path, busy_timeout_ms=5000, migrations_dir=self._migrations_qui_echouent())
        with self.assertRaises(RuntimeError) as ctx:
            store_ko.initialize()

        self.assertIn("DB restauree depuis backup pre_migration", str(ctx.exception))
        self.assertEqual(_quick_check(self.db_path), "ok")
        # Le backup pre_migration restaure est celui cree par CE boot, juste
        # avant la migration ratee : il porte donc les deux marqueurs.
        self.assertEqual(
            self._marqueurs(),
            ["APRES_BACKUP", "AVANT_BACKUP"],
            "le rollback n'a pas ramene l'etat d'avant la migration ratee",
        )
        self.assertEqual(_sidecars(self.db_path), [])


if __name__ == "__main__":
    unittest.main()
