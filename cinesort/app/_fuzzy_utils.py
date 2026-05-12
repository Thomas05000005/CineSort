"""Utilitaires fuzzy matching pour les modules de synchronisation."""

from __future__ import annotations

import logging
import unicodedata
from typing import Iterable, Optional, Tuple

logger = logging.getLogger(__name__)

# Seuil par defaut pour le fuzzy matching (0-100)
DEFAULT_FUZZY_THRESHOLD = 85


def normalize_for_fuzzy(title: str) -> str:
    """Normalise un titre pour comparaison fuzzy.

    - lowercase
    - strip accents (NFD + strip combining marks)
    - strip ponctuation courante
    - strip whitespace multiple
    """
    if not title:
        return ""
    t = title.lower().strip()
    # Strip accents via decomposition Unicode
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    # Strip ponctuation courante
    for ch in ":-.,'\"!?()[]{}":
        t = t.replace(ch, " ")
    # Normaliser les espaces
    t = " ".join(t.split())
    return t


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
) -> Optional[Tuple[str, int]]:
    """Cherche le meilleur match fuzzy d'un titre parmi une liste de candidats.

    Utilise `rapidfuzz.process.extractOne` qui est vectorise en C : reduction
    typique x100 a x1000 par rapport a une boucle Python sur les candidats.

    Args:
        query: Le titre a chercher (deja normalise ou non — on normalise ici).
        choices: Iterable de titres candidats (deja normalises ou non).
        threshold: Score minimum (0-100) pour considerer un match.
        use_token_sort: Si True, utilise fuzz.token_sort_ratio (insensible
            a l'ordre des mots) au lieu de fuzz.ratio. Utile pour les titres
            avec sous-titres reorganises.

    Returns:
        (match_normalise, score) si un match >= threshold est trouve, sinon None.
        Le caller doit ensuite retrouver l'objet original via index/dict.

    Cf issue #29 : remplace les boucles O(n^2) dans radarr_sync,
    jellyfin_validation et watchlist par cet appel O(n) vectorise.
    """
    from rapidfuzz import fuzz, process

    q_norm = normalize_for_fuzzy(query)
    if not q_norm:
        return None

    # Pre-normalise les choix pour eviter la re-normalisation a chaque ratio
    norm_choices = [normalize_for_fuzzy(c) for c in choices]
    # Filtre les choix vides apres normalisation pour eviter les artefacts
    norm_choices = [c for c in norm_choices if c]
    if not norm_choices:
        return None

    scorer = fuzz.token_sort_ratio if use_token_sort else fuzz.ratio
    best = process.extractOne(q_norm, norm_choices, scorer=scorer, score_cutoff=threshold)
    if best is None:
        return None
    # process.extractOne renvoie (choice, score, index)
    match_str, score, _ = best
    logger.debug("fuzzy_vectorized: match '%s' ~ '%s' = %d (>= %d)", q_norm[:40], match_str[:40], int(score), threshold)
    return (match_str, int(score))
