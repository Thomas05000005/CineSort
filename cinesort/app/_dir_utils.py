"""Helpers FS purs pour casser le cycle d'import cleanup <-> apply_core.

Cf issue #288 : `is_dir_empty` etait dans `apply_core` mais `cleanup` en avait
besoin, creant un cycle d'import. Extrait ici pour usage par les deux modules
sans lazy import.
"""

from __future__ import annotations

from pathlib import Path


def is_dir_empty(path: Path) -> bool:
    """True si `path` est un dossier existant et strictement vide."""
    if not path.exists() or not path.is_dir():
        return False
    try:
        next(path.iterdir())
        return False
    except StopIteration:
        return True
    except (OSError, PermissionError):
        return False
