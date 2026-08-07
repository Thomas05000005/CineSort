from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import closing, contextmanager, suppress
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

from .backup import DEFAULT_MAX_BACKUPS, backup_db_with_rotation, list_backups, restore_backup
from .connection import connect_sqlite
from .migration_manager import MigrationManager, _is_idempotent_error, _split_sql_statements
from .repositories import (
    AnomalyRepository,
    ApplyRepository,
    FilmModalRepository,
    PerceptualRepository,
    ProbeRepository,
    QualityRepository,
    RunRepository,
    ScanRepository,
)
from .repositories.decisions import DecisionsRepository
from .repositories.field_locks import FieldLocksRepository

DEFAULT_DB_FILENAME = "cinesort.sqlite"

# v1.3 SQLite cloud-sync warning : dossiers synchronises (OneDrive, Dropbox,
# Google Drive, iCloud, Box, pCloud, Mega) sont incompatibles avec SQLite WAL.
# Le moteur de sync peut copier le fichier .sqlite alors que des pages sont
# encore dans le -wal ou -shm, ce qui produit une corruption silencieuse
# (PRAGMA integrity_check FAILED au prochain boot). On detecte ces chemins
# au demarrage et on logue un WARNING explicite. Detection case-insensitive
# pour matcher OneDrive, OneDrive - Personal, OneDriveCommercial, etc.
_CLOUD_SYNC_MARKERS: tuple[str, ...] = (
    "OneDrive",
    "Dropbox",
    "GoogleDrive",
    "Google Drive",
    "iCloudDrive",
    "iCloud Drive",
    "Box",
    "pCloud",
    "Mega",
)


def _detect_cloud_sync_folder(db_path: Path) -> Optional[str]:
    """Retourne le nom du provider cloud detecte dans le chemin DB, ou None.

    Detection case-insensitive sur les segments du chemin pour eviter les
    faux positifs (e.g., un fichier nomme `box.sqlite` dans un dossier
    normal). On compare segment par segment au lieu de chercher la sous-chaine
    dans tout le chemin.
    """
    # Verif totale 2026-07 : l'ancien `marker.lower() in path_str` cherchait la
    # sous-chaine dans TOUT le chemin -> faux positifs (D:\xbox\ matchait "Box",
    # D:\mega games\ matchait "Mega"). On compare desormais segment par segment :
    # match EXACT du nom de dossier, SAUF la famille OneDrive qui s'accole des
    # suffixes sans separateur ("OneDrive - Personal", "OneDriveCommercial").
    try:
        segments = [p.lower() for p in Path(db_path).parts]
    except (TypeError, ValueError):
        return None
    markers_low = [(m, m.lower()) for m in _CLOUD_SYNC_MARKERS]
    for seg in segments:
        for marker, mlow in markers_low:
            if seg == mlow or (mlow.startswith("onedrive") and seg.startswith("onedrive")):
                return marker
    return None


# Fix audit 2026-05-26 (v1.5.6) Vague L (mig-2) : tables critiques verifiees
# apres migrations. Si manquantes, _ensure_required_schema rejoue le bootstrap
# ordonne (toutes les migrations en mode CREATE TABLE IF NOT EXISTS),
# independamment de PRAGMA user_version. C'est le filet de securite
# self-healing pour le bug ou une migration etait marquee appliquee mais
# n'avait pas cree ses tables (cas observe sur 023). Ajout des 3 tables de
# 023 (ignored_alerts, film_marked_for_deletion, film_tmdb_overrides) ici
# pour que la detection soit independante de uv.
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
    # R8-022 (F2-d) : incremental_row_cache (migration 008, scan incremental v2) etait
    # absente du filet self-heal -> si droppee/manquante, ni _ensure_required_schema ni
    # _with_schema_group('incremental') ne la recreaient -> Operationalable 'no such table'
    # au scan. 008 est IF NOT EXISTS + deja dans le bootstrap : on n'ajoute que la detection.
    "incremental_row_cache",
    "perceptual_reports",
    "duplicate_decisions",
    # Fix audit 2026-05-26 (v1.5.6) Vague L (mig-2) : tables 023 (Modal Film)
    # ajoutees ici pour detection self-healing independante de user_version.
    "ignored_alerts",
    "film_marked_for_deletion",
    "film_tmdb_overrides",
    # Fix BUG-002 (hotfix1) : tables des migrations 029/030/031 (Vague P).
    # Sans elles, _ensure_required_schema ne detectait pas leur absence et
    # le filet de securite self-healing ne se declenchait jamais pour les
    # features apply atomique / field locks / decisions tri-etat.
    "apply_batch_modes",
    "film_field_locks",
    "film_decisions_v2",
    # Nuance N27 (ultra-audit 2026-08-03) : `user_quality_feedback` (migration
    # 014) etait la SEULE table exposee par SCHEMA_GROUPS a manquer ici. Le
    # filet self-heal ne la recreait donc jamais : sur une base ou elle seule
    # manque, chaque envoi de feedback de score levait
    # `sqlite3.OperationalError: no such table` (que le `except (OSError, ...)`
    # appelant n'attrape PAS — sqlite3.Error n'herite pas de OSError) et
    # poussait au passage un `.pre_migration.bak` de plus.
    "user_quality_feedback",
)

# AUDIT F29 (revue R1) : socle minimal exige d'un backup pour etre un candidat
# de restore. `runs` est cree par la toute premiere migration
# (001_init_runs_errors.sql) : tout backup issu d'une DB reellement initialisee
# la porte. Son absence signe une base VIDE (ou etrangere), qu'il ne faut jamais
# ecrire par-dessus la bibliotheque de l'utilisateur.
_BACKUP_CORE_TABLES: tuple[str, ...] = ("runs",)
# Taille d'une page SQLite par defaut : en dessous, le fichier ne peut pas
# contenir de donnees (le cas nominal etant le .bak de 0 octet).
_MIN_USABLE_BACKUP_BYTES = 4096
# Nuance N23 (ultra-audit 2026-08-03) : prefixe du statut "je n'ai pas pu
# OUVRIR le fichier", a distinguer du prefixe historique "error: " qui, lui,
# signale une reponse du MOTEUR sur le contenu de la base (= corruption).
UNREADABLE_STATUS_PREFIX = "unreadable: "
# Nuance N26 : nombre maximal de violations de FK detaillees dans le log de
# diagnostic (une base durablement incoherente ne doit pas noyer le journal).
_FK_VIOLATIONS_LOG_CAP = 10
SCHEMA_GROUPS: Dict[str, tuple[str, ...]] = {
    "runs": ("runs",),
    "probe_cache": ("probe_cache",),
    "quality": ("quality_profiles", "quality_reports"),
    "anomalies": ("anomalies",),
    "apply_journal": ("apply_batches", "apply_operations"),
    # CR-1 audit QA 20260429 : journal write-ahead pour atomicite shutil.move.
    "apply_pending": ("apply_pending_moves",),
    "incremental": ("incremental_file_hashes", "incremental_scan_cache", "incremental_row_cache"),
    "perceptual": ("perceptual_reports",),
    # P4.1 : table calibration feedback utilisateur (migration 014).
    "user_feedback": ("user_quality_feedback",),
    # Spec 06 Modal Film (migration 023) : etat persistant des decisions
    # utilisateur sur le modal (alertes ignorees, marquages suppression,
    # overrides TMDb manuels).
    "film_modal_state": (
        "ignored_alerts",
        "film_marked_for_deletion",
        "film_tmdb_overrides",
    ),
    # Phase 4 doublons (migration 024, spec docs/internal/design/refonte_2026_05_17/screens/01-doublons.md).
    "duplicate_decisions": ("duplicate_decisions",),
    # Vague P / VP-A (migration 029) : apply atomique forward rollback (opt-in).
    "apply_atomic": ("apply_batch_modes",),
    # Vague P / VP-C (migration 030) : verrous champ-par-champ Jellyfin-style.
    "field_locks": ("film_field_locks",),
    # Vague P / VP-D (migration 031) : decisions tri-etat
    # (accepted/rejected/deferred). Backward compat ABSOLUE preservee via
    # helper `to_legacy_ok_bool` (cf cinesort/infra/db/repositories/decisions.py).
    "tri_etat_decisions": ("film_decisions_v2",),
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
        pragma_profile_name: Optional[str] = None,
    ):
        self.db_path = Path(db_path)
        self.busy_timeout_ms = int(max(1, busy_timeout_ms))
        self._debug_logger = debug_logger
        # VO-A backend : override explicite du profil PRAGMA (None = autodetect
        # via pragma_profile.detect_storage_type a chaque connexion).
        self.pragma_profile_name: Optional[str] = pragma_profile_name
        # V1-09 audit ID-Y-001 : flag rempli par initialize(). "unknown" tant
        # que initialize() n'a pas tourne, "ok" sinon, ou message d'erreur.
        self._integrity_status: str = "unknown"
        # V2-11 audit QA 20260504 : evenement structure de l'integrity check
        # consomme par le runtime_support pour publier une notification UI
        # persistante au prochain boot si une corruption a ete detectee.
        # Forme : {"status": "ok"|"restored"|"restore_failed"|"corrupt_no_backup",
        #          "raw": str, "backup_used": Optional[str], "ts": float}
        self._integrity_event: Optional[Dict[str, Any]] = None
        # Nuance N23 : True quand le dernier _check_integrity() n'a pas reussi a
        # OUVRIR le fichier, et n'a donc RIEN pu dire de son contenu.
        self._integrity_unreadable: bool = False
        # #986 : verdict d'integrite NON CONCLUANT (checkpoint WAL en echec).
        # Distinct de `_integrity_unreadable` : la base est lisible, c'est le
        # VERDICT qui ne fait pas autorite. Meme consequence — pas d'auto-restore.
        self._integrity_non_concluant: bool = False

        # Nuance N21 (ultra-audit 2026-08-03) : memo des verifications de schema
        # deja faites par CE store sur CE fichier. Sans lui, chaque appel de
        # repository refaisait la chaine _ensure_tables -> _schema_satisfies ->
        # _existing_tables, qui ouvre sa PROPRE connexion (plus une 3e via
        # get_user_version() des qu'un min_user_version est passe) AVANT la
        # connexion de travail de _with_schema_group : 2 a 3 connexions la ou
        # une seule est utile, sur des chemins boucles par film.
        # Cle = (tables triees, min_user_version) -> identite du fichier DB, de
        # sorte qu'un .sqlite supprime puis recree invalide le memo.
        self._verified_schema_keys: Dict[tuple, tuple] = {}

        # v1.3 SQLite cloud-sync warning : on detecte au plus tot (avant meme
        # toute connexion SQLite) si la DB est posee dans un dossier de
        # synchronisation cloud, et on logue un WARNING explicite. La detection
        # est best-effort et ne bloque PAS le demarrage : l'utilisateur peut
        # choisir d'ignorer (auquel cas integrity_check finira par signaler
        # une corruption lors d'un futur boot).
        self._cloud_sync_provider: Optional[str] = _detect_cloud_sync_folder(self.db_path)
        if self._cloud_sync_provider:
            logger.warning(
                "DB SQLite detectee dans un dossier de synchronisation cloud (%s). "
                "Chemin: %s. Risque de corruption silencieuse: le moteur de sync "
                "peut copier le fichier .sqlite alors que des pages sont encore "
                "dans le -wal ou -shm. Recommandation forte: deplacer la DB hors "
                "du dossier %s, ou exclure les fichiers .sqlite/.sqlite-wal/"
                ".sqlite-shm de la synchronisation. Voir docs/TROUBLESHOOTING.md "
                "section 'Stockage DB'.",
                self._cloud_sync_provider,
                self.db_path,
                self._cloud_sync_provider,
            )

        default_migrations_dir = Path(__file__).resolve().parent / "migrations"
        self.migrations_dir = Path(migrations_dir) if migrations_dir else default_migrations_dir
        self.migrations = MigrationManager(
            db_path=self.db_path,
            migrations_dir=self.migrations_dir,
            busy_timeout_ms=self.busy_timeout_ms,
            # Fix PRAGMA-05 : propager l'override explicite du profil PRAGMA
            # afin que les connexions ouvertes pendant apply_migrations()
            # utilisent le meme profil que celui du store (e.g., 'nas_smb'
            # pour forcer synchronous=FULL pendant les ALTER TABLE /
            # CREATE INDEX critiques). Sans ca, autodetect uniquement.
            pragma_profile_name=self.pragma_profile_name,
        )

    def _debug(self, message: str) -> None:
        if not self._debug_logger:
            return
        with suppress(OSError, TypeError, ValueError):
            self._debug_logger(message)

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(
            str(self.db_path),
            busy_timeout_ms=self.busy_timeout_ms,
            profile=self.pragma_profile_name,
        )

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

        Fix audit 2026-05-26 (v1.5.6) Vague L (mig-2) : ce bootstrap est
        invoque en filet de securite quand des tables critiques manquent
        APRES migrations (peut arriver suite a un bug historique du migration
        manager, ou DB clonee partiellement). Or les migrations contiennent
        des ALTER TABLE ADD COLUMN qui ne sont pas IF NOT EXISTS-able : sur
        une DB partiellement existante, ces statements echouent avec
        "duplicate column name" et plantent tout le bootstrap. On adopte
        donc ici le meme mecanisme savepoint+_is_idempotent_error que dans
        MigrationManager.apply pour rester self-healing.

        Fix BUG-001 (hotfix1) : le script bootstrap concatene TOUTES les
        migrations, y compris celles porteuses du marker `@manager: disable_fk`
        (ex: migration 025 qui DROP/RECREATE `runs`). Sans cette desactivation,
        le DROP TABLE runs declenche ON DELETE CASCADE et supprime
        silencieusement errors/quality_reports/anomalies dont les rows ne
        seront jamais reinjectes. On replique donc ici la meme logique que
        MigrationManager.apply : detection du marker dans le script global,
        PRAGMA foreign_keys=OFF avant BEGIN, restauration ON apres COMMIT.
        PRAGMA foreign_keys ne fonctionne PAS dans une transaction, on le
        pose donc avant BEGIN et on le restaure dans un finally.
        """
        script, version = self.migrations.build_bootstrap_script()
        if not script or version <= 0:
            raise RuntimeError("Aucune migration SQL disponible pour initialiser le schema SQLite.")

        statements = _split_sql_statements(script)
        # Fix BUG-001 : detection du marker disable_fk au niveau global du
        # script bootstrap. Si au moins une migration concatenee le porte,
        # on desactive les FK pour TOUT le bootstrap (les DROP TABLE des
        # migrations FK-sensitives sinon CASCADE-supprimeraient les rows
        # enfants des migrations posterieures, alors meme qu'on est en mode
        # self-healing sur une DB partielle).
        # Fix BUG-001/014 (hotfix2) : matcher STRICT ligne commencant par
        # `-- @manager: disable_fk` apres trim, pour eviter qu'un commentaire
        # descriptif (ex: "ne PAS utiliser @manager: disable_fk ici") n'active
        # le PRAGMA a tort. Replique le pattern strict line-match adopte dans
        # migration_manager.py (BUG-014 hotfix1) pour coherence : sans ca, le
        # bootstrap differerait du chemin migration-par-migration et un faux
        # positif desactiverait silencieusement les FK pour TOUT le bootstrap.
        needs_fk_disable = any(line.strip().startswith("-- @manager: disable_fk") for line in script.splitlines())
        with self._managed_conn() as conn:
            if needs_fk_disable:
                conn.execute("PRAGMA foreign_keys = OFF")
            try:
                conn.execute("BEGIN")
                try:
                    for idx, stmt in enumerate(statements):
                        sp_name = f"bootstrap_{idx}"
                        conn.execute(f"SAVEPOINT {sp_name}")
                        try:
                            conn.execute(stmt)
                            conn.execute(f"RELEASE SAVEPOINT {sp_name}")
                        except sqlite3.OperationalError as stmt_exc:
                            # R8-021 RETRACTE (filet F2-d) : NE PAS attraper IntegrityError ici.
                            # Sur une source corrompue (PK dupliquee), skipper l'INSERT...SELECT
                            # de rebuild laisserait X_new VIDE -> DROP+RENAME = wipe silencieux.
                            # Bloquer le boot (re-lever) est le comportement SUR (recuperable).
                            # Fix audit 2026-05-26 (v1.5.6) Vague L (mig-2) :
                            # tolere les erreurs idempotentes (duplicate column,
                            # already exists) pour rester self-healing sur DB
                            # partielle.
                            # Issue #623 (volet 2) : la tolerance est APPARIEE au
                            # statement (cf _IDEMPOTENT_RULES). Sans `stmt`, un
                            # `CREATE VIEW`/`CREATE VIRTUAL TABLE` en echec passait
                            # pour « deja applique ». Ce site est le SECOND chemin
                            # de boot : il doit muter avec l'autre, pas apres.
                            if _is_idempotent_error(stmt_exc, stmt):
                                conn.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                                conn.execute(f"RELEASE SAVEPOINT {sp_name}")
                                logger.warning(
                                    "bootstrap_schema: statement %d ignore (idempotence): %s",
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
                    # Best effort : restaurer le PRAGMA quoi qu'il arrive.
                    with suppress(sqlite3.Error):
                        conn.execute("PRAGMA foreign_keys = ON")
        # R8-020 (F2-d) : backfiller schema_migrations apres un self-heal bootstrap.
        # Le bootstrap pose user_version mais n'insere RIEN dans schema_migrations ->
        # historique desync (diagnostic d'incident 023 impossible). On enregistre chaque
        # migration <= version (INSERT OR IGNORE, idempotent) maintenant que la table
        # schema_migrations existe (creee par la migration 012 dans le script bootstrap).
        try:
            with self._managed_conn() as conn:
                for mig_version, mig_path in self.migrations.list_migrations():
                    if int(mig_version) <= int(version):
                        MigrationManager._record_migration(conn, int(mig_version), mig_path.name)
        except sqlite3.Error as backfill_exc:
            self._debug(f"_bootstrap_schema_latest: schema_migrations backfill ignore: {backfill_exc}")
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
        # Nuance N21 : initialize() peut DROP/RECREATE des tables (bootstrap
        # self-heal, migrations de rebuild). Tout ce qui etait memoise avant
        # devient suspect.
        self._verified_schema_keys.clear()
        self._prepare_db_directory()
        db_existed = self.db_path.is_file()
        self._integrity_status = self._check_integrity()
        # V2-11 : auto-restore si corruption detectee et backup disponible.
        # Nuance N23 : "illisible" n'est PAS "corrompu". Un fichier que l'OS
        # refuse d'ouvrir (antivirus, agent de sauvegarde, Volume Shadow Copy,
        # permission) ne dit RIEN de son contenu ; ecraser la base vivante par
        # un backup sur ce seul symptome est une restauration a tort.
        if self._integrity_unreadable:
            self._integrity_event = {
                "status": "unreadable",
                "raw": self._integrity_status,
                "backup_used": None,
                "ts": time.time(),
            }
        elif self._integrity_non_concluant:
            # #986 : meme raisonnement que N23, autre cause. Le checkpoint WAL a
            # echoue, donc `integrity_check` a pu porter sur des pages perimees
            # et signaler une corruption FANTOME. Un checkpoint echoue justement
            # quand un AUTRE ecrivain tient la base : restaurer ici detruirait
            # ses commits sur un diagnostic dont le code lui-meme dit qu'il n'est
            # pas fiable.
            #
            # Statut DISTINCT de `unreadable` : la base est lisible, c'est le
            # verdict qui ne fait pas autorite. L'operateur doit pouvoir
            # distinguer les deux dans le journal.
            self._integrity_event = {
                "status": "inconclusive",
                "raw": self._integrity_status,
                "backup_used": None,
                "ts": time.time(),
            }
        elif self._integrity_status not in ("ok", "unknown"):
            self._attempt_auto_restore()
        # Nuance N28 : ce backup etait pousse a CHAQUE initialize(), migration
        # en attente ou non ; comme rotate_backups ne trie que par mtime, quelques
        # lancements suffisaient a evincer des backups riches par des copies de
        # la base courante. On ne le pousse plus que si le schema va reellement
        # bouger, ce qui est le contrat annonce par le nom de la methode et par
        # le trigger "pre_migration".
        schema_change_pending = db_existed and self._schema_change_pending()
        self._backup_before_migrations(schema_change_pending=schema_change_pending)
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
        # Nuance N26 : les migrations de rebuild recopient les tables enfants et
        # peuvent laisser des lignes qui violent la FK qu'elles viennent de
        # poser (cas mesure : `errors` recopiee sans filtre orphelin). Aucune
        # requete applicative ne les retourne et `integrity_check` repond "ok",
        # donc l'etat est aujourd'hui totalement invisible. On le rend au moins
        # DIAGNOSTIQUABLE, sans rien supprimer : filtrer ces lignes detruirait
        # le journal d'erreurs de l'utilisateur, ce que le fix BUG-001 (cf
        # _bootstrap_schema_latest) a precisement ete ecrit pour eviter.
        if schema_change_pending:
            self._log_foreign_key_violations()
        self._debug(f"SQLite initialized, schema version = {version}")
        return version

    @property
    def cloud_sync_provider(self) -> Optional[str]:
        """v1.3 : nom du provider cloud detecte dans le chemin DB, ou None.

        Valeurs possibles : "OneDrive", "Dropbox", "GoogleDrive",
        "Google Drive", "iCloudDrive", "iCloud Drive", "Box", "pCloud",
        "Mega", ou None si la DB n'est pas dans un dossier synchronise.

        Consomme par la couche UI (runtime_support) pour afficher un dialog
        non-bloquant au premier boot et inciter l'utilisateur a deplacer la DB.
        """
        return self._cloud_sync_provider

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

        Nuance N23 (ultra-audit 2026-08-03) : deux echecs de nature opposee
        produisaient le meme statut `error: <exc>`, et donc la meme consequence
        dans initialize() — un auto-restore qui ECRASE la base vivante :
          - "je n'ai pas pu OUVRIR le fichier" (l'OS refuse le handle), qui ne
            dit rien du contenu ;
          - "le moteur a repondu que le contenu est invalide", la corruption.
        Le premier cas est desormais renvoye avec le prefixe `unreadable: ` et
        pose `_integrity_unreadable`, que initialize() lit pour NE PAS tenter de
        restauration. Le chemin de corruption reelle est inchange.
        """
        self._integrity_unreadable = False
        self._integrity_non_concluant = False
        if not self.db_path.is_file():
            return "ok"
        try:
            conn = self._connect()
        except sqlite3.DatabaseError as exc:
            self._integrity_unreadable = True
            logger.error(
                "DB illisible (%s). Path: %s. Aucun diagnostic d'integrite n'est possible : "
                "l'auto-restore N'EST PAS declenche (la base n'est pas presumee corrompue).",
                exc,
                self.db_path,
            )
            return f"{UNREADABLE_STATUS_PREFIX}{exc}"
        try:
            with closing(conn):
                # Fix audit 2026-05-25 (v1.5.3) Vague H : flush WAL avant
                # integrity_check. Sans checkpoint, des pages encore dans le
                # WAL pouvaient masquer une corruption (ou en signaler une
                # fantome) selon l'etat du -wal/-shm. RESTART force le merge
                # complet vers le main file et reinitialise le WAL, donnant
                # un check fiable et reproductible. Best-effort : si le
                # checkpoint echoue (DB read-only, lock concurrent), on
                # continue avec un warning plutot que de skip l'integrity.
                try:
                    conn.execute("PRAGMA wal_checkpoint(RESTART)")
                except sqlite3.OperationalError as exc:
                    # #986 — UN CHECKPOINT EN ECHEC REND LE VERDICT NON FIABLE,
                    # ET IL INTERDIT DESORMAIS L'AUTO-RESTAURATION.
                    #
                    # Le commentaire ci-dessus le dit deja : sans checkpoint, des
                    # pages encore dans le WAL peuvent masquer une corruption
                    # « OU EN SIGNALER UNE FANTOME ». Or le verdict etait malgre
                    # tout traite comme assez autoritaire par `initialize()` pour
                    # ECRASER la base vivante via `_attempt_auto_restore` — et un
                    # checkpoint echoue precisement quand un AUTRE ecrivain tient
                    # la base. Les commits de cet autre ecrivain disparaissaient.
                    #
                    # C'est exactement la forme tranchee par la nuance N23 vingt
                    # lignes plus haut : un signal qui ne dit rien du CONTENU ne
                    # doit pas declencher une restauration. La restauration etant
                    # destructive, le doute va dans le sens RESTRICTIF.
                    #
                    # Le niveau passe de WARNING a ERROR : ce n'est plus une
                    # simple information, cela change ce que fait le demarrage.
                    self._integrity_non_concluant = True
                    logger.error(
                        "wal_checkpoint a echoue avant integrity_check (%s) — le verdict d'integrite porte "
                        "peut-etre sur des pages WAL perimees. L'auto-restore N'EST PAS declenche : ecraser "
                        "la base vivante sur un diagnostic non fiable detruirait les commits d'un autre "
                        "ecrivain. Path: %s",
                        exc,
                        self.db_path,
                    )
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
            # une corruption silencieuse cote operateur.
            #
            # #986 : ce message annoncait « Auto-restore from backup will be
            # attempted » DANS TOUS LES CAS. Depuis que le checkpoint en echec
            # interdit la restauration, cette phrase etait devenue fausse la
            # moitie du temps — et c'est precisement le genre de log qui fait
            # chercher un bug la ou il n'y en a pas.
            if self._integrity_non_concluant:
                logger.error(
                    "DB integrity check a repondu : %s. Path: %s. Verdict NON CONCLUANT "
                    "(le checkpoint WAL a echoue) : aucune restauration ne sera tentee.",
                    status,
                    self.db_path,
                )
            else:
                logger.error(
                    "DB integrity check FAILED: %s. Path: %s. Auto-restore from backup will be attempted.",
                    status,
                    self.db_path,
                )
        return status

    def _attempt_auto_restore(self) -> None:
        """V2-11 audit QA 20260504 : tente un restore auto depuis les backups
        disponibles quand l'integrity_check a echoue.

        AUDIT F29 : les backups sont parcourus du plus RECENT au plus ANCIEN et
        chacun est pre-teste en lecture ; on s'arrete au premier qui restaure une
        DB saine. Avant, seul backups[0] etait tente : un backup recent lui-meme
        corrompu faisait abandonner alors qu'un backup sain existait derriere.

        Trois issues possibles, toutes encodees dans self._integrity_event :
        - "restored"        : backup restaure + integrity_check post = ok.
        - "restore_failed"  : aucun candidat n'a rendu une DB saine (backups
                              corrompus, exception pendant le restore, ou
                              integrity_check post != ok).
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
        except OSError as exc:
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

        # AUDIT F29 : on ITERE du plus recent au plus ancien au lieu de ne tenter
        # que backups[0]. Avant ce fix, un backup recent lui-meme corrompu faisait
        # abandonner en "restore_failed" alors qu'un backup plus ancien et SAIN
        # existait juste derriere (et se faisait ensuite evincer par la rotation).
        # Chaque candidat est pre-teste EN LECTURE : on n'ecrase jamais la DB avec
        # un backup dont on sait deja qu'il est inexploitable.
        examined: List[Path] = []
        rejected: List[Path] = []
        restored_from: Optional[Path] = None
        for candidate in backups[: DEFAULT_MAX_BACKUPS + 2]:
            examined.append(candidate)
            reject_reason = self._backup_rejection_reason(candidate)
            if reject_reason is not None:
                logger.warning(
                    "auto_restore: backup %s ecarte (%s), essai du suivant",
                    candidate.name,
                    reject_reason,
                )
                rejected.append(candidate)
                continue

            logger.warning("DB corrompue, tentative auto-restore depuis %s", candidate)
            try:
                restore_backup(candidate, self.db_path)
            except (sqlite3.Error, OSError) as exc:
                logger.error(
                    "auto_restore: restore depuis %s a echoue: %s",
                    candidate,
                    exc,
                )
                continue
            restored_from = candidate

            # Re-check integrity apres restore (autorite finale)
            post_status = self._check_integrity()
            if post_status == "ok":
                logger.info(
                    "auto_restore: succes depuis %s. DB restauree.",
                    candidate,
                )
                self._integrity_status = "ok"
                self._integrity_event = {
                    "status": "restored",
                    "raw": raw_status,
                    "backup_used": str(candidate),
                    "backups_tried": len(examined),
                    "backups_rejected": len(rejected),
                    "ts": ts,
                }
                return
            logger.error(
                "auto_restore: restore effectue depuis %s mais integrity_check post = %s",
                candidate,
                post_status,
            )
            self._integrity_status = post_status

        logger.error(
            "auto_restore: aucun backup exploitable (%d examines, %d ecartes avant restore). Path: %s",
            len(examined),
            len(rejected),
            self.db_path,
        )
        # AUDIT F29 (revue R1) : `backup_used` documente "le backup RESTAURE".
        # L'ancienne valeur (dernier candidat EXAMINE) pouvait designer un fichier
        # ecarte par le pre-ecran, donc jamais restaure -> contrat viole et
        # diagnostic trompeur. On n'y met desormais que le dernier candidat
        # reellement ecrit sur la DB (None si le pre-ecran les a tous ecartes).
        self._integrity_event = {
            "status": "restore_failed",
            "raw": raw_status,
            "backup_used": str(restored_from) if restored_from is not None else None,
            "backups_tried": len(examined),
            "backups_rejected": len(rejected),
            "ts": ts,
        }

    def _integrity_of_file(self, path: Path) -> str:
        """PRAGMA integrity_check sur un fichier de backup (jamais sur self.db_path).

        Retourne "ok", "missing", le message brut de SQLite, ou "error: <exc>".
        Ne leve jamais : c'est un pre-ecran de selection, pas une autorite.
        NB : sqlite3.Error n'herite PAS de OSError, les deux classes sont
        obligatoires dans le except.
        """
        if not path.is_file():
            return "missing"
        try:
            with closing(sqlite3.connect(str(path))) as conn:
                row = conn.execute("PRAGMA integrity_check").fetchone()
                return str(row[0]) if row else "unknown"
        except (sqlite3.Error, OSError) as exc:
            return f"error: {exc}"

    def _backup_rejection_reason(self, path: Path) -> Optional[str]:
        """Pre-ecran de selection d'un backup : None = candidat acceptable.

        AUDIT F29 (revue R1) : `PRAGMA integrity_check` NE SUFFIT PAS. Un fichier
        de 0 octet est un SQLite parfaitement valide qui repond "ok" — et
        `backup_db` en laissait justement un dans backups/ quand le backup d'une
        DB corrompue echouait. Restaurer ce fichier remplace la bibliotheque par
        une base VIDE, `_check_integrity()` post-restore confirme "ok", l'event
        passe a "restored" et l'utilisateur recoit la notification rassurante
        "Base de donnees restauree automatiquement" alors que TOUT a disparu (et
        que le backup sain plus ancien n'a jamais ete essaye).

        On exige donc d'un candidat, en LECTURE SEULE et sans jamais lever :
          1. une taille >= 1 page SQLite (elimine le fichier de 0 octet) ;
          2. `PRAGMA integrity_check` == "ok" ;
          3. `PRAGMA page_count` > 0 ;
          4. la presence des tables du socle (`_BACKUP_CORE_TABLES`), sans quoi
             le backup ne porte aucune donnee de bibliotheque a restaurer.
        On ne verifie PAS l'integralite de REQUIRED_SCHEMA_TABLES : un backup
        anterieur a une migration recente est un candidat legitime (les
        migrations le completeront), le rejeter reviendrait a jeter une
        bibliotheque recuperable.
        """
        if not path.is_file():
            return "missing"
        try:
            size = int(path.stat().st_size)
        except OSError as exc:
            return f"error: {exc}"
        if size < _MIN_USABLE_BACKUP_BYTES:
            return f"taille {size} octets < 1 page SQLite (base vide)"
        status = self._integrity_of_file(path)
        if status != "ok":
            return f"integrity={status}"
        try:
            with closing(sqlite3.connect(str(path))) as conn:
                row = conn.execute("PRAGMA page_count").fetchone()
                if not row or int(row[0]) <= 0:
                    return "page_count=0 (base vide)"
                placeholders = ",".join("?" for _ in _BACKUP_CORE_TABLES)
                cur = conn.execute(
                    f"SELECT name FROM sqlite_master WHERE type='table' AND name IN ({placeholders})",
                    _BACKUP_CORE_TABLES,
                )
                found = {str(r[0]) for r in cur.fetchall() if r and r[0]}
        except (sqlite3.Error, OSError, TypeError, ValueError) as exc:
            return f"error: {exc}"
        missing = [t for t in _BACKUP_CORE_TABLES if t not in found]
        if missing:
            return f"schema absent (tables manquantes: {', '.join(missing)})"
        return None

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
        except OSError as exc:
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
        except (sqlite3.Error, OSError) as exc:
            logger.error("rollback_migration: restore depuis %s echoue: %s", most_recent, exc)
            return None
        return most_recent

    def _schema_change_pending(self) -> bool:
        """Nuance N28 : `initialize()` va-t-il reellement toucher le schema ?

        True si au moins une migration est en attente (`user_version` sous la
        derniere migration disponible) OU si une table de
        `REQUIRED_SCHEMA_TABLES` manque — auquel cas `_ensure_required_schema`
        rejouera le bootstrap, qui DROP/RECREATE. En cas de doute (erreur
        pendant la mesure) on repond True : mieux vaut un backup de trop qu'un
        backup manquant avant une migration.
        """
        try:
            with closing(self._connect()) as conn:
                row = conn.execute("PRAGMA user_version").fetchone()
                current_version = int(row[0]) if row else 0
                if current_version < int(self.migrations.latest_version() or 0):
                    return True
                placeholders = ",".join("?" for _ in REQUIRED_SCHEMA_TABLES)
                cur = conn.execute(
                    f"SELECT name FROM sqlite_master WHERE type='table' AND name IN ({placeholders})",
                    tuple(REQUIRED_SCHEMA_TABLES),
                )
                found = {str(r[0]) for r in cur.fetchall() if r and r[0]}
        except (sqlite3.Error, OSError, TypeError, ValueError) as exc:
            logger.warning(
                "schema_change_pending: mesure impossible (%s) — backup pre_migration conserve par prudence",
                exc,
            )
            return True
        return bool(set(REQUIRED_SCHEMA_TABLES) - found)

    def _log_foreign_key_violations(self) -> None:
        """Nuance N26 : trace les lignes orphelines laissees par un rebuild.

        Purement diagnostique — ne supprime rien, ne leve jamais, et n'est
        appele qu'apres un changement de schema effectif (donc jamais sur un
        boot nominal). `PRAGMA foreign_key_check` n'etait invoque nulle part
        dans le produit : une base violant une FK que le schema promet passait
        totalement inapercue, `integrity_check` repondant "ok".
        """
        try:
            with closing(self._connect()) as conn:
                rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        except (sqlite3.Error, OSError) as exc:
            logger.debug("foreign_key_check: diagnostic impossible (%s)", exc)
            return
        if not rows:
            return
        per_relation: Dict[str, int] = {}
        for row in rows:
            # PRAGMA foreign_key_check -> (table_enfant, rowid, table_parente, fkid)
            values = tuple(row)
            relation = f"{values[0]} -> {values[2]}" if len(values) >= 3 else "?"
            per_relation[relation] = per_relation.get(relation, 0) + 1
        detail = ", ".join(f"{rel}: {count}" for rel, count in sorted(per_relation.items())[:_FK_VIOLATIONS_LOG_CAP])
        logger.error(
            "PRAGMA foreign_key_check signale %d ligne(s) orpheline(s) apres changement de schema "
            "(%s). Path: %s. Aucune donnee n'est supprimee : ces lignes sont invisibles des requetes "
            "applicatives, mais elles violent une contrainte que le schema declare.",
            len(rows),
            detail,
            self.db_path,
        )

    def _backup_before_migrations(self, *, schema_change_pending: Optional[bool] = None) -> None:
        """CR-2 : si la DB existe deja, faire un backup avant d'appliquer
        les migrations. Tolerant : un echec de backup ne bloque pas le
        boot (mieux DB sans backup que app cassee).

        Nuance N28 (ultra-audit 2026-08-03) : le backup n'est plus pousse a
        chaque boot mais seulement quand le schema va reellement bouger.
        `rotate_backups` ne trie que par mtime et ne regarde jamais le contenu :
        sur une base videe hors des deux boutons de reset (suppression manuelle
        du .sqlite recommandee en dernier recours par docs/TROUBLESHOOTING.md),
        DEFAULT_MAX_BACKUPS lancements suffisaient a remplacer tous les backups
        riches par des copies de la base vierge. `schema_change_pending=None`
        laisse la methode faire elle-meme la mesure.
        """
        if not self.db_path.is_file():
            return  # fresh install, rien a backupper
        if self._backup_blocked_by_integrity("backup_before_migrations", "pre_migration"):
            return
        pending = self._schema_change_pending() if schema_change_pending is None else bool(schema_change_pending)
        if not pending:
            logger.debug(
                "backup_before_migrations: aucune migration en attente et schema complet — backup saute "
                "(ne pas evincer par rotation des backups plus riches que la base courante)."
            )
            return
        try:
            backup_db_with_rotation(
                self.db_path,
                self._backup_dir(),
                trigger="pre_migration",
                max_count=DEFAULT_MAX_BACKUPS,
            )
        except Exception as exc:
            logger.warning("backup_before_migrations: ignore (%s)", exc)

    def _backup_blocked_by_integrity(self, caller: str, trigger: str) -> bool:
        """AUDIT F29 (anti-aggravation) : ne JAMAIS backupper une DB dont
        l'integrity_check vient d'echouer.

        Sinon chaque backup pousse une copie corrompue (voire un .bak de 0 octet,
        cf backup_db) en tete de backups/ et la rotation (DEFAULT_MAX_BACKUPS)
        evince les backups SAINS en quelques cycles -> perte definitive d'une
        bibliotheque qui etait recuperable.

        Revue R1 : la garde etait posee dans le seul `_backup_before_migrations`
        alors que `backup_now()` tourne apres CHAQUE apply reel (trigger
        "post_apply") et depuis l'UI Parametres — sur une DB corrompue en mode
        degrade, ce chemin continuait donc a fabriquer le candidat n°1 du
        prochain auto-restore. La garde est desormais partagee par les deux.

        "unknown" = initialize() pas encore appele : on ne bloque pas (le backup
        d'une DB non encore diagnostiquee reste utile).
        """
        if self._integrity_status in ("ok", "unknown"):
            return False
        logger.warning(
            "%s: DB corrompue (%s) — backup %s saute (ne pas evincer les backups sains par rotation)",
            caller,
            self._integrity_status,
            trigger,
        )
        return True

    def backup_now(self, *, trigger: str = "manual", max_count: int = DEFAULT_MAX_BACKUPS) -> Optional[Path]:
        """API publique : declenche un backup immediat. Retourne le chemin
        ou None si la DB n'existe pas encore. Utilise par apply_support
        apres apply reel et par UI Settings.
        """
        if self._backup_blocked_by_integrity("backup_now", str(trigger or "manual")):
            return None
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

    def _db_identity(self) -> Optional[tuple]:
        """Nuance N21 : identite du fichier DB courant, ou None si inconnaissable.

        Sert de jeton d'invalidation au memo de `_ensure_tables`. Retourne None
        — donc : ne jamais memoiser — si le fichier n'existe pas, s'il n'est pas
        stat-able, ou si le systeme de fichiers ne fournit pas de numero d'inode
        exploitable (`st_ino == 0`), auquel cas on ne saurait pas distinguer un
        fichier supprime puis recree et on prefere refaire la verification.
        """
        try:
            st = self.db_path.stat()
        except OSError:
            return None
        ino = int(getattr(st, "st_ino", 0) or 0)
        if ino == 0:
            return None
        return (int(getattr(st, "st_dev", 0) or 0), ino)

    def _ensure_tables(self, *table_names: str, min_user_version: Optional[int] = None) -> None:
        """Nuance N21 : la verification est memoisee par (tables, version, fichier).

        Sans memo, cette methode ouvrait une connexion dediee (deux avec
        `min_user_version`, via `get_user_version()`) AVANT la connexion de
        travail de `_with_schema_group`, a chaque appel de repository — soit
        2 a 3 connexions la ou une seule sert, sur des chemins boucles par film.
        Le memo est invalide par `initialize()` et par tout changement
        d'identite du fichier .sqlite (suppression puis recreation).
        """
        cache_key = (
            tuple(sorted(str(name) for name in table_names)),
            int(min_user_version) if min_user_version is not None else None,
        )
        identity = self._db_identity()
        if identity is not None and self._verified_schema_keys.get(cache_key) == identity:
            return
        try:
            if self._schema_satisfies(list(table_names), min_user_version=min_user_version):
                if identity is not None:
                    self._verified_schema_keys[cache_key] = identity
                return
        except sqlite3.Error:
            pass
        # Volontairement PAS de memoisation apres initialize() : le prochain
        # appel refera une verification reelle (et la memoisera si elle passe),
        # plutot que de parier sur ce que le self-heal a recree.
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
        # Fix audit 2026-05-24 : raw=NULL est un cas legitime (run pas encore
        # termine, stats_json pas encore ecrit). Inutile de logger un warning
        # bruyant - retourner silencieusement le default.
        if raw is None:
            return default
        try:
            parsed = json.loads(str(raw))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("corrupt JSON in column %s: %s (raw=%r)", field_name, exc, raw)
            return default
        if parsed is None:
            # JSON 'null' = donnee explicitement vide, comportement legitime
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


class SQLiteStore(_StoreBase):
    # Issue #85 phase B8 COMPLETE (B8a -> B8g) : tous les mixins legacy ont
    # ete supprimes. Les Repositories sont accessibles via composition :
    #   - store.probe (B8a)       - store.quality (B8e)
    #   - store.anomaly (B8b)     - store.run (B8f)
    #   - store.scan (B8c)        - store.apply (B8g)
    #   - store.perceptual (B8d)
    # SQLiteStore n'herite plus que de _StoreBase (gestion connection +
    # initialisation). Le code metier vit dans les 7 Repositories.
    """
    SQLite persistence for v7 foundations.

    Cf issue #85 (CLOSED phase B8a -> B8g) : tous les mixins legacy ont ete
    supprimes. SQLiteStore expose desormais les 8 Repositories par composition :
        store.apply, store.anomaly, store.perceptual, store.probe,
        store.quality, store.run, store.scan, store.film_modal
    Chaque Repository encapsule un bounded context SQL distinct et delegue
    a `_StoreBase` pour la gestion de connexion / migrations / integrity.

    Pattern d'usage (obligatoire pour tout nouveau code) :
        store.apply.insert_batch(...)
        store.quality.get_report(...)

    Les anciennes methodes plates `store.insert_apply_batch(...)` n'existent
    plus (B8 closed) ; tous les call sites internes ont migre.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Cf issue #85 : 7 Repository en composition. Les mixins ont ete
        # supprimes (phase B8 CLOSED), donc plus de cycle -> import top-level.
        self.apply = ApplyRepository(self)
        self.anomaly = AnomalyRepository(self)
        self.perceptual = PerceptualRepository(self)
        self.probe = ProbeRepository(self)
        self.quality = QualityRepository(self)
        self.run = RunRepository(self)
        self.scan = ScanRepository(self)
        # Spec 06 Modal Film (migration 023) : etat utilisateur sur les films.
        self.film_modal = FilmModalRepository(self)
        # Vague P / VP-C (migration 030) : verrous champ-par-champ Jellyfin.
        self.field_locks = FieldLocksRepository(self)
        # Vague P / VP-D (migration 031) : decisions tri-etat
        # (accepted/rejected/deferred). Backward compat ABSOLUE.
        self.decisions = DecisionsRepository(self)
