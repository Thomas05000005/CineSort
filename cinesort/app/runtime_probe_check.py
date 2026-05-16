"""Runtime cross-check post-plan via probe (Phase 6.1.b — extension de Phase 6.1).

Etend la Phase 6.1 (cross-check NFO vs TMDb runtime, in-line dans
`_build_resolved_row`) au cas ou il n'y a PAS de NFO disponible (~60-70% du
corpus typique). Source duree : `probe.duration_s` via ProbeService.

Strategie post-process (alignee sur OMDb Phase 6.2) :
- Iterate sur les PlanRows
- Skip si nfo_runtime existe (deja traite par phase 6.1 in-line)
- Skip si confidence deja >= 95 (deja tres confiant)
- Pour chaque row eligible : probe le fichier (cache lookup d'abord, ffprobe
  si miss) + recupere TMDb runtime + applique score_runtime_delta
- Modifie row.confidence et row.warning_flags in-place

Echec gracieux global : si store/probe indisponible ou film inaccessible,
on skip silencieusement sans bloquer le run.

Cf cinesort/domain/runtime_matching.py pour la logique score_runtime_delta.
Cf cinesort/app/omdb_cross_check.py pour le pattern post-process.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from cinesort.domain.runtime_matching import score_runtime_delta

logger = logging.getLogger(__name__)


# Seuil : on ne re-check pas les rows deja tres confiantes
_CONFIDENCE_SKIP_THRESHOLD = 95


def _get_chosen_tmdb_id(row: Any) -> Optional[int]:
    """Retrouve le tmdb_id du candidate chosen depuis row.candidates.

    Strategie :
    1. Match exact sur (proposed_title, proposed_year) + tmdb_id
    2. Fallback : premier candidate avec un tmdb_id
    """
    title = str(getattr(row, "proposed_title", "") or "").strip()
    year = getattr(row, "proposed_year", None)
    candidates = getattr(row, "candidates", None) or []

    # Match exact d'abord
    for c in candidates:
        c_tmdb = getattr(c, "tmdb_id", None)
        c_title = str(getattr(c, "title", "") or "").strip()
        c_year = getattr(c, "year", None)
        if c_tmdb and c_title == title and c_year == year:
            try:
                return int(c_tmdb)
            except (TypeError, ValueError):
                continue

    # Fallback : premier candidate avec tmdb_id
    for c in candidates:
        c_tmdb = getattr(c, "tmdb_id", None)
        if c_tmdb:
            try:
                return int(c_tmdb)
            except (TypeError, ValueError):
                continue

    return None


def cross_check_rows_with_probe(
    rows: List[Any],
    store: Any,
    settings: Dict[str, Any],
    tmdb: Any,
    *,
    log: Optional[Callable[[str, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    probe_settings: Optional[Dict[str, Any]] = None,
) -> int:
    """Cross-check les PlanRows sans nfo_runtime via probe.duration_s + TMDb runtime.

    Args:
        rows: PlanRows (modifie in-place via confidence + warning_flags)
        store: SQLiteStore pour le cache probe
        settings: settings effectives (pour probe_backend)
        tmdb: TmdbClient pour recuperer le runtime TMDb
        log: callback log optionnel
        should_cancel: callback cancellation optionnel
        probe_settings: settings probe explicites (sinon construits depuis settings)

    Returns:
        Nombre de rows verifiees (ayant fait un probe + TMDb call).
    """
    if not rows or not store or not tmdb:
        return 0

    try:
        from cinesort.infra.probe import ProbeService
    except ImportError as exc:
        logger.debug("runtime_probe_check: ProbeService indispo (%s)", exc)
        return 0

    try:
        probe = ProbeService(store)
    except (TypeError, ValueError) as exc:
        logger.debug("runtime_probe_check: ProbeService init failed (%s)", exc)
        return 0

    # Construit les probe_settings si non fournies
    if probe_settings is None:
        probe_settings = {
            "probe_backend": settings.get("probe_backend", "auto"),
            "probe_timeout_s": settings.get("probe_timeout_s", 30),
            "mediainfo_path": settings.get("mediainfo_path", ""),
            "ffprobe_path": settings.get("ffprobe_path", ""),
        }

    n_checked = 0
    n_full_match = 0
    n_soft_match = 0
    n_mismatch = 0
    n_no_data = 0

    for row in rows:
        if should_cancel and should_cancel():
            if log:
                log("INFO", f"Phase 6.1.b probe cross-check cancele apres {n_checked} films")
            break

        # Skip si NFO runtime deja traite par phase 6.1 in-line
        if getattr(row, "nfo_runtime", None):
            continue

        # Skip rows deja tres confiantes
        confidence = int(getattr(row, "confidence", 0) or 0)
        if confidence >= _CONFIDENCE_SKIP_THRESHOLD:
            continue

        # Resolve video path
        folder = str(getattr(row, "folder", "") or "")
        video = str(getattr(row, "video", "") or "")
        if not folder or not video:
            continue
        try:
            media_path = Path(folder) / video
            if not media_path.exists():
                continue
        except (OSError, ValueError):
            continue

        # Resolve tmdb_id pour fetcher runtime TMDb
        tmdb_id = _get_chosen_tmdb_id(row)
        if not tmdb_id:
            continue

        # TMDb runtime
        try:
            tmdb_runtime = tmdb.get_movie_runtime(int(tmdb_id))
        except (AttributeError, TypeError, ValueError):
            tmdb_runtime = None
        if not tmdb_runtime:
            continue

        # Probe (cache lookup en priorite, fallback ffprobe si miss)
        try:
            probe_result = probe.probe_file(media_path=media_path, settings=probe_settings)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            logger.debug("runtime_probe_check: probe_file failed for %s (%s)", media_path, exc)
            continue
        if not probe_result or not probe_result.get("ok"):
            continue
        normalized = probe_result.get("normalized") if isinstance(probe_result.get("normalized"), dict) else {}
        duration_s = normalized.get("duration_s")
        if not duration_s or float(duration_s) <= 0:
            n_no_data += 1
            continue

        # Apply runtime matching
        edition_label = getattr(row, "edition", None)
        bonus, warning = score_runtime_delta(
            file_runtime_min=float(duration_s) / 60.0,
            tmdb_runtime_min=int(tmdb_runtime),
            edition_label=edition_label,
        )

        n_checked += 1
        if bonus == 0 and not warning:
            # Zone grise, pas de modification
            continue

        new_confidence = max(0, min(100, confidence + bonus))
        row.confidence = new_confidence

        if warning:
            flags = getattr(row, "warning_flags", None)
            if flags is None:
                row.warning_flags = [warning]
            elif warning not in flags:
                flags.append(warning)
            n_mismatch += 1
        elif bonus >= 20:
            n_full_match += 1
        elif bonus > 0:
            n_soft_match += 1

    if log:
        log(
            "INFO",
            f"Phase 6.1.b probe cross-check : {n_checked} films verifies, "
            f"{n_full_match} match parfait, {n_soft_match} acceptable, "
            f"{n_mismatch} mismatch detectes, {n_no_data} sans duree probable",
        )

    return n_checked
