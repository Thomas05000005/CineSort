"""Utilitaires de normalisation de chemin partages entre modules app."""

from __future__ import annotations

import os


def normalize_path(path: str) -> str:
    """Normalise un chemin pour comparaison cross-platform (lowercase, forward slashes)."""
    if not path:
        return ""
    return os.path.normpath(path).replace("\\", "/").lower().strip()
