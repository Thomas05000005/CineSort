"""Helpers FS purs pour casser le cycle d'import cleanup <-> apply_core.

Cf issue #288 : `is_dir_empty` etait dans `apply_core` mais `cleanup` en avait
besoin, creant un cycle d'import. Extrait ici pour usage par les deux modules
sans lazy import.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

# Constante de module plutot qu'un `os.name != "nt"` en ligne : le branchement
# devient substituable dans les tests sans toucher a `os.name` du processus.
_IS_WINDOWS = os.name == "nt"


def is_reparse_point(path: Path) -> bool:
    """True si `path` redirige ailleurs : lien symbolique OU point d'analyse NTFS.

    `Path.is_symlink()` ne suffit pas sous Windows. Mesure sur Windows 11 /
    CPython 3.13 avec une jonction creee par `mklink /J` :

        is_symlink()                 -> False
        is_dir()                     -> True
        st_reparse_tag               -> 0xa0000003 (IO_REPARSE_TAG_MOUNT_POINT)
        FILE_ATTRIBUTE_REPARSE_POINT -> True
        rglob("*")                   -> DESCEND dans la cible

    Une jonction et un point de montage de volume sont donc indiscernables d'un
    dossier ordinaire pour `is_symlink()`, alors que toute enumeration les
    traverse. `FILE_ATTRIBUTE_REPARSE_POINT` couvre les trois familles (les
    liens symboliques Windows sont eux aussi des points d'analyse), d'ou le
    test unique sur cet attribut cote NT.

    Le helper est destine aux chemins DESTRUCTIFS : l'erreur va dans le sens
    restrictif. Si l'attribut est illisible (chemin disparu, volume debranche,
    ACL), on repond True, c'est-a-dire « ne pas traverser, ne pas toucher ».

    Sur-detection assumee pour la meme raison : l'attribut est aussi pose par
    des points d'analyse qui ne redirigent PAS (marqueurs OneDrive « fichiers a
    la demande », deduplication). Filtrer sur le seul bit « name surrogate »
    du reparse tag serait plus fin, mais une erreur de ce test ferait retomber
    dans la traversee ; ici une sur-detection ne fait que refuser un nettoyage,
    refus visible dans le preview (`symlink_count`, `sample_symlink_dirs`).
    """
    if not _IS_WINDOWS:
        try:
            return bool(stat.S_ISLNK(path.lstat().st_mode))
        except (OSError, ValueError):
            return True
    try:
        attributes = int(path.lstat().st_file_attributes)  # type: ignore[attr-defined]
    except (AttributeError, OSError, ValueError):
        return True
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


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
