from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

# V3-11 -- mmap_size pour perf lecture sur grosses DB (>50 MB).
# 256 MB est un bon compromis : suffisant pour bibliotheques 10k films,
# mais ne reserve l'espace que si la DB l'utilise (mmap virtuel).
_MMAP_SIZE_BYTES = 256 * 1024 * 1024  # 256 MB


def connect_sqlite(db_path: str, *, busy_timeout_ms: int = 5000) -> sqlite3.Connection:
    """Create a configured SQLite connection with WAL, foreign keys, and busy timeout."""
    conn = sqlite3.connect(
        str(db_path),
        timeout=max(1.0, busy_timeout_ms / 1000.0),
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
    conn.execute("PRAGMA journal_mode = WAL")
    # synchronous = NORMAL est le mode canonique pour WAL : conserve la durabilite
    # entre deux checkpoints sans la penalite d'un fsync a chaque commit (~30% gain).
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    # 64 MB de cache page (valeur signee negative = KB). Evite le thrashing sur
    # les agregations de quality_reports / perceptual_reports > ~10k films.
    conn.execute("PRAGMA cache_size = -65536")
    # Tables temporaires en memoire plutot qu'en fichier disque.
    conn.execute("PRAGMA temp_store = MEMORY")
    # V3-11 -- mmap_size : memory-mapped I/O pour les lectures sur grosses DB.
    # Sur certains systemes (sans support mmap) le PRAGMA peut echouer : non bloquant.
    try:
        conn.execute(f"PRAGMA mmap_size = {_MMAP_SIZE_BYTES}")
    except sqlite3.DatabaseError as e:
        logger.warning("V3-11 : PRAGMA mmap_size non supporte (%s). Mode standard.", e)
    return conn


def get_mmap_size(conn: sqlite3.Connection) -> int:
    """V3-11 -- Retourne la valeur actuelle de PRAGMA mmap_size (en bytes)."""
    try:
        cur = conn.execute("PRAGMA mmap_size")
        row = cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0
