from __future__ import annotations

from contextlib import closing, contextmanager, suppress
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional

logger = logging.getLogger(__name__)

from .backup import DEFAULT_MAX_BACKUPS, backup_db_with_rotation, list_backups, restore_backup
from .connection import connect_sqlite
from .migration_manager import MigrationManager, _split_sql_statements
from ._run_mixin import _RunMixin
from ._quality_mixin import _QualityMixin
from ._apply_mixin import _ApplyMixin
from ._perceptual_mixin import _PerceptualMixin

DEFAULT_DB_FILENAME = "cinesort.sqlite"
REQUIRED_SCHEMA_TABLES = (
    "runs",
    "errors",
    "probe_cache",
    "quality_profiles",
    "quality_reports",
    "anomalies",
    "apply_batches",
    "apply_operations",
    "apply_pending_moves",
    "incremental_file_hashes",
    "incremental_scan_cache",
    "perceptual_reports",
)
SCHEMA_GROUPS: Dict[str, tuple[str, ...]] = {
    "runs": ("runs",),
    "probe_cache": ("probe_cache",),
    "quality": ("quality_profiles", "quality_reports"),
    "anomalies": ("anomalies",),
    "apply_journal": ("apply_batches", "apply_operations"),
    # CR-1 audit QA 20260429 : journal write-ahead pour atomicite shutil.move.
    "apply_pending": ("apply_pending_moves",),
    "incremental": ("incremental_file_hashes", "incremental_scan_cache"),
    "perceptual": ("perceptual_reports",),
    # P4.1 : table calibration feedback utilisateur (migration 014).
    "user_feedback": ("user_quality_feedback",),
}


def db_path_for_state_dir(state_dir: Path) -> Path:
    return Path(state_dir) / "db" / DEFAULT_DB_FILENAME


class _StoreBase:
    """
    SQLite persistence base: connection management, schema lifecycle, and shared helpers.
    Threading rule: never share a sqlite3 connection between threads.
    Each method opens its own short-lived connection.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        migrations_dir: Optional[Path] = None,
        busy_timeout_ms: int = 5000,
        debug_logger: Optional[Callable[[str], None]] = None,
    ):
        self.db_path = Path(db_path)
        self.busy_timeout_ms = int(max(1, busy_timeout_ms))
        self._debug_logger = debug_logger
        # V1-09 audit ID-Y-001 : flag rempli par initialize(). "unknown" tant
        # que initialize() n'a pas tourne, "ok" sinon, ou message d'erreur.
        self._integrity_status: str = "unknown"
        # V2-11 audit QA 20260504 : evenement structure de l'integrity check
        # consomme par le runtime_support pour publier une notification UI
        # persistante au prochain boot si une corruption a ete detectee.
        # Forme : {"status": "ok"|"restored"|"restore_failed"|"corrupt_no_backup",
        #          "raw": str, "backup_used": Optional[str], "ts": float}
        self._integrity_event: Optional[Dict[str, Any]] = None

        default_migrations_dir = Path(__file__).resolve().parent / "migrations"
        self.migrations_dir = Path(migrations_dir) if migrations_dir else default_migrations_dir
        self.migrations = MigrationManager(
            db_path=self.db_path,
            migrations_dir=self.migrations_dir,
            busy_timeout_ms=self.busy_timeout_ms,
        )

    def _debug(self, message: str) -> None:
        if not self._debug_logger:
            return
        with suppress(OSError, TypeError, ValueError):
            self._debug_logger(message)

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(str(self.db_path), busy_timeout_ms=self.busy_timeout_ms)

    @contextmanager
    def _managed_conn(self) -> Iterator[sqlite3.Connection]:
        with closing(self._connect()) as conn, conn:
            yield conn

    def _bootstrap_schema_latest(self) -> int:
        """
        Fallback bootstrap built directly from the ordered migration files.
        This keeps migrations as the single source of truth for schema shape.

        Cf issue #33 : on n'utilise plus executescript() (qui fait un COMMIT
        implicite par statement et ne permet aucun rollback en cas d'erreur
        au milieu du schema). A la place, on decoupe en statements
        individuels et on les execute dans une transaction explicite
        BEGIN/COMMIT — meme pattern que migration_manager.apply_migrations().
        SQLite supporte le rollback DDL (contrairement a MySQL), donc
        le schema bootstrap devient "tout ou rien".
        """
        script, version = self.migrations.build_bootstrap_script()
        if not script or version <= 0:
            raise RuntimeError("Aucune migration SQL disponible pour initialiser le schema SQLite.")

        statements = _split_sql_statements(script)
        with self._managed_conn() as conn:
            conn.execute("BEGIN")
            try:
                for stmt in statements:
                    conn.execute(stmt)
                conn.execute(f"PRAGMA user_version = {int(version)}")
                conn.commit()
            except sqlite3.DatabaseError:
                conn.rollback()
                raise
        return int(version)

    def _prepare_db_directory(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _apply_schema_migrations(self) -> int:
        return int(self.migrations.apply_migrations() or 0)

    def _missing_tables(self, table_names: tuple[str, ...] | list[str]) -> set[str]:
        wanted = {str(table_name) for table_name in table_names if str(table_name)}
        if not wanted:
            return set()
        return wanted - self._existing_tables(tuple(wanted))

    def _missing_required_tables(self) -> set[str]:
        return self._missing_tables(REQUIRED_SCHEMA_TABLES)

    def _ensure_required_schema(self, version: int) -> int:
        missing_after_migrations = self._missing_required_tables()
        if not missing_after_migrations:
            return int(version)

        self._debug(
            "SQLite schema incomplete after migrations; retrying ordered bootstrap fallback "
            f"for missing tables: {', '.join(sorted(missing_after_migrations))}"
        )
        version = max(int(version), self._bootstrap_schema_latest())

        missing_after_bootstrap = self._missing_required_tables()
        if missing_after_bootstrap:
            missing = ", ".join(sorted(missing_after_bootstrap))
            raise RuntimeError(f"Schema SQLite incomplet apres migrations et bootstrap; tables manquantes: {missing}")
        return int(version)

    def initialize(self) -> int:
        """
        Real initialization flow:
        1. create the DB directory if needed
        2. V1-09 (audit ID-Y-001) : PRAGMA integrity_check sur la DB existante
           AVANT toute operation destructive (backup/migration). Stocke le
           resultat dans self._integrity_status pour exposition UI ulterieure.
        3. V2-11 (audit QA 20260504) : si l'integrity_check echoue ET qu'un
           backup recent existe, tente un restore automatique. L'evenement
           est stocke dans self._integrity_event pour publication par le
           runtime_support en notification UI persistante.
        4. CR-2 (audit QA 20260429) : backup la DB avant migrations si elle
           existe deja (pas un fresh install). Le backup est rotated pour
           garder DEFAULT_MAX_BACKUPS plus recents.
        5. apply ordered SQL migrations
        6. verify the required schema is complete
        7. if not, retry once using the bootstrap built from those same migrations
        """
        self._prepare_db_directory()
        self._integrity_status = self._check_integrity()
        # V2-11 : auto-restore si corruption detectee et backup disponible.
        if self._integrity_status != "ok" and self._integrity_status != "unknown":
            self._attempt_auto_restore()
        self._backup_before_migrations()
        # Cf issue #80 : si une migration leve, restaurer la DB depuis le
        # backup pre_migration cree juste au-dessus. Empeche de laisser la DB
        # dans un etat partial (ex : ALTER TABLE applique mais CREATE INDEX
        # plante au milieu).
        try:
            version = self._apply_schema_migrations()
        except (OSError, sqlite3.DatabaseError, RuntimeError) as exc:
            restored = self._restore_from_pre_migration_backup()
            if restored is not None:
                logger.error(
                    "Migration ratee (%s). DB restauree depuis %s. L'app doit redemarrer.",
                    exc,
                    restored,
                )
                self._integrity_event = {
                    "status": "migration_rolled_back",
                    "raw": str(exc),
                    "backup_used": str(restored),
                    "ts": time.time(),
                }
                raise RuntimeError(
                    f"Migration SQLite echouee ({exc}). DB restauree depuis backup pre_migration."
                ) from exc
            # Pas de backup pre_migration disponible → on remonte tel quel
            logger.error("Migration ratee (%s) — pas de backup pre_migration pour restore.", exc)
            raise
        version = self._ensure_required_schema(version)
        self._debug(f"SQLite initialized, schema version = {version}")
        return version

    @property
    def integrity_status(self) -> str:
        """Statut PRAGMA integrity_check apres initialize().

        Valeurs possibles :
        - "ok" : DB saine (ou fresh install sans fichier prealable).
        - "unknown" : initialize() pas encore appele.
        - autre : message brut de PRAGMA integrity_check ou "error: <exc>"
          si la connexion elle-meme a echoue.

        Consomme par la couche UI (mission V3 polish ulterieure) pour afficher
        un warning a l'utilisateur l'invitant a restaurer un backup.
        """
        return self._integrity_status

    @property
    def integrity_event(self) -> Optional[Dict[str, Any]]:
        """V2-11 : evenement structure de l'integrity check (peut etre None).

        Forme : {
            "status": "ok" | "restored" | "restore_failed" | "corrupt_no_backup",
            "raw": str,                # message brut de PRAGMA integrity_check
            "backup_used": Optional[str],  # chemin du backup restaure (si applicable)
            "ts": float,               # timestamp de la detection
        }
        Consomme par runtime_support pour publier une notification UI persistante.
        Reste None si l'integrity_check n'a pas detecte de probleme.
        """
        return self._integrity_event

    def _check_integrity(self) -> str:
        """V1-09 audit ID-Y-001 : execute PRAGMA integrity_check sur la DB.

        Retourne "ok" si la DB est saine, le message d'erreur sinon.
        Si la DB n'existe pas encore (fresh install), retourne "ok" car il
        n'y a rien a corrompre.
        Logue en ERROR si le statut n'est pas "ok" (visible operateur).
        """
        if not self.db_path.is_file():
            return "ok"
        try:
            with closing(self._connect()) as conn:
                row = conn.execute("PRAGMA integrity_check").fetchone()
                status = str(row[0]) if row else "unknown"
        except sqlite3.DatabaseError as exc:
            logger.error(
                "DB integrity check raised: %s. Path: %s. Consider restoring from backup.",
                exc,
                self.db_path,
            )
            return f"error: {exc}"

        if status != "ok":
            # V2-11 : log en ERROR (et plus seulement WARNING) pour signaler
            # une corruption silencieuse cote operateur. L'auto-restore est
            # tente juste apres dans initialize().
            logger.error(
                "DB integrity check FAILED: %s. Path: %s. Auto-restore from backup will be attempted.",
                status,
                self.db_path,
            )
        return status

    def _attempt_auto_restore(self) -> None:
        """V2-11 audit QA 20260504 : tente un restore auto depuis le backup
        le plus recent quand l'integrity_check a echoue.

        Trois issues possibles, toutes encodees dans self._integrity_event :
        - "restored"        : backup restaure + integrity_check post = ok.
        - "restore_failed"  : restore tente mais integrity_check post != ok
                              (ou exception pendant le restore).
        - "corrupt_no_backup" : pas de backup disponible, l'app continue en
                                mode degrade (l'utilisateur sera prevenu).

        L'evenement sera consomme par runtime_support au prochain boot pour
        publier une notification UI persistante. La methode ne leve jamais :
        en cas d'erreur fatale on log et on laisse l'app continuer (mieux
        un boot warning qu'une app cassee).
        """
        raw_status = self._integrity_status
        ts = time.time()
        try:
            backups = list_backups(self._backup_dir(), stem_filter=self.db_path.stem)
        except (OSError, PermissionError) as exc:
            logger.warning("auto_restore: list_backups echoue (%s)", exc)
            backups = []

        if not backups:
            logger.error(
                "DB corrompue ET aucun backup disponible. Path: %s. "
                "L'application continue mais des donnees peuvent etre perdues.",
                self.db_path,
            )
            self._integrity_event = {
                "status": "corrupt_no_backup",
                "raw": raw_status,
                "backup_used": None,
                "ts": ts,
            }
            return

        most_recent = backups[0]
        logger.warning(
            "DB corrompue, tentative auto-restore depuis %s",
            most_recent,
        )
        try:
            restore_backup(most_recent, self.db_path)
        except (sqlite3.Error, OSError, FileNotFoundError) as exc:
            logger.error(
                "auto_restore: restore depuis %s a echoue: %s",
                most_recent,
                exc,
            )
            self._integrity_event = {
                "status": "restore_failed",
                "raw": raw_status,
                "backup_used": str(most_recent),
                "ts": ts,
            }
            return

        # Re-check integrity apres restore
        post_status = self._check_integrity()
        if post_status == "ok":
            logger.info(
                "auto_restore: succes depuis %s. DB restauree.",
                most_recent,
            )
            self._integrity_status = "ok"
            self._integrity_event = {
                "status": "restored",
                "raw": raw_status,
                "backup_used": str(most_recent),
                "ts": ts,
            }
        else:
            logger.error(
                "auto_restore: restore effectue mais integrity_check post = %s",
                post_status,
            )
            self._integrity_status = post_status
            self._integrity_event = {
                "status": "restore_failed",
                "raw": raw_status,
                "backup_used": str(most_recent),
                "ts": ts,
            }

    def _backup_dir(self) -> Path:
        """Dossier ou sont stockes les backups : <db_dir>/backups/."""
        return self.db_path.parent / "backups"

    def _restore_from_pre_migration_backup(self) -> Optional[Path]:
        """Cf issue #80 : restaure la DB depuis le backup pre_migration le plus
        recent, cree juste avant la serie de migrations en cours.

        Retourne le chemin du backup utilise, ou None si aucun backup
        pre_migration n'est disponible (cas tests sans backup ou fresh install).
        """
        try:
            all_backups = list_backups(self._backup_dir(), stem_filter=self.db_path.stem)
        except (OSError, PermissionError) as exc:
            logger.warning("rollback_migration: list_backups echoue (%s)", exc)
            return None
        # Filtrer pour ne garder que les backups pre_migration (les plus pertinents
        # ici — un post_apply backup pourrait dater d'avant les nouvelles tables
        # introduites par les migrations precedentes).
        pre_migration = [p for p in all_backups if ".pre_migration." in p.name]
        if not pre_migration:
            return None
        most_recent = pre_migration[0]  # list_backups trie plus recent d'abord
        try:
            restore_backup(most_recent, self.db_path)
        except (sqlite3.Error, OSError, FileNotFoundError) as exc:
            logger.error("rollback_migration: restore depuis %s echoue: %s", most_recent, exc)
            return None
        return most_recent

    def _backup_before_migrations(self) -> None:
        """CR-2 : si la DB existe deja, faire un backup avant d'appliquer
        les migrations. Tolerant : un echec de backup ne bloque pas le
        boot (mieux DB sans backup que app cassee).
        """
        if not self.db_path.is_file():
            return  # fresh install, rien a backupper
        try:
            backup_db_with_rotation(
                self.db_path,
                self._backup_dir(),
                trigger="pre_migration",
                max_count=DEFAULT_MAX_BACKUPS,
            )
        except Exception as exc:
            logger.warning("backup_before_migrations: ignore (%s)", exc)

    def backup_now(self, *, trigger: str = "manual", max_count: int = DEFAULT_MAX_BACKUPS) -> Optional[Path]:
        """API publique : declenche un backup immediat. Retourne le chemin
        ou None si la DB n'existe pas encore. Utilise par apply_support
        apres apply reel et par UI Settings.
        """
        return backup_db_with_rotation(
            self.db_path,
            self._backup_dir(),
            trigger=str(trigger or "manual"),
            max_count=int(max_count) if max_count > 0 else DEFAULT_MAX_BACKUPS,
        )

    def list_db_backups(self) -> list:
        """Retourne la liste des backups existants (paths absolus, plus recent d'abord)."""
        return list_backups(self._backup_dir(), stem_filter=self.db_path.stem)

    def close(self) -> None:
        """V2-10 audit QA 20260504 : declenche PRAGMA optimize au shutdown.

        SQLite recommande d'executer PRAGMA optimize regulierement (typiquement
        a la fermeture) pour mettre a jour les statistiques de l'optimiseur de
        requetes (ANALYZE incremental) et reduire la fragmentation. Particulierement
        utile pour les bases utilisees plusieurs mois sans interruption.

        Best effort : toute erreur SQLite est loggee mais ignoree pour ne PAS
        bloquer le shutdown de l'application. Si la DB n'existe pas (cas tests
        ou shutdown precoce), la methode est silencieuse.

        L'API publique etant idempotente (chaque methode du store ouvre sa propre
        connexion courte-vie), close() peut etre appele plusieurs fois sans risque.
        """
        if not self.db_path.is_file():
            return
        try:
            with closing(self._connect()) as conn:
                conn.execute("PRAGMA optimize")
                logger.debug("PRAGMA optimize executed at shutdown for %s", self.db_path)
        except sqlite3.Error as exc:
            # Best effort : ne PAS bloquer le shutdown
            logger.warning("PRAGMA optimize at shutdown failed (ignored): %s", exc)

    def _existing_tables(self, table_names: tuple[str, ...] | list[str]) -> set[str]:
        self._prepare_db_directory()
        wanted = {str(table_name) for table_name in table_names if str(table_name)}
        if not wanted:
            return set()
        with self._managed_conn() as conn:
            cur = conn.execute(
                f"SELECT name FROM sqlite_master WHERE type='table' AND name IN ({','.join('?' for _ in wanted)})",
                tuple(sorted(wanted)),
            )
            return {str(row[0]) for row in cur.fetchall() if row and row[0]}

    def _has_required_tables(self, table_names: tuple[str, ...] | list[str]) -> bool:
        return not self._missing_tables(table_names)

    def _schema_satisfies(
        self, table_names: tuple[str, ...] | list[str], *, min_user_version: Optional[int] = None
    ) -> bool:
        if min_user_version is not None and self.get_user_version() < int(min_user_version):
            return False
        return self._has_required_tables(table_names)

    def _ensure_tables(self, *table_names: str, min_user_version: Optional[int] = None) -> None:
        try:
            if self._schema_satisfies(list(table_names), min_user_version=min_user_version):
                return
        except sqlite3.Error:
            pass
        self.initialize()

    def _schema_group_tables(self, group_name: str) -> tuple[str, ...]:
        table_names = SCHEMA_GROUPS.get(str(group_name), ())
        if not table_names:
            raise KeyError(f"Groupe de schema inconnu: {group_name}")
        return table_names

    def _ensure_schema_group(self, group_name: str, *, min_user_version: Optional[int] = None) -> None:
        self._ensure_tables(*self._schema_group_tables(group_name), min_user_version=min_user_version)

    def _with_schema_group(
        self,
        group_name: str,
        operation: Callable[[sqlite3.Connection], Any],
        *,
        min_user_version: Optional[int] = None,
    ) -> Any:
        self._ensure_schema_group(group_name, min_user_version=min_user_version)
        with self._managed_conn() as conn:
            return operation(conn)

    def _is_missing_table_error(self, exc: sqlite3.Error, table_name: str) -> bool:
        return f"no such table: {str(table_name or '').lower()}" in str(exc).lower()

    def _decode_row_json(
        self,
        row: sqlite3.Row,
        field_name: str,
        *,
        default: Any,
        expected_type: type,
    ) -> Any:
        raw = row[field_name]
        try:
            parsed = json.loads(str(raw or "null"))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("corrupt JSON in column %s: %s (raw=%r)", field_name, exc, raw)
            return default
        if not isinstance(parsed, expected_type):
            logger.warning("unexpected type in column %s: expected %s, got %s", field_name, expected_type, type(parsed))
            return default
        return parsed

    def get_user_version(self) -> int:
        with self._managed_conn() as conn:
            cur = conn.execute("PRAGMA user_version")
            row = cur.fetchone()
            return int(row[0]) if row else 0


class SQLiteStore(
    _StoreBase,
    _RunMixin,
    # Mixins retires (issue #85 phase B8) : Repositories accessibles via store.X
    # - _ProbeMixin (B8a) -> store.probe
    # - _AnomalyMixin (B8b) -> store.anomaly
    # - _ScanMixin (B8c) -> store.scan
    # Reste a migrer en sessions futures (run/apply/quality/perceptual ont 60-120 callers chacun).
    _QualityMixin,
    _ApplyMixin,
    _PerceptualMixin,
):
    """
    SQLite persistence for v7 foundations.

    Cf issue #85 (phase pilote) : composition de 7 Repository ajoutee en
    parallele des mixins historiques. Les Repository (accessibles via
    `store.apply`, `store.quality`, etc.) delegent au meme store sous-jacent
    et permettent d'instancier l'acces DB par bounded context.

    Les mixins (heritage MRO) restent en place tant que les call sites n'ont
    pas tous migre vers store.{repo}.{method}(). Phase D future supprimera
    les mixins une fois la migration complete.

    Pattern d'usage recommande pour les nouveaux call sites :
        store.apply.insert_batch(...)      # au lieu de store.insert_apply_batch
        store.quality.get_report(...)      # au lieu de store.get_quality_report

    L'API publique historique (`store.insert_apply_batch`, etc.) reste
    100% backward-compat via l'heritage des mixins.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Cf issue #85 : 7 Repository en composition (transitoire avec mixins).
        # Import lazy pour eviter cycle (repositories importent les mixins).
        from cinesort.infra.db.repositories import (
            AnomalyRepository,
            ApplyRepository,
            PerceptualRepository,
            ProbeRepository,
            QualityRepository,
            RunRepository,
            ScanRepository,
        )

        self.apply = ApplyRepository(self)
        self.anomaly = AnomalyRepository(self)
        self.perceptual = PerceptualRepository(self)
        self.probe = ProbeRepository(self)
        self.quality = QualityRepository(self)
        self.run = RunRepository(self)
        self.scan = ScanRepository(self)
