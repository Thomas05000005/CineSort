"""Detection de conflit titre conteneur MKV/MP4.

Compare le tag title interne du conteneur avec le titre identifie par CineSort.
La comparaison se fait par TOKENS normalises (minuscules, separateurs scene
aplatis, annee et tags techniques retires) : un nom de release scene
("Inception.2010.1080p.BluRay.x264-SPARKS") n'est donc PAS un conflit face a
"Inception". Seuls les titres reellement incoherents (tokens disjoints : rip.by.XxX,
titre d'un autre film, etc.) levent le flag `mkv_title_mismatch`.

#867 : ce module a longtemps CLASSE les titres ("est-ce un titre scene ?") via
`_is_scene_title` + `_SCENE_PATTERNS` + `_SCENE_THRESHOLD`. Le refactor R8-044
(F4) a remplace cette heuristique par la comparaison par tokens ci-dessous sans
jamais recabler l'ancienne : elle est restee declaree, sans aucun appelant, avec
une docstring de module qui continuait de la decrire. Les trois symboles ont ete
supprimes le 2026-08-05 et cette docstring dit desormais ce que le code fait.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

# R8-044 (F4) : bruit scene à retirer AVANT comparaison de titre (année + tags
# techniques). Sans ça, l'égalité exacte case-insensitive faisait mismatcher 88 %
# des release-names à points ("Inception.2010.1080p.x264-SPARKS" != "Inception")
# = faux signal `mkv_title_mismatch` qui noyait les vrais conflits.
_TITLE_NOISE_RE = re.compile(
    r"\b(?:(?:19|20)\d{2}|x264|x265|h\.?264|h\.?265|hevc|avc|xvid|divx|"
    r"480p|576p|720p|1080p|1440p|2160p|4k|uhd|hdr10|hdr|dv|"
    r"bluray|blu-ray|bdrip|brrip|bdremux|remux|web-?dl|web-?rip|hdtv|dvdrip|hdrip|"
    r"aac|ac3|eac3|dts|dts-hd|truehd|atmos|ddp?5|ddp?7|flac|opus|"
    r"proper|repack|internal|extended|unrated|multi|vff|vfi|vof|vostfr|"
    r"french|truefrench|english|subfrench)\b",
    re.IGNORECASE,
)


def _title_tokens(s: str) -> set:
    """Normalise un titre en tokens significatifs (minuscule, séparateurs scene
    aplatis, année + tags techniques retirés)."""
    s = s.lower()
    s = re.sub(r"[._\-]+", " ", s)
    s = _TITLE_NOISE_RE.sub(" ", s)
    return {t for t in s.split() if t}


def check_container_title(
    container_title: Optional[str],
    proposed_title: str,
) -> List[str]:
    """Compare le titre conteneur avec le titre identifie.

    Retourne une liste de warning flags (vide si pas de conflit).

    R8-044 (F4) : comparaison par TOKENS normalisés (et non égalité exacte). Un
    nom de release scene ("Inception.2010.1080p.x264-SPARKS") dont les tokens de
    titre sont inclus dans / recouvrent fortement ceux du titre proposé n'est PAS
    un conflit. On ne flague QUE les vrais titres incohérents (tokens disjoints).
    """
    if not container_title or not container_title.strip():
        return []
    ct = container_title.strip()
    pt = (proposed_title or "").strip()
    if not pt:
        return []
    if ct.lower() == pt.lower():
        return []
    ct_tok = _title_tokens(ct)
    pt_tok = _title_tokens(pt)
    # Un côté réduit à du pur bruit après normalisation -> pas de conflit fiable.
    if not ct_tok or not pt_tok:
        return []
    overlap = ct_tok & pt_tok
    smaller = min(len(ct_tok), len(pt_tok))
    # Même film si l'un des ensembles de tokens est inclus dans l'autre, OU
    # recouvrement fort (>= 70 % du plus petit ensemble).
    if overlap and (pt_tok <= ct_tok or ct_tok <= pt_tok or len(overlap) / smaller >= 0.7):
        return []
    logger.debug("mkv_title: container='%s' proposed='%s' -> mismatch (tokens disjoints)", ct, pt)
    return ["mkv_title_mismatch"]
