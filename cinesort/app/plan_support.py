from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, fields as dc_fields
import functools
import hashlib
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

import cinesort.app.apply_core as _apply_core_mod
import cinesort.domain.core as core_mod
from cinesort.app.apply_core import quick_hash_cache_key, sha1_quick
from cinesort.domain import duplicate_support as _dup
from cinesort.domain.edition_helpers import extract_edition, strip_edition
from cinesort.domain.integrity_check import check_header
from cinesort.domain.runtime_matching import score_runtime_delta
from cinesort.domain.scan_helpers import (
    _NOT_A_MOVIE_THRESHOLD,
    discover_candidate_folders,
    not_a_movie_score,
)
from cinesort.domain.subtitle_helpers import build_subtitle_report
from cinesort.domain.title_ambiguity import disambiguate_by_context
from cinesort.domain.title_helpers import _norm_for_tokens
from cinesort.domain.tv_helpers import parse_tv_info
from cinesort.infra.fs_safety import is_dir_accessible, safe_path_exists
from cinesort.infra.tmdb_client import TmdbClient
import contextlib

if TYPE_CHECKING:
    from cinesort.domain.core import Config, PlanRow, Stats

_log = logging.getLogger(__name__)

# BUG 1 : version des regles de scoring. Incrementee a chaque changement des regles
# (seuils TMDb, cap confiance, filtres bonus, etc.). Incluse dans la signature de
# configuration du cache incremental → une bump invalide automatiquement tout le
# cache et force un rescan complet avec les nouvelles regles.
#
# Historique :
# - v1 : regles originales (avant audit 2026-04-10)
# - v2 : fix scoring strict (seuil 0.50, penalite annee, filtre bonus, cap confiance)
# - v3 : fix post-run 20260410_131839 (confiance HIGH si deja conforme, cap conditionnel)
_PLAN_CACHE_VERSION = 3

# Seuil de films directement a la racine au-dela duquel on avertit l'utilisateur :
# une racine contenant beaucoup de films non ranges signale probablement une
# bibliotheque en vrac, et l'apply va creer autant de sous-dossiers d'un coup.
_ROOT_BULK_WARNING_THRESHOLD = 20


def plan_row_to_jsonable(row: "PlanRow") -> Dict[str, Any]:
    data = asdict(row)
    data["candidates"] = [asdict(candidate) for candidate in (row.candidates or [])]
    return data


def plan_row_from_jsonable(data: Dict[str, Any]) -> Optional["PlanRow"]:

    if not isinstance(data, dict):
        return None
    try:
        candidates_payload = data.get("candidates")
        candidates = []
        if isinstance(candidates_payload, list):
            for item in candidates_payload:
                if not isinstance(item, dict):
                    continue
                candidates.append(
                    core_mod.Candidate(
                        title=str(item.get("title") or ""),
                        year=int(item["year"]) if item.get("year") not in (None, "") else None,
                        source=str(item.get("source") or ""),
                        tmdb_id=int(item["tmdb_id"]) if item.get("tmdb_id") not in (None, "") else None,
                        poster_url=str(item.get("poster_url") or "") or None,
                        score=float(item.get("score") or 0.0),
                        note=str(item.get("note") or ""),
                        tmdb_collection_id=int(item["tmdb_collection_id"])
                        if item.get("tmdb_collection_id") not in (None, "", 0)
                        else None,
                        tmdb_collection_name=str(item.get("tmdb_collection_name") or "") or None,
                    )
                )
        return core_mod.PlanRow(
            row_id=str(data.get("row_id") or ""),
            kind=str(data.get("kind") or ""),
            folder=str(data.get("folder") or ""),
            video=str(data.get("video") or ""),
            proposed_title=str(data.get("proposed_title") or ""),
            proposed_year=int(data.get("proposed_year") or 0),
            proposed_source=str(data.get("proposed_source") or ""),
            confidence=int(data.get("confidence") or 0),
            confidence_label=str(data.get("confidence_label") or ""),
            candidates=candidates,
            nfo_path=str(data.get("nfo_path") or "") or None,
            notes=str(data.get("notes") or ""),
            detected_year=int(data.get("detected_year") or 0),
            detected_year_reason=str(data.get("detected_year_reason") or ""),
            warning_flags=[str(item) for item in (data.get("warning_flags") or []) if str(item or "").strip()],
            collection_name=str(data.get("collection_name") or "") or None,
            tmdb_collection_id=int(data["tmdb_collection_id"])
            if data.get("tmdb_collection_id") not in (None, "", 0)
            else None,
            tmdb_collection_name=str(data.get("tmdb_collection_name") or "") or None,
            edition=str(data.get("edition") or "") or None,
            nfo_runtime=int(data["nfo_runtime"]) if data.get("nfo_runtime") not in (None, "", 0) else None,
        )
    except (KeyError, TypeError, ValueError):
        return None


def cfg_signature_for_incremental(cfg: "Config") -> str:
    payload = {
        "root": str(cfg.root),
        "enable_collection_folder": bool(cfg.enable_collection_folder),
        "collection_root_name": str(cfg.collection_root_name),
        "empty_folders_folder_name": str(cfg.empty_folders_folder_name),
        "move_empty_folders_enabled": bool(cfg.move_empty_folders_enabled),
        "empty_folders_scope": str(cfg.empty_folders_scope),
        "cleanup_residual_folders_enabled": bool(cfg.cleanup_residual_folders_enabled),
        "cleanup_residual_folders_folder_name": str(cfg.cleanup_residual_folders_folder_name),
        "cleanup_residual_folders_scope": str(cfg.cleanup_residual_folders_scope),
        "cleanup_residual_include_nfo": bool(cfg.cleanup_residual_include_nfo),
        "cleanup_residual_include_images": bool(cfg.cleanup_residual_include_images),
        "cleanup_residual_include_subtitles": bool(cfg.cleanup_residual_include_subtitles),
        "cleanup_residual_include_texts": bool(cfg.cleanup_residual_include_texts),
        "video_exts": sorted(str(item) for item in (cfg.video_exts or [])),
        "side_exts": sorted(str(item) for item in (cfg.side_exts or [])),
        "generic_side_files": sorted(str(item) for item in (cfg.generic_side_files or [])),
        "detect_extras_in_single_folder": bool(cfg.detect_extras_in_single_folder),
        "extras_size_ratio": float(cfg.extras_size_ratio),
        "skip_tv_like": bool(cfg.skip_tv_like),
        "title_match_min_cov": float(cfg.title_match_min_cov),
        "title_match_min_seq": float(cfg.title_match_min_seq),
        "max_year_delta_when_name_has_year": int(cfg.max_year_delta_when_name_has_year),
        "enable_tmdb": bool(cfg.enable_tmdb),
        "tmdb_language": str(cfg.tmdb_language),
        # BUG 1 : la version des regles de scoring fait partie de la signature.
        # Toute evolution des regles -> nouveau cfg_sig -> cache invalide.
        "_plan_cache_version": int(_PLAN_CACHE_VERSION),
    }
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def stats_snapshot_for_cache(stats: "Stats") -> Dict[str, Any]:
    return {
        "folders_scanned": int(stats.folders_scanned or 0),
        "collections_seen": int(stats.collections_seen or 0),
        "singles_seen": int(stats.singles_seen or 0),
        "collection_rows_generated": int(stats.collection_rows_generated or 0),
        "skipped_tv_like": int(stats.skipped_tv_like or 0),
        "planned_rows": int(stats.planned_rows or 0),
        "errors": int(stats.errors or 0),
        "analyse_ignores_total": int(stats.analyse_ignores_total or 0),
        "analyse_ignores_par_raison": dict(stats.analyse_ignores_par_raison or {}),
        "analyse_ignores_extensions": dict(stats.analyse_ignores_extensions or {}),
        "incremental_cache_hits": int(stats.incremental_cache_hits or 0),
        "incremental_cache_misses": int(stats.incremental_cache_misses or 0),
        "incremental_cache_rows_reused": int(stats.incremental_cache_rows_reused or 0),
    }


def stats_delta_for_cache(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    delta: Dict[str, Any] = {}
    dict_keys = {"analyse_ignores_par_raison", "analyse_ignores_extensions"}
    for key, after_value in (after or {}).items():
        before_value = (before or {}).get(key)
        if key in dict_keys:
            child: Dict[str, int] = {}
            after_dict = after_value if isinstance(after_value, dict) else {}
            before_dict = before_value if isinstance(before_value, dict) else {}
            keys = set(after_dict) | set(before_dict)
            for child_key in keys:
                diff = int(after_dict.get(child_key, 0) or 0) - int(before_dict.get(child_key, 0) or 0)
                if diff:
                    child[child_key] = diff
            delta[key] = child
            continue
        if isinstance(after_value, (int, float)):
            delta[key] = int(after_value or 0) - int(before_value or 0)
        else:
            delta[key] = after_value
    return delta


def stats_apply_cached_delta(stats: "Stats", delta: Dict[str, Any]) -> None:
    if not isinstance(delta, dict):
        return
    for key, value in delta.items():
        if key == "analyse_ignores_par_raison" and isinstance(value, dict):
            for child_key, child_delta in value.items():
                stats.analyse_ignores_par_raison[child_key] = int(
                    stats.analyse_ignores_par_raison.get(child_key, 0)
                ) + int(child_delta or 0)
            continue
        if key == "analyse_ignores_extensions" and isinstance(value, dict):
            for child_key, child_delta in value.items():
                stats.analyse_ignores_extensions[child_key] = int(
                    stats.analyse_ignores_extensions.get(child_key, 0)
                ) + int(child_delta or 0)
            continue
        if hasattr(stats, key) and isinstance(getattr(stats, key), int):
            setattr(stats, key, int(getattr(stats, key, 0) or 0) + int(value or 0))


def resolve_incremental_quick_hash(
    path: Path,
    *,
    scan_index: Optional[Any],
    run_hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
) -> str:
    # Cf #83 phase A4 : utilise apply_core.quick_hash_cache_key directement
    # au lieu de l'alias backward-compat core._quick_hash_cache_key (supprime).

    try:
        stat_result = path.stat()
    except (OSError, PermissionError, FileNotFoundError):
        return ""
    cache_key = quick_hash_cache_key(path)
    if cache_key and run_hash_cache is not None and cache_key in run_hash_cache:
        return str(run_hash_cache.get(cache_key) or "")
    if scan_index is not None and hasattr(scan_index, "get_incremental_file_hash"):
        try:
            cached = scan_index.get_incremental_file_hash(
                path=str(path),
                size=int(stat_result.st_size),
                mtime_ns=int(stat_result.st_mtime_ns),
            )
            if cached:
                if cache_key and run_hash_cache is not None:
                    run_hash_cache[cache_key] = str(cached)
                return str(cached)
        except (OSError, TypeError, ValueError):
            pass
    try:
        # Cf #83 etape 2 PR 1 : appelle apply_core directement plutot que de
        # transiter par le wrapper domain.core._sha1_quick (supprime).

        quick_hash = sha1_quick(path)
    except (OSError, PermissionError, FileNotFoundError):
        quick_hash = ""
    if quick_hash and scan_index is not None and hasattr(scan_index, "upsert_incremental_file_hash"):
        with contextlib.suppress(OSError, TypeError, ValueError):
            scan_index.upsert_incremental_file_hash(
                path=str(path),
                size=int(stat_result.st_size),
                mtime_ns=int(stat_result.st_mtime_ns),
                quick_hash=quick_hash,
            )
    if quick_hash and cache_key and run_hash_cache is not None:
        run_hash_cache[cache_key] = quick_hash
    return quick_hash


# PERF-3 (Phase 2 v7.8.0) : cache memoise _nfo_signature par (path, size, mtime_ns).
# Avant ce cache, le scan v2 row-cache appelait _nfo_signature 2x par film en miss
# (lookup + store), soit ~5000 x 2 lectures NFO sur SMB = 200s perdues.
# La cle inclut size+mtime pour invalider si le NFO est modifie entre les 2 appels.
_NFO_SIG_CACHE: Dict[Tuple[str, int, int], str] = {}
_NFO_SIG_CACHE_MAX = 10000  # cap pour eviter accumulation memoire en process long


def _nfo_signature(nfo_path: Optional[Path]) -> Optional[str]:
    """SHA1 of the NFO file content, or None if absent.

    PERF-3 : cache (path, size, mtime_ns) -> sha1. Invalidation auto si NFO modifie.
    """
    if nfo_path is None:
        return None
    try:
        st = nfo_path.stat()
    except (PermissionError, OSError, FileNotFoundError):
        return None
    cache_key = (str(nfo_path), int(st.st_size), int(st.st_mtime_ns))
    cached = _NFO_SIG_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        sig = hashlib.sha1(nfo_path.read_bytes()).hexdigest()
    except (PermissionError, OSError):
        return None
    # Cap simple pour eviter croissance illimitee (drop arbitraire des 100 plus
    # anciens — OK car l'utilisation est lineaire sur 1 scan typiquement)
    if len(_NFO_SIG_CACHE) >= _NFO_SIG_CACHE_MAX:
        for old_key in list(_NFO_SIG_CACHE.keys())[:100]:
            _NFO_SIG_CACHE.pop(old_key, None)
    _NFO_SIG_CACHE[cache_key] = sig
    return sig


def folder_signature(
    cfg: "Config",
    folder: Path,
    *,
    scan_index: Optional[Any],
    run_hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
) -> str:
    # BUG 3 : optimisation NAS via os.scandir (metadata cachees en 1 op systeme)
    import os as _os

    items: List[Tuple[str, str]] = []  # (sort_key, payload_line)
    video_exts = cfg.video_exts or set()
    try:
        scandir_ctx = _os.scandir(str(folder))
    except (OSError, PermissionError, FileNotFoundError):
        return hashlib.sha1(b"").hexdigest()
    try:
        for entry in scandir_ctx:
            name = entry.name
            name_lower = name.lower()
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                st = entry.stat(follow_symlinks=False)
                size = int(st.st_size)
                mtime_ns = int(st.st_mtime_ns)
            except (OSError, PermissionError, FileNotFoundError):
                is_dir = False
                size = 0
                mtime_ns = 0
            kind = "d" if is_dir else "f"
            parts = [kind, name_lower, str(size), str(mtime_ns)]
            if not is_dir:
                dot = name.rfind(".")
                ext = name[dot:].lower() if dot >= 0 else ""
                if ext in video_exts:
                    quick_hash = resolve_incremental_quick_hash(
                        Path(entry.path),
                        scan_index=scan_index,
                        run_hash_cache=run_hash_cache,
                    )
                    if quick_hash:
                        parts.append(quick_hash)
            items.append((name_lower, "|".join(parts)))
    finally:
        with contextlib.suppress(OSError, AttributeError):
            scandir_ctx.close()
    items.sort(key=lambda t: t[0])
    payload = "\n".join(line for _k, line in items)
    return hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()


# =========================================================
# plan_library ORCHESTRATEUR + 3 PHASES PRIVEES (V4-03 refactor)
# =========================================================
# La fonction plan_library scanne la racine d'une bibliotheque et construit la
# liste des PlanRows. Elle a ete splittee en 3 phases prives pour reduire la
# complexite cyclomatique (73 -> ~10) sans changer la signature publique ni le
# comportement :
#   1. _scan_root_phase           : decouverte des dossiers candidats + setup contexte
#   2. _filter_dossiers_phase     : iteration principale (cache, classification, plan)
#   3. _dedup_and_finalize_phase  : purge cache incremental + finalisation stats
# Le contexte mutable (cfg, stats, rows, scan_index, ...) est porte par
# _PlanLibraryContext (dataclass) pour limiter le nombre de parametres.

from dataclasses import dataclass, field


@dataclass
class _PlanLibraryContext:
    """Etat mutable partage entre les 3 phases de plan_library.

    Porte la config normalisee, les accumulateurs (rows, stats, listes de prune)
    et les parametres derives (incremental_enabled, cfg_sig, v2_kwargs).
    """

    cfg: "Config"
    tmdb: Optional[TmdbClient]
    log: Callable[[str, str], None]
    progress: Callable[[int, int, str], None]
    should_cancel: Optional[Callable[[], bool]]
    scan_index: Optional[Any]
    run_id: str
    subtitle_expected_languages: Optional[List[str]]
    # Etat derive (rempli en debut de phase 1)
    stats: Any = None  # core_mod.Stats
    incremental_enabled: bool = False
    cfg_sig: str = ""
    root_key: str = ""
    run_hash_cache: Dict[Tuple[str, int, int], str] = field(default_factory=dict)
    folders_seen_for_prune: List[str] = field(default_factory=list)
    video_paths_seen: List[str] = field(default_factory=list)
    row_cache_stats: Dict[str, int] = field(default_factory=lambda: {"row_hits": 0, "row_misses": 0})
    v2_kwargs: Dict[str, Any] = field(default_factory=dict)
    rows: List[Any] = field(default_factory=list)
    cancel_logged: bool = False
    candidate_folders: List[Path] = field(default_factory=list)
    scanned_total: int = 0
    # PERF-2 (Phase 2 v7.8.0) : pre-resolution de cfg.root pour eviter
    # 2 resolve() par film sur SMB (5-15ms x 2 x 5000 films = 50-150s perdues).
    cfg_root_resolved: Optional[Path] = None

    def get_root_resolved(self) -> Optional[Path]:
        """Retourne cfg.root resolu une seule fois. None si resolve impossible."""
        if self.cfg_root_resolved is None:
            try:
                self.cfg_root_resolved = self.cfg.root.resolve()
            except (OSError, ValueError):
                self.cfg_root_resolved = self.cfg.root  # fallback non-resolu
        return self.cfg_root_resolved

    def check_cancel(self) -> bool:
        """Centralise la detection d'annulation + log unique."""

        if not core_mod._is_cancel_requested(self.should_cancel):
            return False
        if not self.cancel_logged:
            self.log("INFO", "cancel requested")
            self.cancel_logged = True
        return True

    def persist_folder_cache(
        self,
        *,
        folder: Path,
        folder_sig: Optional[str],
        rows_before: int,
        stats_before: Dict[str, Any],
    ) -> None:
        """Persiste le cache incremental pour un dossier traite (no-op si desactive)."""

        if not self.incremental_enabled or folder_sig is None or self.scan_index is None:
            return
        if core_mod._is_cancel_requested(self.should_cancel):
            return
        if not hasattr(self.scan_index, "upsert_incremental_folder_cache"):
            return
        folder_rows = self.rows[rows_before:]
        stats_after = stats_snapshot_for_cache(self.stats)
        stats_delta = stats_delta_for_cache(stats_before, stats_after)
        rows_json = [plan_row_to_jsonable(row) for row in folder_rows]
        try:
            self.scan_index.upsert_incremental_folder_cache(
                root_path=self.root_key,
                folder_path=str(folder),
                cfg_sig=self.cfg_sig,
                folder_sig=folder_sig,
                rows_json=rows_json,
                stats_json=stats_delta,
                run_id=str(self.run_id or ""),
            )
        except (OSError, TypeError, ValueError) as exc:
            self.log("WARN", f"Cache incremental: echec write ({folder.name}): {exc}")


def _scan_root_phase(ctx: _PlanLibraryContext) -> bool:
    """Phase 1 : verifie l'accessibilite du root puis decouvre les dossiers candidats.

    Initialise ctx.candidate_folders + setup des attributs derives (cfg_sig,
    root_key, v2_kwargs, ...). Retourne True si le scan doit continuer, False
    si annulation prematuree.
    """

    if ctx.check_cancel():
        ctx.stats.planned_rows = 0
        return False

    ctx.cfg = ctx.cfg.normalized()
    ctx.incremental_enabled = bool(ctx.cfg.incremental_scan_enabled and ctx.scan_index is not None)
    ctx.cfg_sig = cfg_signature_for_incremental(ctx.cfg) if ctx.incremental_enabled else ""
    ctx.root_key = str(ctx.cfg.root)
    if ctx.incremental_enabled:
        ctx.v2_kwargs = {
            "scan_index": ctx.scan_index,
            "cfg_sig": ctx.cfg_sig,
            "run_id": str(ctx.run_id or ""),
            "run_hash_cache": ctx.run_hash_cache,
            "row_cache_stats": ctx.row_cache_stats,
        }
    if ctx.subtitle_expected_languages is not None:
        ctx.v2_kwargs["subtitle_expected_languages"] = ctx.subtitle_expected_languages

    # M-1 audit QA 20260429 : check accessibilite avec timeout (10s) pour
    # detecter les NAS debranches avant que le scan hang indefiniment sur
    # un syscall stat SMB/CIFS bloque.

    exists = safe_path_exists(ctx.cfg.root, timeout_s=10.0)
    if exists is None:
        raise TimeoutError(
            f"ROOT inaccessible apres 10s : {ctx.cfg.root}. Verifiez la connexion reseau/disque (NAS debranche ?)."
        )
    if not exists:
        raise FileNotFoundError(f"ROOT introuvable: {ctx.cfg.root}")
    _log.info("scan: debut analyse %s (incremental=%s)", ctx.cfg.root, ctx.incremental_enabled)

    if ctx.incremental_enabled:
        ctx.log("INFO", "Scan mode: incremental (changements uniquement)")
    ctx.log("INFO", "Scan folders: streaming")

    # BUG 1 : Phase 1 — decouverte rapide (< 2s sur NAS SMB). UN SEUL scandir par
    # niveau au lieu de la recursion os.walk + iter_videos dans stream_scan_targets.
    import time as _time

    _discover_t0 = _time.monotonic()
    try:
        ctx.candidate_folders = discover_candidate_folders(ctx.cfg)
    except (OSError, PermissionError, FileNotFoundError) as exc:
        raise RuntimeError(f"Impossible de lister ROOT: {exc}")
    discover_total = len(ctx.candidate_folders)
    _discover_dt = _time.monotonic() - _discover_t0
    _log.info("scan: phase 1 decouverte = %d dossiers en %.2fs", discover_total, _discover_dt)
    ctx.log("INFO", f"Decouverte : {discover_total} dossiers trouves ({_discover_dt:.1f}s)")
    return True


def _try_apply_folder_cache(ctx: _PlanLibraryContext, folder: Path) -> Tuple[Optional[str], bool]:
    """Tente un hit dans le cache incremental dossier. Retourne (folder_sig, hit).

    Si hit : applique les rows + stats caches dans ctx, incremente cache_hits,
    et retourne (folder_sig, True) — l'appelant doit `continue`.
    Sinon : incremente cache_misses, retourne (folder_sig, False).
    """

    folder_sig: Optional[str] = None
    if not (ctx.incremental_enabled and ctx.scan_index is not None):
        return folder_sig, False

    folder_sig = folder_signature(
        ctx.cfg,
        folder,
        scan_index=ctx.scan_index,
        run_hash_cache=ctx.run_hash_cache,
    )
    cache_entry = None
    if hasattr(ctx.scan_index, "get_incremental_folder_cache"):
        try:
            cache_entry = ctx.scan_index.get_incremental_folder_cache(
                root_path=ctx.root_key,
                folder_path=str(folder),
                cfg_sig=ctx.cfg_sig,
            )
        except (OSError, TypeError, ValueError):
            cache_entry = None
    if isinstance(cache_entry, dict) and str(cache_entry.get("folder_sig") or "") == folder_sig:
        cached_rows_payload = cache_entry.get("rows_json")
        cached_stats_delta = cache_entry.get("stats_json")
        cached_rows: List[Any] = []
        if isinstance(cached_rows_payload, list):
            for payload_item in cached_rows_payload:
                if not isinstance(payload_item, dict):
                    continue
                row_obj = plan_row_from_jsonable(payload_item)
                if row_obj is not None:
                    cached_rows.append(row_obj)
        if isinstance(cached_stats_delta, dict):
            ctx.rows.extend(cached_rows)
            stats_apply_cached_delta(ctx.stats, cached_stats_delta)
            ctx.stats.incremental_cache_hits += 1
            ctx.stats.incremental_cache_rows_reused += len(cached_rows)
            return folder_sig, True
    ctx.stats.incremental_cache_misses += 1
    return folder_sig, False


def _classify_and_plan_folder(
    ctx: _PlanLibraryContext,
    folder: Path,
    videos: List[Path],
) -> bool:
    """Classifie le dossier (TV/root/single+extras/collection/single) et genere les rows.

    Retourne True si le scan global doit s'arreter (cancel detecte), False sinon.
    """

    if core_mod.looks_tv_like(folder, videos):
        if ctx.cfg.enable_tv_detection:
            # Treat as TV series: plan each video as a TV episode.
            if ctx.incremental_enabled:
                for v in videos:
                    ctx.video_paths_seen.append(str(v))
            for video in sorted(videos, key=lambda p: p.name.lower()):
                if ctx.check_cancel():
                    break
                ctx.rows.extend(
                    _plan_tv_episode(ctx.cfg, folder, video, ctx.tmdb, ctx.log, should_cancel=ctx.should_cancel)
                )
            ctx.stats.tv_episodes_seen += len(videos)
            return ctx.check_cancel()
        elif ctx.cfg.skip_tv_like:
            ctx.stats.skipped_tv_like += 1
            core_mod._stats_add_ignore(ctx.stats, "ignore_tv_like")
            ctx.log("WARN", f"Ignoré (ressemble à une série): {folder.name}")
            return False

    if ctx.incremental_enabled:
        for v in videos:
            ctx.video_paths_seen.append(str(v))

    # Films poses directement a la racine : on force la logique "collection"
    # pour que chaque video soit deplacee dans un nouveau sous-dossier
    # `Titre (Annee)/` sans renommer le fichier, et sans tenter de renommer
    # la racine elle-meme (ce que ferait _plan_single).
    # PERF-2 (v7.8.0) : cfg.root.resolve() est mis en cache via ctx.get_root_resolved()
    try:
        _is_root_candidate = folder.resolve() == ctx.get_root_resolved()
    except (OSError, ValueError):
        _is_root_candidate = False
    if _is_root_candidate:
        ctx.stats.collections_seen += 1
        ctx.stats.root_level_films_seen += len(videos)
        # Avertissement "vrac" : beaucoup de films a la racine = bibliotheque
        # non organisee, l'apply va creer autant de sous-dossiers d'un coup.
        if len(videos) >= _ROOT_BULK_WARNING_THRESHOLD:
            ctx.log(
                "WARN",
                f"Racine en vrac : {len(videos)} films a la racine seront ranges dans "
                f"des sous-dossiers '{{titre}} ({{annee}})/'. Verifier le dry-run avant apply.",
            )
        before_len = len(ctx.rows)
        for video in sorted(videos, key=lambda path: path.name.lower()):
            if ctx.check_cancel():
                break
            ctx.rows.extend(
                _plan_collection_item(
                    ctx.cfg, folder, video, ctx.tmdb, ctx.log, should_cancel=ctx.should_cancel, **ctx.v2_kwargs
                )
            )
        # Marque les lignes issues de la racine pour que l'UI puisse les
        # signaler (badge "Depuis la racine"). On le fait apres _plan_item
        # pour ne pas repolluer sa signature ni le cache incremental v2.
        for _r in ctx.rows[before_len:]:
            if "root_level_source" not in _r.warning_flags:
                _r.warning_flags.append("root_level_source")
        ctx.stats.collection_rows_generated += max(0, len(ctx.rows) - before_len)
        return ctx.check_cancel()

    if len(videos) > 1 and core_mod.detect_single_with_extras(ctx.cfg, videos):
        try:
            main = max(videos, key=lambda path: path.stat().st_size)
        except (OSError, PermissionError, FileNotFoundError):
            main = videos[0]
        ctx.rows.extend(
            _plan_single(ctx.cfg, folder, main, ctx.tmdb, ctx.log, should_cancel=ctx.should_cancel, **ctx.v2_kwargs)
        )
        ctx.stats.singles_seen += 1
        return ctx.check_cancel()

    if len(videos) > 1:
        ctx.stats.collections_seen += 1
        before_len = len(ctx.rows)
        for video in sorted(videos, key=lambda path: path.name.lower()):
            if ctx.check_cancel():
                break
            ctx.rows.extend(
                _plan_collection_item(
                    ctx.cfg, folder, video, ctx.tmdb, ctx.log, should_cancel=ctx.should_cancel, **ctx.v2_kwargs
                )
            )
        ctx.stats.collection_rows_generated += max(0, len(ctx.rows) - before_len)
        return ctx.check_cancel()

    ctx.stats.singles_seen += 1
    ctx.rows.extend(
        _plan_single(ctx.cfg, folder, videos[0], ctx.tmdb, ctx.log, should_cancel=ctx.should_cancel, **ctx.v2_kwargs)
    )
    return ctx.check_cancel()


def _filter_dossiers_phase(ctx: _PlanLibraryContext) -> None:
    """Phase 2 : itere sur les dossiers candidats, applique le cache incremental,
    classe chaque dossier (TV/root/single+extras/collection/single) et genere les
    PlanRows correspondantes via les helpers _plan_*.

    Met a jour ctx.rows, ctx.stats, ctx.folders_seen_for_prune, ctx.video_paths_seen,
    ctx.scanned_total en place.
    """

    # Phase 2 — analyse : total fixe, la barre de progression est maintenant deterministe.
    discover_total = len(ctx.candidate_folders)
    for idx, folder in enumerate(ctx.candidate_folders, start=1):
        if ctx.check_cancel():
            break
        ctx.scanned_total = idx
        ctx.stats.folders_scanned += 1
        # BUG 1 : le total est fixe → progress deterministe, barre qui avance 0 → 100%
        ctx.progress(idx, discover_total, str(folder))
        ctx.folders_seen_for_prune.append(str(folder))

        rows_before = len(ctx.rows)
        stats_before = stats_snapshot_for_cache(ctx.stats)

        folder_sig, cache_hit = _try_apply_folder_cache(ctx, folder)
        if cache_hit:
            continue

        videos = core_mod.iter_videos(ctx.cfg, folder, min_video_bytes=core_mod.MIN_VIDEO_BYTES)
        if not videos:
            core_mod._stats_add_ignore(ctx.stats, "ignore_non_supporte")
            for ext, count in core_mod._collect_non_video_extensions(ctx.cfg, folder).items():
                ctx.stats.analyse_ignores_extensions[ext] = int(ctx.stats.analyse_ignores_extensions.get(ext, 0)) + int(
                    count
                )
            ctx.persist_folder_cache(
                folder=folder,
                folder_sig=folder_sig,
                rows_before=rows_before,
                stats_before=stats_before,
            )
            continue

        should_break = _classify_and_plan_folder(ctx, folder, videos)
        ctx.persist_folder_cache(
            folder=folder,
            folder_sig=folder_sig,
            rows_before=rows_before,
            stats_before=stats_before,
        )
        if should_break:
            break


def _dedup_and_finalize_phase(ctx: _PlanLibraryContext) -> None:
    """Phase 3 : finalise stats.planned_rows, purge les caches incrementaux pour
    les dossiers/videos disparus depuis la derniere passe, propage les compteurs
    cache row v2 et emet les logs finaux.
    """

    ctx.stats.planned_rows = len(ctx.rows)
    if (
        ctx.incremental_enabled
        and (not core_mod._is_cancel_requested(ctx.should_cancel))
        and ctx.scan_index is not None
    ):
        if hasattr(ctx.scan_index, "prune_incremental_scan_cache"):
            try:
                ctx.scan_index.prune_incremental_scan_cache(
                    root_path=ctx.root_key, keep_folders=ctx.folders_seen_for_prune
                )
            except (OSError, TypeError, ValueError) as exc:
                ctx.log("WARN", f"Cache incremental: echec purge dossiers: {exc}")
        if hasattr(ctx.scan_index, "prune_incremental_row_cache"):
            try:
                ctx.scan_index.prune_incremental_row_cache(
                    root_path=ctx.root_key, keep_video_paths=ctx.video_paths_seen
                )
            except (OSError, TypeError, ValueError) as exc:
                ctx.log("WARN", f"Cache incremental: echec purge videos: {exc}")
    # Apply v2 row cache stats to main stats.
    if hasattr(ctx.stats, "incremental_cache_row_hits"):
        ctx.stats.incremental_cache_row_hits = ctx.row_cache_stats.get("row_hits", 0)
    if hasattr(ctx.stats, "incremental_cache_row_misses"):
        ctx.stats.incremental_cache_row_misses = ctx.row_cache_stats.get("row_misses", 0)
    ctx.log("INFO", f"Scan folders: done total={ctx.scanned_total}")
    ctx.log("INFO", f"Plan built: rows={ctx.stats.planned_rows}")
    _log.info("scan: termine %s -> %d rows", ctx.cfg.root, ctx.stats.planned_rows)
    _log.debug(
        "scan: cache stats folder_hits=%d row_hits=%d row_misses=%d",
        getattr(ctx.stats, "incremental_cache_hits", 0),
        ctx.row_cache_stats.get("row_hits", 0),
        ctx.row_cache_stats.get("row_misses", 0),
    )


def plan_library(
    cfg: "Config",
    *,
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    progress: Callable[[int, int, str], None],
    should_cancel: Optional[Callable[[], bool]] = None,
    scan_index: Optional[Any] = None,
    run_id: str = "",
    subtitle_expected_languages: Optional[List[str]] = None,
) -> Tuple[List["PlanRow"], "Stats"]:
    """Scan the library root, build PlanRows for every detected movie, and return (rows, stats).

    Uses incremental cache when *scan_index* is provided and cfg.incremental_scan_enabled is True.

    Pipeline en 3 phases (V4-03 refactor) :
      1. _scan_root_phase           : decouverte des dossiers candidats + setup contexte
      2. _filter_dossiers_phase     : iteration principale (cache, classification, plan_*)
      3. _dedup_and_finalize_phase  : purge cache incremental + finalisation stats
    """

    ctx = _PlanLibraryContext(
        cfg=cfg,
        tmdb=tmdb,
        log=log,
        progress=progress,
        should_cancel=should_cancel,
        scan_index=scan_index,
        run_id=run_id,
        subtitle_expected_languages=subtitle_expected_languages,
        stats=core_mod.Stats(),
    )
    if not _scan_root_phase(ctx):
        return ctx.rows, ctx.stats
    _filter_dossiers_phase(ctx)
    _dedup_and_finalize_phase(ctx)
    return ctx.rows, ctx.stats


# =========================================================
# _plan_item ORCHESTRATOR + PRIVATE HELPERS (V4-01 refactor)
# =========================================================
# La fonction _plan_item construit une PlanRow pour un fichier video (kind="single"
# ou "collection"). Elle a ete splittee en helpers prives pour reduire la complexite
# cyclomatique (126 -> ~10) sans changer la signature publique ni le comportement.
# Pipeline lineaire : cache lookup -> contexte folder/edition -> NFO + cross-checks
# IMDb/TMDb -> TMDb fallback -> disambiguation -> PlanRow (resolved/unresolved) ->
# enrichissements (sous-titres, non-film, integrite) -> cache store.


def _try_lookup_row_cache(
    cfg: "Config",
    folder: Path,
    video: Path,
    *,
    cfg_sig: str,
    scan_index: Optional[Any],
    run_hash_cache: Optional[Dict[Tuple[str, int, int], str]],
    row_cache_stats: Optional[Dict[str, int]],
) -> Optional["PlanRow"]:
    """Tente un hit dans le cache row v2. Retourne la PlanRow cachee ou None.

    Met a jour row_cache_stats (row_hits / row_misses) en place.
    """
    if not (cfg_sig and scan_index is not None and hasattr(scan_index, "get_incremental_row_cache")):
        return None

    try:
        video_stat = video.stat()
        v_size = int(video_stat.st_size)
        v_mtime = int(video_stat.st_mtime_ns)
        v_hash = resolve_incremental_quick_hash(
            video,
            scan_index=scan_index,
            run_hash_cache=run_hash_cache or {},
        )
        nfo_path_for_sig = core_mod.find_best_nfo_for_video(folder, video)
        nfo_sig = _nfo_signature(nfo_path_for_sig)

        cached = scan_index.get_incremental_row_cache(
            root_path=str(cfg.root),
            video_path=str(video),
            cfg_sig=cfg_sig,
        )
        if cached is not None:
            if (
                int(cached.get("video_size") or 0) == v_size
                and int(cached.get("video_mtime_ns") or 0) == v_mtime
                and str(cached.get("video_hash") or "") == v_hash
                and cached.get("nfo_sig") == nfo_sig
            ):
                row_obj = plan_row_from_jsonable(cached.get("row_json") or {})
                if row_obj is not None:
                    if row_cache_stats is not None:
                        row_cache_stats["row_hits"] = row_cache_stats.get("row_hits", 0) + 1
                    return row_obj
        if row_cache_stats is not None:
            row_cache_stats["row_misses"] = row_cache_stats.get("row_misses", 0) + 1
    except (FileNotFoundError, PermissionError, OSError):
        pass
    return None


@functools.lru_cache(maxsize=16)
def _resolve_path_cached(path_str: str) -> str:
    """PERF-2 (v7.8.0) : cache `Path(p).resolve()` pour 16 derniers chemins uniques.

    Sur scan 5000 films, cfg.root est resolved 5000+ fois (1x par film via
    _resolve_folder_context). Avec ce cache, seule la 1ere resolution coute.

    Retourne le string resolu (compare facile, dict-cacheable). En cas d'echec
    de resolution (chemin inexistant, droits), retourne path_str inchange.
    """
    try:
        return str(Path(path_str).resolve())
    except (OSError, ValueError):
        return path_str


def _resolve_folder_context(
    cfg: "Config",
    folder: Path,
    video: Path,
    *,
    is_collection: bool,
    cfg_root_resolved: Optional[Path] = None,
) -> Tuple[str, str, Optional[str]]:
    """Calcule folder_name, log_ctx et l'edition detectee pour cet item.

    PERF-2 (v7.8.0) : `cfg_root_resolved` est pre-calcule par l'appelant pour
    eviter `cfg.root.resolve()` par film (5-15ms SMB). Fallback transparent
    si non fourni.
    """
    # Pour un film pose directement a la racine, le "folder_name" serait la racine
    # elle-meme (ex: "Films" ou "D:\"), qui ne porte aucune info de titre. On se
    # rabat sur le stem du fichier video pour que l'extraction titre/annee et la
    # construction des candidats marchent comme pour un dossier film classique.
    if cfg_root_resolved is None:
        # Cache lru_cache module-level (16 dernieres) — gain massif pour cfg.root.
        cfg_root_resolved_str = _resolve_path_cached(str(cfg.root))
    else:
        cfg_root_resolved_str = str(cfg_root_resolved)
    folder_resolved_str = _resolve_path_cached(str(folder))
    _folder_is_root = folder_resolved_str == cfg_root_resolved_str
    folder_name = Path(video.name).stem if _folder_is_root else folder.name
    log_ctx = f"(collection): {folder_name}/{video.name}" if is_collection else f"({folder_name})"

    # Detection edition (Director's Cut, Extended, IMAX, etc.)

    detected_edition = extract_edition(folder_name) or extract_edition(video.name)
    return folder_name, log_ctx, detected_edition


def _build_nfo_candidates(
    cfg: "Config",
    folder_name: str,
    video_name: str,
    *,
    nfo: Optional[Any],
    name_year: Optional[int],
    remaster_hint: bool,
    log: Callable[[str, str], None],
    log_ctx: str,
) -> Tuple[List[Any], Dict[str, Any]]:
    """Analyse la coherence du NFO et construit les candidats nfo_cands.

    Retourne (nfo_cands, nfo_state) ou nfo_state contient :
        nfo_ok, nfo_cov, nfo_seq, nfo_reject_reason, year_delta_reject, nfo_partial_match.
    """

    state = {
        "nfo_ok": False,
        "nfo_cov": 0.0,
        "nfo_seq": 0.0,
        "nfo_reject_reason": "",
        "year_delta_reject": False,
        "nfo_partial_match": False,  # P1.1.b : NFO matche folder XOR filename
    }
    nfo_cands: List[Any] = []
    if not (nfo and nfo.year and (nfo.title or nfo.originaltitle)):
        return nfo_cands, state

    consistency = core_mod.nfo_consistency_check(cfg, nfo, folder_name, video_name)
    state["nfo_ok"] = consistency.ok
    state["nfo_cov"] = consistency.cov
    state["nfo_seq"] = consistency.seq
    state["nfo_partial_match"] = consistency.ok and (consistency.folder_match != consistency.filename_match)
    if state["nfo_partial_match"]:
        which = "dossier" if consistency.folder_match else "fichier"
        log(
            "WARN",
            f"NFO partial match {log_ctx}: matche seulement le {which} "
            f"(folder_cov={consistency.folder_cov:.2f}, file_cov={consistency.filename_cov:.2f}). "
            "Fichier vidéo potentiellement remplacé — à vérifier.",
        )
    if not state["nfo_ok"]:
        soft_ok = core_mod.nfo_soft_consistent(
            name_year=name_year,
            nfo_year=nfo.year,
            cov=state["nfo_cov"],
            seq=state["nfo_seq"],
        )
        if soft_ok:
            state["nfo_ok"] = True
            state["nfo_reject_reason"] = (
                f"NFO accepte en mode tolerant (cov={state['nfo_cov']:.2f}, "
                f"seq={state['nfo_seq']:.2f}, annee coherente)."
            )
            log("INFO", f"NFO soft-match accept {log_ctx} cov={state['nfo_cov']:.2f} seq={state['nfo_seq']:.2f}")
        else:
            log("WARN", f"NFO mismatch -> ignore {log_ctx} cov={state['nfo_cov']:.2f} seq={state['nfo_seq']:.2f}")

    if state["nfo_ok"]:
        reject_year, year_msg = core_mod.should_reject_nfo_year(
            cfg,
            name_year=name_year,
            nfo_year=nfo.year,
            remaster_hint=remaster_hint,
            cov=state["nfo_cov"],
            seq=state["nfo_seq"],
        )
        if reject_year:
            state["year_delta_reject"] = True
            log("WARN", f"NFO year reject {log_ctx}: nfo={nfo.year} name={name_year}")
            state["nfo_reject_reason"] = year_msg
        else:
            if year_msg:
                state["nfo_reject_reason"] = year_msg
                log("INFO", f"NFO year relax {log_ctx}: {year_msg}")
            nfo_cands = core_mod.build_candidates_from_nfo(nfo)

    return nfo_cands, state


def _augment_candidates_from_nfo_imdb(
    cfg: "Config",
    nfo: Optional[Any],
    nfo_cands: List[Any],
    folder_name: str,
    video_name: str,
    *,
    name_year: Optional[int],
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    log_ctx: str,
) -> None:
    """Cross-check NFO IMDb ID via TMDb find. Ajoute un candidat nfo_imdb si OK.

    BUG CRITIQUE : un NFO pollue (copie par erreur) peut pointer vers un IMDb ID
    d'un film totalement different. On verifie la similarite entre le titre
    retourne par TMDb et le nom du dossier/fichier AVANT d'accepter le candidat.
    """
    if not (nfo and getattr(nfo, "imdbid", None) and tmdb and cfg.enable_tmdb):
        return

    try:
        imdb_result = tmdb.find_by_imdb_id(nfo.imdbid)
        if not (imdb_result and imdb_result.id):
            return
        # Verifier similarite titre vs folder/video name
        imdb_title = imdb_result.title or ""
        imdb_original = getattr(imdb_result, "original_title", "") or ""
        sim_folder = max(
            core_mod._title_similarity(core_mod.clean_title_guess(folder_name) or folder_name, imdb_title),
            core_mod._title_similarity(core_mod.clean_title_guess(folder_name) or folder_name, imdb_original)
            if imdb_original
            else 0.0,
        )
        sim_video = max(
            core_mod._title_similarity(core_mod.clean_title_guess(video_name) or video_name, imdb_title),
            core_mod._title_similarity(core_mod.clean_title_guess(video_name) or video_name, imdb_original)
            if imdb_original
            else 0.0,
        )
        sim_best = max(sim_folder, sim_video)
        # Verifier aussi l'annee si disponible
        year_ok = True
        year_delta = None
        if name_year is not None and imdb_result.year:
            year_delta = abs(int(imdb_result.year) - int(name_year))
            if year_delta > 2:
                year_ok = False
        # Seuil strict : on accepte si la similarite est >= 0.50 OU
        # si annee matche parfaitement et similarite >= 0.35
        accept = (sim_best >= 0.50) or (year_ok and year_delta is not None and year_delta <= 1 and sim_best >= 0.35)
        if accept:
            nfo_imdb_cand = core_mod.Candidate(
                title=imdb_result.title,
                year=imdb_result.year,
                source="nfo_imdb",
                tmdb_id=imdb_result.id,
                score=0.95,
                note=f"IMDb lookup {nfo.imdbid} → tmdb:{imdb_result.id}, sim={sim_best:.2f}",
            )
            nfo_cands.append(nfo_imdb_cand)
            _log.info(
                "scan: .nfo IMDb %s → tmdb:%d '%s' (sim=%.2f)",
                nfo.imdbid,
                imdb_result.id,
                imdb_result.title,
                sim_best,
            )
        else:
            log(
                "WARN",
                f"NFO IMDb lookup rejete {log_ctx}: "
                f"titre TMDb '{imdb_title}' ne correspond pas au dossier "
                f"(sim={sim_best:.2f}, delta_annee={year_delta}). NFO probablement pollue.",
            )
            _log.warning(
                "scan: .nfo IMDb %s rejete (sim=%.2f year_delta=%s) tmdb='%s' folder='%s'",
                nfo.imdbid,
                sim_best,
                year_delta,
                imdb_title,
                folder_name,
            )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        _log.debug("scan: echec IMDb lookup %s — %s", nfo.imdbid, exc)


def _augment_candidates_from_nfo_tmdb_id(
    cfg: "Config",
    nfo: Optional[Any],
    nfo_cands: List[Any],
    folder_name: str,
    video_name: str,
    *,
    name_year: Optional[int],
    nfo_ok: bool,
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    log_ctx: str,
) -> None:
    """Cross-check NFO TMDb ID (P1.1.c, symetrique a IMDb lookup).

    Un NFO pollué peut contenir <tmdbid>27205</tmdbid> pointant sur un film
    totalement différent (copie d'un autre dossier). On vérifie la similarité
    titre TMDb officiel vs nom de dossier/fichier AVANT d'accepter.
    """
    if not (nfo and getattr(nfo, "tmdbid", None) and tmdb and cfg.enable_tmdb):
        return

    try:
        tmdb_result = tmdb.find_by_tmdb_id(nfo.tmdbid)
        if not (tmdb_result and tmdb_result.id):
            return
        tmdb_title = tmdb_result.title or ""
        tmdb_original = getattr(tmdb_result, "original_title", "") or ""
        folder_clean = core_mod.clean_title_guess(folder_name) or folder_name
        video_clean = core_mod.clean_title_guess(video_name) or video_name
        sim_folder = max(
            core_mod._title_similarity(folder_clean, tmdb_title),
            core_mod._title_similarity(folder_clean, tmdb_original) if tmdb_original else 0.0,
        )
        sim_video = max(
            core_mod._title_similarity(video_clean, tmdb_title),
            core_mod._title_similarity(video_clean, tmdb_original) if tmdb_original else 0.0,
        )
        sim_best = max(sim_folder, sim_video)
        year_ok = True
        year_delta = None
        if name_year is not None and tmdb_result.year:
            year_delta = abs(int(tmdb_result.year) - int(name_year))
            if year_delta > 2:
                year_ok = False
        accept = (sim_best >= 0.50) or (year_ok and year_delta is not None and year_delta <= 1 and sim_best >= 0.35)
        if accept:
            # Ne pas doublonner si un candidat NFO/IMDb avec ce tmdb_id existe déjà
            already_have = any(getattr(c, "tmdb_id", None) == tmdb_result.id for c in nfo_cands)
            if not already_have:
                nfo_tmdb_cand = core_mod.Candidate(
                    title=tmdb_result.title,
                    year=tmdb_result.year,
                    source="nfo_tmdb",
                    tmdb_id=tmdb_result.id,
                    score=0.93,
                    note=f"TMDb ID {nfo.tmdbid} verifie, sim={sim_best:.2f}",
                )
                nfo_cands.append(nfo_tmdb_cand)
                _log.info(
                    "scan: .nfo TMDb %s -> '%s' (sim=%.2f)",
                    nfo.tmdbid,
                    tmdb_result.title,
                    sim_best,
                )
        else:
            log(
                "WARN",
                f"NFO TMDb ID rejete {log_ctx}: "
                f"titre TMDb '{tmdb_title}' ne correspond pas au dossier "
                f"(sim={sim_best:.2f}, delta_annee={year_delta}). NFO probablement pollue.",
            )
            _log.warning(
                "scan: .nfo TMDb %s rejete (sim=%.2f year_delta=%s) tmdb='%s' folder='%s'",
                nfo.tmdbid,
                sim_best,
                year_delta,
                tmdb_title,
                folder_name,
            )
            # Si ni le titre NFO ni le TMDb ID ne matchent, le NFO est
            # probablement pollué — on dégrade nfo_ok pour forcer la review
            if not nfo_ok:
                # Déjà rejeté pour cause titre : flag déjà posé
                pass
            else:
                # NFO titre matche mais TMDb ID pointe ailleurs = incohérence interne du NFO
                log(
                    "WARN",
                    f"NFO incoherent {log_ctx}: titre NFO matche dossier mais TMDb ID pointe sur '{tmdb_title}'.",
                )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        _log.debug("scan: echec TMDb ID lookup %s — %s", nfo.tmdbid, exc)


def _build_tmdb_fallback_candidates(
    cfg: "Config",
    folder_name: str,
    video_name: str,
    *,
    is_collection: bool,
    name_year: Optional[int],
    nfo_cands: List[Any],
    year_delta_reject: bool,
    tmdb: Optional[TmdbClient],
    should_cancel: Optional[Callable[[], bool]],
) -> Tuple[List[Any], bool]:
    """Lance le TMDb fallback si necessaire. Retourne (tmdb_cands, tmdb_used)."""

    if not (tmdb and cfg.enable_tmdb):
        return [], False

    need = (not nfo_cands) or year_delta_reject or (not name_year)
    if not need:
        return [], False

    if core_mod._is_cancel_requested(should_cancel):
        return [], False

    # Collection: prefer video name first; single: prefer folder name first.
    # Retirer l'edition avant le clean pour eviter la pollution du matching TMDb
    if is_collection:
        queries = [
            core_mod.clean_title_guess(strip_edition(video_name)),
            core_mod.clean_title_guess(strip_edition(folder_name)),
        ]
    else:
        queries = [
            core_mod.clean_title_guess(strip_edition(folder_name)),
            core_mod.clean_title_guess(strip_edition(video_name)),
        ]
    tmdb_cands = core_mod.build_candidates_from_tmdb_fallback(
        tmdb,
        queries=queries,
        year=name_year,
        language=cfg.tmdb_language,
        should_cancel=should_cancel,
    )
    return tmdb_cands, True


def _disambiguate_candidates(
    cands: List[Any],
    *,
    nfo: Optional[Any],
    name_year: Optional[int],
    log: Callable[[str, str], None],
    log_ctx: str,
) -> Tuple[List[Any], bool]:
    """Désambiguise par contexte (P2.2) si plusieurs films partagent le titre.

    Retourne (cands_ajustes, title_ambiguous). Modifie les scores uniquement si
    ambiguïté détectée (ex : Dune 1984 vs 2021).
    """

    ambig_context = {
        "name_year": name_year,
        "nfo_tmdb_id": (
            int(nfo.tmdbid) if nfo and getattr(nfo, "tmdbid", None) and str(nfo.tmdbid).strip().isdigit() else None
        ),
        "nfo_runtime": getattr(nfo, "runtime", None) if nfo else None,
    }
    cands, title_ambiguous, ambig_title = disambiguate_by_context(cands, ambig_context)
    if title_ambiguous:
        log(
            "WARN",
            f"Titres TMDb ambigus {log_ctx}: {ambig_title!r} existe dans plusieurs années. "
            "Désambiguïsation sur contexte.",
        )
    return cands, title_ambiguous


def _build_unresolved_row(
    folder: Path,
    video: Path,
    *,
    row_id: str,
    kind: str,
    is_collection: bool,
    folder_name: str,
    cands: List[Any],
    nfo: Optional[Any],
    nfo_path: Optional[Path],
    nfo_state: Dict[str, Any],
    name_year: Optional[int],
    name_year_reason: str,
    remaster_hint: bool,
    tmdb_used: bool,
    title_ambiguous: bool,
    detected_edition: Optional[str],
    log: Callable[[str, str], None],
) -> "PlanRow":
    """Construit une PlanRow pour le cas ou aucun candidat fiable n'a ete trouve."""

    if not is_collection:
        log("WARN", f"Cannot resolve single: {folder_name}")
    note = core_mod.build_plan_note(
        confidence=0,
        label="low",
        chosen=None,
        name_year=name_year,
        name_year_reason=name_year_reason,
        remaster_hint=remaster_hint,
        nfo_present=bool(nfo),
        nfo_ok=nfo_state["nfo_ok"],
        nfo_cov=nfo_state["nfo_cov"],
        nfo_seq=nfo_state["nfo_seq"],
        nfo_reject_reason=nfo_state["nfo_reject_reason"],
        tmdb_used=tmdb_used,
    )
    warning_flags = core_mod._warning_flags_from_analysis(
        chosen=None,
        name_year_reason=name_year_reason,
        nfo_present=bool(nfo),
        nfo_ok=nfo_state["nfo_ok"],
        year_delta_reject=nfo_state["year_delta_reject"],
        nfo_partial_match=nfo_state["nfo_partial_match"],
        title_ambiguity=title_ambiguous,
    )
    note = f"{note} Impossible de determiner un titre+annee fiables."
    fallback_title = (core_mod.clean_title_guess(video.name) or video.stem) if is_collection else folder_name
    return core_mod.PlanRow(
        row_id=row_id,
        kind=kind,
        folder=str(folder),
        video=video.name,
        proposed_title=fallback_title,
        proposed_year=name_year or 0,
        proposed_source="unknown",
        confidence=0,
        confidence_label="low",
        candidates=cands,
        nfo_path=str(nfo_path) if nfo_path else None,
        notes=note,
        detected_year=int(name_year or 0),
        detected_year_reason=str(name_year_reason or ""),
        warning_flags=warning_flags,
        collection_name=folder.name if is_collection else None,
        edition=detected_edition,
        nfo_runtime=nfo.runtime if nfo else None,
    )


def _resolve_tmdb_collection(
    cfg: "Config",
    chosen: Any,
    folder_name: str,
    *,
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
) -> Tuple[Optional[int], Optional[str]]:
    """Retourne (collection_id, collection_name) si fiable, sinon (None, None).

    FIX 6 : la collection doit partager au moins un mot significatif avec le
    nom du dossier source OU avec le titre du candidat. Sinon le collection
    boost est toxique (ex: 'Ca' → Pirates des Caraibes).
    """

    if not (tmdb is not None and chosen.tmdb_id):
        return None, None
    coll_id: Optional[int] = None
    coll_name: Optional[str] = None
    with contextlib.suppress(KeyError, TypeError, ValueError):
        coll_id, coll_name = tmdb.get_movie_collection(chosen.tmdb_id)
    if not coll_name:
        return coll_id, coll_name
    coll_tokens = {t for t in core_mod.tokens(coll_name) if len(t) >= 3}
    folder_tokens = set(core_mod.tokens(folder_name))
    title_tokens = set(core_mod.tokens(chosen.title or ""))
    if coll_tokens and not (coll_tokens & folder_tokens) and not (coll_tokens & title_tokens):
        _log.warning(
            "scan: collection TMDb '%s' rejetee (pas de mot commun avec dossier='%s' ni titre='%s')",
            coll_name,
            folder_name,
            chosen.title,
        )
        log(
            "WARN",
            f"Collection '{coll_name}' ignoree pour '{folder_name}' (aucun mot commun avec le nom source).",
        )
        return None, None
    return coll_id, coll_name


def _build_resolved_row(
    cfg: "Config",
    folder: Path,
    video: Path,
    chosen: Any,
    *,
    row_id: str,
    kind: str,
    is_collection: bool,
    folder_name: str,
    cands: List[Any],
    nfo: Optional[Any],
    nfo_path: Optional[Path],
    nfo_state: Dict[str, Any],
    name_year: Optional[int],
    name_year_reason: str,
    remaster_hint: bool,
    tmdb_used: bool,
    title_ambiguous: bool,
    detected_edition: Optional[str],
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
) -> "PlanRow":
    """Construit une PlanRow pour le cas ou un candidat fiable a ete choisi."""

    confidence, label = core_mod.compute_confidence(
        cfg,
        chosen,
        nfo_ok=nfo_state["nfo_ok"],
        year_delta_reject=nfo_state["year_delta_reject"],
        tmdb_used=tmdb_used,
        nfo_partial_match=nfo_state["nfo_partial_match"],
    )
    proposed_title = core_mod.windows_safe(chosen.title)
    # BUG 3 : si le dossier courant est deja conforme (meme titre + annee que
    # le candidat), la confiance doit etre HIGH — aucune action ne sera prise
    # meme si la similarite textuelle TMDb < 0.60 (le cap de compute_confidence
    # penalise a tort les films conformes sans rename propose).
    is_already_conform = False
    if not is_collection and chosen.year:
        try:
            is_already_conform = core_mod._single_folder_is_conform(
                folder_name,
                chosen.title,
                int(chosen.year),
                naming_template=str(getattr(cfg, "naming_movie_template", "") or ""),
            )
        except (TypeError, ValueError, AttributeError):
            is_already_conform = False
    if is_already_conform and confidence < 85:
        confidence = 90
        label = "high"
    # Phase 6.1 : runtime cross-check NFO vs TMDb, edition-aware.
    # Source duree = nfo.runtime (deja parse, zero cout scan). Phase 6.1.b
    # branchera probe.duration_s en complement quand cache probe dispo.
    runtime_warning: Optional[str] = None
    if nfo is not None and getattr(nfo, "runtime", None) and tmdb is not None and chosen.tmdb_id:
        try:
            tmdb_runtime = tmdb.get_movie_runtime(int(chosen.tmdb_id))
        except (AttributeError, TypeError, ValueError):
            tmdb_runtime = None
        if tmdb_runtime:
            bonus, runtime_warning = score_runtime_delta(
                file_runtime_min=float(nfo.runtime),
                tmdb_runtime_min=tmdb_runtime,
                edition_label=detected_edition,
            )
            confidence = max(0, min(100, confidence + bonus))
            if bonus >= 10:
                label = "high" if confidence >= 85 else label
            elif bonus < 0:
                label = "low" if confidence < 60 else label
    note = core_mod.build_plan_note(
        confidence=confidence,
        label=label,
        chosen=chosen,
        name_year=name_year,
        name_year_reason=name_year_reason,
        remaster_hint=remaster_hint,
        nfo_present=bool(nfo),
        nfo_ok=nfo_state["nfo_ok"],
        nfo_cov=nfo_state["nfo_cov"],
        nfo_seq=nfo_state["nfo_seq"],
        nfo_reject_reason=nfo_state["nfo_reject_reason"],
        tmdb_used=tmdb_used,
    )
    warning_flags = core_mod._warning_flags_from_analysis(
        chosen=chosen,
        name_year_reason=name_year_reason,
        nfo_present=bool(nfo),
        nfo_ok=nfo_state["nfo_ok"],
        year_delta_reject=nfo_state["year_delta_reject"],
        nfo_partial_match=nfo_state["nfo_partial_match"],
        title_ambiguity=title_ambiguous,
    )
    if runtime_warning and runtime_warning not in warning_flags:
        warning_flags.append(runtime_warning)
    coll_id, coll_name = _resolve_tmdb_collection(cfg, chosen, folder_name, tmdb=tmdb, log=log)
    return core_mod.PlanRow(
        row_id=row_id,
        kind=kind,
        folder=str(folder),
        video=video.name,
        proposed_title=proposed_title,
        proposed_year=int(chosen.year),
        proposed_source=chosen.source,
        confidence=confidence,
        confidence_label=label,
        candidates=cands,
        nfo_path=str(nfo_path) if nfo_path else None,
        notes=note,
        detected_year=int(name_year or 0),
        detected_year_reason=str(name_year_reason or ""),
        warning_flags=warning_flags,
        collection_name=folder.name if is_collection else None,
        tmdb_collection_id=coll_id,
        tmdb_collection_name=coll_name,
        edition=detected_edition,
        nfo_runtime=nfo.runtime if nfo else None,
    )


def _apply_subtitle_detection(
    folder: Path,
    video: Path,
    result_row: "PlanRow",
    *,
    subtitle_expected_languages: Optional[List[str]],
) -> None:
    """Enrichit la PlanRow avec les infos sous-titres + warning flags associes."""
    if subtitle_expected_languages is None:
        return

    sub_report = build_subtitle_report(folder, video, subtitle_expected_languages)
    result_row.subtitle_count = sub_report.count
    result_row.subtitle_languages = list(sub_report.languages)
    result_row.subtitle_formats = list(sub_report.formats)
    result_row.subtitle_missing_langs = list(sub_report.missing_languages)
    result_row.subtitle_orphans = sub_report.orphans
    for missing_lang in sub_report.missing_languages:
        flag = f"subtitle_missing_{missing_lang}"
        if flag not in result_row.warning_flags:
            result_row.warning_flags.append(flag)
    if sub_report.orphans > 0 and "subtitle_orphan" not in result_row.warning_flags:
        result_row.warning_flags.append("subtitle_orphan")
    if sub_report.duplicate_languages and "subtitle_duplicate_lang" not in result_row.warning_flags:
        result_row.warning_flags.append("subtitle_duplicate_lang")


def _apply_not_a_movie_detection(video: Path, result_row: "PlanRow") -> None:
    """Pose le flag 'not_a_movie' si l'heuristique depasse le seuil."""

    try:
        video_size = video.stat().st_size if video.exists() else 0
    except (OSError, PermissionError):
        video_size = 0
    nam_score = not_a_movie_score(
        video_name=video.name,
        file_size=video_size,
        proposed_source=result_row.proposed_source,
        confidence=result_row.confidence,
        title=result_row.proposed_title,
    )
    if nam_score >= _NOT_A_MOVIE_THRESHOLD and "not_a_movie" not in result_row.warning_flags:
        result_row.warning_flags.append("not_a_movie")


def _apply_integrity_check(video: Path, result_row: "PlanRow") -> None:
    """Pose le flag 'integrity_header_invalid' si magic bytes invalides.

    Ne jamais bloquer le scan pour un check d'integrite (try/except large).
    """

    try:
        hdr_valid, _hdr_detail = check_header(video)
        if not hdr_valid and "integrity_header_invalid" not in result_row.warning_flags:
            result_row.warning_flags.append("integrity_header_invalid")
    except (OSError, PermissionError, FileNotFoundError, ValueError):
        pass  # ne jamais bloquer le scan pour un check d'integrite


def _store_row_cache(
    cfg: "Config",
    folder: Path,
    video: Path,
    nfo_path: Optional[Path],
    result_row: "PlanRow",
    *,
    kind: str,
    cfg_sig: str,
    run_id: str,
    scan_index: Optional[Any],
    run_hash_cache: Optional[Dict[Tuple[str, int, int], str]],
) -> None:
    """Persiste la PlanRow dans le cache row v2 (best-effort, jamais bloquant)."""
    if not (cfg_sig and scan_index is not None and hasattr(scan_index, "upsert_incremental_row_cache")):
        return
    try:
        v_stat = video.stat()
        v_hash = resolve_incremental_quick_hash(
            video,
            scan_index=scan_index,
            run_hash_cache=run_hash_cache or {},
        )
        scan_index.upsert_incremental_row_cache(
            root_path=str(cfg.root),
            video_path=str(video),
            video_size=int(v_stat.st_size),
            video_mtime_ns=int(v_stat.st_mtime_ns),
            video_hash=v_hash,
            folder_path=str(folder),
            nfo_sig=_nfo_signature(nfo_path),
            cfg_sig=cfg_sig,
            kind=kind,
            row_json=plan_row_to_jsonable(result_row),
            run_id=str(run_id),
        )
    except (FileNotFoundError, PermissionError, OSError):
        pass


def _plan_item(
    cfg: "Config",
    folder: Path,
    video: Path,
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    *,
    kind: str,
    should_cancel: Optional[Callable[[], bool]] = None,
    scan_index: Optional[Any] = None,
    cfg_sig: str = "",
    run_id: str = "",
    run_hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    row_cache_stats: Optional[Dict[str, int]] = None,
    subtitle_expected_languages: Optional[List[str]] = None,
) -> List["PlanRow"]:
    """Orchestre la construction d'une PlanRow pour un fichier video.

    kind : "single" (film standalone) ou "collection" (film dans une saga).
    Pour les episodes TV, voir _plan_tv_episode (pipeline distinct).

    Pipeline : cache lookup -> contexte folder/edition -> NFO + cross-checks
    IMDb/TMDb -> TMDb fallback -> disambiguation -> PlanRow -> enrichissements
    (sous-titres, non-film, integrite) -> cache store.
    """

    is_collection = kind == "collection"
    row_id_prefix = "C" if is_collection else "S"
    row_id = f"{row_id_prefix}|{hash((str(folder), video.name)) & 0xFFFFFFFF:x}"

    # --- Scan v2: per-video row cache lookup ---
    cached_row = _try_lookup_row_cache(
        cfg,
        folder,
        video,
        cfg_sig=cfg_sig,
        scan_index=scan_index,
        run_hash_cache=run_hash_cache,
        row_cache_stats=row_cache_stats,
    )
    if cached_row is not None:
        return [cached_row]

    folder_name, log_ctx, detected_edition = _resolve_folder_context(cfg, folder, video, is_collection=is_collection)

    name_year, name_year_reason, remaster_hint = core_mod.infer_name_year(folder_name, video.name)
    name_cands = core_mod.build_candidates_from_name(folder_name, video.name, preferred_year=name_year)

    if core_mod._is_cancel_requested(should_cancel):
        return []

    nfo_path = core_mod.find_best_nfo_for_video(folder, video)
    if core_mod._is_cancel_requested(should_cancel):
        return []
    nfo = core_mod.parse_movie_nfo(nfo_path) if nfo_path else None

    nfo_cands, nfo_state = _build_nfo_candidates(
        cfg,
        folder_name,
        video.name,
        nfo=nfo,
        name_year=name_year,
        remaster_hint=remaster_hint,
        log=log,
        log_ctx=log_ctx,
    )

    _augment_candidates_from_nfo_imdb(
        cfg,
        nfo,
        nfo_cands,
        folder_name,
        video.name,
        name_year=name_year,
        tmdb=tmdb,
        log=log,
        log_ctx=log_ctx,
    )

    _augment_candidates_from_nfo_tmdb_id(
        cfg,
        nfo,
        nfo_cands,
        folder_name,
        video.name,
        name_year=name_year,
        nfo_ok=nfo_state["nfo_ok"],
        tmdb=tmdb,
        log=log,
        log_ctx=log_ctx,
    )

    tmdb_cands, tmdb_used = _build_tmdb_fallback_candidates(
        cfg,
        folder_name,
        video.name,
        is_collection=is_collection,
        name_year=name_year,
        nfo_cands=nfo_cands,
        year_delta_reject=nfo_state["year_delta_reject"],
        tmdb=tmdb,
        should_cancel=should_cancel,
    )

    cands = []
    cands.extend(nfo_cands)
    cands.extend(tmdb_cands)
    cands.extend(name_cands)

    cands, title_ambiguous = _disambiguate_candidates(
        cands,
        nfo=nfo,
        name_year=name_year,
        log=log,
        log_ctx=log_ctx,
    )

    chosen = core_mod.pick_best_candidate(cands)
    if not chosen or not chosen.year:
        result_row = _build_unresolved_row(
            folder,
            video,
            row_id=row_id,
            kind=kind,
            is_collection=is_collection,
            folder_name=folder_name,
            cands=cands,
            nfo=nfo,
            nfo_path=nfo_path,
            nfo_state=nfo_state,
            name_year=name_year,
            name_year_reason=name_year_reason,
            remaster_hint=remaster_hint,
            tmdb_used=tmdb_used,
            title_ambiguous=title_ambiguous,
            detected_edition=detected_edition,
            log=log,
        )
    else:
        result_row = _build_resolved_row(
            cfg,
            folder,
            video,
            chosen,
            row_id=row_id,
            kind=kind,
            is_collection=is_collection,
            folder_name=folder_name,
            cands=cands,
            nfo=nfo,
            nfo_path=nfo_path,
            nfo_state=nfo_state,
            name_year=name_year,
            name_year_reason=name_year_reason,
            remaster_hint=remaster_hint,
            tmdb_used=tmdb_used,
            title_ambiguous=title_ambiguous,
            detected_edition=detected_edition,
            tmdb=tmdb,
            log=log,
        )

    _apply_subtitle_detection(folder, video, result_row, subtitle_expected_languages=subtitle_expected_languages)
    _apply_not_a_movie_detection(video, result_row)
    _apply_integrity_check(video, result_row)
    _store_row_cache(
        cfg,
        folder,
        video,
        nfo_path,
        result_row,
        kind=kind,
        cfg_sig=cfg_sig,
        run_id=run_id,
        scan_index=scan_index,
        run_hash_cache=run_hash_cache,
    )

    return [result_row]


def _plan_single(
    cfg: "Config",
    folder: Path,
    video: Path,
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    *,
    should_cancel: Optional[Callable[[], bool]] = None,
    scan_index: Optional[Any] = None,
    cfg_sig: str = "",
    run_id: str = "",
    run_hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    row_cache_stats: Optional[Dict[str, int]] = None,
    subtitle_expected_languages: Optional[List[str]] = None,
) -> List["PlanRow"]:
    return _plan_item(
        cfg,
        folder,
        video,
        tmdb,
        log,
        kind="single",
        should_cancel=should_cancel,
        scan_index=scan_index,
        cfg_sig=cfg_sig,
        run_id=run_id,
        run_hash_cache=run_hash_cache,
        row_cache_stats=row_cache_stats,
        subtitle_expected_languages=subtitle_expected_languages,
    )


def _plan_collection_item(
    cfg: "Config",
    folder: Path,
    video: Path,
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    *,
    should_cancel: Optional[Callable[[], bool]] = None,
    scan_index: Optional[Any] = None,
    cfg_sig: str = "",
    run_id: str = "",
    run_hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    row_cache_stats: Optional[Dict[str, int]] = None,
    subtitle_expected_languages: Optional[List[str]] = None,
) -> List["PlanRow"]:
    return _plan_item(
        cfg,
        folder,
        video,
        tmdb,
        log,
        kind="collection",
        should_cancel=should_cancel,
        scan_index=scan_index,
        cfg_sig=cfg_sig,
        run_id=run_id,
        run_hash_cache=run_hash_cache,
        row_cache_stats=row_cache_stats,
        subtitle_expected_languages=subtitle_expected_languages,
    )


def _plan_tv_episode(
    cfg: "Config",
    folder: Path,
    video: Path,
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    *,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> List["PlanRow"]:
    """Build a PlanRow for a TV episode (kind='tv_episode')."""

    tv = parse_tv_info(folder, video)
    if tv is None:
        return []

    row_id = f"T|{hash((str(folder), video.name)) & 0xFFFFFFFF:x}"
    series_name = tv.series_name
    season = tv.season
    episode = tv.episode
    year = tv.year
    tmdb_series_id: Optional[int] = None
    episode_title: Optional[str] = None
    source = "name"
    confidence = 45

    # TMDb TV lookup.
    if tmdb and cfg.enable_tmdb and series_name:
        if core_mod._is_cancel_requested(should_cancel):
            return []
        try:
            tv_results = tmdb.search_tv(series_name, year=year, language=cfg.tmdb_language)
            if tv_results:
                best = tv_results[0]
                tmdb_series_id = best.id
                series_name = best.name or series_name
                if best.first_air_date_year:
                    year = best.first_air_date_year
                source = "tmdb_tv"
                confidence = 65

                if season is not None and episode is not None and tmdb_series_id:
                    ep_title = tmdb.get_tv_episode_title(
                        tmdb_series_id,
                        season,
                        episode,
                        language=cfg.tmdb_language,
                    )
                    if ep_title:
                        episode_title = ep_title
                        confidence = 85
        except (FileNotFoundError, PermissionError, OSError):
            pass

    if season is not None and episode is not None:
        confidence = min(100, confidence + 10)
    confidence = max(0, min(100, confidence))
    label = "high" if confidence >= 80 else "med" if confidence >= 60 else "low"

    proposed_title = core_mod.windows_safe(series_name)
    note_parts = [f"Serie: {series_name}"]
    if season is not None:
        note_parts.append(f"S{season:02d}")
    if episode is not None:
        note_parts.append(f"E{episode:02d}")
    if episode_title:
        note_parts.append(f'"{episode_title}"')
    note_parts.append(f"source={source}")

    return [
        core_mod.PlanRow(
            row_id=row_id,
            kind="tv_episode",
            folder=str(folder),
            video=video.name,
            proposed_title=proposed_title,
            proposed_year=int(year or 0),
            proposed_source=source,
            confidence=confidence,
            confidence_label=label,
            candidates=[],
            notes=" | ".join(note_parts),
            detected_year=int(year or 0),
            detected_year_reason="tv_first_air_date" if source == "tmdb_tv" else "folder",
            warning_flags=[],
            tv_series_name=series_name,
            tv_season=season,
            tv_episode=episode,
            tv_episode_title=episode_title,
            tv_tmdb_series_id=tmdb_series_id,
        )
    ]


# =========================================================
# MULTI-ROOT SUPPORT
# =========================================================


def _merge_stats(target: "Stats", source: "Stats") -> None:
    """Additionne les compteurs de *source* dans *target* (in-place)."""
    for f in dc_fields(target):
        val = getattr(source, f.name)
        if isinstance(val, int):
            setattr(target, f.name, getattr(target, f.name) + val)
        elif isinstance(val, dict):
            merged = dict(getattr(target, f.name))
            for k, v in val.items():
                merged[k] = merged.get(k, 0) + int(v)
            setattr(target, f.name, merged)


def _detect_cross_root_duplicates(rows: List["PlanRow"]) -> int:
    """Detecte les doublons cross-root et ajoute un warning_flag. Retourne le nombre de doublons."""
    by_key: Dict[Tuple[str, int], List["PlanRow"]] = defaultdict(list)
    for row in rows:
        key = (str(row.proposed_title or "").strip().lower(), int(row.proposed_year or 0))
        if key[0]:
            by_key[key].append(row)

    dup_count = 0
    for key, group in by_key.items():
        roots_seen = {r.source_root for r in group if r.source_root}
        if len(roots_seen) < 2:
            continue
        for row in group:
            if "duplicate_cross_root" not in (row.warning_flags or []):
                if row.warning_flags is None:
                    row.warning_flags = []
                row.warning_flags.append("duplicate_cross_root")
                other_roots = [r for r in roots_seen if r != row.source_root]
                if other_roots:
                    row.notes = (row.notes or "") + f" | Aussi dans: {', '.join(other_roots)}"
                dup_count += 1
    return dup_count


def plan_multi_roots(
    roots: List[Path],
    *,
    build_cfg: Callable[[Path], "Config"],
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    progress: Callable[[int, int, str], None],
    should_cancel: Optional[Callable[[], bool]] = None,
    scan_index: Optional[Any] = None,
    run_id: str = "",
    subtitle_expected_languages: Optional[List[str]] = None,
) -> Tuple[List["PlanRow"], "Stats"]:
    """Scanne plusieurs roots sequentiellement et merge les resultats.

    - Chaque root est scanne via plan_library() avec son propre Config
    - Les rows recus sont annotes avec source_root
    - Les Stats sont additionnees
    - Les doublons cross-root sont detectes (warning_flag)
    - Un root inaccessible est skip avec un warning (pas d'erreur fatale)
    """

    all_rows: List[core_mod.PlanRow] = []
    all_stats = core_mod.Stats()
    accessible_count = 0
    skipped_roots: List[str] = []

    for i, root in enumerate(roots):
        if should_cancel and should_cancel():
            log("WARN", "Analyse annulee.")
            break

        root_label = f"Root {i + 1}/{len(roots)}"
        # M-1 audit QA 20260429 : detection NAS debranche via timeout 10s.

        exists = safe_path_exists(root, timeout_s=10.0)
        if exists is None:
            log("WARN", f"{root_label} : {root} inaccessible apres 10s (NAS debranche ?), skip.")
            skipped_roots.append(str(root))
            continue
        if not exists:
            log("WARN", f"{root_label} : {root} inaccessible, skip.")
            skipped_roots.append(str(root))
            continue
        if not is_dir_accessible(root, timeout_s=5.0):
            log("WARN", f"{root_label} : {root} n'est pas un dossier accessible, skip.")
            skipped_roots.append(str(root))
            continue

        accessible_count += 1
        log("INFO", f"=== {root_label} : {root} ===")

        cfg = build_cfg(root)

        def multi_progress(idx: int, total: int, current: str) -> None:
            progress(idx, total, f"[{root_label}] {current}")

        rows_i, stats_i = plan_library(
            cfg,
            tmdb=tmdb,
            log=log,
            progress=multi_progress,
            should_cancel=should_cancel,
            scan_index=scan_index,
            run_id=run_id,
            subtitle_expected_languages=subtitle_expected_languages,
        )

        for row in rows_i:
            row.source_root = str(root)

        all_rows.extend(rows_i)
        _merge_stats(all_stats, stats_i)

    if len(roots) > 1:
        dup_count = _detect_cross_root_duplicates(all_rows)
        if dup_count > 0:
            log("INFO", f"Doublons cross-root detectes : {dup_count} film(s)")
        if skipped_roots:
            log("WARN", f"{len(skipped_roots)}/{len(roots)} root(s) inaccessible(s) : {', '.join(skipped_roots)}")
        log("INFO", f"Multi-root : {accessible_count}/{len(roots)} root(s) scannes, {len(all_rows)} film(s) total")

    return all_rows, all_stats


# ---------------------------------------------------------------------------
# Cf #83 etape 2 PR 4b : find_duplicate_targets COTE APP avec DI complete.
#
# Phase precedente (PR 3) : ce wrapper deleguait a domain.core. Phase
# actuelle : le wrapper pre-remplit lui-meme les 7 helpers DI vers
# `cinesort.domain.duplicate_support`, ce qui permet de supprimer la
# fonction de domain/core.py (et avec elle, 6 helpers prives DI qui
# n'avaient pas d'autre usage). Aucun cycle : app->domain est legitime.
# ---------------------------------------------------------------------------


def find_duplicate_targets(
    cfg: "Config",
    rows: List["PlanRow"],
    decisions: Dict[str, Dict[str, object]],
    *,
    max_groups: int = 120,
) -> Dict[str, object]:
    """Detecte les groupes de doublons sur les destinations planifiees (#83 PR 4b).

    Pre-remplit les 7 helpers DI vers `domain.duplicate_support.find_duplicate_targets`.
    Tous les helpers viennent de :
    - `cinesort.app.apply_core` (is_managed_merge_file, files_identical_quick)
    - `cinesort.domain.duplicate_support` (movie_dir_title_year, movie_key,
      existing_movie_folder_index, planned_target_folder, is_under_collection_root,
      can_merge_single/collection_item_without_blocking, find_video_case_insensitive)
    - `cinesort.domain.core` (windows_safe, _norm_win_path, classify_sidecars
      pour le sub-helper)
    - `cinesort.domain.title_helpers` (_norm_for_tokens)
    """
    _apply_core = _apply_core_mod
    _norm_win_path = core_mod._norm_win_path
    classify_sidecars = core_mod.classify_sidecars
    windows_safe = core_mod.windows_safe

    def _movie_key(title: str, year: int, edition: Optional[str] = None) -> str:
        return _dup.movie_key(title, year, norm_for_tokens=_norm_for_tokens, edition=edition)

    def _existing_movie_folder_index(cfg_: Any) -> Dict[str, List[str]]:
        return _dup.existing_movie_folder_index(
            cfg_,
            movie_dir_title_year=_dup.movie_dir_title_year,
            movie_key=_movie_key,
        )

    def _is_under_collection_root(cfg_: Any, folder: Path) -> bool:
        return _dup.is_under_collection_root(cfg_, folder, norm_win_path=_norm_win_path)

    def _planned_target_folder(cfg_: Any, row: Any, title: str, year: int) -> Path:
        return _dup.planned_target_folder(
            cfg_,
            row,
            title,
            year,
            is_under_collection_root=_is_under_collection_root,
            windows_safe=windows_safe,
        )

    def _can_merge_single(cfg_: Any, src_dir: Path, dst_dir: Path) -> Tuple[bool, str]:
        return _dup.can_merge_single_without_blocking(
            cfg_,
            src_dir,
            dst_dir,
            is_managed_merge_file=_apply_core.is_managed_merge_file,
            files_identical_quick=_apply_core.files_identical_quick,
        )

    def _can_merge_collection_item(cfg_: Any, row: Any, target_dir: Path) -> Tuple[bool, str]:
        # Note : la signature reelle dans domain.duplicate_support attend
        # find_video_case_insensitive + classify_sidecars (PAS is_managed_merge_file
        # comme on aurait pu croire — c'est specifique aux items de collection).
        return _dup.can_merge_collection_item_without_blocking(
            cfg_,
            row,
            target_dir,
            find_video_case_insensitive=_dup.find_video_case_insensitive,
            classify_sidecars=lambda cfg_arg, folder_arg, video_arg: classify_sidecars(
                cfg_arg, folder_arg, video_arg, is_collection=True
            ),
            files_identical_quick=_apply_core.files_identical_quick,
        )

    return _dup.find_duplicate_targets(
        cfg.normalized() if hasattr(cfg, "normalized") else cfg,
        rows,
        decisions,
        max_groups=max_groups,
        existing_movie_folder_index=_existing_movie_folder_index,
        movie_key=_movie_key,
        planned_target_folder=_planned_target_folder,
        norm_win_path=_norm_win_path,
        can_merge_single_without_blocking=_can_merge_single,
        can_merge_collection_item_without_blocking=_can_merge_collection_item,
        windows_safe=windows_safe,
    )
