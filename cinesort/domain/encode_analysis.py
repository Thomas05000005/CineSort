"""Analyse d'encodage — detection upscale, 4K light, re-encode degrade.

Analyse le bitrate, la resolution et le codec video pour detecter :
- upscale_suspect : bitrate trop bas pour la resolution (probable upscale)
- 4k_light : vrai 4K mais compression web/streaming (informatif)
- reencode_degraded : re-encode destructif a tres bas bitrate

Refonte lot #641/#682/#745/#806 (2026-08-04)
============================================
Les quatre issues decrivaient le meme defaut sous quatre angles : la bande de
resolution etait choisie sur la HAUTEUR BRUTE et chaque bande avait sa propre
grille de codecs. Trois consequences mesurables :

* #641 — un 720p cinemascope (1280x536) tombait dans la bande SD (536 < 680) et
  un 1080p scope (1920x800) dans la bande 720p. Ils etaient donc juges avec des
  seuils d'une bande TROP BASSE, donc trop permissifs : `upscale_suspect`
  n'existe meme pas en SD. La classification passe desormais par
  `resolution_class.classify_resolution` (largeur-primaire), la meme echelle que
  `quality_score._resolution_label`.
* #745 — le bloc re-encode n'avait pas de branche 2160p : toute la 4K etait
  jugee au seuil 1080p (800 kbps), qu'aucun fichier 4K reel n'atteint. Le palier
  etait mort en 4K. Il existe maintenant (`_REENCODE_2160P_KBPS`).
* #806 — la bande 1080p ne testait l'upscale que sur HEVC/H264 : un 1080p VP9 ou
  MPEG-2 a 400 kbps n'etait jamais flagge, alors que la bande 720p, elle, est
  codec-agnostique. Le gating par codec disparait (cf. ci-dessous).
* #682 — deja desamorce au SEUL site d'appel de production par la PR #854 (la
  hauteur CANONIQUE y est passee a `compute_genre_adjustments`) ; on durcit
  `genre_rules` lui-meme pour que la garde ne dependre plus du site d'appel.

Regle de codec, unique et volontairement conservatrice
-----------------------------------------------------
Deux seuils par bande seulement : un pour la famille H264 (moins efficace, donc
seuil plus haut) et un pour TOUT LE RESTE. Les codecs hors H264 qui ne sont pas
HEVC-like (MPEG-2, XviD, VC-1...) sont MOINS efficaces que H264 : leur appliquer
le seuil HEVC — le plus permissif de la bande — ne peut que SOUS-flagger, jamais
sur-flagger. C'est la direction voulue : un faux `upscale_suspect` deprecie un
bon fichier, et un fichier deprecie est celui qu'un arbitrage de doublons
propose de supprimer. On refuse donc d'inventer un seuil « generique » calibre
au jugé ; on reutilise une valeur deja validee du depot.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from cinesort.domain.conversions import to_int
from cinesort.domain.resolution_class import (
    RES_720P,
    RES_1080P,
    RES_2160P,
    RES_SD,
    RES_UNKNOWN,
    classify_resolution,
)

logger = logging.getLogger(__name__)

# --- Seuils upscale (kbps) ------------------------------------------------
# En dessous de ces valeurs, le fichier est probablement upscale.
# Le suffixe H264 marque la seule exception codec ; la valeur nue s'applique a
# tous les autres codecs (cf. « Regle de codec » dans le docstring du module).
_UPSCALE_2160P_KBPS = 3500
_UPSCALE_1080P_KBPS = 1500
_UPSCALE_1080P_H264_KBPS = 2000
_UPSCALE_720P_KBPS = 1000

# --- Zone 4K light (kbps) -------------------------------------------------
# Entre le seuil upscale et ce plafond, c'est du vrai 4K compresse web.
_4K_LIGHT_CEILING_KBPS = 25000

# --- Seuils re-encode degrade (kbps) --------------------------------------
# Bitrate extremement bas = re-encode destructif multi-generation.
# #745 : le seuil 2160p manquait. Il n'est PAS devine : dans les trois bandes
# deja calibrees, le seuil re-encode vaut la moitie du seuil upscale
# (800/1500, 1000/2000, 500/1000). On applique la meme derivation a la 4K :
# 3500 / 2 = 1750. Aucun 4K reel ne descend la sans avoir ete re-encode.
_REENCODE_2160P_KBPS = 1750
_REENCODE_1080P_KBPS = 800
_REENCODE_1080P_H264_KBPS = 1000
_REENCODE_720P_KBPS = 500
_REENCODE_SD_KBPS = 300

# Codecs H264-like : seule famille qui merite un seuil distinct (moins efficace
# a qualite egale que HEVC/AV1/VP9, donc exige plus de debit).
_H264_CODECS = frozenset({"h264", "h.264", "x264", "avc"})


def _upscale_threshold_kbps(res: str, *, is_h264: bool) -> int:
    """Seuil `upscale_suspect` de la bande, en kbps (0 = bande non couverte).

    La bande SD est volontairement hors detection d'upscale : un fichier SD est
    deja au plancher, il n'y a pas de resolution plus basse dont il pourrait
    avoir ete etire.
    """
    if res == RES_2160P:
        return _UPSCALE_2160P_KBPS
    if res == RES_1080P:
        return _UPSCALE_1080P_H264_KBPS if is_h264 else _UPSCALE_1080P_KBPS
    if res == RES_720P:
        return _UPSCALE_720P_KBPS
    return 0


def _reencode_threshold_kbps(res: str, *, is_h264: bool) -> int:
    """Seuil `reencode_degraded` de la bande, en kbps (0 = bande non couverte)."""
    if res == RES_2160P:
        return _REENCODE_2160P_KBPS
    if res == RES_1080P:
        return _REENCODE_1080P_H264_KBPS if is_h264 else _REENCODE_1080P_KBPS
    if res == RES_720P:
        return _REENCODE_720P_KBPS
    if res == RES_SD:
        return _REENCODE_SD_KBPS
    return 0


def analyze_encode_quality(detected: Dict[str, Any]) -> List[str]:
    """Analyse les metriques d'encodage et retourne les warning flags.

    Utilise les champs de detected tels que stockes dans quality_reports.metrics
    (`width`, `height`, `bitrate_kbps`, `video_codec`). `width` est produit par
    `quality_score._build_quality_metrics_helper` depuis la v1.0.0 : les deux
    sites d'appel de production (`quality_report_support`, `radarr_sync`)
    transmettent le dict `metrics.detected` entier, il est donc present.
    Quand il manque, la hauteur reste un filet de securite (cf.
    `resolution_class.classify_resolution`) et le comportement est celui d'avant
    ce lot.

    Retourne une liste (potentiellement vide) de flags parmi :
    - "upscale_suspect"
    - "4k_light"
    - "reencode_degraded"
    """
    if not detected or not isinstance(detected, dict):
        return []

    res = classify_resolution(detected.get("width"), detected.get("height"))
    # `to_int` et non `int(x or 0)` : le dict vient d'un JSON SQLite persiste,
    # une valeur corrompue faisait lever ValueError et echouer tout le rapport.
    bitrate_kbps = to_int(detected.get("bitrate_kbps"), 0)
    codec = str(detected.get("video_codec") or "").strip().lower()

    # Guards : pas de donnees → pas de flag
    if res == RES_UNKNOWN or bitrate_kbps <= 0 or not codec:
        return []

    flags: List[str] = []
    is_h264 = codec in _H264_CODECS

    # --- upscale / 4K light ---
    if res == RES_2160P and is_h264:
        # 4K H264 natif est quasi-impossible → toujours suspect.
        flags.append("upscale_suspect")
    else:
        upscale_kbps = _upscale_threshold_kbps(res, is_h264=is_h264)
        if upscale_kbps and bitrate_kbps < upscale_kbps:
            flags.append("upscale_suspect")
        elif res == RES_2160P and bitrate_kbps <= _4K_LIGHT_CEILING_KBPS:
            # Au-dessus du seuil upscale mais sous le plafond : vrai 4K compresse
            # web. Au-dela de 25000 kbps → vrai 4K, pas de flag.
            flags.append("4k_light")

    # --- Re-encode degrade (peut coexister avec upscale_suspect) ---
    reencode_kbps = _reencode_threshold_kbps(res, is_h264=is_h264)
    if reencode_kbps and bitrate_kbps < reencode_kbps:
        flags.append("reencode_degraded")

    if flags:
        logger.debug("encode: res=%s flags=%s", res, flags)
    return flags
