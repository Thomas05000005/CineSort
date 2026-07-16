"""Runtime HARD filter (VN-D.3) — exclusion stricte des candidats TMDb.

Complement de `runtime_matching.py` (qui ne fait que pondérer la confidence) :
ce module **exclut** purement et simplement les candidats TMDb dont la duree
diverge trop du fichier reel, sauf si une edition longue est detectee
(Director's Cut, Extended, Ultimate, Uncut...).

Cas d'usage : audit L05/L01 du plan iridescent-weaving-sloth -- "Dune" sur un
fichier de 155 min matchait par erreur Dune 1984 (137 min) avec une similarite
textuelle eleveee + annee 1984 ambigue. Le scoring soft bonus de
`runtime_matching.score_runtime_delta` posait un warning mais ne supprimait
pas le candidat ; le user voyait quand meme le faux candidat propose.

Politique :
- delta_min = abs(file_runtime_min - candidate_runtime_min)
- Si delta_min > threshold_min ET pas d'edition longue detectee -> EXCLU
- Si delta_min > threshold_min AVEC edition longue -> CONSERVE + warning
- Si delta_min <= threshold_min -> CONSERVE (pas de modification, le scoring
  bonus existant de score_runtime_delta s'applique en aval)
- Si une des durees est manquante (probe FAILED, runtime TMDb absent) ->
  CONSERVE (le filtre ne peut pas trancher, on retombe sur l'algo existant)

Configurable via settings.runtime_hard_filter_enabled (default True) et
settings.runtime_hard_threshold_min (default 60) pour rollback rapide.
"""

from __future__ import annotations

from typing import Optional, Tuple

# Reuse le set d'editions longues defini en runtime_matching pour rester
# coherent : si on change la liste a un endroit, l'autre suit.
from cinesort.domain.runtime_matching import _EXTENDED_EDITIONS, _is_extended_edition

# Seuil par defaut : delta > 60 min est tres improbable meme pour une
# Extended Edition non flaggee. Au-dela on considere que c'est un autre film.
DEFAULT_RUNTIME_HARD_THRESHOLD_MIN = 60

# Warning pose quand un candidat est conserve uniquement grace a son edition flag.
WARN_RUNTIME_HARD_KEPT_VIA_EDITION = "runtime_hard_kept_via_edition_flag"

# Warning pose quand un candidat serait exclu par le delta MAIS la duree fichier
# vient d'une source DECLAREE (NFO), pas MESUREE (probe). Une duree declaree n'a
# pas autorite pour une exclusion dure (le NFO peut annoncer un autre cut que le
# fichier reel) : on conserve + on signale, la reconciliation probe tranchera.
WARN_RUNTIME_HARD_KEPT_DECLARED = "runtime_hard_kept_declared_runtime"

# Warning pose sur la PlanRow quand au moins un candidat a ete exclu par le
# filtre HARD (utile pour debug user en UI : "Pourquoi mon film n'a pas matche ?").
WARN_RUNTIME_HARD_EXCLUDED = "runtime_hard_filter_excluded_candidate"


def evaluate_runtime_hard_filter(
    file_runtime_min: Optional[float],
    candidate_runtime_min: Optional[int],
    edition_label: Optional[str] = None,
    *,
    enabled: bool = True,
    threshold_min: int = DEFAULT_RUNTIME_HARD_THRESHOLD_MIN,
    runtime_measured: bool = True,
) -> Tuple[bool, Optional[str]]:
    """Decide si un candidat TMDb doit etre EXCLU au regard de sa duree.

    Args:
        file_runtime_min: Duree fichier (probe.duration_s/60 ou nfo.runtime).
            None si probe FAILED -> filtre desactive (on conserve).
        candidate_runtime_min: Runtime TMDb du candidat. None si TMDb n'a pas
            de runtime -> filtre desactive pour ce candidat (on conserve).
        edition_label: Edition canonique detectee dans le nom du fichier
            (extract_edition()) ou None.
        enabled: Si False, filtre completement desactive (rollback rapide).
        threshold_min: Seuil au-dela duquel le delta est considere comme
            franc mismatch (default 60 min). Configurable via settings.
        runtime_measured: True si `file_runtime_min` a ete MESURE (cache probe)
            -> fait autorite, une divergence franche EXCLUT. False si la duree
            est DECLAREE (NFO) : le NFO peut annoncer un autre cut que le
            fichier reel, donc une divergence ne doit JAMAIS exclure durement
            -> conserve + warning, reconcilie plus tard par le probe (H5).

    Returns:
        (excluded, warning_flag) :
        - (False, None) : candidat conserve, pas de warning particulier
        - (False, WARN_RUNTIME_HARD_KEPT_VIA_EDITION) : delta > threshold
          MAIS edition longue detectee -> conserve avec warning
        - (False, WARN_RUNTIME_HARD_KEPT_DECLARED) : delta > threshold, pas
          d'edition, MAIS duree seulement DECLAREE (NFO) -> conserve + warning
        - (True, None) : candidat EXCLU (delta > threshold, pas d'edition, et
          duree MESUREE qui fait autorite)

    Note: ne touche pas a la confidence score. Le caller compose ce filtre
    avec `score_runtime_delta` (bonus +20 / penalty -25) pour les candidats
    conserves.
    """
    if not enabled:
        return False, None

    # Donnees manquantes -> on ne peut pas trancher, conserver
    if file_runtime_min is None or candidate_runtime_min is None:
        return False, None
    try:
        file_min = float(file_runtime_min)
        cand_min = int(candidate_runtime_min)
    except (TypeError, ValueError):
        return False, None
    if file_min <= 0 or cand_min <= 0:
        return False, None
    try:
        threshold = int(threshold_min)
    except (TypeError, ValueError):
        threshold = DEFAULT_RUNTIME_HARD_THRESHOLD_MIN
    if threshold <= 0:
        return False, None

    delta = abs(file_min - cand_min)
    if delta <= threshold:
        # Sous le seuil HARD : pas d'exclusion. Le scoring soft s'applique.
        return False, None

    # Delta > seuil : on regarde l'edition flag
    if _is_extended_edition(edition_label):
        # Edition longue declare -> on conserve mais on signale au user
        return False, WARN_RUNTIME_HARD_KEPT_VIA_EDITION

    # H5 : une duree seulement DECLAREE (NFO) ne fait pas autorite pour une
    # exclusion dure. On conserve + signale ; le probe (mesure) reconciliera.
    if not runtime_measured:
        return False, WARN_RUNTIME_HARD_KEPT_DECLARED

    # Duree MESUREE + pas d'edition longue -> EXCLU
    return True, None


__all__ = [
    "DEFAULT_RUNTIME_HARD_THRESHOLD_MIN",
    "WARN_RUNTIME_HARD_EXCLUDED",
    "WARN_RUNTIME_HARD_KEPT_DECLARED",
    "WARN_RUNTIME_HARD_KEPT_VIA_EDITION",
    "evaluate_runtime_hard_filter",
]
