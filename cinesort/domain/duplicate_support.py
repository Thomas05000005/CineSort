from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_MOVIE_DIR_RE = re.compile(r"^\s*(?P<title>.+?)\s*\((?P<year>19\d{2}|20\d{2})\)\s*$")


def is_under_collection_root(
    cfg: Any,
    folder: Path,
    *,
    norm_win_path: Callable[[Path], Any],
) -> bool:
    folder_pw = norm_win_path(folder)
    root_pw = norm_win_path(cfg.root)
    try:
        rel = folder_pw.relative_to(root_pw)
    except (ValueError, TypeError):
        return False
    parts = [part.lower() for part in rel.parts]
    return len(parts) >= 1 and parts[0] == str(cfg.collection_root_name or "").lower()


def movie_dir_title_year(name: str) -> Optional[Tuple[str, int]]:
    match = _MOVIE_DIR_RE.match(name or "")
    if not match:
        return None
    title = (match.group("title") or "").strip()
    year = int(match.group("year"))
    if not title:
        return None
    return title, year


def movie_key(
    title: str,
    year: int,
    *,
    norm_for_tokens: Callable[[str], str],
    edition: Optional[str] = None,
) -> str:
    normalized_year = int(year or 0)
    base = f"{norm_for_tokens(title)}|{normalized_year}"
    ed = (edition or "").strip().lower()
    if ed:
        return f"{base}|{ed}"
    return base


def single_folder_is_conform(
    folder_name: str,
    title: str,
    year: int,
    *,
    windows_safe: Callable[[str], str],
    norm_for_tokens: Callable[[str], str],
    movie_dir_title_year: Callable[[str], Optional[Tuple[str, int]]],
    naming_template: str = "",
) -> bool:
    # Check 1 : template actif (si fourni)
    if naming_template:
        from cinesort.domain.naming import folder_matches_template

        if folder_matches_template(folder_name, naming_template, title, year):
            return True

    # Check 2 : fallback format historique "Title (Year)"
    expected_title = windows_safe(title or "")
    if 1900 <= int(year or 0) <= 2100:
        current = movie_dir_title_year(folder_name)
        if not current:
            return False
        current_title, current_year = current
        return int(current_year) == int(year) and (norm_for_tokens(current_title) == norm_for_tokens(expected_title))
    return norm_for_tokens(folder_name) == norm_for_tokens(expected_title)


def find_video_case_insensitive(folder: Path, video_name: str) -> Optional[Path]:
    candidate = folder / video_name
    if candidate.exists():
        return candidate
    try:
        for child in folder.iterdir():
            if child.is_file() and child.name.lower() == str(video_name or "").lower():
                return child
    except (OSError, PermissionError, FileNotFoundError):
        return None
    return None


def planned_target_folder(
    cfg: Any,
    row: Any,
    title: str,
    year: int,
    *,
    is_under_collection_root: Callable[[Any, Path], bool],
    windows_safe: Callable[[str], str],
) -> Path:
    folder_name = windows_safe(f"{title} ({year})")
    if row.kind == "single":
        return Path(row.folder).parent / folder_name

    col_folder = Path(row.folder)
    if cfg.enable_collection_folder and (not is_under_collection_root(cfg, col_folder)):
        col_folder = cfg.root / cfg.collection_root_name / windows_safe(col_folder.name)
    return col_folder / folder_name


def existing_movie_folder_index(
    cfg: Any,
    *,
    movie_dir_title_year: Callable[[str], Optional[Tuple[str, int]]],
    movie_key: Callable[[str, int], str],
) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    try:
        level1 = [path for path in cfg.root.iterdir() if path.is_dir()]
    except (OSError, PermissionError, FileNotFoundError):
        return out

    for level1_dir in level1:
        if level1_dir.name.startswith("_"):
            continue
        if level1_dir.name.lower() == "_review":
            continue

        pair = movie_dir_title_year(level1_dir.name)
        if pair:
            title, year = pair
            out.setdefault(movie_key(title, year), []).append(str(level1_dir))

        try:
            children = [path for path in level1_dir.iterdir() if path.is_dir()]
        except (OSError, PermissionError, FileNotFoundError):
            children = []
        for level2_dir in children:
            pair2 = movie_dir_title_year(level2_dir.name)
            if not pair2:
                continue
            title2, year2 = pair2
            out.setdefault(movie_key(title2, year2), []).append(str(level2_dir))
    return out


def _check_file_collisions(
    src_files: List[Path],
    *,
    dst_for: Callable[[Path], Path],
    files_identical_quick: Callable[[Path, Path], bool],
) -> Tuple[bool, str]:
    for src in src_files:
        dst = dst_for(src)
        if not dst.exists():
            continue
        if not dst.is_file():
            return False, f"collision path type mismatch: {dst}"
        if files_identical_quick(src, dst):
            continue
        return False, f"file collision not resolvable: {dst.name}"
    return True, "target folder exists; merge will be performed safely"


def can_merge_single_without_blocking(
    cfg: Any,
    src_dir: Path,
    dst_dir: Path,
    *,
    is_managed_merge_file: Callable[[Any, Path], bool],
    files_identical_quick: Callable[[Path, Path], bool],
) -> Tuple[bool, str]:
    if not dst_dir.exists():
        return True, "target folder absent"
    if not dst_dir.is_dir():
        return False, "target exists and is not a folder"
    if not src_dir.exists() or not src_dir.is_dir():
        return False, "source folder missing"

    try:
        files = [path for path in src_dir.rglob("*") if path.is_file() and is_managed_merge_file(cfg, path)]
    except (OSError, PermissionError, FileNotFoundError):
        return False, "source folder not readable"

    return _check_file_collisions(
        files,
        dst_for=lambda src: dst_dir / src.relative_to(src_dir),
        files_identical_quick=files_identical_quick,
    )


def can_merge_collection_item_without_blocking(
    cfg: Any,
    row: Any,
    target_dir: Path,
    *,
    find_video_case_insensitive: Callable[[Path, str], Optional[Path]],
    classify_sidecars: Callable[[Any, Path, Path], List[Path]],
    files_identical_quick: Callable[[Path, Path], bool],
) -> Tuple[bool, str]:
    if not target_dir.exists():
        return True, "target folder absent"
    if not target_dir.is_dir():
        return False, "target exists and is not a folder"

    folder = Path(row.folder)
    if not folder.exists():
        return False, "source collection folder missing"

    video = find_video_case_insensitive(folder, row.video)
    if not video:
        return False, "source video missing"

    src_files = [video]
    try:
        src_files.extend(classify_sidecars(cfg, folder, video))
    except (OSError, PermissionError, FileNotFoundError):
        return False, "source sidecars unreadable"

    return _check_file_collisions(
        src_files,
        dst_for=lambda src: target_dir / src.name,
        files_identical_quick=files_identical_quick,
    )


def find_duplicate_targets(
    cfg: Any,
    rows: List[Any],
    decisions: Dict[str, Dict[str, object]],
    *,
    max_groups: int = 120,
    existing_movie_folder_index: Callable[[Any], Dict[str, List[str]]],
    movie_key: Callable[[str, int], str],
    planned_target_folder: Callable[[Any, Any, str, int], Path],
    norm_win_path: Callable[[Path], str],
    can_merge_single_without_blocking: Callable[[Any, Path, Path], tuple[bool, str]],
    can_merge_collection_item_without_blocking: Callable[[Any, Any, Path], tuple[bool, str]],
    windows_safe: Callable[[str], str],
) -> Dict[str, object]:
    existing_idx = existing_movie_folder_index(cfg)
    planned_idx: Dict[str, List[Dict[str, str]]] = {}
    rows_by_id = {row.row_id: row for row in rows}
    total_checked = 0

    for row in rows:
        dec = decisions.get(row.row_id, {})
        if not bool(dec.get("ok", False)):
            continue

        title = str(dec.get("title") or row.proposed_title).strip() or row.proposed_title
        try:
            year = int(dec.get("year") or row.proposed_year)
        except (ValueError, TypeError):
            year = int(row.proposed_year or 0)
        if not (1900 <= year <= 2100):
            continue

        total_checked += 1
        row_edition = getattr(row, "edition", None)
        key = movie_key(title, year, edition=row_edition)
        target = planned_target_folder(cfg, row, title, year)
        planned_idx.setdefault(key, []).append(
            {
                "row_id": row.row_id,
                "kind": row.kind,
                "title": windows_safe(title),
                "year": str(year),
                "target": str(target),
                "source_folder": str(row.folder),
            }
        )

    groups: List[Dict[str, object]] = []
    mergeables: List[Dict[str, object]] = []
    for key, items in planned_idx.items():
        year = int(items[0]["year"])
        title = str(items[0]["title"])
        existing_paths = existing_idx.get(key, [])
        plan_targets = [item["target"] for item in items]

        has_plan_dupe = len(set(plan_targets)) < len(plan_targets)
        existing_elsewhere = []
        target_norms = {norm_win_path(Path(target)) for target in plan_targets}
        for existing_path in existing_paths:
            try:
                existing_norm = norm_win_path(Path(existing_path))
            except (ValueError, TypeError, OSError):
                continue

            matched_target = False
            conflict = False
            for item in items:
                try:
                    target_norm = norm_win_path(Path(item["target"]))
                    source_norm = norm_win_path(Path(item["source_folder"]))
                except (ValueError, TypeError, OSError):
                    continue
                if existing_norm != target_norm:
                    continue
                matched_target = True
                same_current_single = (str(item.get("kind") or "") == "single") and (source_norm == target_norm)
                if not same_current_single:
                    row_obj = rows_by_id.get(str(item.get("row_id") or ""))
                    mergeable = False
                    reason = "target folder exists"
                    if row_obj is not None:
                        if row_obj.kind == "single":
                            mergeable, reason = can_merge_single_without_blocking(
                                cfg,
                                Path(row_obj.folder),
                                Path(item["target"]),
                            )
                        else:
                            mergeable, reason = can_merge_collection_item_without_blocking(
                                cfg,
                                row_obj,
                                Path(item["target"]),
                            )
                    if mergeable:
                        mergeables.append(
                            {
                                "title": title,
                                "year": year,
                                "row_id": str(item.get("row_id") or ""),
                                "kind": "mergeable",
                                "mergeable": True,
                                "reason": reason,
                                "target": str(item["target"]),
                                "source_folder": str(item["source_folder"]),
                            }
                        )
                    else:
                        conflict = True
                break

            if conflict or ((not matched_target) and existing_norm not in target_norms):
                existing_elsewhere.append(existing_path)

        if (not has_plan_dupe) and (not existing_elsewhere):
            continue

        groups.append(
            {
                "title": title,
                "year": year,
                "rows": items,
                "existing_paths": existing_elsewhere[:8],
                "plan_conflict": bool(has_plan_dupe),
            }
        )
        if len(groups) >= max_groups:
            break

    return {
        "checked_rows": total_checked,
        "total_groups": len(groups),
        "groups": groups,
        "mergeable_count": len(mergeables),
        "mergeables": mergeables[:200],
    }
