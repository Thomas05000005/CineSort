"""Utilitaires fuzzy matching pour les modules de synchronisation.

Note (refactor iter4b 2026-06-09): `normalize_for_fuzzy` a ete deplacee vers
`cinesort.domain._fuzzy_normalize` (logique de string pure = domain). Le
symbole reste re-exporte ici pour preserver la backward compat absolue
(callers app/, tests existants).
"""

from __future__ import annotations

import logging
from typing import Iterable, List, Optional, Tuple

# Backward compat: re-export depuis le bon etage architectural (domain).
from cinesort.domain._fuzzy_normalize import normalize_for_fuzzy

logger = logging.getLogger(__name__)

# Seuil par defaut pour le fuzzy matching (0-100)
DEFAULT_FUZZY_THRESHOLD = 85

__all__ = [
    "DEFAULT_FUZZY_THRESHOLD",
    "normalize_for_fuzzy",
    "fuzzy_title_match",
    "find_best_fuzzy_match",
]


def fuzzy_title_match(local_title: str, remote_title: str, threshold: int = DEFAULT_FUZZY_THRESHOLD) -> bool:
    """Compare deux titres avec fuzzy matching apres normalisation.

    Retourne True si le ratio >= threshold (0-100).
    """
    from rapidfuzz import fuzz

    a = normalize_for_fuzzy(local_title)
    b = normalize_for_fuzzy(remote_title)
    if not a or not b:
        return False
    ratio = fuzz.ratio(a, b)
    if ratio >= threshold:
        logger.debug("fuzzy: match '%s' ~ '%s' = %d (>= %d)", a[:40], b[:40], int(ratio), threshold)
    return ratio >= threshold


def find_best_fuzzy_match(
    query: str,
    choices: Iterable[str],
    *,
    threshold: int = DEFAULT_FUZZY_THRESHOLD,
    use_token_sort: bool = False,
    choices_are_normalized: bool = False,
) -> Optional[Tuple[str, int, int]]:
    """Cherche le meilleur match fuzzy d'un titre parmi une liste de candidats.

    Utilise `rapidfuzz.process.extractOne` qui est vectorise en C : reduction
    typique x100 a x1000 par rapport a une boucle Python sur les candidats.

    Args:
        query: Le titre a chercher (deja normalise ou non — on normalise ici,
            `normalize_for_fuzzy` etant idempotente).
        choices: Sequence de titres candidats, dans l'ordre du caller.
        threshold: Score minimum (0-100) pour considerer un match.
        use_token_sort: Si True, utilise fuzz.token_sort_ratio (insensible
            a l'ordre des mots) au lieu de fuzz.ratio. Utile pour les titres
            avec sous-titres reorganises.
        choices_are_normalized: True si les candidats sortent deja d'un index
            pre-normalise (radarr_by_year_normalized & co) : on evite alors de
            re-normaliser a chaque requete, ce qui annulerait le gain de
            l'index de l'issue #29.

    Returns:
        `(match_normalise, score, index)` si un match >= threshold est trouve,
        sinon None. `index` est la position dans la sequence `choices` D'ORIGINE
        (pas dans la liste filtree en interne) : c'est elle qui permet au caller
        de remonter a l'objet metier associe au titre.

    Cf issue #29 : remplace les boucles O(n^2) dans radarr_sync,
    jellyfin_validation et watchlist par cet appel O(n) vectorise.
    """
    from rapidfuzz import fuzz, process

    q_norm = normalize_for_fuzzy(query)
    if not q_norm:
        return None

    # Pre-normalise les choix pour eviter la re-normalisation a chaque ratio,
    # en filtrant ceux qui deviennent vides. On MEMORISE l'index d'origine de
    # chaque choix retenu : sans cette table, le filtre decale les index et le
    # caller ne peut plus retrouver l'objet correspondant au titre matche.
    # C'est ce contrat casse qui rendait ce helper inutilisable — et qui a
    # pousse les 3 call sites de l'issue #29 a re-inliner extractOne.
    norm_choices: List[str] = []
    origin_index: List[int] = []
    for i, c in enumerate(choices):
        n = c if choices_are_normalized else normalize_for_fuzzy(c)
        if n:
            norm_choices.append(n)
            origin_index.append(i)
    if not norm_choices:
        return None

    scorer = fuzz.token_sort_ratio if use_token_sort else fuzz.ratio
    best = process.extractOne(q_norm, norm_choices, scorer=scorer, score_cutoff=threshold)
    if best is None:
        return None
    # process.extractOne renvoie (choice, score, index_dans_norm_choices)
    match_str, score, filtered_idx = best
    logger.debug("fuzzy_vectorized: match '%s' ~ '%s' = %d (>= %d)", q_norm[:40], match_str[:40], int(score), threshold)
    return (match_str, int(score), origin_index[filtered_idx])
