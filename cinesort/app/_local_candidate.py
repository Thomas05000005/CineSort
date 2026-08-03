"""Pre-extraction locale parallelisable pour le scan de la bibliotheque.

VO-B refactor (v7.8.0+) — encapsule la portion thread-safe de
`_filter_dossiers_phase` (iter_videos scandir + collect_non_video_extensions)
dans une fonction pure `extract_local_candidate`, alimentee par un
ThreadPoolExecutor optionnel (cf. `_resolve_scan_max_workers`).

Constraintes :
  - Aucune mutation de structure partagee (ctx.stats / ctx.rows / scan_index).
  - Aucun appel TMDb / SQLite (sortis de Phase 1).
  - Backward compat stricte : max_workers=1 garde le code-path sequentiel
    historique sans creer de pool (cf. `_filter_dossiers_phase`).

Voir docs/internal/VO_B_ANALYSIS.md pour la cartographie complete.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import cinesort.domain.core as core_mod

logger = logging.getLogger(__name__)


# Cap dur pour eviter d'enfler un pool inutilement.
_SCAN_PARALLEL_MAX_WORKERS_CAP = 32


@dataclass
class _StatsBucket:
    """Bucket local par worker pour accumuler les rejets `iter_videos` sans
    muter `ctx.stats` (thread-safety). Re-joue les compteurs en Phase 2."""

    analyse_ignores_par_raison: Dict[str, int] = field(default_factory=dict)


@dataclass
class LocalCandidate:
    """Resultat de la pre-extraction locale d'un dossier candidat.

    Tous les champs sont purs (Path, list, dict primitifs). Aucun pointeur
    vers ctx, scan_index, tmdb. Peut etre serialise / passe entre threads.
    """

    folder: Path
    # Resultat de core_mod.iter_videos avec un bucket stats local.
    videos: List[Path]
    # Inventaire ext->count des fichiers non-video (utile uniquement si
    # videos=[] pour le bandeau diagnostic UI).
    non_video_exts: Dict[str, int]
    # Compteurs locaux d'ignores accumules par iter_videos (cle = raison,
    # ex. 'ignore_extension', 'ignore_taille_min', 'ignore_nom_suspect',
    # 'ignore_scandir_error'). Doivent etre rejoues en Phase 2 sur ctx.stats.
    ignores_par_raison: Dict[str, int]
    # Erreurs eventuelles capturees pendant la pre-extraction (rejouees via
    # ctx.log en Phase 2 pour conserver un ordre chronologique stable).
    errors: List[str] = field(default_factory=list)


def extract_local_candidate(folder: Path, cfg: Any) -> LocalCandidate:
    """Pre-extraction locale d'un dossier candidat (pure, thread-safe).

    Effectue uniquement les operations sur le filesystem local :
      - `iter_videos` (scandir) avec un bucket stats prive
      - `collect_non_video_extensions` si la branche `videos=[]` peut etre prise

    Aucun appel TMDb / SQLite / mutation de ctx. Les rejets et erreurs sont
    accumules dans des dicts locaux a rejouer en Phase 2 sequentielle.

    Args:
        folder: chemin du dossier candidat (issu de `discover_candidate_folders`).
        cfg: `Config` normalisee (lecture seule).

    Returns:
        `LocalCandidate` avec videos, non_video_exts, ignores_par_raison.
    """
    bucket = _StatsBucket()
    errors: List[str] = []

    # Helper minimal qui mime stats.analyse_ignores_par_raison (cf.
    # scan_helpers._bump_stats_reject). Permet a iter_videos d'accumuler
    # sans toucher a Stats partage.
    class _LocalStats:
        __slots__ = ("analyse_ignores_par_raison",)

        def __init__(self) -> None:
            self.analyse_ignores_par_raison = bucket.analyse_ignores_par_raison

    local_stats = _LocalStats()

    # Resolution du seuil min_video_bytes identique a la logique
    # _filter_dossiers_phase (cf. plan_support L758-L759).
    cfg_min = getattr(cfg, "min_video_bytes", None)
    effective_min_bytes = int(cfg_min) if cfg_min is not None else core_mod.MIN_VIDEO_BYTES

    try:
        videos = core_mod.iter_videos(
            cfg,
            folder,
            min_video_bytes=effective_min_bytes,
            stats=local_stats,
        )
    except (OSError, PermissionError, FileNotFoundError, ValueError) as exc:
        errors.append(f"iter_videos failed on {folder}: {exc}")
        videos = []

    non_video_exts: Dict[str, int] = {}
    if not videos:
        # Inventaire utile uniquement quand `videos=[]` (branche diagnostic).
        try:
            non_video_exts = core_mod._collect_non_video_extensions(cfg, folder)
        except (OSError, PermissionError, FileNotFoundError, ValueError) as exc:
            errors.append(f"collect_non_video_extensions failed on {folder}: {exc}")
            non_video_exts = {}

    return LocalCandidate(
        folder=folder,
        videos=videos,
        non_video_exts=non_video_exts,
        ignores_par_raison=dict(bucket.analyse_ignores_par_raison),
        errors=errors,
    )


def resolve_scan_max_workers(cfg: Any) -> int:
    """Resout le nombre de workers pour Phase 1 parallele.

    Lit `cfg.scan_max_workers` (entier optionnel, default = 1 = sequentiel
    strict). Clampe a [1, _SCAN_PARALLEL_MAX_WORKERS_CAP].

    - `1` (default) : backward compat stricte, pas de pool cree (cf. branche
      `if max_workers == 1` dans `_filter_dossiers_phase`).
    - `>= 2` : ThreadPoolExecutor active.
    - `0` ou invalide : tombe sur 1 (sequentiel).

    Args:
        cfg: `Config` normalisee.

    Returns:
        Entier >= 1.
    """
    raw = getattr(cfg, "scan_max_workers", None)
    if raw is None:
        return 1
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 1
    if n <= 0:
        return 1
    return min(n, _SCAN_PARALLEL_MAX_WORKERS_CAP)


def parallel_extract_local_candidates(
    folders: List[Path],
    cfg: Any,
    *,
    max_workers: int,
    should_cancel: Optional[callable] = None,
) -> List[LocalCandidate]:
    """Pre-extraction parallelisee de N dossiers candidats, ordre preserve.

    Patron `futures_in_order[idx]` : ordre 1..N strict garanti via
    `pool.submit` + `fut.result()` (PAS `as_completed`), pour preserver
    l'ordre des emits `ctx.progress` en Phase 2.

    Fast path : `max_workers <= 1` ou `len(folders) <= 1` -> execution
    sequentielle directe (pas de pool cree).

    Args:
        folders: liste des dossiers candidats (issus de discover_candidate_folders).
        cfg: Config normalisee.
        max_workers: taille du pool (resolue via `resolve_scan_max_workers`).
        should_cancel: callback optionnel pour annulation cooperative. Si True,
            les futures non encore demarrees sont annulees et les positions
            non extraites recoivent un placeholder vide.

    Returns:
        Liste de `LocalCandidate` de meme longueur et meme ordre que `folders`.
    """
    n = len(folders)
    if n == 0:
        return []

    workers = max(1, int(max_workers))

    # Fast path / backward compat : sequentiel, jamais de ThreadPoolExecutor.
    if workers <= 1 or n <= 1:
        out: List[LocalCandidate] = []
        for folder in folders:
            if should_cancel is not None:
                try:
                    if should_cancel():
                        out.append(_empty_placeholder(folder))
                        continue
                except Exception:  # noqa: BLE001
                    pass
            out.append(extract_local_candidate(folder, cfg))
        return out

    # Branche parallele : ThreadPoolExecutor. Le GIL est libere pendant
    # os.scandir / stat sur NAS SMB (I/O bound), gain ~7x sur Phase 1.
    from concurrent.futures import ThreadPoolExecutor

    results: List[Optional[LocalCandidate]] = [None] * n
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="scan-local")
    futures = []
    try:
        for folder in folders:
            futures.append(executor.submit(extract_local_candidate, folder, cfg))

        for idx, fut in enumerate(futures):
            # Cancel cooperative : si demande, on annule les futures restantes
            # et on remplit le reste avec des placeholders vides.
            if should_cancel is not None:
                try:
                    cancelled = bool(should_cancel())
                except Exception:  # noqa: BLE001
                    cancelled = False
                if cancelled:
                    for remaining in futures[idx:]:
                        remaining.cancel()
                    for j in range(idx, n):
                        results[j] = _empty_placeholder(folders[j])
                    break
            try:
                results[idx] = fut.result()
            except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
                logger.warning("extract_local_candidate failed for %s: %s", folders[idx], exc)
                placeholder = _empty_placeholder(folders[idx])
                placeholder.errors.append(f"extract_local_candidate: {exc}")
                results[idx] = placeholder
    finally:
        cancel_futures = False
        if should_cancel is not None:
            try:
                cancel_futures = bool(should_cancel())
            except Exception:  # noqa: BLE001
                cancel_futures = False
        executor.shutdown(wait=not cancel_futures, cancel_futures=cancel_futures)

    # Final sweep pour s'assurer qu'aucun slot ne reste None (defensif).
    for idx, item in enumerate(results):
        if item is None:
            results[idx] = _empty_placeholder(folders[idx])
    return [r for r in results if r is not None]


def _empty_placeholder(folder: Path) -> LocalCandidate:
    """Placeholder neutre (videos=[], pas d'ignores) utilise sur cancellation."""
    return LocalCandidate(
        folder=folder,
        videos=[],
        non_video_exts={},
        ignores_par_raison={},
        errors=[],
    )


__all__ = [
    "LocalCandidate",
    "extract_local_candidate",
    "parallel_extract_local_candidates",
    "resolve_scan_max_workers",
]
