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
MAX_BACKUP_ATTEMPTS = 10000


def _format_backup_name(stem: str, trigger: str, ts: Optional[float] = None) -> str:
    """Construit le nom du backup : {stem}.{YYYYMMDD-HHMMSS-NNNNNN}Z.{trigger}.bak

    Cf issue #81 (audit-2026-05-12:b1c3) :
    - `gmtime` (UTC) plutot que `localtime` evite les collisions de noms a
      chaque changement DST (le 31 octobre 2h heure d'ete = 1h heure d'hiver,
      memes timestamps formattes deux fois).
    - Suffixe `Z` marque explicitement le fuseau UTC dans le nom.
    - Microsecondes (`NNNNNN`, 6 chiffres) garantissent l'unicite meme
      lorsque deux backups sont declenches dans la meme seconde (cas typique :
      backup pre-migration + post-apply en moins d'une seconde au boot).
    """
    t = float(ts if ts is not None else time.time())
    timestr = time.strftime("%Y%m%d-%H%M%S", time.gmtime(t))
    micros = int(round((t - int(t)) * 1_000_000)) % 1_000_000
    return f"{stem}.{timestr}-{micros:06d}Z.{trigger}{BACKUP_SUFFIX}"


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
    # Tri par mtime decroissant (plus recent d'abord), avec le nom de fichier
    # en cle secondaire (decroissante elle aussi : le nom contient le timestamp
    # formate donc l'ordre alphabetique des noms correspond a l'ordre temporel).
    # Pourquoi la cle secondaire : sur Windows, st_mtime peut etre identique
    # entre plusieurs backups crees a < 15 ms d'intervalle (granularite du
    # timer systeme), ce qui rendait l'ordre non-deterministe et faisait
    # supprimer/retourner le mauvais fichier en rotation.
    candidates.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
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
        # Issue #382 : sur Windows, AV (Defender, Avast) ou Volume Shadow Copy
        # peuvent tenir un handle transitoire sur le .bak. Retry court (3
        # tentatives, 50/150/300 ms) couvre les fenetres typiques AV sans
        # bloquer le scan. Au-dela, on log warning et on accepte que la
        # rotation soit incomplete ce cycle (sera rejouee au prochain).
        last_exc: Optional[BaseException] = None
        for attempt, delay_s in enumerate((0.0, 0.05, 0.15, 0.3)):
            if delay_s:
                time.sleep(delay_s)
            try:
                path.unlink()
                deleted.append(path)
                _logger.info("rotate_backups: supprime %s", path.name)
                last_exc = None
                break
            except PermissionError as exc:
                last_exc = exc
                continue
            except OSError as exc:
                last_exc = exc
                break
        if last_exc is not None:
            _logger.warning("rotate_backups: unlink %s echoue apres %d tentatives: %s", path, attempt + 1, last_exc)
    return len(backups) - len(deleted), deleted


def _resolve_unique_backup_path(backup_dir: Path, base_name: str) -> Path:
    """Retourne un chemin unique dans `backup_dir` derive de `base_name`.

    Si `base_name` n'existe pas, retourne `backup_dir/base_name`. Sinon insere
    un suffixe `-N` (1, 2, ...) avant le `.bak` final jusqu'a trouver un nom
    libre.

    Pourquoi : sur Windows, `time.time()` a une granularite du timer systeme
    d'environ 15 ms (et `time.time_ns()` aussi). Plusieurs backups declenches
    dans la meme tranche de 15 ms partagent les memes microsecondes formatees
    et donc le meme nom — la seconde ecriture ecrase silencieusement la
    premiere, ce qui fait perdre un backup. Ce helper garantit qu'aucun
    backup precedent ne sera ecrase, meme en rafale.
    """
    candidate = Path(backup_dir) / base_name
    if not candidate.exists():
        return candidate
    # Insere `-N` avant le suffixe .bak (preserve l'extension et le tri par nom)
    if base_name.endswith(BACKUP_SUFFIX):
        stem_part = base_name[: -len(BACKUP_SUFFIX)]
    else:
        stem_part = base_name
    counter = 1
    while counter <= MAX_BACKUP_ATTEMPTS:
        alt_name = f"{stem_part}-{counter}{BACKUP_SUFFIX}"
        alt = Path(backup_dir) / alt_name
        if not alt.exists():
            return alt
        counter += 1
    raise RuntimeError(
        f"Aucun nom de backup libre apres {MAX_BACKUP_ATTEMPTS} essais dans {backup_dir}"
    )


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
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = _resolve_unique_backup_path(backup_dir, backup_name)

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
