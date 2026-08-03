"""VO-A backend -- profils PRAGMA SQLite adaptes au type de stockage.

Centralise les 4 profils PRAGMA SQLite (local SSD, local HDD, NAS SMB,
NAS SMB lent) et la detection automatique du type de stockage. L'objectif
est de couvrir les configurations utilisateur reelles :

  - local_ssd       : NVMe / SATA SSD, faible latence, bonne bande passante
  - local_hdd       : HDD mecanique local, latence elevee, sequentiel OK
  - nas_smb         : partage reseau SMB/CIFS (UNC path), corruption silencieuse
                      confirmee (Sonarr #1886) -> synchronous=FULL obligatoire,
                      mmap_size=0 (mmap incompatible SMB), wal autocheckpoint
                      tres frequent pour limiter le WAL ouvert sur partage.
  - nas_smb_slow    : NAS lent (Wi-Fi, bras de seek mecanique, vieux SMB1) ->
                      busy_timeout double, cache reduit, autocheckpoint encore
                      plus agressif.

Detection auto (Windows uniquement) :

  1. Si le `db_path` commence par `\\\\` (UNC) -> 'nas_smb'.
  2. Sinon, on interroge `GetDriveType` via ctypes pour distinguer
     DRIVE_REMOTE (-> 'nas_smb') / DRIVE_FIXED (-> 'local_ssd' faute de
     pouvoir distinguer SSD vs HDD a l'arrache).
  3. En cas d'echec (Linux, ctypes indisponible, exception), fallback
     'local_ssd' qui est le profil le moins penalisant pour une DB locale.

Override explicite via `connect_sqlite(db_path, profile='nas_smb')` ou
`SQLiteStore(db_path, pragma_profile_name='nas_smb_slow')`.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Dict, Mapping, Optional

logger = logging.getLogger(__name__)

# Sources valides pour pragma_history.source (migration 028). On reste laxiste
# (TEXT libre cote schema) mais on documente les valeurs canoniques pour que
# les callers et les requetes de debug puissent compter dessus.
_VALID_PRAGMA_HISTORY_SOURCES = ("auto", "manual_settings", "env_override")

# AUDIT REAL 2/2 (pragma_profile.py:219) : _record_pragma_history insere une
# ligne a CHAQUE ouverture de connexion (chaque methode repository en ouvre 1-3),
# et AUCUNE purge n'existait -> croissance non bornee de pragma_history (des
# dizaines de milliers de lignes JSON par scan de bibliotheque). On borne la
# table a ce nombre de lignes (les plus recentes) apres chaque insert : c'est
# une table d'audit/debug, l'historique ancien n'a aucune valeur metier. La
# purge se fait par id (PK AUTOINCREMENT monotone) -> un DELETE range indexe.
_PRAGMA_HISTORY_MAX_ROWS = 500


# ---------------------------------------------------------------------------
# Profils PRAGMA. Chaque profil est un mapping nom_pragma -> valeur attendue.
# Les valeurs negatives pour cache_size signifient "KB de cache" (signe SQLite
# pour cache_size : negatif = bytes en KB, positif = nombre de pages).
# ---------------------------------------------------------------------------
PROFILES: Dict[str, Dict[str, int | str]] = {
    "local_ssd": {
        "journal_mode": "WAL",
        "synchronous": "NORMAL",
        "busy_timeout": 5000,
        "mmap_size": 268435456,  # 256 MB -- lectures memory-mapped agressives
        "cache_size": -20000,  # ~20 MB
        "wal_autocheckpoint": 1000,  # default SQLite, OK sur SSD rapide
    },
    "local_hdd": {
        "journal_mode": "WAL",
        "synchronous": "NORMAL",
        "busy_timeout": 10000,  # HDD : seek mecanique, on tolere plus de wait
        "mmap_size": 67108864,  # 64 MB -- mmap reduit (HDD = pas de gain massif)
        "cache_size": -20000,
        "wal_autocheckpoint": 1000,
    },
    "nas_smb": {
        "journal_mode": "WAL",
        # synchronous=FULL obligatoire sur SMB : Sonarr #1886 confirme corruption
        # silencieuse sur NORMAL (cache cote serveur ne flush pas). Cost: ~30%
        # perf en ecriture, mais c'est l'unique garantie de durabilite reseau.
        "synchronous": "FULL",
        "busy_timeout": 30000,  # SMB lock contention peut etre tres longue
        "mmap_size": 0,  # mmap incompatible SMB (donnees corrompues)
        "cache_size": -20000,
        "wal_autocheckpoint": 200,  # WAL court : limite la fenetre de corruption
    },
    "nas_smb_slow": {
        "journal_mode": "WAL",
        "synchronous": "FULL",
        "busy_timeout": 60000,  # Wi-Fi / SMB1 / vieux NAS : 60s
        "mmap_size": 0,
        "cache_size": -10000,  # cache reduit (RAM client souvent limitee)
        "wal_autocheckpoint": 100,  # checkpoint quasi continu
    },
}

# Nom des PRAGMA qui sont des etats SQLite (writable + readable) pour readback.
# Note : busy_timeout est ecrit en ms mais peut etre relu via "PRAGMA busy_timeout".
_PRAGMA_READBACK_KEYS = (
    "journal_mode",
    "synchronous",
    "busy_timeout",
    "mmap_size",
    "cache_size",
    "wal_autocheckpoint",
)


def _profile_keys() -> tuple[str, ...]:
    """Noms des profils valides (tri stable pour erreurs deterministes)."""
    return tuple(sorted(PROFILES.keys()))


def detect_storage_type(db_path: str | Path) -> str:
    """Detecte le type de stockage du chemin DB pour choisir un profil PRAGMA.

    Strategie Windows :
      1. UNC path (`\\\\server\\share\\...`) -> 'nas_smb'.
      2. GetDriveType via ctypes :
           DRIVE_REMOTE (4) -> 'nas_smb'
           DRIVE_FIXED  (3) -> 'local_ssd' (on ne distingue pas SSD vs HDD
                               sans WMI, fallback raisonnable)
           autre        -> 'local_ssd' (USB removable, RAM disk, etc.)
      3. En cas d'erreur (Linux, ctypes KO, GetDriveType raise) -> 'local_ssd'.

    Le profil 'nas_smb_slow' n'est jamais retourne par l'autodetect : il
    requiert un override explicite (l'utilisateur sait mieux que nous si
    son NAS est lent).
    """
    db_str = str(db_path)

    # 1. Detection UNC robuste : str.startswith couvre les chemins bruts ;
    #    Path.drive sur Windows retourne "\\\\server\\share" pour les UNC, on
    #    s'en sert en second filet quand la chaine a deja ete normalisee.
    if db_str.startswith("\\\\"):
        return "nas_smb"
    try:
        drive = Path(db_str).drive
        if drive.startswith("\\\\"):
            return "nas_smb"
    except (TypeError, ValueError, OSError):
        # Path() peut lever sur des chemins exotiques : on continue le sondage.
        pass

    # 2. Windows GetDriveType via ctypes. Inutile sur Linux/macOS ou la
    #    distinction reseau-vs-local se ferait via /proc/mounts (hors scope ici).
    try:
        import ctypes  # type: ignore[import-not-found]

        kernel32 = getattr(ctypes, "windll", None)
        if kernel32 is None:
            return "local_ssd"
        get_drive_type = kernel32.kernel32.GetDriveTypeW
        # GetDriveTypeW attend un root path "X:\\" ou "\\\\server\\share\\".
        # On extrait via pathlib.
        drive = Path(db_str).drive
        if not drive:
            return "local_ssd"
        root = drive + "\\" if not drive.endswith("\\") else drive
        kind = int(get_drive_type(root))
        # 4 = DRIVE_REMOTE (mapped network drive). UNC pur ne devrait pas
        # tomber ici (intercepte plus haut), mais on couvre Z: -> \\\\nas01.
        if kind == 4:
            return "nas_smb"
        return "local_ssd"
    except (AttributeError, OSError, ValueError):
        return "local_ssd"
    except Exception as exc:  # noqa: BLE001 -- ctypes peut lever divers types
        logger.debug("detect_storage_type: fallback local_ssd (%s)", exc)
        return "local_ssd"


def get_pragma_snapshot(conn: sqlite3.Connection) -> Dict[str, object]:
    """Renvoie un snapshot des PRAGMA pertinents pour log/readback.

    Tolerant : si un PRAGMA n'est pas supporte (vieille version SQLite,
    PRAGMA inexistant) on consigne `None` plutot que de lever.
    """
    snapshot: Dict[str, object] = {}
    for key in _PRAGMA_READBACK_KEYS:
        try:
            cur = conn.execute(f"PRAGMA {key}")
            row = cur.fetchone()
            snapshot[key] = row[0] if row is not None else None
        except sqlite3.Error as exc:
            logger.debug("get_pragma_snapshot: PRAGMA %s indisponible (%s)", key, exc)
            snapshot[key] = None
    return snapshot


def _record_pragma_history(
    conn: sqlite3.Connection,
    *,
    profile_name: str,
    db_path: Optional[str],
    storage_type_detected: Optional[str],
    pragmas_snapshot: Mapping[str, object],
    source: str,
) -> None:
    """Insere une ligne dans `pragma_history` (migration 028).

    Tolerant : si la table n'existe pas (DB pre-migration 028, DB de test
    vierge, migration partielle), on log en DEBUG et on n'echoue PAS. Le
    but est l'observabilite/audit -- jamais bloquer une connexion legitime.

    `pragmas_snapshot` est serialise en JSON (sort_keys=True pour
    deterministe). `source` est libre cote schema mais on documente les
    valeurs canoniques via `_VALID_PRAGMA_HISTORY_SOURCES`.
    """
    try:
        payload = json.dumps(dict(pragmas_snapshot), sort_keys=True, default=str)
    except (TypeError, ValueError) as exc:
        logger.debug("_record_pragma_history: serialize snapshot a echoue (%s)", exc)
        payload = "{}"

    # IMPORTANT (Vague O / VO-A migration 028) : on COMMIT explicitement apres
    # l'INSERT. apply_pragmas() est appelee depuis connect_sqlite() au tout
    # debut du cycle de vie d'une connexion, AVANT que MigrationManager.apply()
    # ne pose son propre BEGIN. Sans commit ici, l'INSERT ouvre une transaction
    # implicite (isolation_level=DEFERRED) et le BEGIN du manager echoue avec
    # "cannot start a transaction within a transaction" (cf. test_migration_chain
    # test_idempotent_alter_table_tolerated).
    #
    # C'est conceptuellement correct : pragma_history est une table d'audit
    # log pure, elle n'est jamais liee a une transaction metier.
    try:
        conn.execute(
            "INSERT INTO pragma_history "
            "(applied_at, profile_name, db_path, storage_type_detected, pragmas_json, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                int(time.time()),
                str(profile_name),
                str(db_path) if db_path is not None else "",
                storage_type_detected,
                payload,
                str(source),
            ),
        )
        # AUDIT REAL 2/2 : purge bornee DANS la meme transaction implicite que
        # l'INSERT (un seul commit plus bas). On garde les _PRAGMA_HISTORY_MAX_ROWS
        # lignes les plus recentes (par id, PK AUTOINCREMENT monotone). Le DELETE
        # range `id <= max_id - cap` est indexe et O(rows supprimees). Tolerant :
        # un echec de purge ne doit pas perdre l'INSERT (on log en debug et on
        # commit quand meme la ligne inseree).
        try:
            row = conn.execute("SELECT MAX(id) FROM pragma_history").fetchone()
            max_id = int(row[0]) if row and row[0] is not None else 0
            cutoff = max_id - _PRAGMA_HISTORY_MAX_ROWS
            if cutoff > 0:
                conn.execute("DELETE FROM pragma_history WHERE id <= ?", (cutoff,))
        except sqlite3.Error as purge_exc:
            logger.debug("_record_pragma_history: purge bornee ignoree (%s)", purge_exc)
        # COMMIT immediat : libere la transaction implicite ouverte par INSERT.
        # En cas d'echec ici, on ROLLBACK pour ne pas laisser de pending tx
        # (un connect_sqlite suivi d'un BEGIN doit toujours fonctionner).
        try:
            conn.commit()
        except sqlite3.Error as commit_exc:
            logger.debug(
                "_record_pragma_history: commit a echoue (%s) -- rollback",
                commit_exc,
            )
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
    except sqlite3.OperationalError as exc:
        # Cas attendu : table absente (migration 028 pas encore appliquee).
        # On log en DEBUG car ce n'est pas une erreur fonctionnelle.
        logger.debug(
            "_record_pragma_history: insertion ignoree (%s) -- table absente ?",
            exc,
        )
        # Aucun INSERT n'a abouti -> pas de transaction implicite a fermer.
    except sqlite3.Error as exc:
        logger.warning(
            "_record_pragma_history: insertion a echoue (%s) -- audit perdu",
            exc,
        )
        with contextlib.suppress(sqlite3.Error):
            conn.rollback()


def apply_pragmas(
    conn: sqlite3.Connection,
    profile_name: str,
    *,
    db_path: Optional[str] = None,
    storage_type_detected: Optional[str] = None,
    source: str = "auto",
    record_history: bool = True,
) -> Dict[str, object]:
    """Applique le profil PRAGMA `profile_name` a la connexion `conn`.

    Chaque PRAGMA est applique dans son propre try/except : un PRAGMA non
    supporte (cas mmap_size sur certains builds SQLite, ou journal_mode sur
    une DB chiffree) ne doit jamais empecher l'app de booter.

    Retourne le snapshot readback post-application pour traceabilite et
    pour permettre aux tests de verifier l'effet reel des PRAGMA.

    Note importante : `foreign_keys` et `temp_store` ne font PAS partie des
    profils -- ce sont des invariants applicatifs (FK toujours ON, temp en
    memoire) appliques separement par `connect_sqlite`.

    VO-A migration 028 : si `record_history=True` et que la table
    `pragma_history` existe, une ligne d'audit est inseree apres readback.
    Backward compat : tous les nouveaux kwargs ont un defaut, l'appel
    `apply_pragmas(conn, profile_name)` continue de marcher inchange.
    """
    profile = PROFILES.get(profile_name)
    if profile is None:
        valid = ", ".join(_profile_keys())
        raise ValueError(f"Profil PRAGMA inconnu: {profile_name!r}. Valides: {valid}")

    for pragma_name, value in profile.items():
        try:
            # PRAGMA accepte litteralement le nom de mode (WAL, NORMAL, FULL)
            # sans guillemets. Pour les valeurs numeriques on cast en int via
            # f-string -- evite l'injection (les valeurs viennent de PROFILES).
            conn.execute(f"PRAGMA {pragma_name} = {value}")
        except sqlite3.Error as exc:
            logger.warning(
                "apply_pragmas[%s]: PRAGMA %s = %s a echoue (%s) -- ignore",
                profile_name,
                pragma_name,
                value,
                exc,
            )

    snapshot = get_pragma_snapshot(conn)
    logger.debug(
        "apply_pragmas[%s]: readback = %s",
        profile_name,
        snapshot,
    )

    if record_history:
        _record_pragma_history(
            conn,
            profile_name=profile_name,
            db_path=db_path,
            storage_type_detected=storage_type_detected,
            pragmas_snapshot=snapshot,
            source=source,
        )

    return snapshot


def resolve_profile(
    db_path: str | Path,
    explicit_profile: Optional[str] = None,
) -> str:
    """Resout le profil a appliquer : explicit si fourni et valide, sinon auto.

    Centralise la logique de fallback pour eviter la duplication dans
    `connect_sqlite` et `SQLiteStore`.
    """
    if explicit_profile is not None:
        if explicit_profile not in PROFILES:
            valid = ", ".join(_profile_keys())
            raise ValueError(f"Profil PRAGMA inconnu: {explicit_profile!r}. Valides: {valid}")
        return explicit_profile
    return detect_storage_type(db_path)


def is_unc_path(db_path: str | Path) -> bool:
    """Helper : True si `db_path` est un chemin UNC (`\\\\server\\share\\...`).

    Utilise pour le WARN log a la connexion + sera consomme par
    DB_LOCAL_GUARD (VO-A-NAS) qui veut interdire les DBs SQLite hostees
    sur un partage reseau.
    """
    db_str = str(db_path)
    if db_str.startswith("\\\\"):
        return True
    try:
        drive = Path(db_str).drive
    except (TypeError, ValueError, OSError):
        return False
    return drive.startswith("\\\\")


__all__ = [
    "PROFILES",
    "apply_pragmas",
    "detect_storage_type",
    "get_pragma_snapshot",
    "is_unc_path",
    "resolve_profile",
    "_record_pragma_history",
]
