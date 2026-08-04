"""Cache disque JSON pour les probes ffprobe / mediainfo (ITER13 - CACHE_PROBE).

Couche infra strict : N'importe AUCUN module `ui/`, `app/`, `domain/`.

Pourquoi un cache DISQUE en plus du cache DB `probe_cache` (ProbeRepository) :

1. **Resilience SMB/NAS** : sur partage reseau lent, SQLite peut subir
   `BrokenPipeError` ou contention WAL ; le cache disque JSON est independant
   de la DB et survit a une indisponibilite ponctuelle de celle-ci.
2. **Multi-instance / outils externes** : permet a un autre process (ex: scan
   en CLI, debug) de reutiliser les probes sans toucher la DB.
3. **Audit** : un fichier JSON par film est lisible / inspectable directement.

Backward-compat : c'est une COUCHE SECONDAIRE, le cache DB reste autoritatif.
Le cache disque est ecrit en best-effort apres le cache DB et lu en fallback
quand le cache DB rate (miss ou exception). Aucun code existant n'est casse.

Cle de cache : `(path resolu, size, mtime, tool)`. Stockee en hash SHA-256
court (16 hex) comme nom de fichier. Le contenu JSON contient :
    {
        "key": {"path": "...", "size": ..., "mtime": ..., "tool": "..."},
        "raw_json": {...},
        "normalized_json": {...},
        "ts": 1717891200.123,
        "version": 1
    }

Configurable via env `CINESORT_PROBE_DISK_CACHE=0` pour desactiver totalement
(defaut : active). Repertoire : `<state_dir>/cache/probe/<hash>.json`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from cinesort.infra.state import default_state_dir

logger = logging.getLogger(__name__)


# Version du schema JSON cache disque. Bump si la structure change pour
# invalider les anciennes entrees sans wipe explicit.
DISK_CACHE_VERSION = 1

# Cap defensif : un fichier cache > 5 MB est anormal (probes sont quelques KB),
# on refuse de le lire (probable pollution / corruption).
DISK_CACHE_MAX_BYTES = 5 * 1024 * 1024


def _disk_cache_enabled() -> bool:
    """Cache active par defaut. Desactivable via CINESORT_PROBE_DISK_CACHE=0."""
    raw = str(os.environ.get("CINESORT_PROBE_DISK_CACHE", "1")).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _cache_dir() -> Path:
    """Resolve `<state_dir>/cache/probe/`. Override via CINESORT_PROBE_CACHE_DIR."""
    override = os.environ.get("CINESORT_PROBE_CACHE_DIR", "").strip()
    if override:
        return Path(override)
    return default_state_dir() / "cache" / "probe"


def _hash_key(*, path: str, size: int, mtime: float, tool: str) -> str:
    """Hash stable d'une cle de cache. 16 hex = collision negligeable a < 10^10."""
    raw = f"{path}|{size}|{mtime}|{tool}".encode("utf-8")
    return hashlib.sha256(raw, usedforsecurity=False).hexdigest()[:16]


def _entry_path(key_hash: str) -> Path:
    return _cache_dir() / f"{key_hash}.json"


def get_disk_cache(
    *,
    path: str,
    size: int,
    mtime: float,
    tool: str,
) -> Optional[Dict[str, Any]]:
    """Lit une entree cache disque. None si miss / erreur.

    Best-effort : toute exception est avalee (cache OPTIONNEL, ne casse jamais
    le probe).
    """
    if not _disk_cache_enabled():
        return None
    try:
        key_hash = _hash_key(path=path, size=size, mtime=mtime, tool=tool)
        entry = _entry_path(key_hash)
        if not entry.is_file():
            return None
        st = entry.stat()
        if st.st_size > DISK_CACHE_MAX_BYTES:
            logger.warning(
                "Cache probe disque ignore (taille anormale %d > %d) path=%s",
                st.st_size,
                DISK_CACHE_MAX_BYTES,
                entry,
            )
            return None
        with open(entry, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        # Validation legere : version + cle coherente.
        if int(data.get("version", 0)) != DISK_CACHE_VERSION:
            return None
        cached_key = data.get("key")
        if not isinstance(cached_key, dict):
            return None
        # Verification defense en profondeur : si le hash collide ou si
        # quelqu'un a renomme un fichier, on rejette.
        if (
            str(cached_key.get("path", "")) != str(path)
            or int(cached_key.get("size", -1)) != int(size)
            or float(cached_key.get("mtime", -1.0)) != float(mtime)
            or str(cached_key.get("tool", "")) != str(tool)
        ):
            return None
        raw_json = data.get("raw_json")
        normalized_json = data.get("normalized_json")
        if not isinstance(raw_json, dict) or not isinstance(normalized_json, dict):
            return None
        ts_raw = data.get("ts", 0.0)
        try:
            ts = float(ts_raw)
        except (TypeError, ValueError):
            ts = 0.0
        return {
            "path": str(path),
            "size": int(size),
            "mtime": float(mtime),
            "tool": str(tool),
            "raw_json": raw_json,
            "normalized_json": normalized_json,
            "ts": ts,
        }
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.debug("Cache probe disque lecture echouee path=%s err=%s", path, exc)
        return None


def upsert_disk_cache(
    *,
    path: str,
    size: int,
    mtime: float,
    tool: str,
    raw_json: Dict[str, Any],
    normalized_json: Dict[str, Any],
    ts: Optional[float] = None,
) -> bool:
    """Ecrit (ou met a jour) une entree cache disque. Best-effort.

    Returns:
        True si ecriture reussie, False sinon. Le caller peut ignorer le retour.
    """
    if not _disk_cache_enabled():
        return False
    try:
        cache_dir = _cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        key_hash = _hash_key(path=path, size=size, mtime=mtime, tool=tool)
        entry = _entry_path(key_hash)
        payload = {
            "version": DISK_CACHE_VERSION,
            "key": {
                "path": str(path),
                "size": int(size),
                "mtime": float(mtime),
                "tool": str(tool),
            },
            "raw_json": raw_json,
            "normalized_json": normalized_json,
            "ts": float(ts if ts is not None else time.time()),
        }
        # Ecriture atomique : tmp + os.replace pour eviter fichier corrompu
        # si interruption (kill process, panne disque) en cours d'ecriture.
        tmp = entry.with_suffix(f".tmp.{os.getpid()}.{time.time_ns()}")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            # fsync avant os.replace : garantit la durabilite physique sur disque
            # (parite avec tmdb/omdb _save_cache_atomic) pour eviter une entree
            # tronquee promue si crash kernel / panne courant.
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, entry)
        return True
    except (OSError, TypeError, ValueError) as exc:
        logger.debug("Cache probe disque ecriture echouee path=%s err=%s", path, exc)
        # Best-effort cleanup tmp si os.replace a echoue mais tmp existe.
        try:
            if "tmp" in locals() and tmp.exists():  # type: ignore[has-type]
                tmp.unlink()  # type: ignore[has-type]
        except OSError:
            pass
        return False


def clear_disk_cache() -> int:
    """Purge tout le cache disque probe. Retourne le nombre de fichiers supprimes.

    Best-effort : les fichiers en cours d'utilisation (lock Windows) sont
    ignores silencieusement.
    """
    if not _disk_cache_enabled():
        return 0
    removed = 0
    try:
        cache_dir = _cache_dir()
        if not cache_dir.is_dir():
            return 0
        for entry in cache_dir.glob("*.json"):
            try:
                entry.unlink()
                removed += 1
            except OSError:
                continue
    except OSError as exc:
        logger.debug("Cache probe disque purge partielle err=%s", exc)
    return removed


def prune_disk_cache(*, retention_days: int = 90) -> int:
    """Supprime les entrees cache disque non-touchees depuis `retention_days`.

    Symetrique de `ProbeRepository.prune_probe_cache` cote DB. Best-effort.
    """
    if not _disk_cache_enabled():
        return 0
    retention = max(1, int(retention_days))
    cutoff = time.time() - (retention * 24 * 3600)
    removed = 0
    try:
        cache_dir = _cache_dir()
        if not cache_dir.is_dir():
            return 0
        for entry in cache_dir.glob("*.json"):
            try:
                if entry.stat().st_mtime < cutoff:
                    entry.unlink()
                    removed += 1
            except OSError:
                continue
    except OSError as exc:
        logger.debug("Cache probe disque prune partielle err=%s", exc)
    return removed
