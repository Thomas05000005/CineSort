"""Analyse d'encodage — detection upscale, 4K light, re-encode degrade.

Analyse le bitrate, la resolution et le codec video pour detecter :
- upscale_suspect : bitrate trop bas pour la resolution (probable upscale)
- 4k_light : vrai 4K mais compression web/streaming (informatif)
- reencode_degraded : re-encode destructif a tres bas bitrate
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# --- Seuils upscale (kbps) ------------------------------------------------
# En dessous de ces valeurs, le fichier est probablement upscale.
_UPSCALE_2160P_HEVC_KBPS = 3500
_UPSCALE_1080P_HEVC_KBPS = 1500
_UPSCALE_1080P_H264_KBPS = 2000
_UPSCALE_720P_KBPS = 1000

# --- Zone 4K light (kbps) -------------------------------------------------
# Entre le seuil upscale et ce plafond, c'est du vrai 4K compresse web.
_4K_LIGHT_CEILING_KBPS = 25000

# --- Seuils re-encode degrade (kbps) --------------------------------------
# Bitrate extremement bas = re-encode destructif multi-generation.
_REENCODE_1080P_HEVC_KBPS = 800
_REENCODE_1080P_H264_KBPS = 1000
_REENCODE_720P_KBPS = 500
_REENCODE_SD_KBPS = 300

# Codecs HEVC-like (efficaces a bas bitrate)
_HEVC_CODECS = frozenset({"hevc", "h265", "h.265", "x265", "av1"})
# Codecs H264-like
_H264_CODECS = frozenset({"h264", "h.264", "x264", "avc"})


def analyze_encode_quality(detected: Dict[str, Any]) -> List[str]:
    """Analyse les metriques d'encodage et retourne les warning flags.

    Utilise les champs de detected tels que stockes dans quality_reports.metrics.
    Retourne une liste (potentiellement vide) de flags parmi :
    - "upscale_suspect"
    - "4k_light"
    - "reencode_degraded"
    """
    if not detected or not isinstance(detected, dict):
        return []

    height = int(detected.get("height") or 0)
    bitrate_kbps = int(detected.get("bitrate_kbps") or 0)
    codec = str(detected.get("video_codec") or "").strip().lower()

    # Guards : pas de donnees → pas de flag
    if height <= 0 or bitrate_kbps <= 0 or not codec:
        return []

    flags: List[str] = []
    is_hevc = codec in _HEVC_CODECS
    is_h264 = codec in _H264_CODECS

    # --- 2160p (4K) ---
    if height >= 2100:
        if is_h264:
            # 4K H264 natif est quasi-impossible → toujours suspect
            flags.append("upscale_suspect")
        elif is_hevc:
            if bitrate_kbps < _UPSCALE_2160P_HEVC_KBPS:
                flags.append("upscale_suspect")
            elif bitrate_kbps <= _4K_LIGHT_CEILING_KBPS:
                flags.append("4k_light")
            # > 25000 kbps → vrai 4K, pas de flag

    # --- 1080p ---
    elif height >= 1000:
        if is_hevc and bitrate_kbps < _UPSCALE_1080P_HEVC_KBPS:
            flags.append("upscale_suspect")
        elif is_h264 and bitrate_kbps < _UPSCALE_1080P_H264_KBPS:
            flags.append("upscale_suspect")

    # --- 720p ---
    elif height >= 680:
        if bitrate_kbps < _UPSCALE_720P_KBPS:
            flags.append("upscale_suspect")

    # --- Re-encode degrade (peut coexister avec upscale_suspect) ---
    if height >= 1000:
        if is_hevc and bitrate_kbps < _REENCODE_1080P_HEVC_KBPS:
            flags.append("reencode_degraded")
        elif is_h264 and bitrate_kbps < _REENCODE_1080P_H264_KBPS:
            flags.append("reencode_degraded")
    elif height >= 680:
        if bitrate_kbps < _REENCODE_720P_KBPS:
            flags.append("reencode_degraded")
    elif height > 0:
        if bitrate_kbps < _REENCODE_SD_KBPS:
            flags.append("reencode_degraded")

    if flags:
        logger.debug("encode: flags=%s", flags)
    return flags
