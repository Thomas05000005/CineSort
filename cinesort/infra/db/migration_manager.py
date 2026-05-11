from __future__ import annotations

import logging
from contextlib import closing
import re
import sqlite3
from pathlib import Path
from typing import List, Tuple

from .connection import connect_sqlite

logger = logging.getLogger(__name__)


_MIGRATION_FILE_RE = re.compile(r"^(?P<version>\d+)_.*\.sql$")

_IDEMPOTENT_ERROR_FRAGMENTS = (
    "duplicate column name",
    "already exists",
)


def _is_idempotent_error(exc: sqlite3.OperationalError) -> bool:
    msg = str(exc).lower()
    return any(fragment in msg for fragment in _IDEMPOTENT_ERROR_FRAGMENTS)


def _split_sql_statements(sql: str) -> List[str]:
    """
    Decoupe un script SQL en instructions individuelles (split sur `;`).
    Ignore les commentaires `-- ...` et les instructions vides.
    Filtre les `PRAGMA user_version = X` qui sont gerees separement par le manager.

    NB: cette fonction ne supporte PAS les triggers `CREATE TRIGGER ... BEGIN ... END;`
    qui contiennent plusieurs `;` — aucune migration n'en utilise actuellement.
    """
    out: List[str] = []
    for raw in sql.split(";"):
        # Retirer les commentaires ligne a ligne
        lines = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                continue
            lines.append(line)
        stmt = "\n".join(lines).strip()
        if not stmt:
            continue
        # PRAGMA user_version est gere explicitement par apply() — ne pas double-executer
        if stmt.upper().startswith("PRAGMA USER_VERSION"):
            continue
        out.append(stmt)
    return out


class MigrationManager:
    """
    Applies SQL migrations in ascending order based on numeric file prefix.
    """

    def __init__(self, db_path: Path, migrations_dir: Path, *, busy_timeout_ms: int = 5000):
        self.db_path = Path(db_path)
        self.migrations_dir = Path(migrations_dir)
        self.busy_timeout_ms = int(max(1, busy_timeout_ms))

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(str(self.db_path), busy_timeout_ms=self.busy_timeout_ms)

    def _list_migrations(self) -> List[Tuple[int, Path]]:
        if not self.migrations_dir.exists():
            return []

        out: List[Tuple[int, Path]] = []
        for p in self.migrations_dir.glob("*.sql"):
            m = _MIGRATION_FILE_RE.match(p.name)
            if not m:
                continue
            out.append((int(m.group("version")), p))
        out.sort(key=lambda t: t[0])
        return out

    def list_migrations(self) -> List[Tuple[int, Path]]:
        return self._list_migrations()

    def latest_version(self) -> int:
        migrations = self._list_migrations()
        if not migrations:
            return 0
        return int(migrations[-1][0])

    def build_bootstrap_script(self) -> Tuple[str, int]:
        migrations = self._list_migrations()
        if not migrations:
            return "", 0

        chunks: List[str] = []
        for _version, path in migrations:
            sql = path.read_text(encoding="utf-8").strip()
            if sql:
                chunks.append(sql)
        script = "\n\n".join(chunks).strip()
        if script:
            script += "\n"
        return script, int(migrations[-1][0])

    def apply(self) -> int:
        """
        Applies pending migrations and returns final schema version.
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        migrations = self._list_migrations()

        with closing(self._connect()) as conn:
            cur = conn.execute("PRAGMA user_version")
            row = cur.fetchone()
            current_version = int(row[0]) if row else 0

            pending = [(v, p) for v, p in migrations if v > current_version]
            if pending:
                logger.info("db: %d migrations disponibles, schema actuel v%d", len(pending), current_version)

            for version, path in pending:
                try:
                    sql = path.read_text(encoding="utf-8")
                    # M2 : executescript fait un COMMIT implicite par statement — dangereux.
                    # On execute chaque statement dans une transaction explicite pour pouvoir rollback.
                    statements = _split_sql_statements(sql)
                    conn.execute("BEGIN")
                    try:
                        for idx, stmt in enumerate(statements):
                            sp_name = f"mig_{int(version)}_{idx}"
                            conn.execute(f"SAVEPOINT {sp_name}")
                            try:
                                conn.execute(stmt)
                                conn.execute(f"RELEASE SAVEPOINT {sp_name}")
                            except sqlite3.OperationalError as stmt_exc:
                                # H-1 audit 20260428 : ALTER TABLE ADD COLUMN n'est pas
                                # IF NOT EXISTS-able avant SQLite 3.35. Si la colonne existe
                                # deja (DB clonee, restauree, ou migration partiellement
                                # appliquee a la main), on tolere et on continue plutot que
                                # de bloquer l'app. Meme logique pour CREATE TABLE/INDEX.
                                if _is_idempotent_error(stmt_exc):
                                    conn.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                                    conn.execute(f"RELEASE SAVEPOINT {sp_name}")
                                    logger.warning(
                                        "db: migration %s — instruction %d ignoree (idempotence): %s",
                                        path.name,
                                        idx,
                                        stmt_exc,
                                    )
                                    continue
                                raise
                        conn.execute(f"PRAGMA user_version = {int(version)}")
                        conn.commit()
                    except sqlite3.DatabaseError:
                        conn.rollback()
                        raise
                    # DB3 audit : tracer dans schema_migrations si la table existe
                    # (elle est creee par la migration 012 elle-meme). INSERT OR IGNORE
                    # pour que ce soit idempotent si la migration est rejouee.
                    self._record_migration(conn, version, path.name)
                    current_version = version
                    logger.info("db: migration %s appliquee -> v%d", path.name, version)
                except (OSError, PermissionError, TypeError, ValueError, sqlite3.DatabaseError) as exc:
                    logger.error("db: echec migration %s: %s", path.name, exc)
                    raise

            return current_version

    @staticmethod
    def _record_migration(conn: sqlite3.Connection, version: int, name: str) -> None:
        """Enregistre la migration dans schema_migrations si la table existe.

        La table est creee par la migration 012 ; pour les migrations <= 11
        appliquees en retro, l'INSERT est silencieusement ignore si la table
        n'existe pas encore.
        """
        try:
            # Recuperer la version app depuis le fichier VERSION si possible
            app_version = ""
            try:
                from pathlib import Path as _P

                # Le repo root est 3 niveaux au-dessus de ce fichier (cinesort/infra/db)
                version_file = _P(__file__).resolve().parents[3] / "VERSION"
                if version_file.is_file():
                    app_version = version_file.read_text(encoding="utf-8").strip()
            except (OSError, PermissionError):
                app_version = ""
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, name, app_version) VALUES (?, ?, ?)",
                (int(version), str(name), app_version),
            )
            conn.commit()
        except sqlite3.DatabaseError:
            # Table absente (migrations anterieures a 012) : silence.
            pass

    def apply_migrations(self) -> int:
        """
        Compatibility alias used by higher-level stores.
        """
        return self.apply()
