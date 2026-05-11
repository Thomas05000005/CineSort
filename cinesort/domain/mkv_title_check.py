"""Detection de conflit titre conteneur MKV/MP4.

Compare le tag title interne du conteneur avec le titre identifie par CineSort.
Detecte les titres scene (Inception.2010.1080p.BluRay.x264-SPARKS) et les
titres incoherents (rip.by.XxX, titres en langue etrangere, etc.).
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

# Patterns scene : au moins 2 matches parmi ces regex = titre scene probable
_SCENE_PATTERNS = [
    re.compile(r"\w\.\w"),  # word.word
    re.compile(r"\b(19|20)\d{2}\b"),  # annee 4 chiffres
    re.compile(r"\b(x264|x265|h\.?264|h\.?265|hevc|avc|xvid|divx)\b", re.IGNORECASE),
    re.compile(r"\b(720p|1080p|2160p|4k|480p)\b", re.IGNORECASE),
    re.compile(r"\b(BluRay|BDRip|WEB-DL|WEBRip|HDTV|DVDRip|BRRip|HDRip)\b", re.IGNORECASE),
    re.compile(r"-[A-Z][A-Za-z0-9]+$"),  # tag group scene en fin (-SPARKS)
]

_SCENE_THRESHOLD = 2  # Nombre minimum de patterns pour considerer comme scene


def _is_scene_title(title: str) -> bool:
    """Retourne True si le titre ressemble a un nom de release scene."""
    matches = sum(1 for p in _SCENE_PATTERNS if p.search(title))
    return matches >= _SCENE_THRESHOLD


def check_container_title(
    container_title: Optional[str],
    proposed_title: str,
) -> List[str]:
    """Compare le titre conteneur avec le titre identifie.

    Retourne une liste de warning flags (vide si pas de conflit).
    """
    if not container_title or not container_title.strip():
        return []
    ct = container_title.strip()
    pt = (proposed_title or "").strip()
    if not pt:
        return []
    # Comparaison case-insensitive
    if ct.lower() == pt.lower():
        return []
    logger.debug("mkv_title: container='%s' proposed='%s' -> mismatch", ct, pt)
    return ["mkv_title_mismatch"]
