"""Extraction AV1 film grain parameters (§15 v7.5.0).

AV1 supporte nativement le film grain synthesis via AFGS1 (AOMedia Film
Grain Spec 1). Les parametres sont stockes :
  - dans le frame header (apply_grain, grain_seed, scaling points, ar_coeff_lag)
  - dans un payload ITU-T T.35 cote side_data_list (country_code 0xB5 + provider
    0x5890 pour AOMedia)

ffprobe expose ces donnees depuis v6.0+ via `-show_entries stream=side_data_list`.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from cinesort.infra.subprocess_safety import tracked_run

from .ffmpeg_runner import _runner_platform_kwargs

logger = logging.getLogger(__name__)

# ITU-T T.35 AOMedia markers
_T35_COUNTRY_CODE_USA = 0xB5
_T35_PROVIDER_AOMEDIA = 0x5890

_AFGS1_MARKERS = (
    "AFGS1",
    "Film Grain Synthesis",
    "AOMedia Film Grain",
    "grain synthesis",
)


@dataclass(frozen=True)
class Av1FilmGrainInfo:
    """Resultat de l'extraction AV1 film grain parameters."""

    present: bool
    apply_grain: bool  # flag AV1 apply_grain (frame header)
    grain_seed: Optional[int]
    ar_coeff_lag: Optional[int]  # 0-3, autoregressive lag
    num_y_points: Optional[int]
    has_afgs1_t35: bool  # ITU-T T.35 AOMedia metadata detectee
    raw_params: Optional[Dict[str, Any]]  # payload brut pour debug


def has_afgs1_in_side_data(side_data_list: List[Dict[str, Any]]) -> bool:
    """Cherche un payload AFGS1 (ITU-T T.35 AOMedia) dans side_data_list.

    Deux heuristiques :
      1. Pattern ITU-T T.35 : country_code == 0xB5 + provider_code == 0x5890
      2. Chaine de caracteres explicite "AFGS1" ou "grain synthesis" dans les values
    """
    if not side_data_list:
        return False
    for item in side_data_list:
        if not isinstance(item, dict):
            continue
        # Heuristique 1 : codes ITU-T T.35
        try:
            country_code = int(item.get("itu_t_t35_country_code", -1))
        except (ValueError, TypeError):
            country_code = -1
        try:
            provider_code = int(item.get("itu_t_t35_provider_code", -1))
        except (ValueError, TypeError):
            provider_code = -1
        if country_code == _T35_COUNTRY_CODE_USA and provider_code == _T35_PROVIDER_AOMEDIA:
            return True
        # Heuristique 2 : string markers dans les valeurs serialisees
        blob = " ".join(str(v) for v in item.values()).lower()
        for marker in _AFGS1_MARKERS:
            if marker.lower() in blob:
                return True
    return False


def extract_av1_film_grain_params(
    ffprobe_path: str,
    media_path: str,
    *,
    timeout_s: float = 10.0,
) -> Optional[Av1FilmGrainInfo]:
    """Extrait les parametres film grain AV1 via ffprobe.

    Args:
        ffprobe_path: chemin de ffprobe.
        media_path: chemin du fichier media.
        timeout_s: timeout ffprobe.

    Returns:
        Av1FilmGrainInfo si le codec est AV1 et que des parametres grain sont
        detectes, None sinon (codec non-AV1, erreur, ou pas de grain metadata).
    """
    if not ffprobe_path or not media_path:
        return None

    cmd = [
        ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,profile,side_data_list",
        str(media_path),
    ]

    try:
        platform_kwargs = _runner_platform_kwargs()
        cp = tracked_run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout_s)),
            encoding="utf-8",
            errors="replace",
            **platform_kwargs,
        )
    except subprocess.TimeoutExpired:
        logger.warning("av1_grain: ffprobe timeout apres %ss sur %s", timeout_s, media_path)
        return None
    except OSError as exc:
        logger.warning("av1_grain: ffprobe OSError sur %s: %s", media_path, exc)
        return None

    if cp.returncode != 0:
        logger.warning("av1_grain: ffprobe returncode=%d sur %s", cp.returncode, media_path)
        return None

    try:
        parsed = json.loads(cp.stdout or "{}")
    except (json.JSONDecodeError, ValueError):
        return None

    streams = parsed.get("streams") if isinstance(parsed, dict) else None
    if not isinstance(streams, list) or not streams:
        return None
    stream = streams[0]
    if not isinstance(stream, dict):
        return None

    codec = str(stream.get("codec_name") or "").strip().lower()
    if codec not in ("av1", "av01"):
        return None

    side_data = stream.get("side_data_list") if isinstance(stream.get("side_data_list"), list) else []
    has_afgs1 = has_afgs1_in_side_data(side_data)

    # ffprobe n'expose pas encore tous les params per-frame (apply_grain, seed, etc.)
    # sans -show_frames. On marque present si AFGS1 T.35 est detecte OU si un
    # indice "apply_grain" apparait explicitement dans le stream.
    apply_grain_flag = False
    grain_seed: Optional[int] = None
    ar_lag: Optional[int] = None
    num_y: Optional[int] = None
    raw: Optional[Dict[str, Any]] = None

    for item in side_data:
        if not isinstance(item, dict):
            continue
        if "apply_grain" in item:
            try:
                apply_grain_flag = bool(int(item.get("apply_grain") or 0))
            except (ValueError, TypeError):
                apply_grain_flag = False
        if "grain_seed" in item:
            try:
                grain_seed = int(item.get("grain_seed") or 0)
            except (ValueError, TypeError):
                grain_seed = None
        if "ar_coeff_lag" in item:
            try:
                ar_lag = int(item.get("ar_coeff_lag") or 0)
            except (ValueError, TypeError):
                ar_lag = None
        if "num_y_points" in item:
            try:
                num_y = int(item.get("num_y_points") or 0)
            except (ValueError, TypeError):
                num_y = None
        if raw is None and any(k in item for k in ("apply_grain", "grain_seed", "ar_coeff_lag")):
            raw = dict(item)

    present = has_afgs1 or apply_grain_flag
    if not present:
        return None

    return Av1FilmGrainInfo(
        present=True,
        apply_grain=apply_grain_flag,
        grain_seed=grain_seed,
        ar_coeff_lag=ar_lag,
        num_y_points=num_y,
        has_afgs1_t35=has_afgs1,
        raw_params=raw,
    )
