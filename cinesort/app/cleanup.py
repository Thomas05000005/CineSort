from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Set

from cinesort.app.move_journal import atomic_move

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cinesort.domain.core import ApplyResult, Config


def _collect_root_all_empty_dirs(cfg: "Config") -> List[Path]:
    # Cf issue #83 phase 2 : import direct depuis l'origine app au lieu du
    # re-export domain.core (qui creait un cycle domain -> app).
    from cinesort.app.apply_core import is_dir_empty as _is_dir_empty

    out: List[Path] = []
    try:
        entries = [p for p in cfg.root.iterdir() if p.is_dir()]
    except (OSError, PermissionError, FileNotFoundError):
        return out
    for directory in entries:
        if _is_dir_empty(directory):
            out.append(directory)
    return out


def _residual_allowed_exts(cfg: "Config") -> Set[str]:
    from cinesort.domain.core import RESIDUAL_IMAGE_EXTS, RESIDUAL_NFO_EXTS, RESIDUAL_SUBTITLE_EXTS, RESIDUAL_TEXT_EXTS

    allowed: Set[str] = set()
    if cfg.cleanup_residual_include_nfo:
        allowed.update(RESIDUAL_NFO_EXTS)
    if cfg.cleanup_residual_include_images:
        allowed.update(RESIDUAL_IMAGE_EXTS)
    if cfg.cleanup_residual_include_subtitles:
        allowed.update(RESIDUAL_SUBTITLE_EXTS)
    if cfg.cleanup_residual_include_texts:
        allowed.update(RESIDUAL_TEXT_EXTS)
    return allowed


def _residual_cleanup_families(cfg: "Config") -> List[str]:
    families: List[str] = []
    if cfg.cleanup_residual_include_nfo:
        families.append("NFO/XML")
    if cfg.cleanup_residual_include_images:
        families.append("Images")
    if cfg.cleanup_residual_include_subtitles:
        families.append("Sous-titres")
    if cfg.cleanup_residual_include_texts:
        families.append("Textes")
    return families


def _classify_cleanable_residual_dir(cfg: "Config", path: Path) -> str:
    """Classe un dossier candidat (eligible/empty/has_video/ambiguous/symlink/...).

    Renvoie une étiquette utilisée par le preview et le move pour distinguer les dossiers
    sûrs à déplacer (`eligible`/`empty`) des dossiers à protéger (vidéos, symlinks).
    """
    # Cf issue #83 phase 2 : import direct depuis l'origine app au lieu du
    # re-export domain.core (qui creait un cycle domain -> app).
    from cinesort.app.apply_core import is_dir_empty as _is_dir_empty

    if not path.exists() or not path.is_dir():
        return "invalid"
    if _is_dir_empty(path):
        return "empty"

    allowed_exts = _residual_allowed_exts(cfg)
    if not allowed_exts:
        return "disabled"

    saw_file = False
    try:
        for item in path.rglob("*"):
            if item.is_symlink():
                return "symlink"
            if item.is_dir():
                continue
            if not item.is_file():
                return "ambiguous"
            saw_file = True
            ext = item.suffix.lower()
            if ext in cfg.video_exts or ext in {".iso"}:
                return "has_video"
            if ext not in allowed_exts:
                return "ambiguous"
    except (PermissionError, OSError):
        return "ambiguous"
    return "eligible" if saw_file else "no_files"


def _is_cleanable_residual_dir(cfg: "Config", path: Path) -> bool:
    return _classify_cleanable_residual_dir(cfg, path) == "eligible"


def _collect_root_all_dirs(cfg: "Config") -> List[Path]:
    out: List[Path] = []
    try:
        entries = [p for p in cfg.root.iterdir() if p.is_dir()]
    except (OSError, PermissionError, FileNotFoundError):
        return out
    for directory in entries:
        out.append(directory)
    return out


def _residual_cleanup_skip_names(cfg: "Config", bucket_root: Path) -> Set[str]:
    skip_names = {
        bucket_root.name.lower(),
        "_review",
        cfg.collection_root_name.lower(),
        cfg.empty_folders_folder_name.lower(),
    }
    if cfg.collection_root_name.lower() != "collection":
        skip_names.add("collection")
    return skip_names


def _residual_cleanup_candidates(
    cfg: "Config",
    touched_top_level_dirs: Set[Path],
    *,
    bucket_root: Path,
) -> List[Path]:
    """Liste les dossiers de premier niveau candidats au nettoyage résiduel.

    Filtre selon le scope (touched_only vs all), exclut les dossiers système
    (collection, bucket cible, dossiers en `_*`) et garde l'ordre alphabétique.
    """
    if cfg.cleanup_residual_folders_scope == "touched_only":
        raw_candidates = sorted(
            {p for p in touched_top_level_dirs if p.parent == cfg.root}, key=lambda p: p.name.lower()
        )
    else:
        raw_candidates = sorted(_collect_root_all_dirs(cfg), key=lambda p: p.name.lower())

    skip_names = _residual_cleanup_skip_names(cfg, bucket_root)
    out: List[Path] = []
    for src in raw_candidates:
        if not src.exists() or not src.is_dir():
            continue
        if src.parent != cfg.root:
            continue
        if src.name.lower() in skip_names:
            continue
        if src.name.startswith("_"):
            continue
        out.append(src)
    return out


def preview_cleanup_residual_folders(cfg: "Config", touched_top_level_dirs: Set[Path]) -> Dict[str, Any]:
    """Construit le rapport de prévisualisation du nettoyage des dossiers résiduels.

    Inventorie les dossiers candidats sans rien déplacer puis renvoie compteurs
    (eligibles, vidéos bloquées, ambigus, vides, symlinks) + échantillons + statut
    affichables tels quels par l'UI.
    """
    cfg = cfg.normalized()
    bucket_root = cfg.root / cfg.cleanup_residual_folders_folder_name
    families = _residual_cleanup_families(cfg)

    preview: Dict[str, Any] = {
        "enabled": bool(cfg.cleanup_residual_folders_enabled),
        "target_folder_name": str(cfg.cleanup_residual_folders_folder_name),
        "target_folder_path": str(bucket_root),
        "scope": str(cfg.cleanup_residual_folders_scope),
        "families": families,
        "candidates_considered": 0,
        "probable_eligible_count": 0,
        "empty_dir_count": 0,
        "has_video_count": 0,
        "ambiguous_count": 0,
        "symlink_count": 0,
        "no_files_count": 0,
        "sample_eligible_dirs": [],
        "sample_video_blocked_dirs": [],
        "sample_ambiguous_dirs": [],
        "sample_empty_dirs": [],
        "sample_symlink_dirs": [],
        "status": "disabled",
        "reason_code": "disabled",
        "message": "Nettoyage résiduel désactivé.",
    }

    if not cfg.cleanup_residual_folders_enabled:
        return preview

    candidates = _residual_cleanup_candidates(cfg, touched_top_level_dirs, bucket_root=bucket_root)
    preview["candidates_considered"] = int(len(candidates))

    if not families:
        preview["status"] = "no_action_likely"
        preview["reason_code"] = "no_families_enabled"
        preview["message"] = "Nettoyage activé mais aucune famille résiduelle n'est activée."
        return preview

    for src in candidates:
        reason = _classify_cleanable_residual_dir(cfg, src)
        if reason == "eligible":
            preview["probable_eligible_count"] = int(preview["probable_eligible_count"]) + 1
            if len(preview["sample_eligible_dirs"]) < 5:
                preview["sample_eligible_dirs"].append(str(src))
        elif reason == "empty":
            preview["empty_dir_count"] = int(preview["empty_dir_count"]) + 1
            if len(preview["sample_empty_dirs"]) < 5:
                preview["sample_empty_dirs"].append(str(src))
        elif reason == "has_video":
            preview["has_video_count"] = int(preview["has_video_count"]) + 1
            if len(preview["sample_video_blocked_dirs"]) < 5:
                preview["sample_video_blocked_dirs"].append(str(src))
        elif reason == "symlink":
            preview["symlink_count"] = int(preview["symlink_count"]) + 1
            if len(preview["sample_symlink_dirs"]) < 5:
                preview["sample_symlink_dirs"].append(str(src))
        elif reason == "no_files":
            preview["no_files_count"] = int(preview["no_files_count"]) + 1
        else:
            preview["ambiguous_count"] = int(preview["ambiguous_count"]) + 1
            if len(preview["sample_ambiguous_dirs"]) < 5:
                preview["sample_ambiguous_dirs"].append(str(src))

    probable = int(preview["probable_eligible_count"] or 0)
    if probable > 0:
        preview["status"] = "ready"
        preview["reason_code"] = "eligible"
        preview["message"] = (
            f"Nettoyage résiduel : {probable} dossier(s) probablement éligible(s) "
            f"vers {cfg.cleanup_residual_folders_folder_name}."
        )
        return preview

    preview["status"] = "no_action_likely"
    if int(preview["candidates_considered"] or 0) == 0 and cfg.cleanup_residual_folders_scope == "touched_only":
        preview["reason_code"] = "scope_touched_only_none"
        preview["message"] = (
            "Nettoyage activé mais le scope touched_only n'a trouvé aucun dossier top-level touché à inspecter."
        )
    elif int(preview["has_video_count"] or 0) > 0 and int(preview["ambiguous_count"] or 0) == 0:
        preview["reason_code"] = "videos_present"
        preview["message"] = "Aucun dossier sidecar-only éligible : des vidéos sont encore présentes."
    elif int(preview["ambiguous_count"] or 0) > 0:
        preview["reason_code"] = "ambiguous_extensions"
        preview["message"] = "Aucun dossier éligible : extensions ambiguës ou prudence moteur."
    elif int(preview["empty_dir_count"] or 0) > 0 and int(preview["candidates_considered"] or 0) == int(
        preview["empty_dir_count"] or 0
    ):
        preview["reason_code"] = "empty_only"
        preview["message"] = "Aucun dossier résiduel non vide éligible : seuls des dossiers vides relèvent de _Vide."
    else:
        preview["reason_code"] = "none_eligible"
        preview["message"] = "Aucun dossier sidecar-only éligible trouvé pour ce run."
    return preview


def _move_dirs_to_bucket(
    candidates: List[Path],
    *,
    is_eligible: Callable[[Path], bool],
    bucket_root: Path,
    dry_run: bool,
    log: Callable[[str, str], None],
    log_prefix: str,
    record_op: Callable[[Dict[str, Any]], None] | None = None,
) -> int:
    """Déplace chaque dossier éligible vers `bucket_root` et journalise l'opération.

    Renvoie le nombre de dossiers réellement déplacés (0 si dry_run ou aucun éligible).
    """
    # Cf issue #83 phase 2 : imports directs depuis les origines pour casser
    # le cycle domain.core -> app. windows_safe reste dans domain (logique
    # de naming pur), record_apply_op et unique_path sont dans app.apply_core.
    from cinesort.app.apply_core import record_apply_op as _record_apply_op, unique_path as _unique_path
    from cinesort.domain.core import windows_safe

    moved = 0
    for src in candidates:
        if not is_eligible(src):
            continue
        dst = _unique_path(bucket_root / windows_safe(src.name))
        log("INFO", f"{log_prefix}: {src} -> {dst}")
        _logger.info("cleanup: %s -> %s (dry_run=%s)", src.name, dst, dry_run)
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            atomic_move(record_op, src=src, dst=dst, op_type="MOVE_DIR")
            _record_apply_op(
                record_op,
                op_type="MOVE_DIR",
                src_path=src,
                dst_path=dst,
                reversible=True,
            )
        moved += 1
    return moved


def _move_residual_top_level_dirs(
    cfg: "Config",
    *,
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    touched_top_level_dirs: Set[Path],
    record_op: Callable[[Dict[str, Any]], None] | None = None,
) -> None:
    """Déplace les dossiers résiduels de premier niveau vers le bucket de nettoyage.

    No-op si le nettoyage résiduel est désactivé. Met à jour `res.cleanup_residual_folders_moved_count`.
    """
    from cinesort.domain.core import ensure_inside_root

    if not cfg.cleanup_residual_folders_enabled:
        return

    bucket_root = cfg.root / cfg.cleanup_residual_folders_folder_name
    ensure_inside_root(cfg, bucket_root)
    candidates = _residual_cleanup_candidates(cfg, touched_top_level_dirs, bucket_root=bucket_root)

    res.cleanup_residual_folders_moved_count += _move_dirs_to_bucket(
        candidates,
        is_eligible=lambda src: _classify_cleanable_residual_dir(cfg, src) == "eligible",
        bucket_root=bucket_root,
        dry_run=dry_run,
        log=log,
        log_prefix="DOSSIER NETTOYAGE",
        record_op=record_op,
    )


def _move_empty_top_level_dirs(
    cfg: "Config",
    *,
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    touched_top_level_dirs: Set[Path],
    record_op: Callable[[Dict[str, Any]], None] | None = None,
) -> None:
    """Déplace les dossiers vides de premier niveau vers le bucket dédié.

    No-op si l'option `move_empty_folders_enabled` est désactivée. Met à jour
    `res.empty_folders_moved_count`.
    """
    # Cf issue #83 phase 2 : imports directs depuis origines. is_dir_empty
    # vient d'app.apply_core, ensure_inside_root reste dans domain.core
    # (logique de validation path-traversal pure).
    from cinesort.app.apply_core import is_dir_empty as _is_dir_empty
    from cinesort.domain.core import ensure_inside_root

    if not cfg.move_empty_folders_enabled:
        return

    bucket_root = cfg.root / cfg.empty_folders_folder_name
    ensure_inside_root(cfg, bucket_root)

    if cfg.empty_folders_scope == "touched_only":
        raw_candidates = sorted(
            {p for p in touched_top_level_dirs if p.parent == cfg.root}, key=lambda p: p.name.lower()
        )
    else:
        raw_candidates = sorted(_collect_root_all_empty_dirs(cfg), key=lambda p: p.name.lower())

    skip_names = {
        bucket_root.name.lower(),
        "_review",
        cfg.collection_root_name.lower(),
    }
    if cfg.collection_root_name.lower() != "collection":
        skip_names.add("collection")

    candidates = [
        src
        for src in raw_candidates
        if src.exists()
        and src.is_dir()
        and src.parent == cfg.root
        and src.name.lower() not in skip_names
        and not src.name.startswith("_")
    ]

    res.empty_folders_moved_count += _move_dirs_to_bucket(
        candidates,
        is_eligible=_is_dir_empty,
        bucket_root=bucket_root,
        dry_run=dry_run,
        log=log,
        log_prefix="DOSSIER VIDE",
        record_op=record_op,
    )
