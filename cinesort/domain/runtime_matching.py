"""Scoring runtime film vs TMDb, edition-aware (Phase 6.1).

Compare la duree d'un film (en minutes) au runtime TMDb, en ajustant la
tolerance selon l'edition detectee (Director's Cut, Extended Edition, etc.).
Retourne un bonus de confidence et un warning flag eventuel.

Source duree (file_runtime_min) :
- Phase 6.1 actuelle : NFO runtime parsed (nfo.runtime).
- Phase 6.1.b (futur) : probe.duration_s / 60 si cache probe dispo.

Logique :
- delta < 3 min : match parfait                 -> +20, pas de warning
- delta < tolerance edition (5 ou 15 min)       -> +10, pas de warning
- delta < 30 min : zone grise                   ->   0, pas de warning
- delta >= 30 min : franc mismatch              -> -25, warning

La tolerance edition reflete le fait qu'une version "Director's Cut" peut
durer 15 min de plus que la version theatrique stockee par TMDb.
"""

from __future__ import annotations

from typing import Optional, Tuple

# Tolerance standard sans edition detectee : 5 min couvre les arrondis
# (TMDb arrondit a la minute, NFO/probe peuvent diverger de quelques sec).
_RUNTIME_TOLERANCE_THEATRICAL = 5

# Tolerance elargie quand une edition longue est detectee : 15 min absorbe
# le delta theorique de la Director's Cut/Extended (+15 a +30 min).
_RUNTIME_TOLERANCE_EDITION = 15

# Seuil du franc mismatch : au-dela, on flag.
_RUNTIME_MISMATCH_THRESHOLD = 30

# Bonus/penalty applique a la confidence (clamp [0, 100] cote appelant).
_BONUS_EXACT_MATCH = 20
_BONUS_SOFT_MATCH = 10
_PENALTY_MISMATCH = -25

# Editions qui justifient une tolerance elargie (durent significativement
# plus longtemps que la version theatricale TMDb).
_EXTENDED_EDITIONS = {
    "director's cut",
    "directors cut",
    "extended",
    "extended cut",
    "extended edition",
    "ultimate cut",
    "ultimate edition",
    "final cut",
    "special edition",
    "criterion",
    "criterion edition",
    "criterion collection",
}

# Warning flag pose dans warning_flags quand le delta est franc.
WARN_RUNTIME_MISMATCH = "runtime_mismatch_likely_wrong_film"


def _is_extended_edition(edition_label: Optional[str]) -> bool:
    """Retourne True si l'edition justifie une tolerance elargie."""
    if not edition_label:
        return False
    return edition_label.strip().lower() in _EXTENDED_EDITIONS


def score_runtime_delta(
    file_runtime_min: Optional[float],
    tmdb_runtime_min: Optional[int],
    edition_label: Optional[str] = None,
) -> Tuple[int, Optional[str]]:
    """Compare la duree fichier vs TMDb runtime et retourne (bonus, warning).

    Args:
        file_runtime_min: Duree du fichier en minutes (None si indisponible).
        tmdb_runtime_min: Runtime TMDb en minutes (None si indisponible).
        edition_label: Label edition canonique (extract_edition()) ou None.

    Returns:
        (bonus_points, warning_flag_or_None) :
        - (0, None) si donnees manquantes (no-op).
        - (+20, None) si delta < 3 min.
        - (+10, None) si delta < tolerance (5 ou 15 min selon edition).
        - (0, None) si delta < 30 min (zone grise).
        - (-25, WARN_RUNTIME_MISMATCH) si delta >= 30 min.
    """
    if file_runtime_min is None or tmdb_runtime_min is None:
        return 0, None
    try:
        file_min = float(file_runtime_min)
        tmdb_min = int(tmdb_runtime_min)
    except (TypeError, ValueError):
        return 0, None
    if file_min <= 0 or tmdb_min <= 0:
        return 0, None

    delta = abs(file_min - tmdb_min)
    tolerance = _RUNTIME_TOLERANCE_EDITION if _is_extended_edition(edition_label) else _RUNTIME_TOLERANCE_THEATRICAL

    if delta < 3:
        return _BONUS_EXACT_MATCH, None
    if delta < tolerance:
        return _BONUS_SOFT_MATCH, None
    if delta < _RUNTIME_MISMATCH_THRESHOLD:
        return 0, None
    return _PENALTY_MISMATCH, WARN_RUNTIME_MISMATCH
