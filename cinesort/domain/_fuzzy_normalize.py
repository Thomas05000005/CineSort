"""Normalisation de titres pour le fuzzy matching (logique string pure = domain).

Refactor iter4b 2026-06-09 : `normalize_for_fuzzy` a ete extraite de
`cinesort.app._fuzzy_utils` vers ce module domain pour respecter le contrat
`domain_pure` (domain ne doit pas dependre de app). Logique de chaine pure,
sans dependance externe (stdlib uniquement).
"""

from __future__ import annotations

import unicodedata

_PUNCTUATION = ":-.,'\"!?()[]{}"


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
    for ch in _PUNCTUATION:
        t = t.replace(ch, " ")
    # Normaliser les espaces
    t = " ".join(t.split())
    return t
