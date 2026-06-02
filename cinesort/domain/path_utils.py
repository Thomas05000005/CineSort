"""Helpers FS purs pour la couche domain (VQ-1 : extraction depuis domain.core).

Ce module heberge les primitives de manipulation de chemins / noms Windows
qui etaient historiquement definies dans `cinesort.domain.core`. L'extraction
brise le cycle :

    core -> duplicate_support -> (lazy) naming -> core

Apres extraction :
    core -> path_utils
    naming -> path_utils  (au lieu de naming -> core)
    duplicate_support (DI) -> reste agnostique

Aucune dependance vers app/infra/ui : contract `domain_pure` (import-linter)
respecte. Aucune dependance vers d'autres modules de domain non plus, ce qui
en fait une feuille du graphe d'imports.

BACKWARD COMPATIBILITY :
- Les noms `windows_safe`, `_norm_win_path` restent re-exportes depuis
  `cinesort.domain.core` (avec le meme contrat) pour ne casser aucun caller
  externe (app, infra, ui, tests). Cf. core.py.
- Le nom public `norm_win_path` est introduit ici en plus de l'alias prive
  `_norm_win_path` (compat historique).
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path, PureWindowsPath

__all__ = [
    "norm_win_path",
    "_norm_win_path",
    "windows_safe",
]

# Noms reserves Windows DOS (8.3 legacy) que windows_safe doit prefixer
# d'un underscore pour eviter l'erreur OS au create.
_RESERVED_DOS_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        "com1",
        "com2",
        "com3",
        "com4",
        "com5",
        "com6",
        "com7",
        "com8",
        "com9",
        "lpt1",
        "lpt2",
        "lpt3",
        "lpt4",
        "lpt5",
        "lpt6",
        "lpt7",
        "lpt8",
        "lpt9",
    }
)


def norm_win_path(p: Path) -> PureWindowsPath:
    """Normalise un chemin pour comparaison cross-plateforme Windows.

    - Remplace `/` par `\\`
    - Applique `os.path.normcase` + `os.path.normpath`
    - Retourne un `PureWindowsPath` (comparable y compris sous Linux/CI).

    Utilisee par `ensure_inside_root` (guard path-traversal) et par
    `is_under_collection_root` via Dependency Injection depuis app/plan_support.
    """
    s = str(p).replace("/", "\\")
    s = os.path.normcase(os.path.normpath(s))
    return PureWindowsPath(s)


# Alias historique conserve pour compat (anciens callers : app/plan_support_dedup,
# app/apply_core, core.py). Ne PAS supprimer sans audit complet des 14+ sites
# externes referencant `_norm_win_path`.
_norm_win_path = norm_win_path


def windows_safe(name: str) -> str:
    """Sanitise *name* pour usage comme nom de fichier Windows.

    Contrat strict (couvert par tests/test_domain_core.py + tests VQ-1) :
    - Normalise NFC (eviter divergence NFC/NFD entre macOS/SMB et NTFS local)
    - Retire `< > : " / \\ | ? *` (caracteres interdits NTFS)
    - Retire dots et espaces traillants
    - Collapse les espaces multiples en un seul
    - Prefixe `_` les noms DOS reserves (CON, NUL, COM1-9, LPT1-9, ...)
    - Remplace par `_untitled` si le resultat est vide
    - Tronque a 180 caracteres (marge sous la limite NTFS 255 pour permettre
      l'ajout d'extension + suffixe)
    """
    name = unicodedata.normalize("NFC", name)
    name = re.sub(r'[<>:"/\\|?*]', "", name).strip().rstrip(".")
    name = re.sub(r"\s+", " ", name)
    if name.lower() in _RESERVED_DOS_NAMES:
        name = f"_{name}"
    if not name:
        name = "_untitled"
    return name[:180].strip()
