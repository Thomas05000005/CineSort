from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Issue #83 : le cycle domain->app est CASSE (verifie par import-linter,
# contrat `domain_pure` KEPT en CI : domain n'importe ni app, ni infra, ni ui).
# Ce module n'importe plus rien de cinesort.app ; les alias historiques
# core_apply_support/core_plan_support et les re-exports ont ete supprimes
# (les commentaires "compatibility" plus bas ne sont que de la memoire
# d'archeologie pour les rares appelants externes qui pointaient vers ces
# re-exports et doivent desormais importer depuis cinesort.app directement).
#
# TmdbClient est sous TYPE_CHECKING car utilise uniquement comme annotation
# (seule exception whitelistee du contrat domain_pure, cf .importlinter).
import cinesort.domain.duplicate_support as core_duplicate_support
from cinesort.domain.confidence_thresholds import (
    CONF_HIGH as _CONF_HIGH,
)
from cinesort.domain.confidence_thresholds import (
    CONF_MEDIUM as _CONF_MEDIUM,
)
from cinesort.domain.scan_helpers import (
    collect_non_video_extensions as _collect_non_video_extensions,
)
from cinesort.domain.scan_helpers import (
    iter_videos,
)
from cinesort.domain.title_helpers import (
    _expand_tmdb_queries,
    _extract_trailing_sequel_num,
    _norm_for_tokens,
    _title_similarity,
    _tmdb_prefix_equivalent,
    clean_title_guess,
    extract_provider_tags,
    extract_year,
    infer_name_year,
    strip_provider_tags,
    title_match_score,
    title_prefix_before_parenthesized_year,
    tokens,
)

if TYPE_CHECKING:
    from cinesort.infra.tmdb_client import TmdbClient

# Cf #83 PR A2 : 3 cleanup re-exports backward-compat supprimes :
#   _move_empty_top_level_dirs, _move_residual_top_level_dirs,
#   preview_cleanup_residual_folders
# Aucun caller externe identifie (grep cinesort/ tests/). Si besoin futur,
# importer depuis cinesort.app.cleanup directement.

_COMPAT_SCAN_EXPORTS = (
    _collect_non_video_extensions,
    iter_videos,
)


# =========================================================
# CONFIG
# =========================================================

VIDEO_EXTS_DEFAULT = {
    ".mkv",
    ".mp4",
    ".avi",
    ".m2ts",
    ".m4v",
    ".mov",
    ".wmv",
    ".flv",
    ".ts",
    ".webm",
    ".mpg",
    ".mpeg",
    ".ogv",
    ".vob",
}

# Phase 6 (v7.8.0) : VIDEO_EXTS_ALL = union maximale des extensions video
# reconnues dans toute la codebase. Avant ce constant, apply_core/apply_support
# avaient 5 sets hardcodes divergents — un fichier .wmv pouvait etre considere
# video par 1 module et pas par les autres. A utiliser partout ou on detecte
# "un fichier video quelconque" (collisions, cleanup, integrity check).
VIDEO_EXTS_ALL = frozenset(
    {
        ".mkv",
        ".mp4",
        ".m2ts",
        ".avi",
        ".iso",
        ".ts",
        ".wmv",
        ".mov",
        ".webm",
    }
)
# #874 : `.idx` est la MOITIE d'une paire atomique VobSub (`.sub` = flux bitmap,
# `.idx` = index des timings/offsets). `.sub` etait dans la table, `.idx` non —
# alors que les deux autres tables de sidecars (SIDECAR_METADATA_EXTS,
# RESIDUAL_SUBTITLE_EXTS) les listent toutes les deux. Consequence sur les deux
# sites qui DEPLACENT des fichiers (`classify_sidecars` ci-dessous et
# `apply_core.is_managed_merge_file`) : un merge/move emportait `Film.fr.sub` et
# laissait `Film.fr.idx` derriere. Un `.sub` prive de son `.idx` est illisible.
# Aucune migration de reglages n'est requise : `build_cfg_from_settings`
# (ui/api/settings_support.py) ne cable JAMAIS `side_exts`, donc le champ vaut
# toujours None et `normalized()` retombe sur ce defaut.
SIDE_EXTS_DEFAULT = {".nfo", ".jpg", ".jpeg", ".png", ".webp", ".srt", ".ass", ".sub", ".idx"}

MIN_VIDEO_BYTES = (
    10 * 1024 * 1024
)  # 10MB (abaisse depuis 50MB pour couvrir DivX/Xvid legacy, courts metrages, animations)

GENERIC_SIDE_FILES_DEFAULT = {
    "movie.nfo",
    "poster.jpg",
    "poster.png",
    "fanart.jpg",
    "fanart.png",
    "folder.jpg",
}

SIDECAR_METADATA_EXTS = {
    ".nfo",
    ".xml",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tbn",
    ".srt",
    ".ass",
    ".sub",
    ".idx",
    ".txt",
    ".url",
}

SIDECAR_METADATA_BASENAMES = {
    "movie.nfo",
    "tvshow.nfo",
    "folder.jpg",
    "poster.jpg",
    "fanart.jpg",
    "landscape.jpg",
    "logo.png",
}

RESIDUAL_NFO_EXTS = {".nfo", ".xml"}
RESIDUAL_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tbn"}
RESIDUAL_SUBTITLE_EXTS = {".srt", ".ass", ".sub", ".idx"}
RESIDUAL_TEXT_EXTS = {".txt", ".url", ".md"}

# TV-like skip heuristics
_TV_HINT_RE = re.compile(
    r"\b(?:S\d{1,2}E\d{1,3}|\d{1,2}x\d{1,3}|episode[ ._-]?\d{1,3}|ep[ ._-]?\d{1,3})\b", re.IGNORECASE
)
_TV_SEASON_RE = re.compile(r"^season[ ._-]?\d{1,2}$", re.IGNORECASE)

# TMDb candidate scoring constants.
_TMDB_SCORE_BASE = 0.25
_TMDB_SCORE_SIM_CAP = 0.55
_TMDB_SCORE_YEAR_CLOSE_BONUS = 0.15
# #451 : `_TMDB_SCORE_YEAR_FAR_PENALTY` (0.08) vivait ici. Son unique lecteur
# etait la branche `elif year_delta >= 6` de build_candidates_from_tmdb, rendue
# inatteignable par la branche `>= _TMDB_YEAR_FAR_THRESHOLD` (3) qui la precede.
# Constante et branche supprimees ensemble : la penalite d'ecart d'annee est
# desormais unique (_TMDB_YEAR_FAR_HEAVY_PENALTY).
_TMDB_SCORE_POPULAR_BONUS = 0.05
_TMDB_SCORE_SEQUEL_MATCH_BONUS = 0.12
_TMDB_SCORE_SEQUEL_MISSING_PENALTY = 0.22
_TMDB_SCORE_SEQUEL_MISMATCH_PENALTY = 0.26

# Scoring strict (anti-faux positifs catastrophiques).
# FIX 1 : seuil absolu de rejet sur la similarite textuelle.
_TMDB_STRICT_MIN_SIM = 0.50
# FIX 3 : ecart d'annee au-dela duquel on penalise fortement.
_TMDB_YEAR_FAR_THRESHOLD = 3
_TMDB_YEAR_FAR_HEAVY_PENALTY = 0.30
# FIX 8 : seuil pour titres courts (<=4 caracteres normalises).
_TMDB_SHORT_TITLE_MAX_LEN = 4
_TMDB_SHORT_TITLE_MIN_SIM = 0.90
# FIX 4 : mots-cles qui trahissent un bonus/documentaire (a filtrer).
_TMDB_BONUS_KEYWORDS = frozenset(
    {
        "making of",
        "behind the scenes",
        "featurette",
        "bonus",
        "the mutant watch",
        "inside look",
        "promo",
        "trailer",
    }
)

# F03/F34 : le filtre bonus se faisait par SOUS-CHAINE nue ("promo" in
# "the promotion" -> True, "trailer" in "trailer park boys" -> True), ce qui
# eliminait TOUS les resultats TMDb corrects pour une classe de titres
# legitimes -> aucun tmdb_id, aucune jaquette, +25 pts "pas de match TMDb".
# On exige desormais une frontiere de MOT (le mot-cle ne doit pas etre colle a
# une lettre ou un chiffre), les mots-cles multi-mots restant supportes tels quels.
_TMDB_BONUS_KEYWORD_RE = re.compile(
    r"(?<![0-9a-z])(?:" + "|".join(re.escape(kw) for kw in sorted(_TMDB_BONUS_KEYWORDS)) + r")(?![0-9a-z])"
)

# Un regex PAR mot-cle : la neutralisation liee a la requete doit etre
# selective. Une garde tout-ou-rien desactiverait les 7 autres mots-cles des que
# la requete en contient un seul, ce qui reactiverait le probleme d'origine dans
# l'autre sens (un vrai bonus « Behind the Scenes » redeviendrait candidat pour
# la requete « Trailer Park Boys »).
_TMDB_BONUS_KEYWORD_RES = tuple(
    re.compile(r"(?<![0-9a-z])" + re.escape(kw) + r"(?![0-9a-z])") for kw in sorted(_TMDB_BONUS_KEYWORDS)
)


@dataclass(frozen=True)
class Config:
    root: Path
    enable_collection_folder: bool = True
    collection_root_name: str = "_Collection"
    empty_folders_folder_name: str = "_Vide"
    move_empty_folders_enabled: bool = False
    empty_folders_scope: str = "root_all"
    cleanup_residual_folders_enabled: bool = False
    cleanup_residual_folders_folder_name: str = "_Dossier Nettoyage"
    cleanup_residual_folders_scope: str = "touched_only"
    cleanup_residual_include_nfo: bool = True
    cleanup_residual_include_images: bool = True
    cleanup_residual_include_subtitles: bool = True
    cleanup_residual_include_texts: bool = True

    video_exts: Set[str] = None
    side_exts: Set[str] = None
    generic_side_files: Set[str] = None

    detect_extras_in_single_folder: bool = True
    extras_size_ratio: float = 4.0
    skip_tv_like: bool = True
    enable_tv_detection: bool = False

    # NFO safety
    title_match_min_cov: float = 0.75
    title_match_min_seq: float = 0.78
    max_year_delta_when_name_has_year: int = 1

    # TMDb
    enable_tmdb: bool = True
    tmdb_language: str = "fr-FR"

    # Scan
    incremental_scan_enabled: bool = False
    # Seuil minimal taille fichier video (en octets). None = utilise MIN_VIDEO_BYTES (10MB).
    # Permet de configurer le seuil pour bibliotheques avec courts metrages / animations.
    min_video_bytes: Optional[int] = None
    # VO-B : nombre de workers pour la pre-extraction locale parallele de
    # `_filter_dossiers_phase`. 1 (default) = comportement sequentiel strict
    # historique (pas de ThreadPoolExecutor cree). >=2 active la parallelisation
    # Phase 1 (iter_videos + collect_non_video_extensions). Plafonne a 32.
    # Voir cinesort/app/_local_candidate.py et docs/internal/VO_B_ANALYSIS.md.
    scan_max_workers: int = 1

    # Profils de renommage
    naming_movie_template: str = "{title} ({year})"
    naming_tv_template: str = "{series} ({year})"

    # ITER7 - Reglage UI "Extensions en minuscule (.mkv vs .MKV)" : SUPPRIME.
    # Son seul effet etait de reconstruire le NOM DU FICHIER VIDEO cible avec un
    # suffixe force en minuscules (`Film.MKV` -> `Film.mkv`), ce qui viole la
    # regle inviolable n1 (« ne JAMAIS renommer le fichier video » : le nom doit
    # rester synchrone avec le torrent, sinon le seeding casse). Aucun nom de
    # DOSSIER n'en dependait. La cle peut subsister dans un settings.json
    # existant : elle est simplement ignoree (le merge read-modify-write de
    # save_settings_payload preserve les cles inconnues).

    # ITER7 etape 3 - Reglage UI "Separateur" (selecteur {".", " ", "_", "-"})
    # Persiste par _save_section_naming (ui/api/settings_support.py L1611-1613)
    # avec coerce-and-default (sep in {".", " ", "_", "-"} sinon ".").
    # Approvisionne le pipeline Domain -> App via cfg.separator. Exposee comme
    # variable opt-in `{sep}` dans le contexte template (build_naming_context),
    # ce qui permet aux templates custom de l'utiliser sans rupture (templates
    # existants type "{title} ({year})" ne referencent pas {sep} donc rendu
    # strictement inchange : STOP_FORK CUSTOM TEMPLATE preserve).
    # Default " " (espace) aligne sur le comportement historique du template
    # "{title} ({year})" et sur le sentinel "valeur saine" du selecteur UI.
    separator: str = " "

    def normalized(self) -> "Config":
        collection_name = windows_safe(str(self.collection_root_name or "_Collection")) or "_Collection"
        empty_name = windows_safe(str(self.empty_folders_folder_name or "_Vide")) or "_Vide"
        empty_scope = str(self.empty_folders_scope or "root_all").strip().lower()
        if empty_scope not in {"touched_only", "root_all"}:
            empty_scope = "root_all"
        residual_name = (
            windows_safe(str(self.cleanup_residual_folders_folder_name or "_Dossier Nettoyage")) or "_Dossier Nettoyage"
        )
        residual_scope = str(self.cleanup_residual_folders_scope or "touched_only").strip().lower()
        if residual_scope not in {"touched_only", "root_all"}:
            residual_scope = "touched_only"
        return Config(
            root=self.root,
            enable_collection_folder=self.enable_collection_folder,
            collection_root_name=collection_name,
            empty_folders_folder_name=empty_name,
            move_empty_folders_enabled=bool(self.move_empty_folders_enabled),
            empty_folders_scope=empty_scope,
            cleanup_residual_folders_enabled=bool(self.cleanup_residual_folders_enabled),
            cleanup_residual_folders_folder_name=residual_name,
            cleanup_residual_folders_scope=residual_scope,
            cleanup_residual_include_nfo=bool(self.cleanup_residual_include_nfo),
            cleanup_residual_include_images=bool(self.cleanup_residual_include_images),
            cleanup_residual_include_subtitles=bool(self.cleanup_residual_include_subtitles),
            cleanup_residual_include_texts=bool(self.cleanup_residual_include_texts),
            video_exts=set(x.lower() for x in (self.video_exts or VIDEO_EXTS_DEFAULT)),
            side_exts=set(x.lower() for x in (self.side_exts or SIDE_EXTS_DEFAULT)),
            generic_side_files=set(x.lower() for x in (self.generic_side_files or GENERIC_SIDE_FILES_DEFAULT)),
            detect_extras_in_single_folder=self.detect_extras_in_single_folder,
            extras_size_ratio=float(self.extras_size_ratio),
            skip_tv_like=self.skip_tv_like,
            enable_tv_detection=bool(self.enable_tv_detection),
            title_match_min_cov=float(self.title_match_min_cov),
            title_match_min_seq=float(self.title_match_min_seq),
            max_year_delta_when_name_has_year=int(self.max_year_delta_when_name_has_year),
            enable_tmdb=self.enable_tmdb,
            tmdb_language=self.tmdb_language,
            incremental_scan_enabled=bool(self.incremental_scan_enabled),
            min_video_bytes=int(self.min_video_bytes) if self.min_video_bytes is not None else None,
            scan_max_workers=max(1, int(self.scan_max_workers or 1)),
            naming_movie_template=str(self.naming_movie_template or "{title} ({year})"),
            naming_tv_template=str(self.naming_tv_template or "{series} ({year})"),
            # ITER7 etape 3 : coerce-and-default identique a _save_section_naming
            # pour proteger les configs anciennes ou editees a la main contre une
            # valeur invalide qui sortirait du jeu {".", " ", "_", "-"}.
            separator=(str(self.separator) if str(self.separator) in {".", " ", "_", "-"} else " "),
        )


@dataclass
class Stats:
    folders_scanned: int = 0
    collections_seen: int = 0
    singles_seen: int = 0
    collection_rows_generated: int = 0
    skipped_tv_like: int = 0
    tv_episodes_seen: int = 0
    root_level_films_seen: int = 0

    planned_rows: int = 0
    errors: int = 0
    analyse_ignores_total: int = 0
    analyse_ignores_par_raison: Dict[str, int] = field(default_factory=dict)
    analyse_ignores_extensions: Dict[str, int] = field(default_factory=dict)
    incremental_cache_hits: int = 0
    incremental_cache_misses: int = 0
    incremental_cache_rows_reused: int = 0
    incremental_cache_row_hits: int = 0
    incremental_cache_row_misses: int = 0
    # Phase 2 SCAN-1 (observabilite) : compteurs detailles de rejet pour debug post-scan.
    # Exposes via dashboard_support dans une carte "Diagnostic scan".
    films_rejected_ext: int = 0  # fichier video : extension hors VIDEO_EXTS
    films_rejected_size: int = 0  # fichier video : taille < MIN_VIDEO_BYTES
    films_rejected_name: int = 0  # fichier video : nom matche IGNORE_VIDEO_NAME_RE (sample/trailer/teaser)
    folders_rejected_underscore: int = 0  # dossier prefixe '_' (skip _Collection, _Vide, etc.)
    folders_rejected_depth: int = 0  # dossier au-dela de max_depth
    folders_rejected_scandir_error: int = 0  # echec os.scandir (PermissionError, OSError, timeout SMB)
    folders_rejected_tv_like_count_videos: int = 0  # dossier rejete par looks_tv_like (compte videos)


def _stats_add_ignore(stats: Stats, reason: str) -> None:
    key = str(reason or "ignore_autre")
    stats.analyse_ignores_total += 1
    stats.analyse_ignores_par_raison[key] = int(stats.analyse_ignores_par_raison.get(key, 0)) + 1


def _stats_add_ignored_extension(stats: Stats, ext: str) -> None:
    key = str(ext or "").strip().lower() or "<sans_ext>"
    stats.analyse_ignores_extensions[key] = int(stats.analyse_ignores_extensions.get(key, 0)) + 1


# =========================================================
# DATA MODELS (rows)
# =========================================================


@dataclass
class Candidate:
    title: str
    year: Optional[int]
    source: str  # "nfo"|"name"|"tmdb"
    tmdb_id: Optional[int] = None
    poster_url: Optional[str] = None
    score: float = 0.0  # 0..1 for internal ranking
    note: str = ""
    tmdb_collection_id: Optional[int] = None
    tmdb_collection_name: Optional[str] = None


@dataclass
class PlanRow:
    row_id: str
    # AUDIT 2026-07-13 [CRIT-1] cause racine : ce commentaire OMETTAIT "extra" et
    # c'est contre cette liste incomplete que la garde destructive `== "collection"`
    # de apply_core avait ete ecrite (extra/tv_episode tombaient sur MOVE_DIR =
    # dossier PARTAGE emporte). Liste EXHAUSTIVE des kinds ecrits par le planner :
    #   - "single"     -> plan_support_replan.py:798 / apply_core.py:1044
    #   - "collection" -> plan_support_replan.py:830
    #   - "tv_episode" -> plan_support_replan.py:908,970
    #   - "extra"      -> plan_support_core.py:760 (video bonus d'un dossier partage)
    # INVARIANT DESTRUCTIF : SEUL "single" possede un dossier dedie ; tout autre kind
    # partage son dossier -> ne jamais deplacer/supprimer le dossier entier.
    kind: str  # "single" | "collection" | "tv_episode" | "extra"
    folder: str  # folder path (string)
    video: str  # video filename (can be empty for single if unknown)
    proposed_title: str
    proposed_year: int
    proposed_source: str  # "nfo"|"name"|"tmdb"
    confidence: int  # 0..100
    confidence_label: str  # "high"|"med"|"low"

    # extra
    candidates: List[Candidate]
    nfo_path: Optional[str] = None
    notes: str = ""
    detected_year: int = 0
    detected_year_reason: str = ""
    warning_flags: List[str] = field(default_factory=list)
    # for collections: original top folder name (useful for quarantine)
    collection_name: Optional[str] = None
    # TV series fields (None for movies)
    tv_series_name: Optional[str] = None
    tv_season: Optional[int] = None
    tv_episode: Optional[int] = None
    tv_episode_title: Optional[str] = None
    tv_tmdb_series_id: Optional[int] = None
    # TMDb collection (saga) — None si pas de collection
    tmdb_collection_id: Optional[int] = None
    tmdb_collection_name: Optional[str] = None
    # Edition (Director's Cut, Extended, IMAX, etc.) — None si pas d'edition
    edition: Optional[str] = None
    # Multi-root: root d'origine (None = legacy single-root)
    source_root: Optional[str] = None
    # Sous-titres externes (detection, pas de renommage)
    subtitle_count: int = 0
    subtitle_languages: List[str] = field(default_factory=list)
    subtitle_formats: List[str] = field(default_factory=list)
    subtitle_missing_langs: List[str] = field(default_factory=list)
    subtitle_orphans: int = 0
    # NFO runtime persisté depuis le scan (minutes). Sert au cross-check probe (P1.1.d).
    nfo_runtime: Optional[int] = None


# =========================================================
# PATH + NAME HELPERS
# =========================================================
#
# VQ-1 (refactor) : `windows_safe` et `_norm_win_path` ont ete extraits vers
# `cinesort.domain.path_utils` (feuille du graphe d'imports) pour casser le
# cycle domain<->domain :
#
#   AVANT : core -> duplicate_support -> (lazy) naming -> core
#   APRES : core -> path_utils  ; naming -> path_utils  (plus de retour vers core)
#
# Les noms sont RE-EXPORTES ici pour preserver integralement la backward
# compatibility : app/apply_core, app/plan_support_*, app/cleanup,
# ui/api/run_data_support, ui/api/settings_support et tests/test_domain_core
# continuent d'utiliser `cinesort.domain.core.windows_safe` /
# `core_mod._norm_win_path` sans aucune modification.
from cinesort.domain.path_utils import (  # noqa: E402  (re-export volontaire)
    _norm_win_path,
    windows_safe,
)


def ensure_inside_root(cfg: Config, dst: Path) -> None:
    """Raise RuntimeError if *dst* resolves outside cfg.root (path-traversal guard)."""
    root_pw = _norm_win_path(cfg.root)
    dst_pw = _norm_win_path(dst)
    try:
        dst_pw.relative_to(root_pw)
    except ValueError:
        raise RuntimeError(f"REFUS: destination hors ROOT: {dst}") from None


def _is_cancel_requested(should_cancel: Optional[Callable[[], bool]]) -> bool:
    if should_cancel is None:
        return False
    try:
        return bool(should_cancel())
    except (RuntimeError, TypeError, ValueError, OSError):
        # Cancellation callback errors must never break planning.
        return False


def looks_tv_like(folder: Path, videos: List[Path]) -> bool:
    hints = 0
    for v in videos:
        if _TV_HINT_RE.search(v.name):
            hints += 1
    if hints >= 2:
        return True
    # Very large folders with episode-style hints are likely TV, not movie collections.
    if len(videos) >= 12 and hints >= 1:
        return True
    try:
        for p in folder.iterdir():
            if p.is_dir() and _TV_SEASON_RE.match(p.name.strip()):
                return True
    except (OSError, PermissionError):
        pass
    return False


def detect_single_with_extras(cfg: Config, videos: List[Path]) -> bool:
    if not cfg.detect_extras_in_single_folder:
        return False
    if len(videos) <= 1:
        return False
    sizes = []
    for v in videos:
        try:
            sizes.append(v.stat().st_size)
        except (OSError, PermissionError):
            sizes.append(0)
    sizes_sorted = sorted(sizes, reverse=True)
    if len(sizes_sorted) < 2:
        return False
    biggest, second = sizes_sorted[0], sizes_sorted[1]
    if second <= 0:
        return True
    return (biggest / second) >= cfg.extras_size_ratio


def is_sidecar_for_video(video_stem: str, sidecar_stem: str) -> bool:
    vs = video_stem.lower()
    ss = sidecar_stem.lower()
    if ss == vs:
        return True
    return any(ss.startswith(vs + delim) for delim in (".", " ", "_", "-", "(", "["))


def classify_sidecars(cfg: Config, folder: Path, video: Path, *, is_collection: bool) -> List[Path]:
    stem = video.stem
    out: List[Path] = []
    try:
        entries = list(folder.iterdir())
    except (OSError, PermissionError):
        return out
    # F03 : arbitrage LONGEST-MATCH. `is_sidecar_for_video` matche par prefixe :
    # dans un dossier PARTAGE, "Alien 2.srt" matche aussi "Alien.mkv". Sans
    # arbitrage, le sous-titre d'un film etait revendique par le film au stem le
    # plus court -> a l'apply (loser de doublon, marquage suppression, collection)
    # le .srt partait avec le MAUVAIS film, voire dans un bucket de suppression.
    # Regle retenue : le sidecar appartient a la video dont le stem est le plus
    # specifique (le plus long) parmi celles qui le revendiquent — c'est la
    # convention Plex/Jellyfin (le nom de base du sous-titre == celui de la video).
    # Les videos que le SCAN rejette (sample/trailer/teaser) ne produisent aucune
    # row : leur attribuer un sidecar le laisserait orphelin dans le dossier
    # source au lieu de suivre le film. On ne les compte donc pas comme
    # concurrentes. Import local : scan_helpers est un module feuille du domaine,
    # l'importer au niveau module alourdirait le graphe pour un seul usage.
    from cinesort.domain.scan_helpers import IGNORE_VIDEO_NAME_RE

    sibling_video_stems = [
        p.stem
        for p in entries
        if p.is_file() and p != video and p.suffix.lower() in cfg.video_exts and not IGNORE_VIDEO_NAME_RE.search(p.stem)
    ]
    for p in entries:
        if not p.is_file() or p == video:
            continue
        if p.suffix.lower() not in cfg.side_exts:
            continue
        name_l = p.name.lower()
        if is_sidecar_for_video(stem, p.stem):
            if any(len(other) > len(stem) and is_sidecar_for_video(other, p.stem) for other in sibling_video_stems):
                # Une autre video du dossier a un stem strictement plus specifique
                # qui revendique aussi ce sidecar : il lui appartient.
                continue
            out.append(p)
            continue
        if (not is_collection) and (name_l in cfg.generic_side_files):
            out.append(p)
    return out


# =========================================================
# NFO PARSING
# =========================================================


@dataclass(frozen=True)
class NfoInfo:
    title: Optional[str]
    originaltitle: Optional[str]
    year: Optional[int]
    tmdbid: Optional[str]
    imdbid: Optional[str]
    # Runtime en minutes (convention Kodi). Source : tag <runtime>, secondaire <fileinfo><streamdetails><video><durationinseconds>.
    runtime: Optional[int] = None


def _parse_nfo_runtime(root: ET.Element) -> Optional[int]:
    """Extrait le runtime en minutes depuis un NFO Kodi.

    Kodi écrit `<runtime>148</runtime>` en minutes. Certains scrapers utilisent
    `<fileinfo><streamdetails><video><durationinseconds>8880</durationinseconds>`
    (TMM tinyMediaManager). On accepte les deux et on normalise en minutes.
    """
    rt_el = root.find("runtime")
    if rt_el is not None and rt_el.text and rt_el.text.strip():
        raw = rt_el.text.strip()
        # Tolérer "148 min" ou "148min"
        digits = "".join(ch for ch in raw if ch.isdigit())
        if digits:
            try:
                minutes = int(digits)
                if 1 <= minutes <= 1200:
                    return minutes
            except ValueError:
                pass

    secs_el = root.find("fileinfo/streamdetails/video/durationinseconds")
    if secs_el is not None and secs_el.text and secs_el.text.strip():
        try:
            secs = int(secs_el.text.strip())
            if 60 <= secs <= 72000:
                return max(1, secs // 60)
        except ValueError:
            pass
    return None


def parse_movie_nfo(nfo_path: Path) -> Optional[NfoInfo]:
    """Parse a Kodi-style .nfo XML file and return structured metadata, or None on failure."""
    # Lire avec encodage UTF-8, fallback Latin-1 (NFO Kodi souvent mal encodes)
    content = None
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            content = nfo_path.read_text(encoding=enc)
            break
        except (UnicodeDecodeError, FileNotFoundError, PermissionError, OSError):
            continue
    if not content:
        return None
    try:
        # Bandit B314 : ET.fromstring peut etre vulnerable a XXE (XML External
        # Entity). Python 3.12+ ne resout plus les entites externes par defaut
        # mais on documente le contexte safe : le NFO est un fichier local du
        # filesystem utilisateur (cree par Kodi/Jellyfin/manual), pas un input
        # reseau venant d'un attaquant. Single-user desktop = pas de privilege
        # escalation possible.
        root = ET.fromstring(content)  # noqa: S314
    except (ET.ParseError, ValueError):
        return None

    def get_text(tag: str) -> Optional[str]:
        el = root.find(tag)
        return el.text.strip() if el is not None and el.text else None

    title = get_text("title")
    original = get_text("originaltitle")
    year_s = get_text("year")
    tmdbid = get_text("tmdbid")
    imdbid = get_text("imdbid") or get_text("id")

    y = int(year_s) if year_s and year_s.isdigit() else None
    runtime = _parse_nfo_runtime(root)
    return NfoInfo(title=title, originaltitle=original, year=y, tmdbid=tmdbid, imdbid=imdbid, runtime=runtime)


def find_best_nfo_for_video(folder: Path, video: Path) -> Optional[Path]:
    try:
        nfos = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".nfo"]
    except (PermissionError, OSError):
        return None
    if not nfos:
        return None
    same = [p for p in nfos if p.stem.lower() == video.stem.lower()]
    if same:
        return same[0]
    nongeneric = [p for p in nfos if p.name.lower() != "movie.nfo"]
    if nongeneric:
        return sorted(nongeneric, key=lambda p: p.name.lower())[0]
    movie = [p for p in nfos if p.name.lower() == "movie.nfo"]
    return movie[0] if movie else sorted(nfos, key=lambda p: p.name.lower())[0]


@dataclass(frozen=True)
class NfoConsistency:
    """Résultat détaillé de la cohérence NFO vs dossier/fichier.

    P1.1.b : distinguer "NFO matche le dossier" et "NFO matche le fichier vidéo".
    Un NFO qui ne matche QUE le dossier (pas le fichier) est le signal classique
    d'un fichier vidéo remplacé/déplacé sans mise à jour du NFO — l'utilisateur
    peut avoir écrasé matrix.mkv par inception.mkv dans un dossier "Inception/".

    Attributs :
        ok : true si `folder_match` OU `filename_match`.
        cov, seq : meilleures métriques globales (rétrocompat `nfo_consistent`).
        folder_match : le NFO matche le nom du dossier.
        filename_match : le NFO matche le nom du fichier vidéo.
        folder_cov/seq, filename_cov/seq : métriques par source (pour debug/explain).
    """

    ok: bool
    cov: float
    seq: float
    folder_match: bool
    filename_match: bool
    folder_cov: float
    folder_seq: float
    filename_cov: float
    filename_seq: float


def nfo_consistency_check(cfg: Config, nfo: NfoInfo, folder_name: str, video_name: str) -> NfoConsistency:
    """Version détaillée de `nfo_consistent` — retourne folder_match et filename_match séparés."""
    titles = [t for t in (nfo.title, nfo.originaltitle) if t and t.strip()]
    if not titles:
        return NfoConsistency(
            ok=False,
            cov=0.0,
            seq=0.0,
            folder_match=False,
            filename_match=False,
            folder_cov=0.0,
            folder_seq=0.0,
            filename_cov=0.0,
            filename_seq=0.0,
        )

    folder_candidates = [
        c
        for c in (
            folder_name,
            clean_title_guess(folder_name),
            title_prefix_before_parenthesized_year(folder_name),
        )
        if c and c.strip()
    ]
    filename_candidates = [
        c
        for c in (
            video_name,
            clean_title_guess(video_name),
            title_prefix_before_parenthesized_year(video_name),
        )
        if c and c.strip()
    ]

    def _best(cands: List[str]) -> Tuple[float, float]:
        best_cov, best_seq = 0.0, 0.0
        for t in titles:
            for c in cands:
                cov, seq = title_match_score(t, c)
                best_cov = max(best_cov, cov)
                best_seq = max(best_seq, seq)
        return best_cov, best_seq

    folder_cov, folder_seq = _best(folder_candidates)
    filename_cov, filename_seq = _best(filename_candidates)

    folder_match = (folder_cov >= cfg.title_match_min_cov) or (folder_seq >= cfg.title_match_min_seq)
    filename_match = (filename_cov >= cfg.title_match_min_cov) or (filename_seq >= cfg.title_match_min_seq)

    best_cov = max(folder_cov, filename_cov)
    best_seq = max(folder_seq, filename_seq)
    ok = folder_match or filename_match

    logger.debug(
        "nfo_consistency: folder=%r video=%r titles=%d -> ok=%s folder=%s(cov=%.2f,seq=%.2f) file=%s(cov=%.2f,seq=%.2f)",
        folder_name,
        video_name,
        len(titles),
        ok,
        folder_match,
        folder_cov,
        folder_seq,
        filename_match,
        filename_cov,
        filename_seq,
    )
    return NfoConsistency(
        ok=ok,
        cov=best_cov,
        seq=best_seq,
        folder_match=folder_match,
        filename_match=filename_match,
        folder_cov=folder_cov,
        folder_seq=folder_seq,
        filename_cov=filename_cov,
        filename_seq=filename_seq,
    )


def nfo_consistent(cfg: Config, nfo: NfoInfo, folder_name: str, video_name: str) -> Tuple[bool, float, float]:
    """
    Verifie si title/originaltitle du NFO correspond au dossier ou au fichier video.
    Retourne (ok, best_cov, best_seq). Wrapper rétrocompat autour de `nfo_consistency_check`.
    """
    result = nfo_consistency_check(cfg, nfo, folder_name, video_name)
    return result.ok, result.cov, result.seq


def nfo_soft_consistent(*, name_year: Optional[int], nfo_year: Optional[int], cov: float, seq: float) -> bool:
    """
    Tolérance contrôlée:
    - année cohérente (écart <= 1)
    - similarité moyenne mais exploitable
    """
    if name_year is None or nfo_year is None:
        return False
    if abs(int(name_year) - int(nfo_year)) > 1:
        return False
    if cov >= 0.62 or seq >= 0.78:
        return True
    if cov >= 0.50 and seq >= 0.70:
        return True
    return False


# =========================================================
# RESOLVE CANDIDATES + CONFIDENCE
# =========================================================


def _nfo_tmdbid_as_int(raw: object) -> Optional[int]:
    """Parse tolerant du <tmdbid> NFO (str) vers int, None si inexploitable."""
    s = str(raw or "").strip()
    if not s.isdigit():
        return None
    val = int(s)
    return val if val > 0 else None


def build_candidates_from_nfo(nfo: NfoInfo) -> List[Candidate]:
    out: List[Candidate] = []
    if (nfo.title or nfo.originaltitle) and nfo.year:
        # GAP-NFO-TMDBID (Lot D 2026-07) : le <tmdbid> du NFO est une identite
        # TMDb gratuite (zero reseau) — sans elle, jaquettes/doublons dependaient
        # d'une resolution TMDb differee par titre. L'anti-NFO-pollue reste
        # assure cote app : _augment_candidates_from_nfo_tmdb_id retire cet id
        # si le cross-check TMDb (quand il est possible) le rejette.
        out.append(
            Candidate(
                title=str(nfo.title or nfo.originaltitle),
                year=int(nfo.year),
                source="nfo",
                tmdb_id=_nfo_tmdbid_as_int(nfo.tmdbid),
                score=0.90,
            )
        )
    return out


def build_candidates_from_name(
    folder_name: str, video_name: str, *, preferred_year: Optional[int] = None
) -> List[Candidate]:
    # B02 : extraction prealable des tags providers {tmdb-XXX} / [imdbid-ttXXX]
    # depuis le nom de dossier ET du fichier video. Si un tmdb_id est trouve,
    # on emet un Candidate haute confiance (source="name_tag", score=0.98) qui
    # sera ensuite verifie via tmdb.find_by_tmdb_id(...) cote app (symetrique
    # au flow NFO dans _augment_candidates_from_nfo_tmdb_id). On strippe AUSSI
    # les tags des noms pour que clean_title_guess()/infer_name_year() ne
    # voient pas les chiffres TMDb ou les accolades.
    folder_tags = extract_provider_tags(folder_name)
    video_tags = extract_provider_tags(video_name)
    # Priorite : tag du dossier > tag du fichier (le dossier est la source de
    # verite pour le contenu du film, le fichier peut etre un .partN).
    tmdb_id_from_tag = folder_tags.tmdb_id or video_tags.tmdb_id
    imdb_id_from_tag = folder_tags.imdb_id or video_tags.imdb_id

    folder_clean = strip_provider_tags(folder_name) if (folder_tags.tmdb_id or folder_tags.imdb_id) else folder_name
    video_clean = strip_provider_tags(video_name) if (video_tags.tmdb_id or video_tags.imdb_id) else video_name

    y = preferred_year
    if y is None:
        y, _, _ = infer_name_year(folder_clean, video_clean)
    t = clean_title_guess(folder_clean)
    if not (2 <= len(t) <= 70):
        t = clean_title_guess(video_clean)
    # LOTD-DUP-TITLE-YEAR (revue round 1) : le proposed_title reste INTACT —
    # "Blade Runner 2049" (film-annee sorti en 2017) ne doit JAMAIS devenir
    # "Blade Runner", le renommage disque suit le titre (seed torrents). La
    # tolerance "Titre 2005"|2005 == "Titre"|2005 est desormais portee
    # UNIQUEMENT par la cle de dedoublonnage/identite (duplicate_support.movie_key
    # + film_history.film_identity_key via title_helpers.strip_trailing_year_if_equal).
    out: List[Candidate] = []

    # B02 : Candidate deterministe issu du tag provider (court-circuit fuzzy).
    # On ne l'emet que si on a aussi pu deduire un titre/annee de base (pour
    # permettre le cross-check de similarite cote app), sinon on degrade
    # gracieusement vers les Candidates classiques.
    # REG-TAGS-03 : tant que la verification TMDb (tmdb.find_by_tmdb_id) n'est
    # pas cablee cote app (cf _augment_candidates_from_name_tags actuellement
    # code mort), on ne peut PAS faire confiance aveuglement au tag : un dossier
    # malicieux/errone `{tmdb-999999999}` injecterait un faux match deterministe
    # dominant. On degrade donc gracieusement le score a 0.72 (niveau d'un
    # name+year+folder_y match) jusqu'a ce que la verification soit cablee.
    if tmdb_id_from_tag and t:
        note_bits = []
        if folder_tags.tmdb_id:
            note_bits.append("folder tag")
        elif video_tags.tmdb_id:
            note_bits.append("video tag")
        if imdb_id_from_tag:
            note_bits.append(f"imdb={imdb_id_from_tag}")
        out.append(
            Candidate(
                title=t,
                year=y,
                source="name_tag",
                tmdb_id=tmdb_id_from_tag,
                score=0.72,
                note=", ".join(note_bits),
            )
        )

    if t and y:
        folder_y = extract_year(folder_clean)
        video_y = extract_year(video_clean)
        score = 0.60
        if folder_y and video_y and folder_y == video_y == y:
            score = 0.72
        elif (folder_y and folder_y == y) or (video_y and video_y == y):
            score = 0.66
        out.append(Candidate(title=t, year=y, source="name", score=score))
    return out


def build_candidates_from_tmdb_fallback(
    tmdb: TmdbClient,
    queries: List[str],
    year: Optional[int],
    language: str,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> List[Candidate]:
    """
    Try multiple queries and merge TMDb candidate lists.
    """
    seen_queries: Set[str] = set()
    merged: Dict[object, Candidate] = {}

    expanded_queries = _expand_tmdb_queries(queries)
    for idx, q in enumerate(expanded_queries):
        if _is_cancel_requested(should_cancel):
            break
        q2 = " ".join((q or "").split())
        if not q2:
            continue
        key = q2.lower()
        if key in seen_queries:
            continue
        seen_queries.add(key)

        cands = build_candidates_from_tmdb(
            tmdb,
            query=q2,
            year=year,
            language=language,
            should_cancel=should_cancel,
        )
        if _is_cancel_requested(should_cancel):
            break
        if not cands:
            continue

        query_bonus = max(0.0, 0.04 - (idx * 0.01))
        for c in cands:
            score = max(0.0, min(1.0, c.score + query_bonus))
            note = c.note
            if idx > 0:
                note = f"{note}, q{idx + 1}" if note else f"q{idx + 1}"
            adjusted = Candidate(
                title=c.title,
                year=c.year,
                source=c.source,
                tmdb_id=c.tmdb_id,
                poster_url=c.poster_url,
                score=score,
                note=note,
            )
            merge_key: object = (
                adjusted.tmdb_id if adjusted.tmdb_id else f"{adjusted.title.lower()}|{adjusted.year or 0}"
            )
            prev = merged.get(merge_key)
            if not prev or adjusted.score > prev.score:
                merged[merge_key] = adjusted

    out = list(merged.values())
    out.sort(key=lambda c: (c.score, c.year or 0), reverse=True)
    return out


def tmdb_poster_thumb_url(poster_path: Optional[str]) -> Optional[str]:
    if not poster_path:
        return None
    p = str(poster_path).strip()
    if not p:
        return None
    if not p.startswith("/"):
        p = "/" + p
    # Low-resolution thumbnail to keep network usage low.
    return f"https://image.tmdb.org/t/p/w92{p}"


def build_candidates_from_tmdb(
    tmdb: TmdbClient,
    query: str,
    year: Optional[int],
    language: str,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> List[Candidate]:
    if _is_cancel_requested(should_cancel):
        return []
    results = tmdb.search_movie(query=query, year=year, language=language, max_results=8)
    # Year filter can hide valid matches when release year differs by market/version.
    if (not results) and year is not None and (not _is_cancel_requested(should_cancel)):
        results = tmdb.search_movie(query=query, year=None, language=language, max_results=8)
    # Fallback langue : si fr-FR retourne 0 resultat, retenter en en-US
    if (not results) and language != "en-US" and (not _is_cancel_requested(should_cancel)):
        results = tmdb.search_movie(query=query, year=year, language="en-US", max_results=8)
        if (not results) and year is not None:
            results = tmdb.search_movie(query=query, year=None, language="en-US", max_results=8)
    out: List[Candidate] = []
    query_clean = clean_title_guess(query) or query
    query_seq = _extract_trailing_sequel_num(query_clean)
    token_count = len(tokens(query_clean))
    min_sim = 0.24
    if token_count <= 1:
        min_sim = 0.46
    elif token_count == 2:
        min_sim = 0.30

    # FIX 8 : les titres ultra-courts matchent trop de choses sur TMDb.
    # On exige un match quasi-exact pour eviter les faux positifs comme
    # "Ca" → "Carmen Miranda Fame" ou "BAC Nord" → "Norm of the North...".
    query_norm = _norm_for_tokens(query_clean)
    is_short_title = len(query_norm.replace(" ", "")) <= _TMDB_SHORT_TITLE_MAX_LEN
    if is_short_title:
        min_sim = max(min_sim, _TMDB_SHORT_TITLE_MIN_SIM)

    # F34 : un mot-cle present dans la REQUETE elle-meme (l'utilisateur cherche
    # bel et bien "Trailer Park Boys") ne doit plus servir a filtrer — sinon on
    # supprime le film recherche. La neutralisation est SELECTIVE : seuls les
    # mots-cles presents dans la requete sont desarmes, les autres continuent
    # d'ecarter les vrais bonus.
    query_terms_lower = f"{query_clean} {query}".lower()
    active_bonus_res = [rx for rx in _TMDB_BONUS_KEYWORD_RES if not rx.search(query_terms_lower)]

    for r in results:
        # FIX 4 : filtrer les bonus/documentaires promo par mot-cle dans le titre.
        combined_title_lower = f"{r.title or ''} {r.original_title or ''}".lower()
        if any(rx.search(combined_title_lower) for rx in active_bonus_res):
            continue

        title_sim = _title_similarity(query_clean, r.title)
        original_sim = _title_similarity(query_clean, r.original_title or "") if r.original_title else 0.0
        sim = max(title_sim, original_sim)

        if _tmdb_prefix_equivalent(query_clean, r.title) or (
            r.original_title and _tmdb_prefix_equivalent(query_clean, r.original_title)
        ):
            sim_floor = 0.80 if token_count >= 3 else 0.76
            sim = max(sim, sim_floor)

        # FIX 1 : seuil absolu de rejet. Un match < 0.50 de similarite textuelle
        # est probablement faux, independamment de l'annee.
        year_delta = abs(r.year - year) if (year and r.year) else None
        year_is_close = year_delta is not None and year_delta <= 1
        if sim < _TMDB_STRICT_MIN_SIM and not (year_is_close and sim >= 0.35):
            continue
        # Ancien seuil par nombre de tokens (garde pour backward compat sur titres
        # longs qui avaient des seuils plus permissifs).
        if sim < min_sim and not (year_is_close and sim >= (min_sim - 0.07)):
            continue

        score = _TMDB_SCORE_BASE + min(_TMDB_SCORE_SIM_CAP, sim * _TMDB_SCORE_SIM_CAP)
        if year_is_close:
            score += _TMDB_SCORE_YEAR_CLOSE_BONUS
        elif year_delta is not None and year_delta >= _TMDB_YEAR_FAR_THRESHOLD:
            # FIX 3 : penalite lourde si ecart annee > 2 ans. UNE SEULE marche :
            # #451 avait raison, la branche `elif year_delta >= 6` qui suivait
            # etait inatteignable (tout delta >= 6 satisfait deja `>= 3`) et sa
            # penalite legere n'a JAMAIS ete appliquee. Elle est supprimee plutot
            # que reordonnee : reintroduire une gradation adoucirait le score des
            # ecarts 3-5 ans, c'est-a-dire exactement les faux positifs que FIX 3
            # visait. Pin du comportement :
            # tests/test_core_heuristics.py::test_tmdb_year_gap_penalty_is_flat.
            score -= _TMDB_YEAR_FAR_HEAVY_PENALTY
        if r.vote_count and r.vote_count > 200:
            score += _TMDB_SCORE_POPULAR_BONUS
        sequel_note = ""
        if query_seq is not None:
            cand_seq = _extract_trailing_sequel_num(r.title or "") or _extract_trailing_sequel_num(
                r.original_title or ""
            )
            if cand_seq is None:
                score -= _TMDB_SCORE_SEQUEL_MISSING_PENALTY
                sequel_note = "seq=?"
            elif cand_seq == query_seq:
                score += _TMDB_SCORE_SEQUEL_MATCH_BONUS
                sequel_note = "seq=ok"
            else:
                score -= _TMDB_SCORE_SEQUEL_MISMATCH_PENALTY
                sequel_note = f"seq={cand_seq}"

        score = max(0.0, min(1.0, score))
        note = f"sim={sim:.2f}"
        if year_delta is not None:
            note += f", dY={year_delta}"
        if sequel_note:
            note += f", {sequel_note}"

        out.append(
            Candidate(
                title=r.title,
                year=r.year,
                source="tmdb",
                tmdb_id=r.id,
                poster_url=tmdb_poster_thumb_url(r.poster_path),
                score=score,
                note=note,
            )
        )

    out.sort(key=lambda c: (c.score, c.year or 0), reverse=True)
    return out


def should_reject_nfo_year(
    cfg: Config,
    *,
    name_year: Optional[int],
    nfo_year: Optional[int],
    remaster_hint: bool,
    cov: float,
    seq: float,
) -> Tuple[bool, str]:
    if name_year is None or nfo_year is None:
        return False, ""
    delta = abs(int(nfo_year) - int(name_year))
    if delta <= cfg.max_year_delta_when_name_has_year:
        return False, ""
    if remaster_hint and nfo_year < name_year and delta <= 80:
        return False, f"Ecart d'annee interprete comme version remaster/restauree (nom={name_year}, nfo={nfo_year})."
    if delta <= 2 and (cov >= 0.92 or seq >= 0.92):
        return False, f"Ecart d'annee mineur accepte (nom={name_year}, nfo={nfo_year})."
    return True, f"NFO ignore: annee incoherente (nom={name_year}, nfo={nfo_year})."


def build_plan_note(
    *,
    confidence: int,
    label: str,
    chosen: Optional[Candidate],
    name_year: Optional[int],
    name_year_reason: str,
    remaster_hint: bool,
    nfo_present: bool,
    nfo_ok: bool,
    nfo_cov: float,
    nfo_seq: float,
    nfo_reject_reason: str,
    tmdb_used: bool,
) -> str:
    """Build a human-readable French note summarising how the title/year was determined."""
    parts: List[str] = [f"Confiance {label.upper()} ({confidence}/100)."]

    if chosen:
        if chosen.source == "nfo":
            parts.append("Source retenue: NFO.")
        elif chosen.source == "tmdb":
            extra = []
            if chosen.tmdb_id:
                extra.append(f"id={chosen.tmdb_id}")
            if chosen.note:
                extra.append(chosen.note)
            suffix = f" ({', '.join(extra)})" if extra else ""
            parts.append(f"Source retenue: TMDb{suffix}.")
        elif chosen.source == "name":
            parts.append("Source retenue: nom du dossier/fichier.")
        else:
            parts.append(f"Source retenue: {chosen.source}.")

    if nfo_present and not nfo_ok:
        parts.append(f"NFO ignore: titre incoherent (cov={nfo_cov:.2f}, seq={nfo_seq:.2f}).")
    if nfo_reject_reason:
        parts.append(nfo_reject_reason)

    if name_year is not None:
        parts.append(f"Annee detectee (brute): {name_year} ({name_year_reason}).")
    else:
        parts.append("Annee detectee (brute): aucune annee dans le nom.")
    if chosen and chosen.year:
        parts.append(f"Annee retenue: {int(chosen.year)}.")

    if remaster_hint:
        parts.append("Indice remaster/restaure detecte.")
    if tmdb_used and (not chosen or chosen.source != "tmdb"):
        parts.append("TMDb utilise en verification.")
    if not chosen or not chosen.year:
        parts.append("Resolution automatique insuffisante: verification manuelle.")

    note = " ".join(parts)
    return (note[:377] + "...") if len(note) > 380 else note


def _warning_flags_from_analysis(
    *,
    chosen: Optional[Candidate],
    name_year_reason: str,
    nfo_present: bool,
    nfo_ok: bool,
    year_delta_reject: bool,
    nfo_partial_match: bool = False,
    title_ambiguity: bool = False,
) -> List[str]:
    flags: List[str] = []
    if nfo_present and (not nfo_ok):
        flags.append("nfo_title_mismatch")
    if nfo_present and nfo_ok and nfo_partial_match:
        # P1.1.b : NFO matche folder XOR filename. Signe d'un fichier vidéo
        # déplacé/remplacé sans mise à jour NFO → à revoir manuellement.
        flags.append("nfo_file_mismatch")
    if title_ambiguity:
        # P2.2 : deux films TMDb avec le même titre (ex: Dune 1984 / 2021).
        # Même après désambiguïsation contextuelle, on flag pour que l'user
        # puisse vérifier manuellement — le risque de confondre remake/original
        # est élevé sans intervention humaine.
        flags.append("title_ambiguity_detected")
    if year_delta_reject:
        flags.append("nfo_year_mismatch")
    if "conflit dossier/fichier" in str(name_year_reason or "").lower():
        flags.append("year_conflict_folder_file")
    if chosen and str(chosen.source or "").lower() == "tmdb":
        dy = _year_delta_from_candidate_note(chosen.note)
        if dy is not None and dy > 0:
            flags.append("tmdb_year_delta")
    out: List[str] = []
    seen: Set[str] = set()
    for f in flags:
        if f in seen:
            continue
        seen.add(f)
        out.append(f)
    return out


def _year_delta_from_candidate_note(note: str) -> Optional[int]:
    m = re.search(r"dY=(\d+)", str(note or ""))
    if not m:
        return None
    try:
        return int(m.group(1))
    except (ValueError, TypeError):
        return None


def _sim_from_candidate_note(note: str) -> Optional[float]:
    m = re.search(r"sim=([0-9]+(?:\.[0-9]+)?)", str(note or ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except (ValueError, TypeError):
        return None


def _consensus_from_candidate_note(note: str) -> Optional[float]:
    m = re.search(r"consensus=\+([0-9]+(?:\.[0-9]+)?)", str(note or ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except (ValueError, TypeError):
        return None


def _candidate_consensus_bonus(candidate: Candidate, cands: List[Candidate]) -> float:
    title_key = _norm_for_tokens(candidate.title or "")
    if not title_key:
        return 0.0
    source_set: Set[str] = set()
    year_votes = 0
    for c in cands:
        if _norm_for_tokens(c.title or "") != title_key:
            continue
        source_set.add(str(c.source or ""))
        if candidate.year and c.year and abs(int(candidate.year) - int(c.year)) <= 1:
            year_votes += 1
    bonus = 0.0
    if len(source_set) >= 2:
        bonus += 0.06
    if len(source_set) >= 3:
        bonus += 0.03
    if candidate.year and year_votes >= 2:
        bonus += 0.02
    return bonus


def pick_best_candidate(cands: List[Candidate]) -> Optional[Candidate]:
    """Select the highest-scoring candidate, applying cross-source consensus bonuses."""
    if not cands:
        return None
    ranked: List[Tuple[float, Candidate]] = []
    for c in cands:
        bonus = _candidate_consensus_bonus(c, cands)
        ranked.append((float(c.score) + bonus, c))
    ranked.sort(key=lambda item: (item[0], item[1].score, 1 if item[1].year else 0), reverse=True)
    best = ranked[0][1]
    best_bonus = max(0.0, ranked[0][0] - float(best.score))
    if best_bonus > 0.0:
        note = str(best.note or "")
        suffix = f"consensus=+{best_bonus:.2f}"
        # #450 : `Candidate` n'est pas frozen et `cands` appartient a l'appelant
        # (plan_support_replan stocke CETTE liste telle quelle dans
        # PlanRow.candidates). Muter `best.note` en place survivrait a l'appel :
        # une seconde evaluation de la meme liste empilerait un second suffixe
        # "consensus=+X". On renvoie une COPIE annotee, la liste d'entree reste
        # intacte.
        best = dataclass_replace(best, note=f"{note}, {suffix}" if note else suffix)
    return best


def compute_confidence(
    cfg: Config,
    chosen: Candidate,
    *,
    nfo_ok: bool,
    year_delta_reject: bool,
    tmdb_used: bool,
    nfo_partial_match: bool = False,
) -> Tuple[int, str]:
    """Score 0..100.

    nfo_partial_match : si True, le NFO matche folder OU filename mais pas les
    deux. Signe classique de fichier vidéo remplacé sans mise à jour du NFO.
    On pénalise de 8 points quand la source retenue est le NFO (P1.1.b).
    """
    score = 0
    if chosen.source == "nfo":
        score += 65 if nfo_ok else 35
        if nfo_ok and nfo_partial_match:
            score -= 8  # P1.1.b : NFO valide côté folder XOR filename, suspicion
    elif chosen.source == "tmdb":
        score += 48
    elif chosen.source in ("name_tag", "name_tmdb", "name_imdb"):
        # REG-TAGS-04 : un tag provider explicite dans le nom (dossier ou fichier)
        # est une intention utilisateur deterministe. On le traite comme un match
        # high-confidence (entre nfo_ok=65 et tmdb=48) car l'utilisateur a
        # explicitement annote le contenu avec un ID provider.
        score += 60
    else:
        score += 45

    # base sur score interne
    score += int(max(0.0, min(1.0, chosen.score)) * 25)
    consensus_bonus = _consensus_from_candidate_note(chosen.note)
    if consensus_bonus is not None and consensus_bonus > 0.0:
        score += int(min(0.10, consensus_bonus) * 40)

    if chosen.source in ("name", "name_tag") and chosen.year:
        score += 5

    if year_delta_reject:
        if chosen.source == "tmdb":
            # If TMDb solved the conflict, keep a small penalty only.
            dy = _year_delta_from_candidate_note(chosen.note)
            if dy is not None and dy <= 1 and chosen.score >= 0.82:
                score -= 2
            else:
                score -= 8
        elif chosen.source == "name":
            score -= 15
        else:
            score -= 25

    if tmdb_used and chosen.source == "tmdb":
        score += 10
        if chosen.score >= 0.90 and chosen.year:
            score += 6
        dy = _year_delta_from_candidate_note(chosen.note)
        if dy is not None and dy <= 1 and chosen.score >= 0.78:
            score += 3
        if dy == 0 and chosen.score >= 0.88:
            score += 3
        sim = _sim_from_candidate_note(chosen.note)
        if sim is not None and dy is not None and dy <= 1 and sim >= 0.80:
            score += 2
        if sim is not None and sim >= 0.92 and chosen.score >= 0.78:
            score += 2

    # FIX 7 : confiance honnete — la similarite textuelle reelle cap le label.
    # Si le titre du candidat ressemble tres peu au titre attendu, le match
    # ne peut pas etre "med" meme si d'autres bonus ont fait monter le score.
    sim_real = _sim_from_candidate_note(chosen.note)
    if sim_real is not None:
        if sim_real < 0.40:
            # Tres faible similarite -> forcer low et cap brutal
            score = min(score, 40)
        elif sim_real < 0.60:
            score = min(score, 59)  # cap sous le seuil "med"

    score = max(0, min(100, score))
    # VN-C.1 (batch 2) : seuils unifies via domain.confidence_thresholds.
    # Avant : >= 80 / >= 60 (hardcode). Apres : CONF_HIGH=85 / CONF_MEDIUM=60.
    # Impact backward-compat : un score 80-84 retourne desormais "med"
    # (au lieu de "high"). Aligne avec le frontend (traitement.js +
    # lib-validation.js) qui utilisait deja 85/60.
    label = "high" if score >= _CONF_HIGH else "med" if score >= _CONF_MEDIUM else "low"
    return score, label


# Cf #83 phase A3 : 11 aliases backward-compat plan_support supprimes
# (0 caller externe, 0 usage interne dans domain/core.py).
# Aliases supprimes :
#   _cfg_signature_for_incremental, _stats_snapshot_for_cache,
#   _stats_delta_for_cache, _stats_apply_cached_delta,
#   _plan_row_to_jsonable, _plan_row_from_jsonable,
#   _resolve_incremental_quick_hash, _folder_signature,
#   plan_library, _plan_single, _plan_collection_item
# Appeler directement core_plan_support.X (alias module-level reste) ou
# importer depuis cinesort.app.plan_support en top-level.


# =========================================================
# APPLY
# =========================================================

SKIP_REASON_NON_VALIDE = "skip_non_valide"
SKIP_REASON_VALIDATION_ABSENTE = "skip_validation_absente"
SKIP_REASON_NOOP_DEJA_CONFORME = "skip_noop_deja_conforme"
SKIP_REASON_OPTION_DESACTIVEE = "skip_option_desactivee"
SKIP_REASON_MERGED = "skip_merged"
SKIP_REASON_CONFLIT_QUARANTAINE = "skip_conflit_quarantaine"
SKIP_REASON_ERREUR_PRECEDENTE = "skip_erreur_precedente"
SKIP_REASON_AUTRE = "skip_autre"
# VQ-3 : kill-switch MAX_PATH Windows. Le check check_path_length_killswitch
# (domain/naming.py) bloque toute operation rename/move qui produirait un
# path > 259 chars sur Windows. Sans ce skip distinct, l'utilisateur voyait
# un OSError cryptique "Le chemin specifie est introuvable" ou pire un
# rename partiel laissant le FS dans un etat intermediaire.
SKIP_REASON_PATH_TOO_LONG = "skip_path_too_long"
# #613 : saison TV INDETERMINEE (`row.tv_season is None`). A ne pas confondre
# avec `tv_season == 0`, qui est une saison LEGITIME (les specials Kodi/Jellyfin
# vivent dans `Saison 00`). `int(row.tv_season or 0)` ecrasait la distinction :
# un episode dont la saison n'avait pas ete resolue (pattern « Episode 12 » sans
# saison, tv_helpers.parse_tv_info) etait range en silence dans `Saison 00`,
# c'est-a-dire melange aux specials, avec un chemin de destination FABRIQUE.
# Chemin destructif -> l'erreur va dans le sens restrictif : on refuse bruyamment.
SKIP_REASON_TV_SAISON_INDETERMINEE = "skip_tv_saison_indeterminee"

ANALYSE_IGNORE_LABELS_FR = {
    "ignore_tv_like": "Ignoré (ressemble à une série)",
    "ignore_nfo_incoherent": "Ignoré (NFO incohérent)",
    # BUG 4 : libelle plus explicite — "format non supporte" laissait croire a un
    # probleme d'extension. En realite, ces dossiers ne contiennent simplement pas
    # de fichier video assez gros (ou pas de video du tout).
    "ignore_non_supporte": "Ignoré (aucun fichier vidéo exploitable)",
    "ignore_chemin_invalide": "Ignoré (chemin invalide)",
    "ignore_autre": "Ignoré (autre)",
}

SKIP_REASON_LABELS_FR = {
    SKIP_REASON_NON_VALIDE: "Non validé (OK=false)",
    SKIP_REASON_VALIDATION_ABSENTE: "Aucune validation (validation.json)",
    SKIP_REASON_NOOP_DEJA_CONFORME: "Déjà conforme (aucune action)",
    SKIP_REASON_OPTION_DESACTIVEE: "Option désactivée",
    SKIP_REASON_MERGED: "Fusionné (MERGE_DIR)",
    SKIP_REASON_CONFLIT_QUARANTAINE: "Conflit -> quarantaine",
    SKIP_REASON_ERREUR_PRECEDENTE: "Erreur précédente",
    SKIP_REASON_AUTRE: "Autre",
    SKIP_REASON_PATH_TOO_LONG: "Chemin trop long (MAX_PATH Windows)",
    SKIP_REASON_TV_SAISON_INDETERMINEE: "Saison TV indéterminée (destination non fabriquée)",
}


@dataclass
class ApplyResult:
    renames: int = 0
    moves: int = 0
    mkdirs: int = 0
    collection_moves: int = 0
    quarantined: int = 0
    skipped: int = 0
    errors: int = 0
    merges_count: int = 0
    # AUDIT 2026-06-14 (R7-4) : compteur des films marques pour suppression
    # deplaces vers _review/_user_marked_for_deletion/ a l'apply.
    marked_for_deletion_moved_count: int = 0
    # R8-018 (F2-b) : compteur DEDIE des doublons "perdants" d'une decision utilisateur
    # deplaces vers _review/_duplicates_user_decided/. Avant, ces moves incrementaient
    # duplicates_identical_moved_count (doublons byte-identiques) -> invariant
    # moved==deleted casse + chemin de recuperation mensonger (UI pointait
    # _duplicates_identical alors que les fichiers sont dans _duplicates_user_decided).
    duplicates_user_decided_moved_count: int = 0
    duplicates_identical_moved_count: int = 0
    # Backward-compatible alias kept for older consumers.
    duplicates_identical_deleted_count: int = 0
    conflicts_quarantined_count: int = 0
    sidecar_conflicts_kept_both_count: int = 0
    # Backward-compatible alias for sidecar conflict routing.
    conflicts_sidecars_quarantined_count: int = 0
    leftovers_moved_count: int = 0
    source_dirs_deleted_count: int = 0
    empty_folders_moved_count: int = 0
    cleanup_residual_folders_moved_count: int = 0
    cleanup_residual_diagnostic: Dict[str, Any] = field(default_factory=dict)
    applied_count: int = 0
    total_rows: int = 0
    considered_rows: int = 0
    skip_reasons: Dict[str, int] = field(default_factory=dict)
    # Fix audit 2026-05-25 (v1.5.3) Vague H : messages contextualises remontes
    # a l'UI (ex : "FICHIER VERROUILLE : 'Film.mkv' est ouvert dans VLC...")
    # quand un PermissionError empeche le move/rename. Liste vide si aucune
    # erreur visible n'est a remonter ; res.errors reste le compteur faisant
    # foi pour l'agregation.
    error_messages: list = field(default_factory=list)


@dataclass
class ApplyExecutionContext:
    cfg: Config
    res: ApplyResult
    decision_keys: Set[str]
    hash_cache: Dict[Tuple[str, int, int], str]
    review_root: Path
    conflicts_root: Path
    conflicts_sidecars_root: Path
    duplicates_identical_root: Path
    leftovers_root: Path
    # Phase 6 doublons (spec 01-doublons.md §3.7) : bucket des losers post-decision UI.
    duplicates_user_decided_root: Optional[Path] = None
    # AUDIT 2026-06-14 (R7-4) : bucket des films marques pour suppression par l'utilisateur.
    marked_for_deletion_root: Optional[Path] = None
    touched_top_level_dirs: Set[Path] = field(default_factory=set)
    folder_map: Dict[str, str] = field(default_factory=dict)
    dedup_seen_ops: Set[Tuple[str, str, str]] = field(default_factory=set)


def _mark_skip(res: ApplyResult, reason: str) -> None:
    key = str(reason or SKIP_REASON_AUTRE)
    res.skipped += 1
    res.skip_reasons[key] = int(res.skip_reasons.get(key, 0)) + 1


# Cf #83 phase A4 : 6 aliases backward-compat apply_core supprimes :
#   _build_apply_context, _record_apply_op, _quick_hash_cache_key,
#   _unique_path, _is_dir_empty, move_collection_folder
# 1 caller externe migre (tests/test_v7_1_features deja utilise apply_core
# direct depuis A1). 2 usages internes migres :
# - cinesort/app/apply_core.py:858 core_mod.move_collection_folder -> local
# - cinesort/app/plan_support.py:204 core_mod._quick_hash_cache_key -> apply_core.quick_hash_cache_key
# Si besoin futur : appeler core_apply_support.X (alias module qui reste) ou
# importer depuis cinesort.app.apply_core en top-level.


def is_under_collection_root(cfg: Config, folder: Path) -> bool:
    return core_duplicate_support.is_under_collection_root(
        cfg,
        folder,
        norm_win_path=_norm_win_path,
    )


def _single_folder_is_conform(
    folder_name: str,
    title: str,
    year: int,
    naming_template: str = "",
    *,
    edition: str = "",
    separator: Optional[str] = None,
) -> bool:
    """Wrapper conserve : 5 callers externes (plan_support, cleanup, tests).

    `edition` / `separator` (#469) : a transmettre par tout appelant qui les
    transmet aussi a l'ecrivain, sinon la conformance est evaluee contre un
    nom que l'apply n'ecrit pas.
    """
    return core_duplicate_support.single_folder_is_conform(
        folder_name,
        title,
        year,
        windows_safe=windows_safe,
        norm_for_tokens=_norm_for_tokens,
        movie_dir_title_year=core_duplicate_support.movie_dir_title_year,
        naming_template=naming_template,
        edition=edition,
        separator=separator,
    )


_find_video_case_insensitive = core_duplicate_support.find_video_case_insensitive


# Cf #83 etape 2 PR 4b : `find_duplicate_targets` et ses 6 helpers DI prives
# supprimes. La vraie logique est cote `cinesort.app.plan_support.find_duplicate_targets`.
# Cf #83 PR A1 : re-export `from cinesort.app.plan_support import find_duplicate_targets`
# supprime apres migration des 4 sites tests vers plan_support.find_duplicate_targets.
#
# Cf #83 PR A1 : alias `apply_rows = _apply_rows_support` supprime apres
# migration des 16 sites tests (test_merge_duplicates + test_v7_1_features)
# vers `apply_core.apply_rows`. Import top-level `_apply_rows_support`
# egalement supprime (ligne 59).
