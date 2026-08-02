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

from cinesort.domain.path_utils import windows_safe
from cinesort.domain.runtime_matching import (
    WARN_RUNTIME_MISMATCH,
    _PENALTY_MISMATCH,
    score_runtime_delta,
)

logger = logging.getLogger(__name__)


def _resync_confidence_fields(row: Any, new_confidence: int) -> None:
    """Realigne les champs derives de la confidence (label + 1re phrase de notes).

    Import LAZY du helper partage : `omdb_cross_check` tire `OmdbClient` (donc
    `requests`) au niveau module, or ce module-ci ne depend que de `domain/`.
    L'implementation reste unique — deux copies divergeraient au 1er changement
    de format de `build_plan_note`.
    """
    from cinesort.app.omdb_cross_check import resync_confidence_fields  # noqa: PLC0415

    resync_confidence_fields(row, new_confidence)


# Seuil : on ne re-check pas les rows deja tres confiantes
_CONFIDENCE_SKIP_THRESHOLD = 95

# AUDIT F27 (revue R1) : nombre max d'ids concurrents interroges quand le chosen
# est ambigu. Borne le cout TMDb (get_movie_runtime est cache-first mais peut
# taper le reseau au premier passage). Au-dela, on RENONCE : conclure sur un
# echantillon d'ids ne prouverait rien.
_MAX_AMBIGUOUS_IDS = 4


def _candidate_tmdb_id(candidate: Any) -> Optional[int]:
    """tmdb_id d'un candidat sous forme d'int, ou None si absent/illisible."""
    raw = getattr(candidate, "tmdb_id", None)
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _get_chosen_tmdb_id(row: Any) -> Optional[int]:
    """Retrouve le tmdb_id du candidate chosen depuis row.candidates.

    Strategie (AUDIT F24/F27) :
    1. Match (titre, annee). Le titre du candidat est compare BRUT *et* passe par
       `windows_safe`, parce que `proposed_title` a deja ete sanitize a la
       construction de la row (plan_support_replan.py:331). Sans ce second essai,
       TOUT titre contenant un caractere interdit NTFS (`:`, `?`, `"`, ...) ratait
       le match — y compris le chosen lui-meme — et on tombait dans le fallback.
    2. Repli : si les candidats de la MEME annee ne portent qu'UN SEUL tmdb_id
       distinct, c'est forcement lui.
    3. Repli : si TOUS les candidats ne portent qu'UN SEUL tmdb_id distinct, lui aussi.
    4. Sinon None. L'ancien fallback "premier candidate avec un tmdb_id" devinait
       dans l'ordre d'insertion (NFO puis TMDb tries par score BRUT), qui diverge
       du chosen de pick_best_candidate (bonus consensus / disambiguation) : un id
       faux vaut un runtime_mismatch -25 A TORT (ou un bonus indu) sur une row
       correcte, alors que ne rien faire ne coute qu'un bonus manque.
    """
    title = str(getattr(row, "proposed_title", "") or "").strip()
    year = getattr(row, "proposed_year", None)
    candidates = getattr(row, "candidates", None) or []

    # 1. Match titre + annee (titre brut OU sanitize comme proposed_title)
    for c in candidates:
        c_tmdb = _candidate_tmdb_id(c)
        if c_tmdb is None or getattr(c, "year", None) != year:
            continue
        c_title = str(getattr(c, "title", "") or "").strip()
        if c_title == title or windows_safe(c_title) == title:
            return c_tmdb

    id_year_pairs = [(_candidate_tmdb_id(c), getattr(c, "year", None)) for c in candidates]

    # 2. Un seul tmdb_id distinct parmi les candidats de la meme annee
    same_year = {cid for cid, cyear in id_year_pairs if cid is not None and cyear == year}
    if len(same_year) == 1:
        return next(iter(same_year))

    # 3. Un seul tmdb_id distinct, toutes annees confondues
    any_ids = {cid for cid, _cyear in id_year_pairs if cid is not None}
    if len(any_ids) == 1:
        return next(iter(any_ids))

    # 4. Ambiguite reelle : on ne devine pas.
    return None


def _ambiguous_tmdb_ids(row: Any) -> List[int]:
    """Ids TMDb distincts des candidats quand `_get_chosen_tmdb_id` n'a pas tranche.

    AUDIT F27 (revue R1). Le `return None` sur ambiguite ferme bien le faux
    positif (id devine -> runtime_mismatch -25 A TORT) mais il fermait AUSSI la
    detection : plus aucun `runtime_mismatch` n'etait posable sur ces rows. Or ce
    flag appartient a `_CONFLICT_FLAGS` donc a `_AUTO_BLOCKING`
    (run_read_support.py) : une row MAL identifiee qui etait bloquee hors
    auto-approbation redevenait auto-approuvable, et l'apply la deplacait.

    On rend donc les ids concurrents pour permettre un verdict NON devinatoire :
    si la duree mesuree diverge de TOUS ces candidats, le mismatch est certain
    quel que soit le bon, et le flag peut etre pose sans rien deviner. L'ordre
    d'insertion est preserve (stabilite du log) et les doublons sont retires.

    La liste n'est PAS tronquee : "tous divergent" calcule sur un sous-ensemble
    ne prouverait rien (l'id ecarte pourrait etre le bon et coller a la duree
    mesuree). C'est l'appelant qui renonce quand la liste depasse
    `_MAX_AMBIGUOUS_IDS`, plutot que de conclure sur un echantillon.
    """
    seen: List[int] = []
    for c in getattr(row, "candidates", None) or []:
        cid = _candidate_tmdb_id(c)
        if cid is None or cid in seen:
            continue
        seen.append(cid)
    return seen


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
        ambiguous_ids: List[int] = []
        if not tmdb_id:
            # AUDIT F27 (revue R1) : plutot que d'abandonner la row, on interroge
            # les ids concurrents pour pouvoir conclure SANS deviner (cf infra).
            ambiguous_ids = _ambiguous_tmdb_ids(row)
            if not 2 <= len(ambiguous_ids) <= _MAX_AMBIGUOUS_IDS:
                # < 2 : rien a arbitrer (deja traite par les replis ci-dessus).
                # > _MAX : on renonce au lieu de payer N requetes TMDb pour une
                # row deja tres douteuse.
                continue

        # TMDb runtime(s) — un seul id si le chosen est resolu, sinon tous les
        # concurrents (cache-first cote TmdbClient).
        tmdb_runtimes: List[int] = []
        for candidate_id in [tmdb_id] if tmdb_id else ambiguous_ids:
            try:
                candidate_runtime = tmdb.get_movie_runtime(int(candidate_id))
            except (AttributeError, TypeError, ValueError):
                candidate_runtime = None
            if candidate_runtime:
                tmdb_runtimes.append(int(candidate_runtime))
        if not tmdb_runtimes:
            continue
        if ambiguous_ids and len(tmdb_runtimes) < len(ambiguous_ids):
            # Un concurrent sans runtime connu : impossible de prouver que la
            # duree mesuree diverge de TOUS. On ne conclut pas (fail-closed).
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
        file_runtime_min = float(duration_s) / 60.0
        scored = [
            score_runtime_delta(
                file_runtime_min=file_runtime_min,
                tmdb_runtime_min=candidate_runtime,
                edition_label=edition_label,
            )
            for candidate_runtime in tmdb_runtimes
        ]
        if tmdb_id:
            bonus, warning = scored[0]
        else:
            # Mode AMBIGU, strictement fail-closed : on ne conclut QUE si la
            # duree mesuree diverge franchement de TOUS les candidats — le
            # mismatch est alors certain quel que soit le bon film, sans rien
            # deviner. Le sens inverse (tous convergent -> bonus) n'est
            # VOLONTAIREMENT pas implemente : remonter la confidence d'une row
            # dont l'identification est ambigue elargirait l'auto-approbation,
            # c'est-a-dire exactement le "bonus indu" que F27 fermait.
            if not all(candidate_warning for _b, candidate_warning in scored):
                continue
            bonus, warning = min(scored, key=lambda scored_pair: scored_pair[0])

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
            # La confidence remonte (souvent 90-100) : re-synchroniser le label
            # ET la 1re phrase de `notes` (revue R1 : elle porte le meme couple en
            # toutes lettres, "Confiance LOW (40/100).", et restait perimee juste
            # a cote du nouveau badge). Sinon : badge faux + review count gonfle.
            _resync_confidence_fields(row, reconciled_confidence)
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
        # confidence bouge (bonus/malus probe), donc label ET notes doivent
        # suivre, sinon une row remontee garde des champs derives perimes
        # (badge faux + review count gonfle + note qui contredit le badge).
        _resync_confidence_fields(row, new_confidence)

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
