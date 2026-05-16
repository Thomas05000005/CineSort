from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Set, Tuple

import cinesort.domain.core as core_mod
from cinesort.app.cleanup import (
    _move_empty_top_level_dirs,
    _move_residual_top_level_dirs,
    preview_cleanup_residual_folders,
)
from cinesort.app.move_journal import atomic_move
from cinesort.domain.naming import build_naming_context, format_movie_folder, format_tv_series_folder

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cinesort.domain.core import ApplyExecutionContext, ApplyResult, Config, PlanRow


def build_apply_context(
    cfg: "Config",
    rows: list["PlanRow"],
    *,
    dry_run: bool,
    quarantine_unapproved: bool,
    run_review_root: Optional[Path],
    decision_presence: Optional[Set[str]],
) -> "ApplyExecutionContext":
    """Construit le contexte d'exécution apply (cfg normalisée, buckets review, cache hash).

    Crée à la volée les sous-dossiers `_review/_conflicts`, `_conflicts_sidecars`,
    `_duplicates_identical` et `_leftovers` (sauf en dry_run).
    """
    cfg = cfg.normalized()
    res = core_mod.ApplyResult()
    res.total_rows = len(rows)
    res.considered_rows = len(rows)
    decision_keys = set(decision_presence or set())
    hash_cache: Dict[Tuple[str, int, int], str] = {}

    review_root = cfg.root / "_review"
    merge_review_root = run_review_root if run_review_root is not None else (cfg.root / "_review")
    conflicts_root = merge_review_root / "_conflicts"
    conflicts_sidecars_root = merge_review_root / "_conflicts_sidecars"
    duplicates_identical_root = merge_review_root / "_duplicates_identical"
    leftovers_root = merge_review_root / "_leftovers"

    if quarantine_unapproved and (not dry_run):
        review_root.mkdir(parents=True, exist_ok=True)
    if not dry_run:
        conflicts_root.mkdir(parents=True, exist_ok=True)
        conflicts_sidecars_root.mkdir(parents=True, exist_ok=True)
        duplicates_identical_root.mkdir(parents=True, exist_ok=True)
        leftovers_root.mkdir(parents=True, exist_ok=True)

    return core_mod.ApplyExecutionContext(
        cfg=cfg,
        res=res,
        decision_keys=decision_keys,
        hash_cache=hash_cache,
        review_root=review_root,
        conflicts_root=conflicts_root,
        conflicts_sidecars_root=conflicts_sidecars_root,
        duplicates_identical_root=duplicates_identical_root,
        leftovers_root=leftovers_root,
    )


def record_apply_op(
    record_op: Optional[Callable[[Dict[str, Any]], None]],
    *,
    op_type: str,
    src_path: Path,
    dst_path: Path,
    reversible: bool = True,
    row_id: str = "",
    src_sha1: Optional[str] = None,
    src_size: Optional[int] = None,
) -> bool:
    """Journalise une operation apply. Retourne False si l'enregistrement echoue.

    P1.2 : `src_sha1` et `src_size` optionnels — calcules par l'appelant avant
    le move pour permettre a l'undo de verifier que le fichier n'a pas ete
    remplace manuellement entre temps.
    """
    import time

    if record_op is None:
        return True
    try:
        payload: Dict[str, Any] = {
            "op_type": str(op_type or "MOVE"),
            "src_path": str(src_path),
            "dst_path": str(dst_path),
            "reversible": bool(reversible),
            "ts": float(time.time()),
            "row_id": str(row_id or ""),
        }
        if src_sha1:
            payload["src_sha1"] = str(src_sha1)
        if src_size is not None:
            payload["src_size"] = int(src_size)
        record_op(payload)
        return True
    except (TypeError, ValueError, OSError) as e:
        _logger.error("record_apply_op: echec journalisation %s src=%s: %s", op_type, src_path, e, exc_info=True)
        return False


def is_managed_merge_file(cfg: "Config", path: Path) -> bool:
    """Indique si le fichier doit être pris en compte lors d'un merge (vidéo ou sidecar)."""
    ext = path.suffix.lower()
    return (ext in cfg.video_exts) or (ext in cfg.side_exts)


def is_sidecar_metadata(cfg: "Config", path: Path) -> bool:
    """Indique si `path` est un sidecar de métadonnées (nfo/srt/jpg/...) plutôt qu'une vidéo."""
    ext = path.suffix.lower()
    if ext in cfg.video_exts or ext in core_mod.VIDEO_EXTS_ALL:
        return False
    if ext in core_mod.SIDECAR_METADATA_EXTS:
        return True
    return path.name.lower() in core_mod.SIDECAR_METADATA_BASENAMES


def find_main_video_in_folder(folder: Path, cfg: "Config") -> Optional[Path]:
    """P1.2 : retourne le plus gros fichier video dans `folder` (non recursif).

    Utilise pour identifier le film principal a hasher lors d'un MOVE_DIR —
    les sidecars (nfo, srt, images) sont ignores. Retourne None si aucun video.
    """
    if not folder.is_dir():
        return None
    # Phase 6 v7.8.0 : utilise constante unifiee VIDEO_EXTS_ALL
    video_exts = set(cfg.video_exts) | core_mod.VIDEO_EXTS_ALL
    best: Optional[Path] = None
    best_size = 0
    try:
        for entry in folder.iterdir():
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in video_exts:
                continue
            try:
                size = entry.stat().st_size
            except (OSError, PermissionError):
                continue
            if size > best_size:
                best = entry
                best_size = size
    except (OSError, PermissionError):
        return None
    return best


def sha1_quick(path: Path) -> str:
    """Fast fingerprint: SHA-1 of the first 8 MB + last 8 MB (or full file if smaller)."""
    digest = hashlib.sha1()
    size = path.stat().st_size
    chunk_8m = 8 * 1024 * 1024
    with path.open("rb") as file_obj:
        if size < (2 * chunk_8m):
            while True:
                block = file_obj.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
        else:
            digest.update(file_obj.read(chunk_8m))
            file_obj.seek(max(0, size - chunk_8m))
            digest.update(file_obj.read(chunk_8m))
    return digest.hexdigest()


def quick_hash_cache_key(path: Path) -> Optional[Tuple[str, int, int]]:
    """Construit la clef de cache (path, size, mtime_ns) pour `sha1_quick_cached`.

    Renvoie None si `stat()` échoue (fichier disparu, permissions).
    """
    try:
        stat_result = path.stat()
    except (OSError, PermissionError):
        return None
    mtime_ns = int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000)))
    return (str(path), int(stat_result.st_size), mtime_ns)


def sha1_quick_cached(path: Path, cache: Optional[Dict[Tuple[str, int, int], str]]) -> str:
    """Variante mémoïsée de `sha1_quick` (clef = path/size/mtime_ns)."""
    if cache is None:
        return sha1_quick(path)
    key = quick_hash_cache_key(path)
    if key is None:
        return sha1_quick(path)
    existing = cache.get(key)
    if existing:
        return existing
    value = sha1_quick(path)
    cache[key] = value
    return value


def files_identical_quick(
    src: Path,
    dst: Path,
    *,
    hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
) -> bool:
    """Compare deux fichiers via taille + `sha1_quick` (False si lecture échoue)."""
    try:
        if src.stat().st_size != dst.stat().st_size:
            return False
        return sha1_quick_cached(src, hash_cache) == sha1_quick_cached(dst, hash_cache)
    except (OSError, PermissionError):
        return False


def unique_path(base: Path) -> Path:
    """Retourne `base` ou la première variante `_2`, `_3`... non existante."""
    if not base.exists():
        return base
    stem = base.stem
    suffix = base.suffix
    idx = 2
    while True:
        candidate = base.with_name(f"{stem}_{idx}{suffix}")
        if not candidate.exists():
            return candidate
        idx += 1


def unique_path_dup(base: Path) -> Path:
    """Retourne `base` ou la première variante `__DUP1`, `__DUP2`... non existante."""
    if not base.exists():
        return base
    stem = base.stem
    suffix = base.suffix
    idx = 1
    while True:
        candidate = base.with_name(f"{stem}__DUP{idx}{suffix}")
        if not candidate.exists():
            return candidate
        idx += 1


def mkdir_counted(
    path: Path,
    *,
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    record_op_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> None:
    """Crée `path` (parents inclus) et incrémente `res.mkdirs` (no-op si existe ou dry_run)."""
    if path.exists():
        return
    log("INFO", f"MKDIR: {path}")
    if not dry_run:
        path.mkdir(parents=True, exist_ok=True)
        record_apply_op(
            record_op_fn,
            op_type="MKDIR",
            src_path=path,
            dst_path=path,
            reversible=False,
        )
    res.mkdirs += 1


def prune_empty_dirs(root: Path) -> bool:
    """Supprime tous les sous-dossiers vides puis `root` lui-même si vide.

    Renvoie True si au moins un dossier a été supprimé. Les erreurs OS sont
    ignorées (skip silencieux).
    """
    if not root.exists() or not root.is_dir():
        return False
    removed_any = False
    for directory in sorted(
        [path for path in root.rglob("*") if path.is_dir()], key=lambda path: len(path.parts), reverse=True
    ):
        try:
            if not any(directory.iterdir()):
                directory.rmdir()
                removed_any = True
        except (OSError, PermissionError) as exc:
            _logger.debug("prune_empty_dirs: skip %s: %s", directory, exc)
    try:
        if root.exists() and root.is_dir() and (not any(root.iterdir())):
            root.rmdir()
            removed_any = True
    except (OSError, PermissionError) as exc:
        _logger.debug("prune_empty_dirs: skip root %s: %s", root, exc)
    return removed_any


def is_dir_empty(path: Path) -> bool:
    """True si `path` est un dossier existant et strictement vide."""
    if not path.exists() or not path.is_dir():
        return False
    try:
        next(path.iterdir())
        return False
    except StopIteration:
        return True
    except (OSError, PermissionError):
        return False


def legacy_collection_root(cfg: "Config") -> Path:
    """Chemin de l'ancien dossier `Collection` (pré-renommage configurable)."""
    return cfg.root / "Collection"


def resolve_collection_folder_after_migration(cfg: "Config", folder: Path) -> Path:
    """Réécrit un chemin pointant sur l'ancien `Collection` vers le nouveau nom configuré.

    Renvoie `folder` inchangé s'il existe, si la migration n'est pas applicable
    ou si le nouveau chemin n'existe pas.
    """
    if folder.exists():
        return folder
    if not cfg.enable_collection_folder:
        return folder
    legacy_root = legacy_collection_root(cfg)
    target_root = cfg.root / cfg.collection_root_name
    if legacy_root.name.lower() == target_root.name.lower():
        return folder
    try:
        rel = folder.relative_to(legacy_root)
    except (ValueError, TypeError):
        return folder
    migrated = target_root / rel
    return migrated if migrated.exists() else folder


def migrate_legacy_collection_root(
    cfg: "Config",
    *,
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    conflicts_root: Path,
    conflicts_sidecars_root: Path,
    duplicates_identical_root: Path,
    leftovers_root: Path,
    hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> None:
    """Migre l'ancien dossier `Collection` vers le nom configuré (`collection_root_name`).

    No-op si désactivé, si l'ancien dossier n'existe pas ou si les noms coïncident.
    En cas de cible existante, fusionne via `merge_dir_safe` plutôt que d'écraser.
    """
    if not cfg.enable_collection_folder:
        return
    target_root = cfg.root / cfg.collection_root_name
    legacy_root = legacy_collection_root(cfg)
    if legacy_root.name.lower() == target_root.name.lower():
        return
    if not legacy_root.exists():
        return
    if not legacy_root.is_dir():
        log("WARN", f"MIGRATION Collection ignoree (pas un dossier): {legacy_root}")
        return
    core_mod.ensure_inside_root(cfg, target_root)

    if not target_root.exists():
        log("INFO", f"MIGRATION Collection -> {cfg.collection_root_name}: {legacy_root} -> {target_root}")
        if not dry_run:
            legacy_root.rename(target_root)
            record_apply_op(
                record_op,
                op_type="MOVE_DIR",
                src_path=legacy_root,
                dst_path=target_root,
                reversible=True,
            )
        return

    if not target_root.is_dir():
        log("WARN", f"MIGRATION Collection impossible (cible invalide): {target_root}")
        return

    log("INFO", f"MIGRATION MERGE Collection -> {cfg.collection_root_name}: {legacy_root} -> {target_root}")
    merge_dir_safe(
        cfg,
        legacy_root,
        target_root,
        dry_run=dry_run,
        log=log,
        res=res,
        conflicts_root=conflicts_root,
        conflicts_sidecars_root=conflicts_sidecars_root,
        duplicates_identical_root=duplicates_identical_root,
        leftovers_root=leftovers_root,
        hash_cache=hash_cache,
        record_op=record_op,
    )


def move_to_review_bucket(
    src_file: Path,
    *,
    src_anchor: Path,
    bucket_root: Path,
    bucket_name: str,
    include_anchor_name: bool,
    use_dup_suffix: bool,
    rel_override: Optional[Path],
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Optional[Path]:
    """Déplace `src_file` dans un sous-dossier de `_review` (conflits/duplicates/leftovers).

    Calcule le chemin destination en préservant la hiérarchie relative à `src_anchor`,
    applique le suffixe `_2` ou `__DUP1` si collision, journalise et retourne le path final.
    """
    if rel_override is not None:
        rel = rel_override
    else:
        try:
            rel = src_file.relative_to(src_anchor)
        except (ValueError, TypeError):
            rel = Path(src_file.name)
    if include_anchor_name:
        dst = bucket_root / core_mod.windows_safe(src_anchor.name) / rel
    else:
        dst = bucket_root / rel
    dst = unique_path_dup(dst) if use_dup_suffix else unique_path(dst)
    msg = f"{bucket_name}: {src_file} -> {dst}"
    log("WARN" if bucket_name == "CONFLICT quarantined" else "INFO", msg)
    source_is_file = src_file.is_file()
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        op_type_str = "QUARANTINE_FILE" if source_is_file else "QUARANTINE_DIR"

        atomic_move(record_op, src=src_file, dst=dst, op_type=op_type_str)
        record_apply_op(
            record_op,
            op_type=op_type_str,
            src_path=src_file,
            dst_path=dst,
            reversible=True,
        )
    return dst


def safe_relative_context(cfg: "Config", path: Path) -> Path:
    """Construit un chemin relatif sûr (Windows-safe) à partir de la racine config."""
    try:
        rel = path.relative_to(cfg.root)
    except (ValueError, TypeError):
        rel = Path(core_mod.windows_safe(path.name))
    parts = [core_mod.windows_safe(part) for part in rel.parts if part not in {"", ".", ".."}]
    return Path(*parts) if parts else Path("_root")


def conflict_context(cfg: "Config", src_anchor: Path, dst_file: Path) -> Path:
    """Construit le sous-chemin `dst_ctx/__from__/src_ctx` utilisé pour bucketiser un conflit."""
    dst_ctx = safe_relative_context(cfg, dst_file.parent)
    src_ctx = safe_relative_context(cfg, src_anchor)
    return dst_ctx / "__from__" / src_ctx


def move_file_with_collision_policy(
    cfg: "Config",
    src_file: Path,
    dst_file: Path,
    *,
    src_anchor: Path,
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    conflicts_root: Path,
    conflicts_sidecars_root: Path,
    duplicates_identical_root: Path,
    hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> str:
    """Déplace `src_file` vers `dst_file` en appliquant la politique de collision.

    Renvoie un statut : `moved`, `conflict`, `duplicate_identical` ou
    `sidecar_conflict`. Calcule sha1+size avant le move pour les vidéos (P1.2/P1.3),
    journalise l'opération même en dry_run pour la preview UI.
    """
    core_mod.ensure_inside_root(cfg, dst_file)
    if dst_file.exists():
        ctx = conflict_context(cfg, src_anchor, dst_file)
        conflicts_ctx_root = conflicts_root / ctx
        sidecars_ctx_root = conflicts_sidecars_root / ctx
        duplicates_ctx_root = duplicates_identical_root / ctx
        if not dst_file.is_file():
            move_to_review_bucket(
                src_file,
                src_anchor=src_anchor,
                bucket_root=conflicts_ctx_root,
                bucket_name="CONFLICT quarantined",
                include_anchor_name=False,
                use_dup_suffix=False,
                rel_override=None,
                dry_run=dry_run,
                log=log,
                res=res,
                record_op=record_op,
            )
            res.conflicts_quarantined_count += 1
            res.quarantined += 1
            return "conflict"

        if files_identical_quick(src_file, dst_file, hash_cache=hash_cache):
            moved_to = move_to_review_bucket(
                src_file,
                src_anchor=src_anchor,
                bucket_root=duplicates_ctx_root,
                bucket_name="DUPLICATE_IDENTICAL moved to _review/_duplicates_identical",
                include_anchor_name=False,
                use_dup_suffix=True,
                rel_override=None,
                dry_run=dry_run,
                log=log,
                res=res,
                record_op=record_op,
            )
            if moved_to is not None:
                log("INFO", f"DUPLICATE_IDENTICAL moved to _review/_duplicates_identical: {moved_to}")
            res.duplicates_identical_moved_count += 1
            res.duplicates_identical_deleted_count += 1
            return "duplicate_identical"

        if is_sidecar_metadata(cfg, src_file):
            try:
                hash8 = sha1_quick_cached(src_file, hash_cache)[:8]
            except (OSError, PermissionError):
                hash8 = "unknown000"
            sidecar_name = f"{src_file.stem}.incoming_{hash8}{src_file.suffix}"
            try:
                sidecar_rel = src_file.relative_to(src_anchor).with_name(sidecar_name)
            except (ValueError, TypeError):
                sidecar_rel = Path(sidecar_name)
            sidecar_dst = move_to_review_bucket(
                src_file,
                src_anchor=src_anchor,
                bucket_root=sidecars_ctx_root,
                bucket_name="SIDECAR CONFLICT kept both",
                include_anchor_name=False,
                use_dup_suffix=False,
                rel_override=sidecar_rel,
                dry_run=dry_run,
                log=log,
                res=res,
                record_op=record_op,
            )
            if sidecar_dst is not None:
                log("INFO", f"SIDECAR CONFLICT kept both: {src_file} -> {sidecar_dst} (dst kept: {dst_file})")
            res.sidecar_conflicts_kept_both_count += 1
            res.conflicts_sidecars_quarantined_count += 1
            return "sidecar_conflict"

        qdst = move_to_review_bucket(
            src_file,
            src_anchor=src_anchor,
            bucket_root=conflicts_ctx_root,
            bucket_name="CONFLICT quarantined",
            include_anchor_name=False,
            use_dup_suffix=False,
            rel_override=None,
            dry_run=dry_run,
            log=log,
            res=res,
            record_op=record_op,
        )
        log("WARN", f"CONFLICT: {src_file} would overwrite {dst_file} -> {qdst}")
        res.conflicts_quarantined_count += 1
        res.quarantined += 1
        return "conflict"

    mkdir_counted(dst_file.parent, dry_run=dry_run, log=log, res=res, record_op_fn=record_op)
    log("INFO", f"MOVE: {src_file} -> {dst_file}")

    # P1.2 + P1.3 : capturer sha1 + taille avant le move (seulement apply réel — pas en dry_run).
    src_sha1: Optional[str] = None
    src_size: Optional[int] = None
    if not dry_run:
        ext = src_file.suffix.lower()
        # Phase 6 v7.8.0 : VIDEO_EXTS_ALL au lieu du set hardcode (4eme copie eliminee)
        is_video = (ext in cfg.video_exts) or (ext in core_mod.VIDEO_EXTS_ALL)
        if is_video:
            try:
                src_size = src_file.stat().st_size
                src_sha1 = sha1_quick_cached(src_file, hash_cache)
            except (OSError, PermissionError) as exc:
                _logger.debug("P1.2: sha1 pre-apply echoue pour %s: %s", src_file, exc)
                src_sha1 = None
                src_size = None

        atomic_move(
            record_op,
            src=src_file,
            dst=dst_file,
            op_type="MOVE_FILE",
            src_sha1=src_sha1,
            src_size=src_size,
        )

    # P1.3 : record l'op même en dry_run pour que la preview puisse la remonter à l'UI.
    record_apply_op(
        record_op,
        op_type="MOVE_FILE",
        src_path=src_file,
        dst_path=dst_file,
        reversible=True,
        src_sha1=src_sha1,
        src_size=src_size,
    )
    res.moves += 1
    return "moved"


def merge_dir_safe(
    cfg: "Config",
    src_dir: Path,
    dst_dir: Path,
    *,
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    conflicts_root: Path,
    conflicts_sidecars_root: Path,
    duplicates_identical_root: Path,
    leftovers_root: Path,
    hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> None:
    """Fusionne `src_dir` dans `dst_dir` fichier par fichier (sans écrasement destructif).

    Délègue chaque fichier à `move_file_with_collision_policy`, puis envoie les
    fichiers non gérés (non-vidéo/non-sidecar) dans `_review/_leftovers` et tente
    de purger l'arborescence source vidée.
    """
    if not src_dir.exists():
        core_mod._mark_skip(res, core_mod.SKIP_REASON_MERGED)
        log("WARN", f"MERGE source missing, skip: {src_dir}")
        return
    if not dst_dir.exists():
        mkdir_counted(dst_dir, dry_run=dry_run, log=log, res=res, record_op_fn=record_op)
    if not dst_dir.is_dir():
        res.errors += 1
        log("ERROR", f"MERGE target invalid (not directory): {dst_dir}")
        return

    log("INFO", f"MERGE_DIR: {src_dir} -> {dst_dir}")
    res.merges_count += 1

    all_files = [path for path in src_dir.rglob("*") if path.is_file()]
    handled_for_leftovers: Set[Path] = set()

    for src_file in all_files:
        if not is_managed_merge_file(cfg, src_file):
            continue
        rel = src_file.relative_to(src_dir)
        dst_file = dst_dir / rel
        status = move_file_with_collision_policy(
            cfg,
            src_file,
            dst_file,
            src_anchor=src_dir,
            dry_run=dry_run,
            log=log,
            res=res,
            conflicts_root=conflicts_root,
            conflicts_sidecars_root=conflicts_sidecars_root,
            duplicates_identical_root=duplicates_identical_root,
            hash_cache=hash_cache,
            record_op=record_op,
        )
        if status in {"moved", "conflict", "duplicate_identical", "sidecar_conflict"}:
            handled_for_leftovers.add(src_file)
        if status == "duplicate_identical":
            core_mod._mark_skip(res, core_mod.SKIP_REASON_NOOP_DEJA_CONFORME)
        elif status in {"conflict", "sidecar_conflict"}:
            core_mod._mark_skip(res, core_mod.SKIP_REASON_CONFLIT_QUARANTAINE)

    if dry_run:
        leftover_files = [path for path in all_files if path not in handled_for_leftovers]
        for leftover_file in leftover_files:
            try:
                rel = leftover_file.relative_to(src_dir)
            except (ValueError, TypeError):
                rel = Path(leftover_file.name)
            planned = unique_path(leftovers_root / core_mod.windows_safe(src_dir.name) / rel)
            log("INFO", f"LEFTOVERS planned: {leftover_file} -> {planned}")
        res.leftovers_moved_count += len(leftover_files)
        if len(leftover_files) == 0:
            res.source_dirs_deleted_count += 1
        return

    remaining_files = [path for path in src_dir.rglob("*") if path.is_file()]
    for src_file in remaining_files:
        move_to_review_bucket(
            src_file,
            src_anchor=src_dir,
            bucket_root=leftovers_root,
            bucket_name="LEFTOVERS moved",
            include_anchor_name=True,
            use_dup_suffix=False,
            rel_override=None,
            dry_run=dry_run,
            log=log,
            res=res,
            record_op=record_op,
        )
        res.leftovers_moved_count += 1

    if prune_empty_dirs(src_dir):
        res.source_dirs_deleted_count += 1


def move_collection_folder(
    cfg: "Config",
    folder: Path,
    *,
    dry_run: bool,
    log: Callable[[str, str], None],
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Path:
    """Déplace un dossier de film sous `<root>/<collection_root_name>/`.

    No-op si `enable_collection_folder` est désactivé, si déjà sous la racine
    Collection ou si la cible existe déjà. Renvoie le nouveau chemin (ou le
    même si pas déplacé).
    """
    if not cfg.enable_collection_folder:
        return folder
    if core_mod.is_under_collection_root(cfg, folder):
        return folder

    target = cfg.root / cfg.collection_root_name / core_mod.windows_safe(folder.name)
    core_mod.ensure_inside_root(cfg, target)

    if target.exists():
        log("WARN", f"Collection dest exists, skip move: {target}")
        return folder

    log("INFO", f"Move collection folder: {folder} -> {target}")
    if not dry_run:
        (cfg.root / cfg.collection_root_name).mkdir(parents=True, exist_ok=True)
        atomic_move(record_op, src=folder, dst=target, op_type="MOVE_DIR")
        record_apply_op(
            record_op,
            op_type="MOVE_DIR",
            src_path=folder,
            dst_path=target,
            reversible=True,
        )
    return target


# 259L : orchestrateur principal apply — boucle lineaire sur chaque row
# avec dispatch par kind (single/collection/tv). Decoupage non trivial
# sans perte de cohesion (cfg/dry_run/record_op/log_fn partagés).
def apply_rows(
    cfg: "Config",
    rows: list["PlanRow"],
    decisions: Dict[str, Dict[str, object]],
    *,
    dry_run: bool,
    quarantine_unapproved: bool,
    log: Callable[[str, str], None],
    run_review_root: Optional[Path] = None,
    decision_presence: Optional[Set[str]] = None,
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> "ApplyResult":
    """Execute the rename/move plan: process each approved row, handle merges, conflicts, quarantine, and cleanup."""
    _logger.info("apply: %d rows a traiter (dry_run=%s)", len(rows), dry_run)
    ctx = build_apply_context(
        cfg,
        rows,
        dry_run=dry_run,
        quarantine_unapproved=quarantine_unapproved,
        run_review_root=run_review_root,
        decision_presence=decision_presence,
    )
    cfg = ctx.cfg
    res = ctx.res
    migrate_legacy_collection_root(
        cfg,
        dry_run=dry_run,
        log=log,
        res=res,
        conflicts_root=ctx.conflicts_root,
        conflicts_sidecars_root=ctx.conflicts_sidecars_root,
        duplicates_identical_root=ctx.duplicates_identical_root,
        leftovers_root=ctx.leftovers_root,
        hash_cache=ctx.hash_cache,
        record_op=record_op,
    )

    for row in rows:
        if row.kind != "collection":
            continue
        original_folder = Path(row.folder)
        if original_folder.parent == cfg.root:
            ctx.touched_top_level_dirs.add(original_folder)

        old_folder = resolve_collection_folder_after_migration(cfg, original_folder)
        if str(original_folder) in ctx.folder_map:
            continue
        if cfg.enable_collection_folder and (not core_mod.is_under_collection_root(cfg, old_folder)):
            target = cfg.root / cfg.collection_root_name / core_mod.windows_safe(old_folder.name)
            core_mod.ensure_inside_root(cfg, target)
            if target.exists():
                if target.is_dir():
                    merge_dir_safe(
                        cfg,
                        old_folder,
                        target,
                        dry_run=dry_run,
                        log=log,
                        res=res,
                        conflicts_root=ctx.conflicts_root,
                        conflicts_sidecars_root=ctx.conflicts_sidecars_root,
                        duplicates_identical_root=ctx.duplicates_identical_root,
                        leftovers_root=ctx.leftovers_root,
                        hash_cache=ctx.hash_cache,
                        record_op=record_op,
                    )
                    ctx.folder_map[str(original_folder)] = str(old_folder) if dry_run else str(target)
                    res.collection_moves += 1
                else:
                    log("WARN", f"Collection destination invalid (file), skip merge: {target}")
                    ctx.folder_map[str(original_folder)] = str(old_folder)
                    core_mod._mark_skip(res, core_mod.SKIP_REASON_AUTRE)
            else:
                # Appel local (fonction definie dans ce meme module) au lieu
                # de passer par core_mod.move_collection_folder qui etait un
                # re-export backward-compat — cf #83 phase A4.
                new_folder = move_collection_folder(
                    cfg,
                    old_folder,
                    dry_run=dry_run,
                    log=log,
                    record_op=record_op,
                )
                if str(new_folder) != str(old_folder):
                    ctx.folder_map[str(original_folder)] = str(old_folder) if dry_run else str(new_folder)
                    res.collection_moves += 1
                else:
                    ctx.folder_map[str(original_folder)] = str(old_folder)
        else:
            ctx.folder_map[str(original_folder)] = str(old_folder)

    def current_folder_path(folder_str: str) -> Path:
        """Retourne le chemin courant d'un folder en tenant compte des moves déjà appliqués."""
        return Path(ctx.folder_map.get(folder_str, folder_str))

    for row in rows:
        dec = decisions.get(row.row_id, {})
        ok = bool(dec.get("ok", False))
        new_title = (dec.get("title") or row.proposed_title).strip()
        new_year = int(dec.get("year") or row.proposed_year)

        folder = current_folder_path(row.folder)
        if folder.parent == cfg.root:
            ctx.touched_top_level_dirs.add(folder)

        # Wrap record_op to inject row_id for Undo v5 traceability.
        row_record_op = None
        if record_op is not None:
            _current_row_id = str(row.row_id or "")

            def row_record_op(payload: Dict[str, Any]) -> None:
                """Wrapper qui injecte `row_id` dans le payload pour la traçabilité Undo v5."""
                if isinstance(payload, dict) and not payload.get("row_id"):
                    payload["row_id"] = _current_row_id
                record_op(payload)

        try:
            if ok:
                pre_actions = (
                    res.renames,
                    res.moves,
                    res.mkdirs,
                    res.collection_moves,
                    res.quarantined,
                    res.merges_count,
                    res.duplicates_identical_moved_count,
                    res.conflicts_quarantined_count,
                    res.sidecar_conflicts_kept_both_count,
                    res.leftovers_moved_count,
                    res.source_dirs_deleted_count,
                )
                pre_skipped = res.skipped
                pre_errors = res.errors
                if row.kind == "tv_episode":
                    apply_tv_episode(
                        cfg,
                        folder,
                        row,
                        dry_run,
                        log,
                        res,
                        record_op=row_record_op,
                    )
                elif row.kind == "single":
                    apply_single(
                        cfg,
                        folder,
                        new_title,
                        new_year,
                        dry_run,
                        log,
                        res,
                        conflicts_root=ctx.conflicts_root,
                        conflicts_sidecars_root=ctx.conflicts_sidecars_root,
                        duplicates_identical_root=ctx.duplicates_identical_root,
                        leftovers_root=ctx.leftovers_root,
                        hash_cache=ctx.hash_cache,
                        record_op=row_record_op,
                        tmdb_collection_name=getattr(row, "tmdb_collection_name", None),
                        edition=getattr(row, "edition", None),
                        # Cf issue #78 : passer le nom du video deja resolu au
                        # scan pour eviter un iterdir+stat dans apply_single.
                        main_video_filename=getattr(row, "video", None) or None,
                    )
                else:
                    apply_collection_item(
                        cfg,
                        folder,
                        row.video,
                        new_title,
                        new_year,
                        dry_run,
                        log,
                        res,
                        conflicts_root=ctx.conflicts_root,
                        conflicts_sidecars_root=ctx.conflicts_sidecars_root,
                        duplicates_identical_root=ctx.duplicates_identical_root,
                        hash_cache=ctx.hash_cache,
                        dedup_seen_ops=ctx.dedup_seen_ops,
                        record_op=row_record_op,
                        edition=getattr(row, "edition", None),
                    )
                post_actions = (
                    res.renames,
                    res.moves,
                    res.mkdirs,
                    res.collection_moves,
                    res.quarantined,
                    res.merges_count,
                    res.duplicates_identical_moved_count,
                    res.conflicts_quarantined_count,
                    res.sidecar_conflicts_kept_both_count,
                    res.leftovers_moved_count,
                    res.source_dirs_deleted_count,
                )
                if post_actions != pre_actions:
                    res.applied_count += 1
                elif res.skipped == pre_skipped and res.errors == pre_errors:
                    core_mod._mark_skip(res, core_mod.SKIP_REASON_AUTRE)
            else:
                if quarantine_unapproved:
                    quarantine_row(
                        cfg,
                        folder,
                        row,
                        dry_run,
                        log,
                        res,
                        ctx.review_root,
                        record_op=row_record_op,
                    )
                else:
                    if row.row_id not in ctx.decision_keys:
                        core_mod._mark_skip(res, core_mod.SKIP_REASON_VALIDATION_ABSENTE)
                    else:
                        core_mod._mark_skip(res, core_mod.SKIP_REASON_NON_VALIDE)
        except (OSError, PermissionError, FileNotFoundError, FileExistsError, ValueError, TypeError) as exc:
            res.errors += 1
            core_mod._mark_skip(res, core_mod.SKIP_REASON_ERREUR_PRECEDENTE)
            log("ERROR", f"Erreur application ({row.row_id}) : {exc}")

    cleanup_preview = preview_cleanup_residual_folders(cfg, ctx.touched_top_level_dirs)
    _move_residual_top_level_dirs(
        cfg,
        dry_run=dry_run,
        log=log,
        res=res,
        touched_top_level_dirs=ctx.touched_top_level_dirs,
        record_op=record_op,
    )
    cleanup_preview["moved_count"] = int(res.cleanup_residual_folders_moved_count or 0)
    cleanup_preview["left_in_place_count"] = int(
        cleanup_preview.get("has_video_count", 0)
        + cleanup_preview.get("ambiguous_count", 0)
        + cleanup_preview.get("symlink_count", 0)
        + cleanup_preview.get("no_files_count", 0)
    )
    if not cfg.cleanup_residual_folders_enabled:
        cleanup_preview["status_post"] = "disabled"
        cleanup_preview["message_post"] = "Nettoyage résiduel désactivé."
    elif dry_run:
        cleanup_preview["status_post"] = "not_executed"
        cleanup_preview["message_post"] = (
            "Dry-run : nettoyage résiduel non exécuté. " + str(cleanup_preview.get("message") or "")
        ).strip()
    elif int(res.cleanup_residual_folders_moved_count or 0) > 0:
        cleanup_preview["status_post"] = "executed"
        cleanup_preview["message_post"] = (
            f"Nettoyage résiduel exécuté : {int(res.cleanup_residual_folders_moved_count or 0)} "
            f"dossier(s) déplacé(s) vers {cfg.cleanup_residual_folders_folder_name}."
        )
    else:
        cleanup_preview["status_post"] = "executed_no_move"
        cleanup_preview["message_post"] = (
            "Nettoyage résiduel exécuté sans déplacement. " + str(cleanup_preview.get("message") or "")
        ).strip()
    res.cleanup_residual_diagnostic = cleanup_preview
    _move_empty_top_level_dirs(
        cfg,
        dry_run=dry_run,
        log=log,
        res=res,
        touched_top_level_dirs=ctx.touched_top_level_dirs,
        record_op=record_op,
    )
    _logger.info(
        "apply: termine — renames=%d moves=%d skipped=%d quarantined=%d errors=%d (dry_run=%s)",
        res.renames,
        res.moves,
        res.skipped,
        res.quarantined,
        res.errors,
        dry_run,
    )
    return res


def apply_single(
    cfg: "Config",
    folder: Path,
    title: str,
    year: int,
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    *,
    conflicts_root: Path,
    conflicts_sidecars_root: Path,
    duplicates_identical_root: Path,
    leftovers_root: Path,
    hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
    tmdb_collection_name: Optional[str] = None,
    edition: Optional[str] = None,
    main_video_filename: Optional[str] = None,
) -> None:
    """Renomme/déplace un dossier de film "single" vers `Titre (Année)` (option Edition).

    Si la cible existe déjà comme dossier, fusionne via `merge_dir_safe` plutôt
    que d'écraser. Si TMDb renvoie une collection (saga) et `enable_collection_folder`,
    place sous `<root>/<collection_root_name>/<saga>/`.
    """
    if not folder.exists():
        log("WARN", f"Single folder missing, skip: {folder}")
        core_mod._mark_skip(res, core_mod.SKIP_REASON_AUTRE)
        return
    _naming_ctx = build_naming_context(title=title, year=year, edition=edition or "")
    new_name = format_movie_folder(cfg.naming_movie_template, _naming_ctx)

    # Si collection TMDb + collection_folder_enabled → placer dans _Collection/Saga/
    _coll_name = (tmdb_collection_name or "").strip()
    if _coll_name and cfg.enable_collection_folder:
        coll_dir = cfg.root / cfg.collection_root_name / core_mod.windows_safe(_coll_name)
        dst = coll_dir / new_name
        if not dry_run:
            coll_dir.mkdir(parents=True, exist_ok=True)
    else:
        dst = folder.parent / new_name
    core_mod.ensure_inside_root(cfg, dst)

    if core_mod._single_folder_is_conform(folder.name, title, year, naming_template=cfg.naming_movie_template):
        core_mod._mark_skip(res, core_mod.SKIP_REASON_NOOP_DEJA_CONFORME)
        return

    if dst.exists():
        if not dst.is_dir():
            log("WARN", f"Rename destination invalid (not directory), skip: {dst}")
            core_mod._mark_skip(res, core_mod.SKIP_REASON_AUTRE)
            return
        core_mod._mark_skip(res, core_mod.SKIP_REASON_MERGED)
        merge_dir_safe(
            cfg,
            folder,
            dst,
            dry_run=dry_run,
            log=log,
            res=res,
            conflicts_root=conflicts_root,
            conflicts_sidecars_root=conflicts_sidecars_root,
            duplicates_identical_root=duplicates_identical_root,
            leftovers_root=leftovers_root,
            hash_cache=hash_cache,
            record_op=record_op,
        )
        return

    log("INFO", f"RENAME: {folder} -> {dst}")
    moved_from = folder
    moved_to = dst
    src_sha1: Optional[str] = None
    src_size: Optional[int] = None

    if not dry_run:
        # P1.2 : capturer le hash du fichier video principal AVANT le rename.
        # Cf issue #78 : si le caller a deja le nom du fichier video (depuis
        # PlanRow.video au scan), on evite le iterdir+stat de
        # find_main_video_in_folder — coute 50-500s sur 5000 films SMB.
        main_video: Optional[Path] = None
        if main_video_filename:
            candidate = folder / main_video_filename
            if candidate.is_file():
                main_video = candidate
        if main_video is None:
            main_video = find_main_video_in_folder(folder, cfg)
        if main_video is not None:
            try:
                src_size = main_video.stat().st_size
                src_sha1 = sha1_quick_cached(main_video, hash_cache)
            except (OSError, PermissionError) as exc:
                _logger.debug("P1.2: sha1 pre-apply (MOVE_DIR) echoue pour %s: %s", main_video, exc)
                src_sha1 = None
                src_size = None

        if folder.name.lower() == dst.name.lower():
            tmp = folder.parent / (folder.name + ".__tmp_ren")
            if tmp.exists():
                tmp = tmp.with_name(tmp.name + "_2")
            folder.rename(tmp)
            try:
                tmp.rename(dst)
            except (OSError, PermissionError):
                # Rollback : restaurer le nom original si le 2e rename echoue
                try:
                    tmp.rename(folder)
                except OSError as rollback_err:
                    # M4 : ne plus masquer silencieusement — le dossier reste en .__tmp_ren
                    _logger.error(
                        "apply: rollback rename echoue %s -> %s: %s (dossier en etat .__tmp_ren)",
                        tmp,
                        folder,
                        rollback_err,
                    )
                raise
        else:
            folder.rename(dst)

    # P1.3 : record l'op même en dry_run pour la preview UI
    record_apply_op(
        record_op,
        op_type="MOVE_DIR",
        src_path=moved_from,
        dst_path=moved_to,
        reversible=True,
        src_sha1=src_sha1,
        src_size=src_size,
    )
    res.renames += 1


def apply_collection_item(
    cfg: "Config",
    folder: Path,
    video_name: str,
    title: str,
    year: int,
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    *,
    conflicts_root: Path,
    conflicts_sidecars_root: Path,
    duplicates_identical_root: Path,
    hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    dedup_seen_ops: Optional[Set[Tuple[str, str, str]]] = None,
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
    edition: Optional[str] = None,
) -> None:
    """Déplace un film d'une collection (multi-films par dossier) dans son sous-dossier dédié.

    Crée `folder/Titre (Année)/`, déplace la vidéo + sidecars associés en
    appliquant la politique de collision. Le set `dedup_seen_ops` évite de
    refaire le même move au sein d'un batch.
    """
    if not folder.exists():
        log("WARN", f"Collection folder missing, skip: {folder}")
        core_mod._mark_skip(res, core_mod.SKIP_REASON_MERGED)
        return

    video = core_mod._find_video_case_insensitive(folder, video_name)
    if not video:
        video = folder / video_name

    if not video.exists():
        merged_video = None
        try:
            merged_video = next(
                (path for path in folder.rglob("*") if path.is_file() and path.name.lower() == str(video_name).lower()),
                None,
            )
        except (OSError, PermissionError):
            merged_video = None
        log("WARN", f"Video missing, skip: {folder}/{video_name}")
        core_mod._mark_skip(res, core_mod.SKIP_REASON_MERGED if merged_video else core_mod.SKIP_REASON_AUTRE)
        return

    _naming_ctx = build_naming_context(title=title, year=year, edition=edition or "")
    sub_name = format_movie_folder(cfg.naming_movie_template, _naming_ctx)
    sub_dir = folder / sub_name
    core_mod.ensure_inside_root(cfg, sub_dir)

    if not sub_dir.exists():
        mkdir_counted(sub_dir, dry_run=dry_run, log=log, res=res, record_op_fn=record_op)

    for sidecar in core_mod.classify_sidecars(cfg, folder, video, is_collection=True):
        dst = sub_dir / sidecar.name
        if dedup_seen_ops is not None:
            op_key = (str(core_mod._norm_win_path(sidecar)), str(core_mod._norm_win_path(dst)), "collection_sidecar")
            if op_key in dedup_seen_ops:
                log("INFO", f"SKIP_DEDUP collection_sidecar: {sidecar} -> {dst}")
                core_mod._mark_skip(res, core_mod.SKIP_REASON_MERGED)
                continue
            dedup_seen_ops.add(op_key)
        status = move_file_with_collision_policy(
            cfg,
            sidecar,
            dst,
            src_anchor=folder,
            dry_run=dry_run,
            log=log,
            res=res,
            conflicts_root=conflicts_root,
            conflicts_sidecars_root=conflicts_sidecars_root,
            duplicates_identical_root=duplicates_identical_root,
            hash_cache=hash_cache,
            record_op=record_op,
        )
        if status == "duplicate_identical":
            core_mod._mark_skip(res, core_mod.SKIP_REASON_NOOP_DEJA_CONFORME)
        elif status in {"conflict", "sidecar_conflict"}:
            core_mod._mark_skip(res, core_mod.SKIP_REASON_CONFLIT_QUARANTAINE)

    dst_video = sub_dir / video.name
    if dedup_seen_ops is not None:
        op_key = (str(core_mod._norm_win_path(video)), str(core_mod._norm_win_path(dst_video)), "collection_video")
        if op_key in dedup_seen_ops:
            log("INFO", f"SKIP_DEDUP collection_video: {video} -> {dst_video}")
            core_mod._mark_skip(res, core_mod.SKIP_REASON_MERGED)
            return
        dedup_seen_ops.add(op_key)
    status = move_file_with_collision_policy(
        cfg,
        video,
        dst_video,
        src_anchor=folder,
        dry_run=dry_run,
        log=log,
        res=res,
        conflicts_root=conflicts_root,
        conflicts_sidecars_root=conflicts_sidecars_root,
        duplicates_identical_root=duplicates_identical_root,
        hash_cache=hash_cache,
        record_op=record_op,
    )
    if status == "duplicate_identical":
        core_mod._mark_skip(res, core_mod.SKIP_REASON_NOOP_DEJA_CONFORME)
    elif status in {"conflict", "sidecar_conflict"}:
        core_mod._mark_skip(res, core_mod.SKIP_REASON_CONFLIT_QUARANTAINE)


def apply_tv_episode(
    cfg: "Config",
    folder: Path,
    row: "PlanRow",
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    *,
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> None:
    """Rename/move a TV episode into Série (année)/Saison NN/S01E01 - Titre.ext structure."""
    video = folder / row.video
    if not video.exists():
        try:
            matches = [p for p in folder.iterdir() if p.is_file() and p.name.lower() == row.video.lower()]
            video = matches[0] if matches else video
        except (PermissionError, OSError):
            pass
    if not video.exists():
        log("WARN", f"TV episode video missing: {video}")
        core_mod._mark_skip(res, core_mod.SKIP_REASON_AUTRE)
        return

    year = int(row.proposed_year or 0)
    season = int(row.tv_season or 0)
    episode = int(row.tv_episode or 0)
    ep_title = str(row.tv_episode_title or "").strip()

    # Build target path: root / Série (année) / Saison NN / S01E01 - Titre.ext
    _naming_ctx = build_naming_context(
        title=str(row.proposed_title or ""),
        year=year,
        tv_series_name=str(row.tv_series_name or row.proposed_title or ""),
        tv_season=season,
        tv_episode=episode,
        tv_episode_title=ep_title,
    )
    series_folder_name = format_tv_series_folder(cfg.naming_tv_template, _naming_ctx)
    season_folder_name = f"Saison {season:02d}" if season else "Saison 00"
    if ep_title:
        target_filename = f"S{season:02d}E{episode:02d} - {core_mod.windows_safe(ep_title)}{video.suffix}"
    else:
        target_filename = f"S{season:02d}E{episode:02d}{video.suffix}"

    target_dir = cfg.root / series_folder_name / season_folder_name
    target_file = target_dir / target_filename
    core_mod.ensure_inside_root(cfg, target_file)

    if target_file.exists():
        log("INFO", f"TV episode already in place: {target_file}")
        core_mod._mark_skip(res, core_mod.SKIP_REASON_NOOP_DEJA_CONFORME)
        return

    log("INFO", f"TV MOVE: {video} -> {target_file}")
    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)
        atomic_move(record_op, src=video, dst=target_file, op_type="MOVE_FILE")
        record_apply_op(
            record_op,
            op_type="MOVE_FILE",
            src_path=video,
            dst_path=target_file,
            reversible=True,
        )

        # Move sidecars (.srt, .nfo, etc.) that match the video stem.
        try:
            for sidecar in core_mod.classify_sidecars(cfg, folder, video, is_collection=True):
                if sidecar.exists():
                    dst_side = target_dir / sidecar.name
                    if not dst_side.exists():
                        atomic_move(record_op, src=sidecar, dst=dst_side, op_type="MOVE_FILE")
                        record_apply_op(
                            record_op,
                            op_type="MOVE_FILE",
                            src_path=sidecar,
                            dst_path=dst_side,
                            reversible=True,
                        )
        except (PermissionError, OSError):
            pass

    res.moves += 1


def quarantine_row(
    cfg: "Config",
    folder: Path,
    row: "PlanRow",
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    review_root: Path,
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> None:
    """Place le contenu d'une ligne non approuvée en quarantaine sous `_review/`.

    Pour un single, déplace tout le dossier ; pour un item de collection,
    déplace la vidéo + ses sidecars dans un sous-dossier dédié. No-op si la
    cible existe déjà ou si la source a disparu.
    """
    if not folder.exists():
        core_mod._mark_skip(res, core_mod.SKIP_REASON_AUTRE)
        return

    if row.kind == "single":
        target = review_root / core_mod.windows_safe(Path(row.folder).name)
        core_mod.ensure_inside_root(cfg, target)
        if target.exists():
            core_mod._mark_skip(res, core_mod.SKIP_REASON_AUTRE)
            return
        log("INFO", f"QUARANTINE folder: {folder} -> {target}")
        if not dry_run:
            atomic_move(record_op, src=folder, dst=target, op_type="QUARANTINE_DIR")
            record_apply_op(
                record_op,
                op_type="QUARANTINE_DIR",
                src_path=folder,
                dst_path=target,
                reversible=True,
            )
        res.quarantined += 1
        return

    video = folder / row.video
    if not video.exists():
        matches = [path for path in folder.iterdir() if path.is_file() and path.name.lower() == row.video.lower()]
        video = matches[0] if matches else video
    if not video.exists():
        core_mod._mark_skip(res, core_mod.SKIP_REASON_AUTRE)
        return

    base = review_root / core_mod.windows_safe(Path(row.folder).name) / core_mod.windows_safe(video.stem)
    core_mod.ensure_inside_root(cfg, base)
    if not base.exists():
        mkdir_counted(base, dry_run=dry_run, log=log, res=res, record_op_fn=record_op)

    for sidecar in core_mod.classify_sidecars(cfg, folder, video, is_collection=True):
        dst = base / sidecar.name
        if dst.exists():
            continue
        log("INFO", f"QUARANTINE MOVE: {sidecar} -> {dst}")
        if not dry_run:
            atomic_move(record_op, src=sidecar, dst=dst, op_type="QUARANTINE_FILE")
            record_apply_op(
                record_op,
                op_type="QUARANTINE_FILE",
                src_path=sidecar,
                dst_path=dst,
                reversible=True,
            )
        res.quarantined += 1

    dst_video = base / video.name
    if not dst_video.exists():
        log("INFO", f"QUARANTINE MOVE: {video} -> {dst_video}")
        if not dry_run:
            atomic_move(record_op, src=video, dst=dst_video, op_type="QUARANTINE_FILE")
            record_apply_op(
                record_op,
                op_type="QUARANTINE_FILE",
                src_path=video,
                dst_path=dst_video,
                reversible=True,
            )
        res.quarantined += 1
    else:
        core_mod._mark_skip(res, core_mod.SKIP_REASON_AUTRE)
