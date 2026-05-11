"""H-2 audit QA 20260428 — pre-check espace disque avant apply.

Refuse de demarrer un apply si la destination n'a pas assez d'espace pour
absorber la somme des fichiers a deplacer. Sur Windows, shutil.move est une
copie + delete des qu'on traverse les volumes, donc l'espace disque cible
doit pouvoir contenir l'ensemble en transit.

Strategie : conservatrice (somme totale + 10% de marge). Si meme volume,
l'espace utilise reste constant donc on est sur-protecteur, mais c'est
sans risque. Si volumes differents, on protege contre l'apply qui se
coupe a mi-parcours par disque plein.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

_logger = logging.getLogger(__name__)

# Marge minimale absolue : meme si la somme calculee est petite, on refuse
# si moins de 100 MB libres au total (zone tampon FS, journal SQLite, logs...).
_MIN_FREE_BYTES = 100 * 1024 * 1024  # 100 MB

# Marge proportionnelle au-dessus de la somme estimee.
_SAFETY_MARGIN = 0.10  # 10%


def _row_estimated_size(row: Any) -> int:
    """Taille estimee des fichiers que ce row va deplacer.

    MVP : on prend la taille du fichier video principal (`folder/video`).
    Pour les collections, on somme les videos directement dans `folder`
    (sans recursion). Si stat echoue : on ignore et on retourne 0
    (mieux laisser l'apply tenter que de bloquer sur un edge case).
    """
    folder_str = str(getattr(row, "folder", "") or "")
    video_str = str(getattr(row, "video", "") or "")
    if not folder_str:
        return 0

    folder = Path(folder_str)

    if video_str:
        candidate = folder / video_str
        try:
            return int(candidate.stat().st_size)
        except (OSError, PermissionError):
            return 0

    # Pas de video specifie (collection) : somme des fichiers immediats.
    total = 0
    try:
        for entry in folder.iterdir():
            if entry.is_file():
                try:
                    total += int(entry.stat().st_size)
                except (OSError, PermissionError):
                    continue
    except (OSError, PermissionError):
        return 0
    return total


def estimate_apply_size(rows: List[Any], approved_keys: set) -> int:
    """Somme estimee des octets a deplacer par les rows approuves.

    `approved_keys` : ensemble des row_id qui seront effectivement appliques.
    """
    total = 0
    for row in rows or []:
        rid = str(getattr(row, "row_id", "") or "")
        if rid and rid not in approved_keys:
            continue
        total += _row_estimated_size(row)
    return total


def check_disk_space_for_apply(
    cfg: Any,
    rows: List[Any],
    approved_keys: set,
) -> Tuple[bool, Dict[str, Any]]:
    """Verifie qu'il y a assez d'espace libre sur le volume de destination.

    Retourne (ok, info) ou info contient :
      - free_bytes : espace libre actuel
      - needed_bytes : somme estimee + marge
      - estimated_bytes : somme brute (sans marge)
      - target_root : chemin verifie
      - message : explication FR pour l'UI

    Si l'estimation est nulle (rows vides ou stat echouees), on verifie
    seulement que le minimum absolu est respecte.
    """
    target_root = Path(getattr(cfg, "root", ".") or ".")
    try:
        usage = shutil.disk_usage(str(target_root))
    except (OSError, PermissionError) as exc:
        _logger.warning("disk_space_check: shutil.disk_usage echoue sur %s: %s", target_root, exc)
        # Si on ne peut meme pas lire l'espace, on laisse passer (mieux apply qui peut
        # echouer plus tard que blocage faux positif).
        return True, {
            "free_bytes": -1,
            "needed_bytes": 0,
            "estimated_bytes": 0,
            "target_root": str(target_root),
            "message": f"Impossible de lire l'espace disque sur {target_root}, pre-check ignore.",
        }

    estimated = estimate_apply_size(rows, approved_keys)
    needed = max(int(estimated * (1.0 + _SAFETY_MARGIN)), _MIN_FREE_BYTES)

    info = {
        "free_bytes": int(usage.free),
        "needed_bytes": int(needed),
        "estimated_bytes": int(estimated),
        "target_root": str(target_root),
    }

    if usage.free < needed:
        free_mb = usage.free / (1024 * 1024)
        needed_mb = needed / (1024 * 1024)
        info["message"] = (
            f"Espace disque insuffisant sur {target_root} : "
            f"{free_mb:.0f} Mo libres, {needed_mb:.0f} Mo necessaires "
            f"(somme estimee + 10% de marge). Liberez de l'espace "
            f"avant de lancer l'apply."
        )
        return False, info

    info["message"] = (
        f"Espace disque OK sur {target_root} : "
        f"{usage.free // (1024 * 1024)} Mo libres, "
        f"{needed // (1024 * 1024)} Mo requis."
    )
    return True, info
