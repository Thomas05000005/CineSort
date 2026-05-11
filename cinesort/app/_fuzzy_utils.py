"""Utilitaires fuzzy matching pour les modules de synchronisation."""

from __future__ import annotations

import logging
import unicodedata

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
