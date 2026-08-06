from __future__ import annotations

import logging
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)

# V3-11 -- mmap_size pour perf lecture sur grosses DB (>50 MB).
# Conserve pour compat retro (et tests). La valeur reelle appliquee depend
# desormais du profil PRAGMA (voir pragma_profile.PROFILES['local_ssd']).
_MMAP_SIZE_BYTES = 256 * 1024 * 1024  # 256 MB


_DEFAULT_BUSY_TIMEOUT_MS = 5000


def connect_sqlite(
    db_path: str,
    *,
    busy_timeout_ms: int = _DEFAULT_BUSY_TIMEOUT_MS,
    profile: Optional[str] = None,
) -> sqlite3.Connection:
    """Create a configured SQLite connection.

    VO-A backend : applique un profil PRAGMA adapte au stockage (local SSD,
    local HDD, NAS SMB, NAS SMB lent). Le profil est :

      - resolu automatiquement via `detect_storage_type(db_path)` si
        `profile is None` ;
      - ou impose explicitement par le caller via `profile='nas_smb'` etc.

    Backward compat (CRITIQUE) :
      - signature `connect_sqlite(db_path)` continue de fonctionner ;
      - `busy_timeout_ms` continue d'etre applique comme PRAGMA busy_timeout
        SI le caller a explicitement fourni une valeur != default 5000 (les
        tests v7_foundations / db_robustness historiques verifient cela).
        Sinon le `busy_timeout` du profil prime ;
      - les invariants applicatifs (foreign_keys ON, temp_store MEMORY,
        row_factory Row) sont preserves quel que soit le profil.

    UNC path : si le chemin pointe sur un partage SMB on log un WARN. La
    refus pur et simple est delegue a DB_LOCAL_GUARD (VO-A-NAS, prochain
    item) pour ne pas casser les setups existants qui dependent encore
    d'une DB NAS-hostee.
    """
    # Import local pour eviter un cycle a froid au moment de l'import du module.
    from .pragma_profile import (
        apply_pragmas,
        detect_storage_type,
        is_unc_path,
        resolve_profile,
        should_record_pragma_history,
    )

    # Resoudre le profil AVANT d'ouvrir la connexion : si le caller passe
    # un nom invalide on doit lever sans laisser de fichier sqlite vide.
    resolved_profile = resolve_profile(db_path, explicit_profile=profile)
    # storage_type_detected loggee dans pragma_history (audit / debug NAS) :
    # on capture la detection brute meme si le caller a override le profil,
    # pour pouvoir comparer "auto eut choisi X" vs "manual a choisi Y" en
    # post-mortem.
    try:
        storage_type_detected = detect_storage_type(db_path)
    except Exception:  # noqa: BLE001 -- detection ne doit JAMAIS bloquer
        storage_type_detected = None
    history_source = "manual_settings" if profile is not None else "auto"

    # Issue #428 : `isolation_level` n'est PAS passe, et c'est delibere. Le
    # defaut `""` est un alias de "DEFERRED" — mesure sur ce Python (3.13.13,
    # SQLite 3.50.4) via `set_trace_callback` : le defaut emet `BEGIN `, et
    # `isolation_level="DEFERRED"` emet `BEGIN DEFERRED`, qui est la MEME chose
    # pour SQLite (une transaction est deferred par defaut). `in_transaction` et
    # le rejet d'un `BEGIN` explicite sont identiques dans les deux cas ; seule
    # la valeur de l'attribut `conn.isolation_level` change, et rien ne la lit
    # dans le depot. L'expliciter serait donc du bruit non testable autrement
    # que par une tautologie.
    #
    # Ce qu'il ne faut PAS faire en revanche : passer `isolation_level=None`
    # (autocommit). `pragma_profile._record_pragma_history` DEPEND du mode
    # transactionnel implicite — il commit explicitement son INSERT parce que
    # celui-ci ouvre une transaction qui ferait echouer le `BEGIN` de
    # `MigrationManager.apply()` (cf. le commentaire detaille la-bas).
    conn = sqlite3.connect(
        str(db_path),
        timeout=max(1.0, busy_timeout_ms / 1000.0),
        # C'est CECI, et non `isolation_level`, qui protege du risque nomme par
        # #428 (« une montee de Python change le comportement transactionnel »).
        # Depuis Python 3.12, `isolation_level` n'est honore QUE tant que
        # `autocommit` vaut LEGACY_TRANSACTION_CONTROL ; le jour ou ce defaut
        # changerait, l'expliciter n'aurait servi a rien. MESURE comparative :
        #
        #   rien passe / LEGACY epingle : BEGIN implicite avant le DML,
        #                                 in_transaction=True, BEGIN explicite REFUSE
        #   autocommit=True             : AUCUN BEGIN implicite,
        #                                 in_transaction=False, BEGIN explicite ACCEPTE
        #
        # Le depot est ecrit contre la premiere colonne : `MigrationManager.apply`
        # pose son propre `BEGIN` puis `commit`/`rollback`, et
        # `_record_pragma_history` commit explicitement pour que ce `BEGIN`
        # passe. Epingler est un no-op aujourd'hui (mesure : traces SQL emises
        # identiques) et une assurance pour demain.
        autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL,
    )
    try:
        conn.row_factory = sqlite3.Row

        # 1. Invariants applicatifs (hors profils) : FK + temp_store.
        #    Cf docstring apply_pragmas : ces deux PRAGMA ne sont PAS dans les
        #    profils car ils sont constants quel que soit le stockage.
        try:
            conn.execute("PRAGMA foreign_keys = ON")
        except sqlite3.Error as exc:
            logger.warning("PRAGMA foreign_keys=ON a echoue (%s)", exc)
        try:
            conn.execute("PRAGMA temp_store = MEMORY")
        except sqlite3.Error as exc:
            logger.warning("PRAGMA temp_store=MEMORY a echoue (%s)", exc)

        # 2. Profil PRAGMA stockage-specifique.
        if is_unc_path(db_path):
            # NB : `is_unc_path` reste True meme si l'utilisateur a override le
            # profil (ex : `profile='local_ssd'`). On WARN dans tous les cas
            # car le risque corruption SMB ne depend pas du profil choisi.
            logger.warning(
                "DB SQLite sur chemin UNC (%s) -- risque corruption SMB connu "
                "(Sonarr #1886). Profil applique: %s. Envisager DB locale.",
                db_path,
                resolved_profile,
            )
        # AUDIT ULTRA 2026-08 (pragma_profile.py:229-268) : l'audit
        # `pragma_history` est OCCASIONNEL, plus systematique. Il coutait
        # INSERT + SELECT MAX(id) + DELETE de purge + commit a CHAQUE
        # ouverture, alors que `SQLiteStore._managed_conn` ouvre une connexion
        # neuve par appel de repository (mesure locale : 3,9 ms/connexion
        # contre 0,07 ms pour un `sqlite3.connect` nu). On n'ecrit plus qu'au
        # premier boot pour ce chemin DB, ou quand le profil/la source change
        # -- ce qui est exactement ce que l'historique sert a diagnostiquer.
        record_history = should_record_pragma_history(
            str(db_path),
            resolved_profile,
            history_source,
        )
        apply_pragmas(
            conn,
            resolved_profile,
            db_path=str(db_path),
            storage_type_detected=storage_type_detected,
            source=history_source,
            record_history=record_history,
        )

        # 3. Backward compat busy_timeout : si le caller a fourni une valeur
        #    explicite differente du default, elle re-override le PRAGMA pose
        #    par le profil. Sans ca on casse les tests historiques (v7_foundations,
        #    db_robustness) qui s'attendent a un mapping direct kwarg -> PRAGMA.
        if busy_timeout_ms != _DEFAULT_BUSY_TIMEOUT_MS:
            try:
                conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
            except sqlite3.Error as exc:
                logger.warning(
                    "PRAGMA busy_timeout=%d a echoue (%s)",
                    int(busy_timeout_ms),
                    exc,
                )
    except BaseException:
        # En cas d'erreur (profile_name invalide, PRAGMA bloquant, etc.) on
        # libere proprement la connexion pour eviter un file lock orphelin
        # sous Windows (le fichier sqlite reste verrouille tant que la conn
        # n'est pas close).
        conn.close()
        raise

    return conn


def get_mmap_size(conn: sqlite3.Connection) -> int:
    """V3-11 -- Retourne la valeur actuelle de PRAGMA mmap_size (en bytes)."""
    try:
        cur = conn.execute("PRAGMA mmap_size")
        row = cur.fetchone()
        return int(row[0]) if row else 0
    except (sqlite3.Error, ValueError, TypeError):
        return 0
