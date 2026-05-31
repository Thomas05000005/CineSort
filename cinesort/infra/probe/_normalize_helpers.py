"""Helpers prives pour normalize.py (Vague M, M-04).

Centralise les conversions de valeurs (int / float / bitrate / bool / ratio fps)
et les utilitaires de selection (pick_value, merge_flag) utilises par les
sous-modules ffprobe / mediainfo / merge.

Les fonctions to_int / to_float / to_bitrate_int / bool_from_text delegueent
aux helpers canoniques de cinesort.domain.conversions (variantes Optional)
pour eliminer la duplication identifiee dans l'audit Vague M.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from cinesort.domain.conversions import (
    to_optional_bitrate as _to_opt_bitrate,
    to_optional_bool as _to_opt_bool,
    to_optional_float as _to_opt_float,
    to_optional_int as _to_opt_int,
)


def _to_float(value: Any) -> Optional[float]:
    """Delegue vers cinesort.domain.conversions.to_optional_float (M-04 dedup)."""
    return _to_opt_float(value)


def _to_int(value: Any) -> Optional[int]:
    """Delegue vers cinesort.domain.conversions.to_optional_int (M-04 dedup)."""
    return _to_opt_int(value)


def _to_bitrate_int(value: Any) -> Optional[int]:
    """Delegue vers cinesort.domain.conversions.to_optional_bitrate (M-04 dedup)."""
    return _to_opt_bitrate(value)


def _bool_from_text(value: Any) -> Optional[bool]:
    """Delegue vers cinesort.domain.conversions.to_optional_bool (M-04 dedup)."""
    return _to_opt_bool(value)


def _ratio_to_fps(value: Any) -> Optional[float]:
    """Parse "30000/1001" -> 29.97 (3 decimales). Retourne None si invalide."""
    s = str(value or "").strip()
    if not s:
        return None
    if "/" in s:
        try:
            n, d = s.split("/", 1)
            n_f = float(n)
            d_f = float(d)
            if d_f == 0:
                return None
            return round(n_f / d_f, 3)
        except (TypeError, ValueError):
            return None
    return _to_float(s)


def _duration_seconds_from_mediainfo(value: Any) -> Optional[float]:
    """MediaInfo peut renvoyer des ms ou s selon le format. Heuristique : > 1e5 -> ms."""
    v = _to_float(value)
    if v is None:
        return None
    if v > 100000.0:
        return round(v / 1000.0, 3)
    return round(v, 3)


def _pick_value(
    *,
    ffprobe_value: Any,
    mediainfo_value: Any,
    prefer_ffprobe: bool = True,
) -> Tuple[Any, str]:
    """Renvoie (value, source) en privilegiant ffprobe ou mediainfo selon le flag."""

    def _has(v: Any) -> bool:
        if v is None:
            return False
        if isinstance(v, str):
            return bool(v.strip())
        if isinstance(v, (list, dict, tuple, set)):
            return len(v) > 0
        return True

    ff_has = _has(ffprobe_value)
    mi_has = _has(mediainfo_value)
    if prefer_ffprobe:
        if ff_has:
            return ffprobe_value, "ffprobe"
        if mi_has:
            return mediainfo_value, "mediainfo"
    else:
        if mi_has:
            return mediainfo_value, "mediainfo"
        if ff_has:
            return ffprobe_value, "ffprobe"
    return None, "none"


def _merge_flag(mi: bool, ff: bool, mi_has: bool, ff_has: bool) -> Tuple[bool, str]:
    """OR logique des flags HDR avec attribution de source pour la traceabilite."""
    value = bool(mi or ff)
    if mi and ff:
        return value, "mediainfo+ffprobe"
    if ff:
        return value, "ffprobe"
    if mi:
        return value, "mediainfo"
    if ff_has:
        return value, "ffprobe"
    if mi_has:
        return value, "mediainfo"
    return value, "none"


def _extract_bit_depth(pix_fmt: str, bits_per_raw_sample: Any) -> Optional[int]:
    """Retourne la profondeur de bits du flux video.

    Prefere `bits_per_raw_sample` (champ explicite ffprobe). Sinon parse le
    `pix_fmt` (yuv420p10le -> 10, yuv420p12le -> 12, yuv420p -> 8).
    """
    explicit = _to_int(bits_per_raw_sample)
    if explicit and explicit > 0:
        return explicit
    pf = str(pix_fmt or "").lower()
    if not pf:
        return None
    # Patterns ffmpeg : p10/p12/p16 (planar) ou 10le/12le/16le
    for depth in (16, 12, 10):
        if f"p{depth}" in pf or f"{depth}le" in pf or f"{depth}be" in pf:
            return depth
    # Fallback : tout pix_fmt yuv/rgb sans suffixe = 8 bits
    if "yuv" in pf or "rgb" in pf or "gray" in pf or "nv" in pf:
        return 8
    return None
