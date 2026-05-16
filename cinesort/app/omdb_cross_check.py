"""OMDb cross-check post-plan (Phase 6.2).

Apres `plan_multi_roots`, on parcourt les PlanRows avec confidence < seuil
configurable et on appelle OMDb pour valider/invalider le match TMDb. La
divergence pose un warning `omdb_disagree` ; la convergence boost la confidence.

Trade-off design :
- **Post-process** (vs in-line dans `_plan_item`) : evite la propagation
  d'OmdbClient a travers 4 niveaux de signatures et l'impact perf
  (rate-limit 1 req/s) qui aurait bloque le scan principal.
- **Title+year search** (vs IMDb id) : OMDb's `search_by_title` est moins
  precis qu'`find_by_imdb_id` mais marche meme sans NFO. Plus tard, on
  pourra prendre IMDb id du NFO en priorite.

Cf cinesort/infra/omdb_client.py pour le client.
Cf cinesort/ui/api/run_flow_support.py pour l'invocation.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional, Tuple

from cinesort.infra.omdb_client import OmdbClient, OmdbResult

logger = logging.getLogger(__name__)


# Warning flag pose en cas de divergence
WARN_OMDB_DISAGREE = "omdb_disagree"

# Bonus/malus appliques a la confidence
_BONUS_FULL_CONVERGENCE = 20  # title + year exacts
_BONUS_PARTIAL_CONVERGENCE = 5  # year exact mais title legerement different
_PENALTY_DIVERGENCE = -25  # title + year tous deux faux

# Tolerance annee pour "convergence partielle"
_YEAR_TOLERANCE = 1


def _normalize_title_for_compare(title: str) -> str:
    """Normalise un titre pour comparaison (lowercase, strip whitespace + punct)."""
    if not title:
        return ""
    # Lowercase + retirer caracteres non-alphanum (espace inclus)
    import re
    import unicodedata

    s = title.lower().strip()
    # Strip accents
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    # Retire articles + ponctuation
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def _compute_adjustment(
    chosen_title: str,
    chosen_year: Optional[int],
    omdb_result: OmdbResult,
) -> Tuple[int, Optional[str]]:
    """Retourne (bonus_confidence, warning_flag).

    Cas :
    - title+year tous deux match exact -> +20, no warning
    - year exact ET title proche (norm equal apres strip articles/punct) -> +20
    - year exact mais title different -> +5 (TMDb a peut-etre un titre traduit)
    - year ±1 ET title similaire -> +5 (delta possible : remaster, release date)
    - tout le reste -> -25 + warning omdb_disagree
    """
    if not omdb_result.year or not chosen_year:
        # OMDb sans annee : on ne peut pas comparer, no-op
        return 0, None

    norm_chosen = _normalize_title_for_compare(chosen_title)
    norm_omdb = _normalize_title_for_compare(omdb_result.title)
    title_match = bool(norm_chosen) and norm_chosen == norm_omdb

    year_diff = abs(omdb_result.year - chosen_year)
    year_exact = year_diff == 0
    year_close = year_diff <= _YEAR_TOLERANCE

    if title_match and year_exact:
        return _BONUS_FULL_CONVERGENCE, None
    if title_match and year_close:
        # Titre identique, annee differente d'1 max : convergence partielle
        return _BONUS_PARTIAL_CONVERGENCE, None
    if year_exact and not title_match:
        # Annee identique mais titre different : TMDb a peut-etre la traduction FR
        # et OMDb le titre original anglais. Convergence partielle.
        return _BONUS_PARTIAL_CONVERGENCE, None
    # Divergence franche : ni title ni year en commun
    return _PENALTY_DIVERGENCE, WARN_OMDB_DISAGREE


def cross_check_rows_with_omdb(
    rows: List[Any],
    omdb_client: OmdbClient,
    *,
    min_confidence_for_call: int = 90,
    log: Optional[Callable[[str, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> int:
    """Cross-check les PlanRows avec confidence basse contre OMDb.

    Modifie en place : ajuste `row.confidence` (clamp [0, 100]) et append le
    warning `omdb_disagree` a `row.warning_flags` en cas de divergence.

    Args:
        rows: liste de PlanRow (modifie en place)
        omdb_client: instance OmdbClient
        min_confidence_for_call: seuil sous lequel on appelle OMDb (default 90)
        log: callback de log optionnel
        should_cancel: callback de cancellation optionnel

    Returns:
        Nombre de rows qui ont ete cross-checkees (= ayant fait un appel OMDb).
    """
    if not rows or not omdb_client:
        return 0

    threshold = max(0, min(100, int(min_confidence_for_call or 90)))

    n_checked = 0
    n_converge = 0
    n_diverge = 0
    n_partial = 0
    n_no_response = 0

    for row in rows:
        if should_cancel and should_cancel():
            if log:
                log("INFO", f"OMDb cross-check cancele apres {n_checked} films")
            break

        confidence = getattr(row, "confidence", 0)
        if confidence >= threshold:
            continue

        title = str(getattr(row, "proposed_title", "") or "")
        year = getattr(row, "proposed_year", None)
        if not title or not year:
            continue

        try:
            omdb_result = omdb_client.search_by_title(title, int(year))
        except (ValueError, TypeError, OSError) as exc:
            logger.debug("omdb cross_check error for %r/%r: %s", title, year, exc)
            omdb_result = None

        n_checked += 1
        if omdb_result is None:
            n_no_response += 1
            continue

        bonus, warning = _compute_adjustment(title, year, omdb_result)
        new_confidence = max(0, min(100, confidence + bonus))
        row.confidence = new_confidence

        if warning:
            flags = getattr(row, "warning_flags", None)
            if flags is None:
                row.warning_flags = [warning]
            elif warning not in flags:
                flags.append(warning)
            n_diverge += 1
        elif bonus >= _BONUS_FULL_CONVERGENCE:
            n_converge += 1
        elif bonus > 0:
            n_partial += 1

    if log:
        log(
            "INFO",
            f"OMDb cross-check : {n_checked} appels, {n_converge} convergence forte, "
            f"{n_partial} partielle, {n_diverge} divergence, {n_no_response} no-response",
        )

    return n_checked
