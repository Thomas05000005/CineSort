"""Detection et extraction des editions de films (Director's Cut, Extended, IMAX, etc.).

Extrait l'edition d'un nom de fichier ou dossier et fournit un label canonique.
"""

from __future__ import annotations

import re
from typing import Optional

# --- Regex de detection (case-insensitive) ---
# Chaque alternative capture une variante ; le mapping _CANONICAL normalise.
_EDITION_RE = re.compile(
    r"\b("
    r"director'?s?\s*cut|"
    r"extended(?:\s+(?:cut|edition))?|"
    r"theatrical(?:\s+(?:cut|edition))?|"
    r"unrated(?:\s+(?:cut|edition))?|"
    r"imax(?:\s+edition)?|"
    r"remaster(?:ed)?|"
    r"special\s+edition|"
    r"final\s+cut|"
    r"ultimate\s+(?:cut|edition)|"
    r"criterion(?:\s+(?:edition|collection))?|"
    r"collector'?s?\s+edition|"
    r"\d+(?:th|st|nd|rd)?\s+anniversary(?:\s+edition)?|"
    r"anniversary\s+edition"
    r")\b",
    re.IGNORECASE,
)

# --- Mapping capture → label canonique ---
# Cle = lowercase de la capture, valeur = label affiche.
# Les variantes longues sont testees en premier (startswith).
_CANONICAL_ORDERED = [
    ("director", "Director's Cut"),
    ("extended cut", "Extended Cut"),
    ("extended edition", "Extended Edition"),
    ("extended", "Extended"),
    ("theatrical cut", "Theatrical Cut"),
    ("theatrical edition", "Theatrical Edition"),
    ("theatrical", "Theatrical"),
    ("unrated cut", "Unrated Cut"),
    ("unrated edition", "Unrated Edition"),
    ("unrated", "Unrated"),
    ("imax edition", "IMAX Edition"),
    ("imax", "IMAX"),
    ("remastered", "Remastered"),
    ("remaster", "Remastered"),
    ("special edition", "Special Edition"),
    ("final cut", "Final Cut"),
    ("ultimate cut", "Ultimate Cut"),
    ("ultimate edition", "Ultimate Edition"),
    ("criterion collection", "Criterion Collection"),
    ("criterion edition", "Criterion Edition"),
    ("criterion", "Criterion"),
    ("collector", "Collector's Edition"),
    ("anniversary edition", "Anniversary Edition"),
    ("anniversary", "Anniversary Edition"),
]

# Nettoyage post-strip : separateurs orphelins
_STRIP_CLEANUP_RE = re.compile(r"[\.\-_]\s*$|^\s*[\.\-_]|\s{2,}")


def _canonicalize(raw: str) -> str:
    """Normalise une capture brute vers le label canonique."""
    low = re.sub(r"\s+", " ", raw.strip()).lower()
    # Cas special : "40th anniversary edition" → "40th Anniversary Edition"
    if "anniversary" in low and any(c.isdigit() for c in low):
        parts = low.split("anniversary", 1)
        prefix = parts[0].strip()  # ex: "40th"
        suffix = parts[1].strip() if len(parts) > 1 else ""
        label = f"{prefix} Anniversary"
        if suffix == "edition":
            label += " Edition"
        return label.strip()
    for prefix, label in _CANONICAL_ORDERED:
        if low.startswith(prefix):
            return label
    return raw.strip().title()


def extract_edition(text: str) -> Optional[str]:
    """Extrait l'edition d'un nom de fichier/dossier. Retourne le label canonique ou None."""
    if not text:
        return None
    # Remplacer les points/underscores par des espaces pour le matching
    cleaned = text.replace(".", " ").replace("_", " ")
    m = _EDITION_RE.search(cleaned)
    if not m:
        return None
    return _canonicalize(m.group(1))


def strip_edition(text: str) -> str:
    """Retire l'edition du texte pour le matching TMDb. Nettoie les separateurs orphelins."""
    if not text:
        return text
    cleaned = text.replace(".", " ").replace("_", " ")
    result = _EDITION_RE.sub(" ", cleaned)
    result = _STRIP_CLEANUP_RE.sub(" ", result)
    return re.sub(r"\s{2,}", " ", result).strip()
