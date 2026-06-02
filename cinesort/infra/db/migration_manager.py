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

    Fix audit 2026-05-25 (v1.5.3) Vague H+ : on RETIRE d'abord les commentaires
    `-- ...` ligne-par-ligne AVANT de split sur `;`. L'ancienne implementation
    splitait d'abord sur `;` puis retirait les commentaires — donc un `;` au
    milieu d'un commentaire produisait deux fragments dont le second commencait
    par du SQL non-commente et plantait avec `syntax error`. Bug latent sur les
    futures migrations qui auraient un `;` dans un commentaire descriptif.

    NB: cette fonction ne supporte PAS les triggers `CREATE TRIGGER ... BEGIN ... END;`
    qui contiennent plusieurs `;` — aucune migration n'en utilise actuellement.
    NB: ne gere pas non plus les `--` a l'interieur d'une string SQL ('--'),
    mais aucune migration n'en utilise non plus.

    Fix BUG-015 (hotfix1) : refus explicite des commentaires bloc `/* ... */`
    et detection des `;` dans literals string SQL ('...') qui pourraient
    produire un split incorrect. Si sqlparse est disponible on l'utilise,
    sinon on refuse explicitement les SQL qui contiennent `/*` ou des literals
    string avec `;` plutot que de continuer silencieusement et produire un
    SQL malforme.

    Fix BUG-015 (hotfix2) : sqlparse n'est PAS une dependance declaree dans
    pyproject.toml. L'ancien code levait ValueError en chaine d'ImportError
    quand `/*` apparaissait dans le SQL, ce qui bloquait le demarrage de
    l'app au runtime. On capture ImportError et on tombe en fallback sur
    le stripper de commentaires bloc + split ligne-par-ligne, avec un
    WARNING log pour signaler que la couverture sqlparse n'est pas active.
    Aucune migration actuelle n'utilise `/*`, mais on garde un stripper
    minimal pour ne pas planter si une migration future en introduit une.
    """
    # BUG-015 (hotfix2) : sqlparse n'est PAS dans pyproject.toml.
    # On tente l'import ; si absent on tombe en fallback safe au lieu
    # de raise ValueError qui empechait l'app de demarrer.
    if "/*" in sql:
        try:
            import sqlparse  # type: ignore[import-not-found]
        except ImportError:
            logger.warning(
                "_split_sql_statements: commentaire bloc /* ... */ detecte dans "
                "le SQL mais sqlparse n'est pas installe. Fallback : strip naif "
                "des blocs /* ... */ puis split simple. Pour une couverture "
                "complete (literals contenant /*, blocs imbriques) installer "
                "sqlparse ou retirer les commentaires bloc de la migration."
            )
            # Strip naif des blocs /* ... */ non-imbriques.
            # Ne gere PAS les /* a l'interieur d'un literal string SQL,
            # mais aucune migration actuelle n'en utilise.
            sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
            # Continuer avec le fallback simple ci-dessous.
        else:
            out: List[str] = []
            for stmt in sqlparse.split(sql):
                cleaned_stmt = sqlparse.format(
                    stmt, strip_comments=True
                ).strip().rstrip(";").strip()
                if not cleaned_stmt:
                    continue
                if cleaned_stmt.upper().startswith("PRAGMA USER_VERSION"):
                    continue
                out.append(cleaned_stmt)
            return out

    cleaned_lines: List[str] = []
    for line in sql.splitlines():
        idx = line.find("--")
        if idx >= 0:
            line = line[:idx]
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)

    # BUG-015 : detection des `;` dans literals string SQL.
    # On parse caractere-par-caractere pour ignorer les `;` a l'interieur
    # de '...' (SQLite utilise ' pour string literals, '' pour escape).
    out: List[str] = []
    buf: List[str] = []
    in_string = False
    i = 0
    n = len(cleaned)
    while i < n:
        ch = cleaned[i]
        if ch == "'":
            buf.append(ch)
            if in_string and i + 1 < n and cleaned[i + 1] == "'":
                # Escape '' a l'interieur d'une string
                buf.append(cleaned[i + 1])
                i += 2
                continue
            in_string = not in_string
            i += 1
            continue
        if ch == ";" and not in_string:
            stmt = "".join(buf).strip()
            if stmt and not stmt.upper().startswith("PRAGMA USER_VERSION"):
                out.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    # Dernier fragment sans `;` terminal
    tail = "".join(buf).strip()
    if tail and not tail.upper().startswith("PRAGMA USER_VERSION"):
        out.append(tail)
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

                    # V8-01 : certaines migrations doivent recreer une table parent
                    # sans declencher de CASCADE sur les enfants (ex: migration 023
                    # qui recree `runs` pour etendre la CHECK status). Le marker
                    # `-- @manager: disable_fk` permet de desactiver les FK pour
                    # cette migration uniquement. PRAGMA foreign_keys ne fonctionne
                    # PAS dans une transaction, donc on le pose avant BEGIN et on
                    # le restaure apres COMMIT.
                    # BUG-014 (hotfix1) : matcher STRICT ligne commencant par
                    # `-- @manager: disable_fk` apres trim, pour eviter qu'un
                    # commentaire descriptif (ex: "ne PAS utiliser
                    # @manager: disable_fk ici") n'active le PRAGMA a tort.
                    needs_fk_disable = any(
                        line.strip().startswith("-- @manager: disable_fk")
                        for line in sql.splitlines()
                    )
                    if needs_fk_disable:
                        conn.execute("PRAGMA foreign_keys = OFF")

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
                    finally:
                        if needs_fk_disable:
                            conn.execute("PRAGMA foreign_keys = ON")
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
                # Le repo root est 3 niveaux au-dessus de ce fichier (cinesort/infra/db)
                # M-03 (refactor #84) : Path deja importe au top-level
                version_file = Path(__file__).resolve().parents[3] / "VERSION"
                if version_file.is_file():
                    app_version = version_file.read_text(encoding="utf-8").strip()
            except (OSError, PermissionError):
                app_version = ""
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, name, app_version) VALUES (?, ?, ?)",
                (int(version), str(name), app_version),
            )
            conn.commit()
        except sqlite3.Error as exc:
            # BUG-013 (hotfix1) : capter sqlite3.Error (parent de OperationalError,
            # DatabaseError, IntegrityError, etc.) au lieu du seul DatabaseError, et
            # logger en warning au lieu d'un pass silencieux. La migration principale
            # a deja ete committee (user_version a jour) ; on accepte que le tracking
            # dans schema_migrations puisse echouer (table absente avant migration 012,
            # DB lock transitoire, etc.) mais on trace pour diagnostiquer plus tard.
            logger.warning(
                "db: tracking schema_migrations a echoue pour v%d (%s): %s",
                int(version),
                name,
                exc,
            )

    def apply_migrations(self) -> int:
        """
        Compatibility alias used by higher-level stores.
        """
        return self.apply()
