"""CR-2 audit QA 20260429 — backup automatique de la base SQLite.

Probleme : aucun backup automatique. Une corruption disque (kill pendant
WAL checkpoint, secteur defectueux, AV qui truncate le fichier) detruit
toute la bibliotheque (films matches, decisions, scores, historique).

Solution :
- `backup_db(src, dst)` utilise `sqlite3.Connection.backup()` natif
  (snapshot online sur online connection, fonctionne meme en WAL avec
  des connexions actives).
- `rotate_backups(dir, max_count)` garde les N plus recents, supprime
  le reste.
- Hook AVANT chaque migration au boot (cf SQLiteStore.initialize).
- Hook APRES chaque apply reel (cf apply_support.apply_changes).
- Helper `restore_backup(backup, target)` pour restauration manuelle
  via UI (UI ulterieure).

Naming convention des backups :
    cinesort.{timestamp}.{trigger}.bak
ou trigger ∈ {pre_migration, post_apply, manual}.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import List, Optional, Tuple

_logger = logging.getLogger(__name__)

DEFAULT_MAX_BACKUPS = 5
BACKUP_SUFFIX = ".bak"


def _format_backup_name(stem: str, trigger: str, ts: Optional[float] = None) -> str:
    """Construit le nom du backup : {stem}.{YYYYMMDD-HHMMSS}.{trigger}.bak"""
    t = float(ts if ts is not None else time.time())
    timestr = time.strftime("%Y%m%d-%H%M%S", time.localtime(t))
    return f"{stem}.{timestr}.{trigger}{BACKUP_SUFFIX}"


def backup_db(src_path: Path, dst_path: Path) -> Path:
    """Copie atomique de src_path vers dst_path via sqlite3.Connection.backup().

    L'API natif sqlite3 backup() est plus robuste que shutil.copy car :
    - Acquiert un lock partage approprie.
    - Fonctionne meme en WAL avec ecritures concurrentes.
    - Garantit la coherence de la copie (pas de partial write).

    Cree le dossier parent si besoin. Retourne le chemin du backup cree.
    Leve sqlite3.Error en cas d'echec (caller decide quoi faire).
    """
    src = Path(src_path)
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.is_file():
        raise FileNotFoundError(f"Source DB introuvable pour backup: {src}")

    # On ouvre une connexion sur la source ET sur la destination, puis on
    # demande au moteur SQLite de faire le backup (snapshot online).
    with closing(sqlite3.connect(str(src))) as src_conn, closing(sqlite3.connect(str(dst))) as dst_conn:
        src_conn.backup(dst_conn)
    _logger.info("backup_db: %s -> %s (%.1f KB)", src.name, dst, dst.stat().st_size / 1024)
    return dst


def list_backups(backup_dir: Path, *, stem_filter: Optional[str] = None) -> List[Path]:
    """Liste les backups d'un dossier, tries du plus recent au plus ancien.

    Si stem_filter fourni, ne retourne que les backups dont le nom commence
    par ce stem (ex: "cinesort").
    """
    backup_dir = Path(backup_dir)
    if not backup_dir.is_dir():
        return []
    candidates = list(backup_dir.glob(f"*{BACKUP_SUFFIX}"))
    if stem_filter:
        prefix = f"{stem_filter}."
        candidates = [p for p in candidates if p.name.startswith(prefix)]
    # Tri par mtime decroissant (plus recent d'abord)
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates


def rotate_backups(
    backup_dir: Path,
    *,
    max_count: int = DEFAULT_MAX_BACKUPS,
    stem_filter: Optional[str] = None,
) -> Tuple[int, List[Path]]:
    """Supprime les backups au-dela de max_count, retourne (n_kept, deleted_list).

    Tolerant : si un unlink echoue, on log et on continue.
    """
    if max_count < 1:
        max_count = 1
    backups = list_backups(backup_dir, stem_filter=stem_filter)
    if len(backups) <= max_count:
        return len(backups), []
    to_delete = backups[max_count:]
    deleted: List[Path] = []
    for path in to_delete:
        try:
            path.unlink()
            deleted.append(path)
            _logger.info("rotate_backups: supprime %s", path.name)
        except (OSError, PermissionError) as exc:
            _logger.warning("rotate_backups: unlink %s echoue: %s", path, exc)
    return len(backups) - len(deleted), deleted


def backup_db_with_rotation(
    src_path: Path,
    backup_dir: Path,
    *,
    trigger: str,
    max_count: int = DEFAULT_MAX_BACKUPS,
) -> Optional[Path]:
    """Combine backup + rotation : cree un backup nomme automatiquement
    et nettoie les anciens.

    `trigger` : etiquette ("pre_migration" | "post_apply" | "manual" | ...).

    Retourne le chemin du backup cree, ou None si la source n'existe pas
    (cas fresh install — pas de backup utile).
    Tolere les erreurs sqlite3.Error : log + retourne None plutot que
    bloquer un boot ou un apply.
    """
    src = Path(src_path)
    if not src.is_file():
        _logger.debug("backup_db_with_rotation: source absente, skip (fresh install): %s", src)
        return None

    stem = src.stem  # ex: "cinesort" pour cinesort.sqlite
    backup_name = _format_backup_name(stem, trigger)
    backup_path = Path(backup_dir) / backup_name

    try:
        backup_db(src, backup_path)
    except (sqlite3.Error, OSError, PermissionError) as exc:
        _logger.warning("backup_db_with_rotation: backup echoue (%s): %s", trigger, exc)
        return None

    rotate_backups(backup_dir, max_count=max_count, stem_filter=stem)
    return backup_path


def restore_backup(backup_path: Path, target_path: Path) -> Path:
    """Restaure un backup vers une cible. Si la cible existe, elle est
    elle-meme sauvegardee en {target}.before_restore.{ts}.bak avant
    ecrasement (defense en profondeur).

    Retourne le chemin de la cible apres restore.
    Leve si backup_path n'existe pas.
    """
    backup = Path(backup_path)
    target = Path(target_path)
    if not backup.is_file():
        raise FileNotFoundError(f"Backup introuvable: {backup}")

    # Sauvegarder le target courant avant ecrasement (si existe)
    if target.is_file():
        guard_name = _format_backup_name(target.stem, "before_restore")
        guard_path = target.parent / guard_name
        try:
            backup_db(target, guard_path)
            _logger.info("restore_backup: garde-fou cree %s", guard_path.name)
        except (sqlite3.Error, OSError) as exc:
            _logger.warning("restore_backup: garde-fou impossible: %s", exc)

    # Restore : lit le backup et ecrit dans target via API natif
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(backup))) as src_conn, closing(sqlite3.connect(str(target))) as dst_conn:
        src_conn.backup(dst_conn)
    _logger.info("restore_backup: %s -> %s", backup.name, target)
    return target
