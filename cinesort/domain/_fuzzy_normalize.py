"""Normalisation de titre pour fuzzy matching (domain pur).

Module deplace depuis `cinesort.app._fuzzy_utils` (etape 2 refactor archi
iter4b, 2026-06-09): la fonction `normalize_for_fuzzy` est de la pure string
normalization (lowercase + unicodedata + ponctuation + whitespace) sans aucune
dependance app/infra/ui. Elle appartient donc a la couche `domain`.

Backward compat: `cinesort.app._fuzzy_utils.normalize_for_fuzzy` reste expose
en re-export depuis ce module pour ne pas casser les callers existants.
"""

from __future__ import annotations

import unicodedata


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
