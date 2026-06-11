"""Core orchestration de plan_library (VP-E refactor, sous-lot VP-6).

Porte les helpers de (de)serialisation PlanRow/Stats, les signatures de
fichier (NFO sha1, folder signature, quick hash incremental), l'orchestrateur
public `plan_library` et son `_PlanLibraryContext` decoupes en 3 phases.

Pipeline single-row : `plan_support_replan`. Dedup + multi-roots :
`plan_support_dedup`. Backward compat via le facade `plan_support`.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

import cinesort.domain.core as core_mod
from cinesort.app._local_candidate import (
    LocalCandidate,
    parallel_extract_local_candidates,
    resolve_scan_max_workers,
)
from cinesort.app.apply_core import quick_hash_cache_key, sha1_quick
from cinesort.domain.scan_helpers import discover_candidate_folders, file_name_looks_bonus
from cinesort.infra.fs_safety import safe_path_exists
from cinesort.infra.tmdb_client import TmdbClient

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
            # AUDIT 2026-06-10 (REAL 2/2) : restaurer les 10 champs TV/sous-titres
            # serialises par plan_row_to_jsonable (asdict). Sans eux, tout hit du
            # cache incremental ramenait tv_season/tv_episode=None ->
            # apply_tv_episode renommait l'episode en S00E00 (perte d'info +
            # violation invariant renommage), et les badges sous-titres
            # disparaissaient en UI.
            tv_series_name=str(data.get("tv_series_name") or "") or None,
            tv_season=int(data["tv_season"]) if data.get("tv_season") not in (None, "") else None,
            tv_episode=int(data["tv_episode"]) if data.get("tv_episode") not in (None, "") else None,
            tv_episode_title=str(data.get("tv_episode_title") or "") or None,
            tv_tmdb_series_id=int(data["tv_tmdb_series_id"])
            if data.get("tv_tmdb_series_id") not in (None, "", 0)
            else None,
            subtitle_count=int(data.get("subtitle_count") or 0),
            subtitle_languages=[str(x) for x in (data.get("subtitle_languages") or [])],
            subtitle_formats=[str(x) for x in (data.get("subtitle_formats") or [])],
            subtitle_missing_langs=[str(x) for x in (data.get("subtitle_missing_langs") or [])],
            subtitle_orphans=int(data.get("subtitle_orphans") or 0),
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


# plan_library = orchestrateur + 3 phases privees (V4-03 refactor) :
#   1. _scan_root_phase           : decouverte des dossiers candidats + setup contexte
#   2. _filter_dossiers_phase     : iteration principale (cache, classification, plan)
#   3. _dedup_and_finalize_phase  : purge cache incremental + finalisation stats
# Le contexte mutable est porte par _PlanLibraryContext (dataclass).


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
    # VN-E.3 : pause cooperative — callable optionnel interroge entre 2
    # dossiers dans _filter_dossiers_phase. La cancellation prevaut.
    should_pause: Optional[Callable[[], bool]] = None
    pause_logged: bool = False
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

    def wait_while_paused(self, poll_interval_s: float = 0.5) -> bool:
        """VN-E.3 : suspend la boucle tant que `should_pause()` retourne True.

        Boucle de sommeil cooperative entre 2 iterations. La cancellation
        prevaut : si `should_cancel()` devient True pendant la pause, on
        sort immediatement (returns True pour signaler 'arret demande').

        Retourne True si une cancellation est intervenue pendant la pause,
        False sinon. No-op si `should_pause` est None (backward compat).
        """

        if self.should_pause is None:
            return False
        try:
            paused_now = bool(self.should_pause())
        # except Exception : callback exterieur, on swallow defensivement
        except Exception:  # noqa: BLE001
            return False
        if not paused_now:
            return False
        if not self.pause_logged:
            self.log("INFO", "pause requested")
            self.pause_logged = True
        # Boucle de pause cooperative — sleep court pour rester reactif au
        # resume ET a la cancellation.
        import time as _time

        while True:
            if core_mod._is_cancel_requested(self.should_cancel):
                return True
            try:
                still_paused = bool(self.should_pause())
            except Exception:  # noqa: BLE001
                still_paused = False
            if not still_paused:
                # Reset du flag de log pour les pauses ulterieures.
                self.pause_logged = False
                self.log("INFO", "pause released")
                return False
            _time.sleep(poll_interval_s)

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
    # niveau (VN-F.3 : l'ancien chemin os.walk via stream_scan_targets a ete
    # supprime, plan_library passe exclusivement par discover_candidate_folders).
    _discover_t0 = time.monotonic()
    try:
        ctx.candidate_folders = discover_candidate_folders(ctx.cfg)
    except (OSError, PermissionError, FileNotFoundError) as exc:
        raise RuntimeError(f"Impossible de lister ROOT: {exc}") from exc
    discover_total = len(ctx.candidate_folders)
    _discover_dt = time.monotonic() - _discover_t0
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
    # Import tardif pour eviter le cycle de chargement (replan importe core).
    from cinesort.app.plan_support_replan import (
        _plan_collection_item,
        _plan_single,
        _plan_tv_episode,
    )

    if core_mod.looks_tv_like(folder, videos):
        # QW07 : compteur dedie au dashboard 'Diagnostic scan'. On compte le
        # nombre de videos detectees comme TV (somme cumulee), pas le nombre
        # de dossiers, conformement au nom du champ ('count_videos').
        if hasattr(ctx.stats, "folders_rejected_tv_like_count_videos"):
            ctx.stats.folders_rejected_tv_like_count_videos = int(
                ctx.stats.folders_rejected_tv_like_count_videos or 0
            ) + len(videos)
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
            # Fix bug "Star Wars BONUS" : un dossier collection qui contient des
            # videos bonus (making-of, featurettes, behind-the-scenes...) ne doit
            # pas generer de PlanRow distincte par bonus avec le meme proposed_title.
            # On marque ces lignes kind='extra' + warning_flag 'bonus_video' pour
            # que l'UI puisse les regrouper/filtrer par defaut.
            looks_bonus = file_name_looks_bonus(video.name)
            new_rows = _plan_collection_item(
                ctx.cfg, folder, video, ctx.tmdb, ctx.log, should_cancel=ctx.should_cancel, **ctx.v2_kwargs
            )
            if looks_bonus:
                for r in new_rows:
                    try:
                        r.kind = "extra"
                    except (AttributeError, TypeError):
                        pass
                    flags = getattr(r, "warning_flags", None)
                    if flags is not None and "bonus_video" not in flags:
                        flags.append("bonus_video")
            ctx.rows.extend(new_rows)
        ctx.stats.collection_rows_generated += max(0, len(ctx.rows) - before_len)
        return ctx.check_cancel()

    ctx.stats.singles_seen += 1
    ctx.rows.extend(
        _plan_single(ctx.cfg, folder, videos[0], ctx.tmdb, ctx.log, should_cancel=ctx.should_cancel, **ctx.v2_kwargs)
    )
    return ctx.check_cancel()


def _merge_local_candidate_into_ctx(
    ctx: _PlanLibraryContext, local: "LocalCandidate"
) -> None:
    """Rejoue les buckets locaux d'un LocalCandidate sur ctx.stats (Phase 2).

    VO-B : iter_videos a tourne en Phase 1 avec un bucket prive (thread-safe).
    On reapplique ici les compteurs `ignores_par_raison` sur `ctx.stats` dans
    l'ordre original (1..N) pour preserver la semantique des deltas SCAN-1
    (cf. _filter_dossiers_phase). Aucun effet si bucket vide.
    """
    if local.ignores_par_raison:
        bucket = ctx.stats.analyse_ignores_par_raison
        for reason, count in local.ignores_par_raison.items():
            if not count:
                continue
            bucket[reason] = int(bucket.get(reason, 0)) + int(count)
    # Replay des erreurs eventuelles en logs Phase 2 (ordre 1..N preserve).
    for msg in local.errors:
        ctx.log("WARN", msg)


def _filter_dossiers_phase(ctx: _PlanLibraryContext) -> None:
    """Phase 2 : itere sur les dossiers candidats, applique le cache incremental,
    classe chaque dossier (TV/root/single+extras/collection/single) et genere les
    PlanRows correspondantes via les helpers _plan_*.

    Met a jour ctx.rows, ctx.stats, ctx.folders_seen_for_prune, ctx.video_paths_seen,
    ctx.scanned_total en place.

    VO-B refactor : si `cfg.scan_max_workers > 1`, la sous-phase locale
    (iter_videos scandir + collect_non_video_extensions) est pre-calculee en
    parallele via ThreadPoolExecutor. La boucle Phase 2 reste sequentielle
    (TMDb / SQLite / progress UI / stats merge en ordre 1..N strict). Pour
    `scan_max_workers <= 1` (default), comportement strictement identique a
    l'historique : pas de pool cree, iter_videos appele inline.
    """
    # Phase 2 — analyse : total fixe, la barre de progression est maintenant deterministe.
    discover_total = len(ctx.candidate_folders)

    # VO-B Phase 1 : pre-extraction parallele optionnelle (videos +
    # non_video_exts + ignores_par_raison locaux). Pour max_workers=1 retourne
    # immediatement une liste vide -> fallback inline historique en Phase 2.
    max_workers = resolve_scan_max_workers(ctx.cfg)
    pre_extracted: List[Optional[LocalCandidate]] = []
    if max_workers > 1 and discover_total > 1:
        pre_extracted = parallel_extract_local_candidates(
            ctx.candidate_folders,
            ctx.cfg,
            max_workers=max_workers,
            should_cancel=ctx.should_cancel,
        )
        _log.info(
            "scan: VO-B phase 1 parallele = %d candidates (workers=%d)",
            len(pre_extracted),
            max_workers,
        )

    for idx, folder in enumerate(ctx.candidate_folders, start=1):
        # VN-E.3 : pause cooperative AVANT cancel check pour que le worker se
        # mette en sommeil au plus tot. wait_while_paused retourne True si une
        # cancellation est intervenue pendant la pause -> on sort de la boucle.
        if ctx.wait_while_paused():
            break
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

        # SCAN-1 : on capture l'etat des compteurs detailles AVANT iter_videos pour
        # pouvoir distinguer la contribution de CE dossier (utile au diagnostic
        # quand videos=[] et qu'on doit savoir pourquoi precisement).
        ignores_par_raison_before = dict(ctx.stats.analyse_ignores_par_raison or {})

        # VO-B : 2 chemins possibles pour obtenir `videos` + `non_video_exts`.
        # - Phase 1 parallele OFF (default, max_workers<=1) : appel inline a
        #   iter_videos avec stats=ctx.stats, exactement comme avant le refactor.
        # - Phase 1 parallele ON : reutilisation du LocalCandidate pre-extrait,
        #   et replay des compteurs locaux sur ctx.stats dans l'ordre 1..N.
        local_cand: Optional[LocalCandidate] = None
        if pre_extracted and (idx - 1) < len(pre_extracted):
            local_cand = pre_extracted[idx - 1]

        if local_cand is not None:
            # Rejoue les ignores_par_raison du worker sur ctx.stats (ordre stable).
            _merge_local_candidate_into_ctx(ctx, local_cand)
            videos = local_cand.videos
            # _collect_non_video_extensions deja calcule en Phase 1 si videos=[].
            non_video_exts_precomputed = local_cand.non_video_exts
        else:
            # Code-path sequentiel historique : iter_videos inline, stats=ctx.stats.
            # SCAN-1 : passage de stats=ctx.stats pour categoriser chaque rejet
            # (extension hors liste / taille < min / nom suspect / erreur stat) au lieu
            # d'incrementer aveuglement 'ignore_non_supporte'. Utilise cfg.min_video_bytes
            # si configure (Phase 3 du plan), sinon core_mod.MIN_VIDEO_BYTES (10MB).
            _cfg_min = getattr(ctx.cfg, "min_video_bytes", None)
            _effective_min_bytes = int(_cfg_min) if _cfg_min is not None else core_mod.MIN_VIDEO_BYTES
            videos = core_mod.iter_videos(
                ctx.cfg,
                folder,
                min_video_bytes=_effective_min_bytes,
                stats=ctx.stats,
            )
            non_video_exts_precomputed = None

        if not videos:
            # SCAN-1 : second passage diagnostic. iter_videos a deja categorise via
            # stats= les rejets (ignore_extension, ignore_nom_suspect, ignore_taille_min,
            # ignore_scandir_error). On calcule ici le delta pour alimenter les
            # compteurs dedies films_rejected_* exposes au dashboard 'Diagnostic scan'.
            ignores_par_raison_after = dict(ctx.stats.analyse_ignores_par_raison or {})

            def _delta(reason: str) -> int:
                return int(ignores_par_raison_after.get(reason, 0)) - int(
                    ignores_par_raison_before.get(reason, 0)
                )

            delta_ext = _delta("ignore_extension")
            delta_size = _delta("ignore_taille_min")
            delta_name = _delta("ignore_nom_suspect")
            delta_scandir = _delta("ignore_scandir_error")
            if delta_ext > 0 and hasattr(ctx.stats, "films_rejected_ext"):
                ctx.stats.films_rejected_ext = int(ctx.stats.films_rejected_ext or 0) + delta_ext
            if delta_size > 0 and hasattr(ctx.stats, "films_rejected_size"):
                ctx.stats.films_rejected_size = int(ctx.stats.films_rejected_size or 0) + delta_size
            if delta_name > 0 and hasattr(ctx.stats, "films_rejected_name"):
                ctx.stats.films_rejected_name = int(ctx.stats.films_rejected_name or 0) + delta_name
            if delta_scandir > 0 and hasattr(ctx.stats, "folders_rejected_scandir_error"):
                ctx.stats.folders_rejected_scandir_error = int(
                    ctx.stats.folders_rejected_scandir_error or 0
                ) + delta_scandir

            # ITER15 #1 (2026-06-10) : `ignore_non_supporte` est le compteur
            # ROLLUP DOSSIER ("aucun fichier video exploitable", cf. core.py L1365
            # et UI dashboard "format non supporte"). Les deltas ci-dessus sont
            # des compteurs FILE-level qui s'additionnent independamment. Quand
            # `videos == []`, on a toujours un dossier sans video exploitable :
            # on bump donc systematiquement ignore_non_supporte. La regression
            # vient de 198a33a (fix SCAN-1 v166) qui n'incrementait ce compteur
            # que si AUCUN rejet detaille — cassant alors le breakdown
            # extensions (test_plan_library_collects_ignored_extensions_breakdown
            # passait de >=1 a 0 pour les dossiers de 'bruit' txt/jpg/nfo).
            core_mod._stats_add_ignore(ctx.stats, "ignore_non_supporte")

            # Inventaire des extensions presentes (pour bandeau diagnostic UI).
            # VO-B : reutilise le calcul Phase 1 si dispo, evite un 2e scandir NAS.
            if non_video_exts_precomputed is not None:
                non_video_exts_iter = non_video_exts_precomputed.items()
            else:
                non_video_exts_iter = core_mod._collect_non_video_extensions(ctx.cfg, folder).items()
            for ext, count in non_video_exts_iter:
                ctx.stats.analyse_ignores_extensions[ext] = int(
                    ctx.stats.analyse_ignores_extensions.get(ext, 0)
                ) + int(count)
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
    # QW07 : repercute les raisons agregees (emises par discover_candidate_folders /
    # scan_helpers._walk) sur les compteurs dedies du dashboard 'Diagnostic scan'.
    # Sans ce report, folders_rejected_underscore et folders_rejected_depth
    # affichaient systematiquement 0 alors que la raison etait bien tracee.
    raisons = dict(ctx.stats.analyse_ignores_par_raison or {})
    if hasattr(ctx.stats, "folders_rejected_underscore"):
        ctx.stats.folders_rejected_underscore = int(
            raisons.get("ignore_prefix_underscore", 0)
        )
    if hasattr(ctx.stats, "folders_rejected_depth"):
        ctx.stats.folders_rejected_depth = int(
            raisons.get("ignore_profondeur_max", 0)
        )
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
    should_pause: Optional[Callable[[], bool]] = None,
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

    VN-E.3 : `should_pause` est interroge dans `_filter_dossiers_phase` pour
    suspendre proprement la boucle entre 2 dossiers tant que le flag est pose
    (cf JobRunner._should_pause_factory). La cancellation prevaut sur la pause.
    """

    ctx = _PlanLibraryContext(
        cfg=cfg,
        tmdb=tmdb,
        log=log,
        progress=progress,
        should_cancel=should_cancel,
        should_pause=should_pause,
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
