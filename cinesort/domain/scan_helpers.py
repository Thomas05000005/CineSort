from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Set
import contextlib

logger = logging.getLogger(__name__)


IGNORE_VIDEO_NAME_RE = re.compile(r"\b(sample|trailer|teaser|demo)\b", re.IGNORECASE)
GENERIC_EXTRA_VIDEO_NAMES = {
    "bonus",
    "bonus feature",
    "bonus features",
    "extra",
    "extras",
    "featurette",
    "featurettes",
    "interview",
    "interviews",
    "making of",
    "deleted scene",
    "deleted scenes",
    "behind the scenes",
}


def iter_videos(cfg: Any, folder: Path, *, min_video_bytes: int) -> List[Path]:
    # BUG 3 : optimisation NAS. `os.scandir()` retourne les metadata
    # (is_file, stat) en une seule operation systeme au lieu de round-trips
    # separes comme avec `folder.iterdir() + p.is_file() + p.stat()`.
    vids: List[Path] = []
    video_exts = cfg.video_exts or set()
    min_bytes = int(min_video_bytes)
    try:
        scandir_ctx = os.scandir(str(folder))
    except (OSError, PermissionError, FileNotFoundError):
        return vids
    try:
        for entry in scandir_ctx:
            name = entry.name
            # suffix via string slicing pour eviter un Path()
            dot = name.rfind(".")
            if dot < 0:
                continue
            ext = name[dot:].lower()
            if ext not in video_exts:
                continue
            if IGNORE_VIDEO_NAME_RE.search(name):
                continue
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                # stat() sur le DirEntry utilise le cache de scandir (0 round-trip NAS)
                st = entry.stat(follow_symlinks=False)
                if st.st_size < min_bytes:
                    continue
            except (OSError, PermissionError, FileNotFoundError, ValueError, TypeError):
                continue
            vids.append(Path(entry.path))
    finally:
        with contextlib.suppress(OSError, AttributeError):
            scandir_ctx.close()
    return vids


def detect_single_with_extras(cfg: Any, videos: List[Path]) -> bool:
    if not getattr(cfg, "detect_extras_in_single_folder", False):
        return False
    if len(videos) <= 1:
        return False
    sizes = []
    for v in videos:
        try:
            sizes.append(v.stat().st_size)
        except (OSError, PermissionError, FileNotFoundError):
            sizes.append(0)
    sizes_sorted = sorted(sizes, reverse=True)
    if len(sizes_sorted) < 2:
        return False
    biggest, second = sizes_sorted[0], sizes_sorted[1]
    if second <= 0:
        return True
    return (biggest / second) >= float(getattr(cfg, "extras_size_ratio", 4.0))


def _looks_like_nested_extra_video(video: Path) -> bool:
    if IGNORE_VIDEO_NAME_RE.search(video.name):
        return True
    stem = video.stem.lower().replace(".", " ").replace("_", " ").replace("-", " ")
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem in GENERIC_EXTRA_VIDEO_NAMES


def collect_non_video_extensions(cfg: Any, folder: Path) -> Dict[str, int]:
    out: Dict[str, int] = {}
    try:
        entries = list(folder.iterdir())
    except (OSError, PermissionError, FileNotFoundError):
        return out
    for p in entries:
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext in cfg.video_exts:
            continue
        key = ext or "<sans_ext>"
        out[key] = int(out.get(key, 0)) + 1
    return out


# BUG 5 : regex qui detecte un nom de dossier "film" via sa parenthese d'annee.
# Un dossier comme "Inception (2010)" est presque certainement un dossier de film,
# donc inutile de faire un scandir dessus pour verifier. Phase 2 (iter_videos) fera
# le tri. Sur NAS SMB, chaque scandir evite = ~14ms de round-trip economise.
_FILM_FOLDER_NAME_RE = re.compile(r"\(\s*(19|20)\d{2}\s*\)")


def discover_candidate_folders(cfg: Any, *, max_depth: int = 3) -> List[Path]:
    """BUG 1 + BUG 5 : decouverte rapide des dossiers candidats, optimisee NAS.

    Strategie :
    - Descente recursive via os.scandir (un scandir par dossier visite).
    - AUCUN stat() sur les fichiers, AUCUN .nfo parse, AUCUNE signature.
    - BUG 5 : si le nom du dossier contient `(YYYY)`, il est considere directement
      comme un dossier de film → candidat immediat, AUCUN scandir n'est fait dessus.
      Gain massif sur bibliotheque plate (857 films x 14ms = 12s → <1s).
      Les dossiers sans `(YYYY)` (categories, sagas, anomalies) sont explores
      normalement pour preserver la detection recursive.

    Regle de candidature (dossiers sans annee) :
    - Dossier feuille (pas de sous-dossiers) avec fichiers → candidat
    - Dossier avec sous-dossiers + des fichiers video non-bonus → candidat + descente
    - Dossier avec sous-dossiers mais uniquement des bonus/trailers → descente seule
    - Dossier vide → ignore

    Cible : < 2s sur NAS SMB pour ~1000 dossiers a majorite plate.
    """
    root = Path(cfg.root)
    collection_name_lower = str(getattr(cfg, "collection_root_name", "") or "").lower()
    video_exts = set(getattr(cfg, "video_exts", set()) or set())
    candidates: List[Path] = []

    def _file_looks_bonus(name: str) -> bool:
        """Filtrage textuel uniquement (pas de stat), reproduit
        _looks_like_nested_extra_video sans toucher au filesystem.
        """
        if IGNORE_VIDEO_NAME_RE.search(name):
            return True
        stem = name.rsplit(".", 1)[0].lower().replace(".", " ").replace("_", " ").replace("-", " ")
        stem = re.sub(r"\s+", " ", stem).strip()
        return stem in GENERIC_EXTRA_VIDEO_NAMES

    def _walk(current: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            scandir_ctx = os.scandir(str(current))
        except (OSError, PermissionError, FileNotFoundError):
            return
        subdirs: List[Path] = []
        any_file = False
        video_files: List[str] = []
        try:
            for entry in scandir_ctx:
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                nm = entry.name
                if is_dir:
                    if nm.startswith("_"):
                        continue
                    if depth == 0 and nm.lower() == collection_name_lower:
                        # Skip le dossier _Collection au niveau 1 du root
                        continue
                    entry_path = Path(entry.path)
                    # BUG 5 : fast-path — si le nom contient `(YYYY)`, candidat
                    # direct, pas de scandir supplementaire. Phase 2 verifiera.
                    if depth >= 0 and _FILM_FOLDER_NAME_RE.search(nm):
                        candidates.append(entry_path)
                    else:
                        subdirs.append(entry_path)
                else:
                    any_file = True
                    # Extension via slicing (pas de Path)
                    dot = nm.rfind(".")
                    if dot >= 0 and nm[dot:].lower() in video_exts:
                        video_files.append(nm)
        finally:
            with contextlib.suppress(OSError, AttributeError):
                scandir_ctx.close()

        if depth == 0:
            # Films poses directement a la racine : la racine devient candidat.
            # iter_videos() en phase 2 est non-recursif, donc les fichiers des
            # sous-dossiers ne seront pas double-comptes.
            non_bonus_root_videos = [v for v in video_files if not _file_looks_bonus(v)]
            if non_bonus_root_videos:
                candidates.append(current)

        if subdirs:
            # Dossier avec sous-dossiers : candidat uniquement si au moins un fichier
            # video non-bonus est present au niveau courant.
            non_bonus_videos = [v for v in video_files if not _file_looks_bonus(v)]
            if depth >= 1 and non_bonus_videos:
                candidates.append(current)
            for sd in subdirs:
                _walk(sd, depth + 1)
        else:
            # Dossier feuille : candidat si au moins un fichier est present.
            # On ne filtre PAS les bonus ici car certains dossiers legitimes
            # n'ont que des videos renommees bizarrement — iter_videos fera
            # le tri en phase 2 avec le min_video_bytes.
            if depth >= 1 and any_file:
                candidates.append(current)

    _walk(root, depth=0)
    candidates.sort(key=lambda p: (str(p.parent).lower(), p.name.lower()))
    return candidates


def stream_scan_targets(cfg: Any, *, min_video_bytes: int) -> Iterator[Path]:
    """Legacy : stream base sur os.walk. Conserve pour compat tests anciens.

    BUG 1 : le nouveau code plan_library passe par discover_candidate_folders()
    + iter_videos() en phase 2 pour eviter les round-trips NAS multiples.
    """
    root_resolved = cfg.root.resolve()
    seen_real_paths: Set[str] = set()

    for current, dirnames, filenames in os.walk(str(cfg.root), followlinks=False):
        folder = Path(current)
        try:
            real_key = str(folder.resolve())
        except (OSError, PermissionError, FileNotFoundError):
            real_key = str(folder.absolute())
        if real_key in seen_real_paths:
            dirnames[:] = []
            continue
        seen_real_paths.add(real_key)

        if folder.resolve() != root_resolved:
            name_l = folder.name.lower()
            if folder.name.startswith("_") or name_l == str(cfg.collection_root_name).lower():
                dirnames[:] = []
                continue

        kept_dirs: List[str] = []
        for dn in dirnames:
            dn_l = dn.lower()
            if dn.startswith("_"):
                continue
            if dn_l == str(cfg.collection_root_name).lower():
                continue
            kept_dirs.append(dn)
        kept_dirs.sort(key=lambda name: name.lower())
        dirnames[:] = kept_dirs

        if folder.resolve() == root_resolved:
            continue

        videos = iter_videos(cfg, folder, min_video_bytes=min_video_bytes)
        if videos:
            if dirnames and all(_looks_like_nested_extra_video(v) for v in videos):
                continue
            yield folder
            dirnames[:] = []
            continue

        has_files = bool(filenames)
        has_subdirs = bool(dirnames)
        if has_files and (not has_subdirs):
            yield folder


def iter_scan_targets(cfg: Any, *, min_video_bytes: int) -> List[Path]:
    return list(stream_scan_targets(cfg, min_video_bytes=min_video_bytes))


# =========================================================
# Detection contenu non-film (scoring par heuristiques)
# =========================================================

# Seuil : score >= 60 → flag not_a_movie
_NOT_A_MOVIE_THRESHOLD = 60

# Points par heuristique
_NAM_SUSPECT_NAME_PTS = 40
_NAM_SIZE_TINY_PTS = 30  # < 100 Mo
_NAM_SIZE_SMALL_PTS = 15  # 100-300 Mo
_NAM_NO_TMDB_PTS = 25
_NAM_SHORT_TITLE_PTS = 10  # ≤ 3 mots
_NAM_UNCOMMON_EXT_PTS = 10
_NAM_DURATION_VERY_SHORT_PTS = 35  # < 5 min
_NAM_DURATION_SHORT_PTS = 25  # < 20 min
_NAM_DURATION_VERY_SHORT_S = 300  # 5 minutes
_NAM_DURATION_SHORT_S = 1200  # 20 minutes

_NAM_SIZE_TINY_BYTES = 100 * 1024 * 1024  # 100 Mo
_NAM_SIZE_SMALL_BYTES = 300 * 1024 * 1024  # 300 Mo

# Mots-cles suspects dans le nom de fichier/dossier
_NOT_A_MOVIE_KEYWORDS_RE = re.compile(
    r"\b(sample|trailer|making|featurette|interview|deleted|extra|behind|teaser|demo|promo|blooper|outtake|recap|gag\s?reel)\b",
    re.IGNORECASE,
)

# Extensions peu courantes (fragments DVD/BD)
_UNCOMMON_VIDEO_EXTS = frozenset({".m2ts", ".ts", ".vob"})


def not_a_movie_score(
    video_name: str,
    file_size: int,
    proposed_source: str,
    confidence: int,
    title: str,
    *,
    duration_s: float | None = None,
) -> int:
    """Calcule un score de probabilite que la video ne soit pas un film.

    Score >= _NOT_A_MOVIE_THRESHOLD (60) → flag not_a_movie.
    """
    score = 0

    # 1. Nom contient un mot-cle suspect
    name_combined = f"{video_name} {title}"
    if _NOT_A_MOVIE_KEYWORDS_RE.search(name_combined):
        score += _NAM_SUSPECT_NAME_PTS

    # 2. Taille du fichier
    sz = int(file_size or 0)
    if 0 < sz < _NAM_SIZE_TINY_BYTES:
        score += _NAM_SIZE_TINY_PTS
    elif _NAM_SIZE_TINY_BYTES <= sz < _NAM_SIZE_SMALL_BYTES:
        score += _NAM_SIZE_SMALL_PTS

    # 3. Pas de match TMDb
    src = str(proposed_source or "").strip().lower()
    if src in ("unknown", "") or int(confidence or 0) == 0:
        score += _NAM_NO_TMDB_PTS

    # 4. Nom tres court (≤ 3 mots dans le titre)
    words = [w for w in str(title or "").split() if len(w) > 1]
    if 0 < len(words) <= 3:
        score += _NAM_SHORT_TITLE_PTS

    # 5. Extension peu courante
    ext = ""
    dot_idx = str(video_name or "").rfind(".")
    if dot_idx >= 0:
        ext = str(video_name)[dot_idx:].lower()
    if ext in _UNCOMMON_VIDEO_EXTS:
        score += _NAM_UNCOMMON_EXT_PTS

    # 6. Duree courte (si disponible)
    if duration_s is not None and duration_s > 0:
        if duration_s < _NAM_DURATION_VERY_SHORT_S:
            score += _NAM_DURATION_VERY_SHORT_PTS
        elif duration_s < _NAM_DURATION_SHORT_S:
            score += _NAM_DURATION_SHORT_PTS

    if score >= _NOT_A_MOVIE_THRESHOLD:
        logger.debug("not_a_movie: %s score=%d", video_name, score)
    return score
