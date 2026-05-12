"""HDR metadata (§5 v7.5.0) — classification + validation + scoring qualite.

Pass 1 (non-intrusif) : extrait le type HDR, MaxCLL/MaxFALL, luminance du
mastering display, a partir du JSON ffprobe deja parse. Zero subprocess.

Pass 2 (opt-in) : verifie la presence HDR10+ via scan de 5 frames
(SMPTE ST 2094-40). Coute ~500-800ms, active seulement si analyse
perceptuelle activee ET fichier HDR10 deja detecte.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .constants import (
    DV_PROFILE_WARNINGS_FR,
    DV_QUALITY_SCORE,
    HDR_MAX_CLL_WARNING_THRESHOLD,
    HDR_QUALITY_SCORE,
)
from cinesort.infra.subprocess_safety import tracked_run

from .ffmpeg_runner import _runner_platform_kwargs

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Detection strings dans les side_data_list ffprobe
# ---------------------------------------------------------------------------
_SIDE_DATA_DV_MARKERS = (
    "DOVI configuration record",
    "dovi",
    "dolby vision",
)
_SIDE_DATA_HDR10_PLUS_MARKERS = (
    "SMPTE ST 2094-40",
    "HDR Dynamic Metadata",
    "HDR10+",
    "Dynamic HDR+",
)
_SIDE_DATA_MASTERING = (
    "Mastering display metadata",
    "mastering_display_metadata",
)
_SIDE_DATA_CONTENT_LIGHT = (
    "Content light level metadata",
    "content_light_level_metadata",
    "Content Light Level",
)


@dataclass(frozen=True)
class HdrInfo:
    """Resultat de l'analyse HDR (Pass 1)."""

    hdr_type: str  # "sdr" | "hdr10" | "hdr10_plus" | "hlg" | "dolby_vision"
    max_cll: float  # nits, 0 si absent
    max_fall: float  # nits, 0 si absent
    min_luminance: float  # nits (du mastering display)
    max_luminance: float  # nits
    color_primaries: str
    color_transfer: str
    color_space: str
    is_valid: bool
    validation_flag: Optional[str]
    quality_score: int


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def parse_ratio(value: Any) -> float:
    """Parse un ratio ffprobe type '10000000/10000' en float.

    Exemples :
        parse_ratio("10000000/10000") -> 1000.0
        parse_ratio("34000/50000")    -> 0.68
        parse_ratio(None)             -> 0.0
        parse_ratio("invalid")        -> 0.0
    """
    if value is None:
        return 0.0
    s = str(value).strip()
    if not s:
        return 0.0
    if "/" in s:
        try:
            num_str, den_str = s.split("/", 1)
            num = float(num_str)
            den = float(den_str)
            # Comparaison float robuste : den peut etre tres petit (1e-300)
            # apres parsing/normalisation mais != 0.0 exact. Cf issue #31.
            if abs(den) < 1e-9:
                return 0.0
            return num / den
        except (ValueError, TypeError):
            return 0.0
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _side_data_contains(side_data_list: List[Dict[str, Any]], markers: Tuple[str, ...]) -> bool:
    """True si au moins un item du side_data_list matche un marqueur (case-insensitive)."""
    if not side_data_list:
        return False
    for item in side_data_list:
        if not isinstance(item, dict):
            continue
        blob = " ".join(str(v) for v in item.values()).lower()
        for marker in markers:
            if marker.lower() in blob:
                return True
    return False


def _side_data_find(side_data_list: List[Dict[str, Any]], markers: Tuple[str, ...]) -> Optional[Dict[str, Any]]:
    """Retourne le premier item matchant un marqueur, ou None."""
    if not side_data_list:
        return None
    for item in side_data_list:
        if not isinstance(item, dict):
            continue
        blob = " ".join(str(v) for v in item.values()).lower()
        for marker in markers:
            if marker.lower() in blob:
                return item
    return None


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def detect_hdr_type(
    color_primaries: str,
    color_transfer: str,
    side_data_list: List[Dict[str, Any]],
) -> str:
    """Classifie le type HDR selon priorite stricte.

    Priorite :
      1. HLG (arib-std-b67 transfer) — utilise pour broadcast
      2. Dolby Vision (DOVI config record)
      3. HDR10+ (SMPTE ST 2094-40 dynamic metadata)
      4. HDR10 (smpte2084 + bt2020)
      5. SDR (default)
    """
    transfer = (color_transfer or "").strip().lower()
    primaries = (color_primaries or "").strip().lower()

    if "arib-std-b67" in transfer or "hlg" in transfer:
        return "hlg"

    if _side_data_contains(side_data_list, _SIDE_DATA_DV_MARKERS):
        return "dolby_vision"

    if _side_data_contains(side_data_list, _SIDE_DATA_HDR10_PLUS_MARKERS):
        return "hdr10_plus"

    if "smpte2084" in transfer and "bt2020" in primaries:
        return "hdr10"
    # Certains fichiers HDR10 n'ont pas color_primaries taggé ; le side_data
    # mastering display suffit comme indice.
    if "smpte2084" in transfer:
        if _side_data_contains(side_data_list, _SIDE_DATA_MASTERING):
            return "hdr10"

    return "sdr"


def _extract_mastering_display(side_data_list: List[Dict[str, Any]]) -> Tuple[float, float]:
    """Retourne (min_luminance, max_luminance) en nits depuis les side_data."""
    item = _side_data_find(side_data_list, _SIDE_DATA_MASTERING)
    if not item:
        return (0.0, 0.0)
    min_lum = parse_ratio(item.get("min_luminance"))
    max_lum = parse_ratio(item.get("max_luminance"))
    return (min_lum, max_lum)


def _extract_content_light(side_data_list: List[Dict[str, Any]]) -> Tuple[float, float]:
    """Retourne (max_cll, max_fall) en nits depuis les side_data."""
    item = _side_data_find(side_data_list, _SIDE_DATA_CONTENT_LIGHT)
    if not item:
        return (0.0, 0.0)
    try:
        max_cll = float(item.get("max_content") or item.get("MaxCLL") or 0)
    except (ValueError, TypeError):
        max_cll = 0.0
    try:
        max_fall = float(item.get("max_average") or item.get("MaxFALL") or 0)
    except (ValueError, TypeError):
        max_fall = 0.0
    return (max_cll, max_fall)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_hdr(
    hdr_type: str,
    max_cll: float,
    max_fall: float,
    color_primaries: str,
) -> Tuple[bool, Optional[str]]:
    """Valide la coherence HDR.

    Returns:
        (is_valid, flag) ou flag parmi :
          "hdr_metadata_missing"       : HDR10 declare mais MaxCLL manquant
          "hdr_low_punch"              : HDR10 valide mais MaxCLL < 500 nits
          "color_mismatch_sdr_bt2020"  : SDR taggé mais primaries BT.2020
          None                         : tout va bien
    """
    primaries = (color_primaries or "").lower()

    if hdr_type == "sdr" and "bt2020" in primaries:
        return (False, "color_mismatch_sdr_bt2020")

    if hdr_type == "hdr10":
        if max_cll <= 0:
            return (False, "hdr_metadata_missing")
        if max_cll < HDR_MAX_CLL_WARNING_THRESHOLD:
            return (True, "hdr_low_punch")
        return (True, None)

    # HDR10+, Dolby Vision, HLG, SDR (sans bt2020) : OK par defaut
    return (True, None)


# ---------------------------------------------------------------------------
# Scoring qualite
# ---------------------------------------------------------------------------


def compute_hdr_quality_score(hdr_info: HdrInfo) -> int:
    """Score qualite HDR 0-100 pour comparaison de doublons (§16)."""
    t = hdr_info.hdr_type
    if t == "dolby_vision":
        return HDR_QUALITY_SCORE["dolby_vision"]
    if t == "hdr10_plus":
        return HDR_QUALITY_SCORE["hdr10_plus"]
    if t == "hdr10":
        if hdr_info.validation_flag == "hdr_metadata_missing":
            return HDR_QUALITY_SCORE["hdr10_invalid"]
        if hdr_info.validation_flag == "hdr_low_punch":
            return HDR_QUALITY_SCORE["hdr10_low_punch"]
        return HDR_QUALITY_SCORE["hdr10_valid"]
    if t == "hlg":
        return HDR_QUALITY_SCORE["hlg"]
    return HDR_QUALITY_SCORE["sdr"]


# ---------------------------------------------------------------------------
# Pass 1 — analyse depuis frame_data deja disponible
# ---------------------------------------------------------------------------


def analyze_hdr_from_frame_data(
    video_stream: Dict[str, Any],
    frame: Optional[Dict[str, Any]] = None,
) -> HdrInfo:
    """Pass 1 : extrait l'info HDR depuis le JSON ffprobe deja parse.

    Args:
        video_stream: dict `streams[i]` pour la piste video.
        frame: dict `frames[0]` si disponible (preferable car contient
            systematiquement les side_data). Sinon fallback sur le stream.

    Returns:
        HdrInfo sans subprocess.
    """
    # Les side_data peuvent etre dans la frame ou dans le stream
    frame_side = frame.get("side_data_list") if isinstance(frame, dict) else None
    stream_side = video_stream.get("side_data_list")
    side_data_list: List[Dict[str, Any]] = []
    if isinstance(frame_side, list):
        side_data_list.extend(x for x in frame_side if isinstance(x, dict))
    if isinstance(stream_side, list):
        side_data_list.extend(x for x in stream_side if isinstance(x, dict))

    # Metadata color — prefere la frame (plus fiable car mesure)
    def _col(key: str) -> str:
        if isinstance(frame, dict) and frame.get(key):
            return str(frame.get(key))
        return str(video_stream.get(key) or "")

    color_primaries = _col("color_primaries")
    color_transfer = _col("color_transfer")
    color_space = _col("color_space")

    hdr_type = detect_hdr_type(color_primaries, color_transfer, side_data_list)
    min_lum, max_lum = _extract_mastering_display(side_data_list)
    max_cll, max_fall = _extract_content_light(side_data_list)
    is_valid, flag = validate_hdr(hdr_type, max_cll, max_fall, color_primaries)

    hdr_info = HdrInfo(
        hdr_type=hdr_type,
        max_cll=max_cll,
        max_fall=max_fall,
        min_luminance=min_lum,
        max_luminance=max_lum,
        color_primaries=color_primaries,
        color_transfer=color_transfer,
        color_space=color_space,
        is_valid=is_valid,
        validation_flag=flag,
        quality_score=0,  # calcule ci-dessous via score_with_self()
    )
    score = compute_hdr_quality_score(hdr_info)
    # HdrInfo est frozen : recree avec le score
    return HdrInfo(
        hdr_type=hdr_info.hdr_type,
        max_cll=hdr_info.max_cll,
        max_fall=hdr_info.max_fall,
        min_luminance=hdr_info.min_luminance,
        max_luminance=hdr_info.max_luminance,
        color_primaries=hdr_info.color_primaries,
        color_transfer=hdr_info.color_transfer,
        color_space=hdr_info.color_space,
        is_valid=hdr_info.is_valid,
        validation_flag=hdr_info.validation_flag,
        quality_score=score,
    )


# ---------------------------------------------------------------------------
# Pass 2 — detection HDR10+ multi-frames
# ---------------------------------------------------------------------------


def detect_hdr10_plus_multi_frame(
    ffprobe_path: str,
    media_path: str,
    *,
    num_frames: int = 5,
    timeout_s: float = 15.0,
) -> bool:
    """Pass 2 : detecte HDR10+ via scan de `num_frames` frames.

    HDR10+ est signale par la presence de SMPTE ST 2094-40 dans les side_data
    de frames individuelles (metadata dynamique per-scene).

    Returns:
        True si au moins une frame scannee contient du HDR10+ metadata.
        False sur timeout/erreur/absence.
    """
    if not ffprobe_path or not media_path:
        return False

    cmd = [
        ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-select_streams",
        "v:0",
        "-show_frames",
        "-read_intervals",
        f"%+#{int(num_frames)}",
        "-show_entries",
        "frame=side_data_list",
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
        logger.warning("hdr10_plus: ffprobe timeout apres %ss sur %s", timeout_s, media_path)
        return False
    except OSError as exc:
        logger.warning("hdr10_plus: ffprobe OSError sur %s: %s", media_path, exc)
        return False

    if cp.returncode != 0:
        logger.warning("hdr10_plus: ffprobe returncode=%d sur %s", cp.returncode, media_path)
        return False

    try:
        parsed = json.loads(cp.stdout or "{}")
    except (json.JSONDecodeError, ValueError):
        return False

    frames = parsed.get("frames") if isinstance(parsed, dict) else None
    if not isinstance(frames, list):
        return False

    for fr in frames:
        if not isinstance(fr, dict):
            continue
        side = fr.get("side_data_list")
        if isinstance(side, list) and _side_data_contains(side, _SIDE_DATA_HDR10_PLUS_MARKERS):
            return True
    return False


# ---------------------------------------------------------------------------
# §6 v7.5.0 — Dolby Vision profile classification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DolbyVisionInfo:
    """Resultat de la classification Dolby Vision."""

    present: bool
    profile: str  # "5" | "7" | "8.1" | "8.2" | "8.4" | "unknown" | "none"
    compatibility: str  # "none" | "hdr10_full" | "hdr10_partial" | "sdr" | "hlg"
    el_present: bool
    rpu_present: bool
    warning: Optional[str]  # message FR pour l'UI
    quality_score: int


def extract_dv_configuration(side_data_list: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Cherche le DOVI configuration record dans side_data_list.

    Returns:
        Dict avec les champs DV (dv_profile, compat_id, rpu_present, el_present, bl_present)
        ou None si aucun DV detecte.
    """
    if not side_data_list:
        return None
    for item in side_data_list:
        if not isinstance(item, dict):
            continue
        side_type = str(item.get("side_data_type") or "").lower()
        if "dovi" not in side_type and "dolby vision" not in side_type:
            continue
        # Normalise les champs (tolerant aux formats int/str)
        try:
            dv_profile = int(item.get("dv_profile") or 0)
        except (ValueError, TypeError):
            dv_profile = 0
        try:
            compat_id = int(item.get("dv_bl_signal_compatibility_id") or 0)
        except (ValueError, TypeError):
            compat_id = 0

        def _flag(key: str) -> bool:
            v = item.get(key)
            if v is None:
                return False
            try:
                return int(v) == 1
            except (ValueError, TypeError):
                s = str(v).strip().lower()
                return s in ("1", "true", "yes")

        return {
            "dv_profile": dv_profile,
            "compat_id": compat_id,
            "rpu_present": _flag("rpu_present_flag"),
            "el_present": _flag("el_present_flag"),
            "bl_present": _flag("bl_present_flag"),
        }
    return None


def classify_dv_profile(
    dv_profile: int,
    compat_id: int,
    el_present: bool,
    rpu_present: bool,
) -> DolbyVisionInfo:
    """Classifie le profil DV selon dv_profile + compat_id + flags.

    Regles :
      - profile=5 -> "5", compat="none"
      - profile=7 OU el_present=1 -> "7", compat="hdr10_partial"
      - profile=8 + compat_id=1 -> "8.1", compat="hdr10_full"
      - profile=8 + compat_id=2 -> "8.2", compat="sdr"
      - profile=8 + compat_id=4 -> "8.4", compat="hlg"
      - autre -> "unknown"
    """
    # Profile 5 : IPTPQc2 proprietary
    if dv_profile == 5:
        return DolbyVisionInfo(
            present=True,
            profile="5",
            compatibility="none",
            el_present=el_present,
            rpu_present=rpu_present,
            warning=DV_PROFILE_WARNINGS_FR.get("5"),
            quality_score=DV_QUALITY_SCORE["5"],
        )

    # Profile 7 : BL+EL+RPU (UHD Blu-ray originaux)
    if dv_profile == 7 or (dv_profile == 0 and el_present):
        return DolbyVisionInfo(
            present=True,
            profile="7",
            compatibility="hdr10_partial",
            el_present=el_present,
            rpu_present=rpu_present,
            warning=DV_PROFILE_WARNINGS_FR.get("7"),
            quality_score=DV_QUALITY_SCORE["7"],
        )

    # Profile 8 : sub-profiles via compat_id
    if dv_profile == 8:
        if compat_id == 1:
            return DolbyVisionInfo(
                present=True,
                profile="8.1",
                compatibility="hdr10_full",
                el_present=el_present,
                rpu_present=rpu_present,
                warning=None,
                quality_score=DV_QUALITY_SCORE["8.1"],
            )
        if compat_id == 2:
            return DolbyVisionInfo(
                present=True,
                profile="8.2",
                compatibility="sdr",
                el_present=el_present,
                rpu_present=rpu_present,
                warning=None,
                quality_score=DV_QUALITY_SCORE["8.2"],
            )
        if compat_id == 4:
            return DolbyVisionInfo(
                present=True,
                profile="8.4",
                compatibility="hlg",
                el_present=el_present,
                rpu_present=rpu_present,
                warning=None,
                quality_score=DV_QUALITY_SCORE["8.4"],
            )
        # Profile 8 avec compat_id inconnu
        return DolbyVisionInfo(
            present=True,
            profile="unknown",
            compatibility="none",
            el_present=el_present,
            rpu_present=rpu_present,
            warning=DV_PROFILE_WARNINGS_FR.get("unknown"),
            quality_score=DV_QUALITY_SCORE["unknown"],
        )

    # Autre profil ou combinaison inconnue
    return DolbyVisionInfo(
        present=True,
        profile="unknown",
        compatibility="none",
        el_present=el_present,
        rpu_present=rpu_present,
        warning=DV_PROFILE_WARNINGS_FR.get("unknown"),
        quality_score=DV_QUALITY_SCORE["unknown"],
    )


def detect_invalid_dv(dv_info: DolbyVisionInfo) -> Optional[str]:
    """Detecte les DV pathologiques.

    Returns:
        Flag warning ou None :
          "dv_invalid_no_rpu"      : tagge DV mais pas de RPU
          "dv_el_expected_missing" : profile 7 annonce mais EL absent
    """
    if not dv_info.present:
        return None
    if not dv_info.rpu_present:
        return "dv_invalid_no_rpu"
    if dv_info.profile == "7" and not dv_info.el_present:
        return "dv_el_expected_missing"
    return None


def compute_dv_quality_score(dv_info: DolbyVisionInfo) -> int:
    """Score qualite DV 0-100 pour comparaison §16."""
    if not dv_info.present:
        return DV_QUALITY_SCORE["none"]
    return DV_QUALITY_SCORE.get(dv_info.profile, DV_QUALITY_SCORE["unknown"])


def analyze_dv_from_frame_data(
    video_stream: Dict[str, Any],
    frame: Optional[Dict[str, Any]] = None,
) -> DolbyVisionInfo:
    """Pass 1 DV : extrait l'info DV depuis le JSON ffprobe deja parse.

    Mutualise le side_data_list avec §5 HDR (meme call ffprobe).
    """
    frame_side = frame.get("side_data_list") if isinstance(frame, dict) else None
    stream_side = video_stream.get("side_data_list")
    side_data_list: List[Dict[str, Any]] = []
    if isinstance(frame_side, list):
        side_data_list.extend(x for x in frame_side if isinstance(x, dict))
    if isinstance(stream_side, list):
        side_data_list.extend(x for x in stream_side if isinstance(x, dict))

    config = extract_dv_configuration(side_data_list)
    if config is None:
        return DolbyVisionInfo(
            present=False,
            profile="none",
            compatibility="none",
            el_present=False,
            rpu_present=False,
            warning=None,
            quality_score=DV_QUALITY_SCORE["none"],
        )

    dv_info = classify_dv_profile(
        dv_profile=config["dv_profile"],
        compat_id=config["compat_id"],
        el_present=config["el_present"],
        rpu_present=config["rpu_present"],
    )
    # Ecrase le warning si invalid_dv detecte
    invalid_flag = detect_invalid_dv(dv_info)
    if invalid_flag == "dv_invalid_no_rpu":
        dv_info = DolbyVisionInfo(
            present=dv_info.present,
            profile=dv_info.profile,
            compatibility=dv_info.compatibility,
            el_present=dv_info.el_present,
            rpu_present=dv_info.rpu_present,
            warning="Fichier tagge DV sans RPU : metadonnees dynamiques absentes.",
            quality_score=dv_info.quality_score,
        )
    elif invalid_flag == "dv_el_expected_missing":
        dv_info = DolbyVisionInfo(
            present=dv_info.present,
            profile=dv_info.profile,
            compatibility=dv_info.compatibility,
            el_present=dv_info.el_present,
            rpu_present=dv_info.rpu_present,
            warning="Profile 7 annonce sans Enhancement Layer (rip incomplet ?).",
            quality_score=dv_info.quality_score,
        )
    return dv_info
