"""Runtime cross-check post-plan via probe (Phase 6.1.b — extension de Phase 6.1).

Etend la Phase 6.1 (cross-check NFO vs TMDb runtime, in-line dans
`_build_resolved_row`) au cas ou il n'y a PAS de NFO disponible (~60-70% du
corpus typique). Source duree : `probe.duration_s` via ProbeService.

Strategie post-process (alignee sur OMDb Phase 6.2) :
- Iterate sur les PlanRows
- Skip si nfo_runtime existe SAUF si phase 6.1 in-line a pose un
  runtime_mismatch : dans ce cas le probe (duree MESUREE) reconcilie le flag,
  car le NFO peut declarer un autre cut que le fichier reel (H5).
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

from cinesort.domain.runtime_matching import (
    WARN_RUNTIME_MISMATCH,
    _PENALTY_MISMATCH,
    score_runtime_delta,
)

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

    # Lazy intentionnel : tests patchent `cinesort.infra.probe.ProbeService`
    # au niveau du module source (pas du re-import client). Top-level
    # casserait 4 tests CrossCheckRowsWithProbeTests dans test_runtime_probe_check.py.
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

        # H5 : la duree MESUREE par le probe fait autorite sur la duree DECLAREE
        # par le NFO. Phase 6.1 in-line a deja score les rows AVEC nfo_runtime a
        # partir du NFO ; on ne re-verifie via probe QUE si elle a pose un
        # runtime_mismatch -- un NFO annoncant un autre cut (ex. 95 min) que le
        # fichier reel (ex. 142 min = TMDb) produit un faux positif bloquant.
        # Les rows sans ce flag restent intactes (pas de double comptage du bonus).
        reconciling_nfo_mismatch = False
        if getattr(row, "nfo_runtime", None):
            existing_flags = getattr(row, "warning_flags", None) or []
            if WARN_RUNTIME_MISMATCH not in existing_flags:
                continue
            reconciling_nfo_mismatch = True

        # Skip rows deja tres confiantes (sauf reconciliation d'un faux mismatch)
        confidence = int(getattr(row, "confidence", 0) or 0)
        if confidence >= _CONFIDENCE_SKIP_THRESHOLD and not reconciling_nfo_mismatch:
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

        if reconciling_nfo_mismatch:
            # Phase 6.1 a pose un runtime_mismatch (-25) sur la foi du NFO.
            if warning:
                # Le probe (mesure) confirme AUSSI le mismatch -> flag justifie,
                # deja pose, on ne re-penalise pas.
                n_mismatch += 1
                continue
            # Le probe contredit le NFO : le fichier reel colle a TMDb -> le
            # mismatch etait un FAUX POSITIF. On retire le flag et on annule la
            # penalite NFO (-_PENALTY_MISMATCH = +25), puis on applique le bonus mesure.
            #
            # Defaut 3 (mineur, connu, erre vers le HAUT) : si la penalite NFO -25
            # avait ete clampee a 0 (confidence de base < 25 avant phase 6.1), on
            # sur-restaure de la difference. Non corrige ici : la base pre-penalite
            # n'est pas memorisee sur la row (elle est posee dans _build_resolved_row,
            # hors de ce module) -> impossible sans toucher d'autres fichiers.
            flags = getattr(row, "warning_flags", None)
            if flags and WARN_RUNTIME_MISMATCH in flags:
                flags.remove(WARN_RUNTIME_MISMATCH)
            reconciled_confidence = max(0, min(100, confidence - _PENALTY_MISMATCH + bonus))
            row.confidence = reconciled_confidence
            # La confidence remonte (souvent 90-100) : re-synchroniser le label,
            # sinon une row reconciliee garde label="low" (badge faux + review count gonfle).
            if hasattr(row, "confidence_label"):
                from cinesort.domain.confidence_thresholds import confidence_label  # noqa: PLC0415

                row.confidence_label = confidence_label(reconciled_confidence)
            if bonus >= 20:
                n_full_match += 1
            elif bonus > 0:
                n_soft_match += 1
            continue

        if bonus == 0 and not warning:
            # Zone grise, pas de modification
            continue

        new_confidence = max(0, min(100, confidence + bonus))
        row.confidence = new_confidence
        # Meme re-synchro que la branche de reconciliation ci-dessus : la
        # confidence bouge (bonus/malus probe), donc le label doit suivre, sinon
        # une row remontee garde un label perime (badge faux + review count gonfle).
        if hasattr(row, "confidence_label"):
            from cinesort.domain.confidence_thresholds import confidence_label  # noqa: PLC0415

            row.confidence_label = confidence_label(new_confidence)

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
