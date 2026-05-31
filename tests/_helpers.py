"""Helpers partages pour la suite de tests CineSort.

Issue #86 PR 2 : module utilitaire commun, utilisable par unittest et pytest.

Le `conftest.py` racine fournit deja les fixtures pytest (`free_port`,
`create_movie_file`, `tmp_state_dir`, `wait_run_terminal`). Ce module
expose les MEMES helpers sous forme de fonctions importables, pour les
tests `unittest.TestCase` qui ne peuvent pas consommer les fixtures pytest
naturellement.

Usage :

    from tests._helpers import find_free_port

    class MyTests(unittest.TestCase):
        def setUp(self):
            self.port = find_free_port()
"""

from __future__ import annotations

import socket
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any, Tuple


def find_free_port() -> int:
    """Retourne un port TCP libre sur 127.0.0.1.

    Remplace les 14 definitions duplicatees de `_find_free_port` dans
    les fichiers de test (issue #86).

    NB : il y a une race condition entre l'obtention du port et son
    utilisation. Acceptable pour les serveurs longs-running du test
    (REST server, etc.), risque negligeable.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def create_file(path: Path, size: int = 2048) -> None:
    """Cree un fichier video minimal de taille `size` bytes.

    Remplace les 8+ definitions duplicatees de `_create_file` dans les
    fichiers de test (issue #86). Cree les parents manquants automatiquement.

    Defaut size=2048 bytes (> MIN_VIDEO_BYTES dans la plupart des configs).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def wait_run_done(api: Any, run_id: str, timeout_s: float = 10.0) -> dict:
    """Poll `api.run.get_status(run_id)` jusqu'a etat terminal (done=True).

    Remplace les 10+ definitions duplicatees de `_wait_done` /
    `_wait_terminal` dans les fichiers de test (issue #86).

    - Retourne le dernier status (dict avec done=True)
    - Raise AssertionError si timeout (compatible avec unittest self.fail
      qui wrappe AssertionError)
    - Poll 30 ms (compromis entre charge CPU et reactivite)

    Si le caller ignore le return (pattern `self._wait_done(api, run_id)`
    sans assignation), c'est OK — la valeur est retournee mais ignoree.
    """
    deadline = time.monotonic() + float(timeout_s)
    last: dict = {}
    while time.monotonic() < deadline:
        last = api.run.get_status(run_id, 0) or {}
        if last.get("done"):
            return last
        time.sleep(0.03)
    raise AssertionError(f"Timeout {timeout_s}s en attendant run_id={run_id}. Dernier status={last}")


# ---------------------------------------------------------------------------
# Vague M — Sprint 0 (item M-00) : fixture migration DB pre-existante
# ---------------------------------------------------------------------------


def _project_migrations_dir() -> Path:
    """Retourne le dossier `cinesort/infra/db/migrations/` du repo courant.

    Resolu relativement a ce fichier (`tests/_helpers.py`), donc le helper
    n'a pas besoin d'un environnement particulier (CI, dev local, worktree).
    """
    here = Path(__file__).resolve()
    repo_root = here.parents[1]
    return repo_root / "cinesort" / "infra" / "db" / "migrations"


def existing_db_fixture(
    target_schema_version: int,
    *,
    migrations_dir: Path | None = None,
    tmp_path: Path | None = None,
) -> Tuple[Path, sqlite3.Connection]:
    """Cree une SQLite temporaire, applique migrations 001..N <= target_schema_version.

    Memoire `feedback_sqlite_migration_test_existing_db` : toute migration
    SQL doit etre testee sur une DB PRE-EXISTANTE (ancien schema) et pas
    uniquement sur fresh DB. Cette fixture mutualise la creation d'une DB
    "ancienne" arretee a une version donnee, qu'un test peut ensuite faire
    avancer (ex: appliquer la migration N+1 nouvelle pour P-04, P-05, etc.).

    Reutilise par : P-04 (undo extend 005), P-05 (quarantine 030),
    O-06 (timeline 028), R-04 (HDR structured), et tout futur test SQL.

    Implementation : reutilise `cinesort.infra.db.migration_manager.MigrationManager`
    pour la coherence — le helper n'a pas son propre parseur SQL. On copie
    les migrations 001..N dans un dossier temporaire et on laisse le manager
    les appliquer. PRAGMA `user_version` correctement positionne a la fin.

    Args:
        target_schema_version: version maximale appliquee (incluse).
            Si 0 ou negatif, DB vierge (aucune migration).
        migrations_dir: dossier source des migrations (defaut : repo CineSort).
        tmp_path: dossier ou creer le fichier .sqlite. Defaut : tempfile.mkdtemp.

    Returns:
        (db_path, connection) : le caller doit fermer la connexion et nettoyer
        le tempdir (ou laisser le GC le faire).

    Raises:
        FileNotFoundError: si le dossier migrations n'existe pas.
        sqlite3.DatabaseError: si une migration echoue.
    """
    src_migrations = (migrations_dir or _project_migrations_dir()).resolve()
    if not src_migrations.is_dir():
        raise FileNotFoundError(
            f"Migrations dir introuvable: {src_migrations}. "
            "Specifier migrations_dir explicitement."
        )

    tmp_root = Path(tmp_path) if tmp_path is not None else Path(tempfile.mkdtemp(prefix="cinesort_existing_db_"))
    tmp_root.mkdir(parents=True, exist_ok=True)

    db_path = tmp_root / "store.sqlite3"

    # Si target <= 0 : DB vierge, on retourne juste une connection vide.
    if target_schema_version <= 0:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA user_version = 0")
        return db_path, conn

    # On copie les migrations <= target_schema_version dans un sous-dossier
    # temporaire, puis on lance MigrationManager dessus. Cette indirection
    # garantit qu'on ne fait jamais avancer la DB au-dela de la version cible
    # (par construction le manager ne voit que les fichiers presents).
    staged = tmp_root / "migrations"
    staged.mkdir(parents=True, exist_ok=True)

    import re as _re

    pattern = _re.compile(r"^(?P<version>\d+)_.*\.sql$")
    copied = 0
    for src in sorted(src_migrations.glob("*.sql")):
        m = pattern.match(src.name)
        if not m:
            continue
        version = int(m.group("version"))
        if version > target_schema_version:
            continue
        dst = staged / src.name
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        copied += 1

    if copied == 0:
        # Aucune migration <= target -> DB vierge avec user_version forcee
        conn = sqlite3.connect(str(db_path))
        conn.execute(f"PRAGMA user_version = {int(target_schema_version)}")
        return db_path, conn

    # Import tardif : evite de payer le cout d'import du backend SQLite
    # complet quand les tests n'utilisent pas cette fixture.
    from cinesort.infra.db.migration_manager import MigrationManager

    manager = MigrationManager(db_path=db_path, migrations_dir=staged)
    final_version = manager.apply()

    if final_version != target_schema_version:
        # Sanity check : si la derniere migration <= target n'est pas
        # exactement target, on log mais on n'echoue pas (cas legitime :
        # target=27 demande la derniere migration appliquee = 27 OK).
        # Echec uniquement si on a depasse, ce qui ne devrait pas arriver
        # grace au filtre ci-dessus.
        if final_version > target_schema_version:
            raise AssertionError(
                f"existing_db_fixture: schema cible {target_schema_version} mais "
                f"DB est a {final_version} apres apply"
            )

    conn = sqlite3.connect(str(db_path))
    return db_path, conn
