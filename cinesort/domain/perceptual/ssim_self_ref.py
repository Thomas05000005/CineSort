"""SSIM self-referential (§13 v7.5.0) — detection fake 4K.

Principe : on compare l'image originale 4K avec sa version downscale 1080p
puis upscale 4K (bicubique). Si les hautes frequences manquent deja (upscale
fake), le "dommage" du downscale/upscale est minimal -> SSIM proche de 1.0.
Une vraie 4K native a des HF qui disparaissent au downscale, donc SSIM < 0.90.

Skip automatique si :
  - height < 1800 (non-4K, pas pertinent)
  - is_animation (aplats donnent des faux positifs)
  - duree insuffisante pour extraire un segment representatif
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from typing import List, Tuple

from .constants import (
    SSIM_SELF_REF_AMBIGUOUS_THRESHOLD,
    SSIM_SELF_REF_FAKE_THRESHOLD,
    SSIM_SELF_REF_MIN_HEIGHT,
    SSIM_SELF_REF_SEGMENT_DURATION_S,
    SSIM_SELF_REF_TIMEOUT_S,
)
from cinesort.domain._runners import tracked_run

from .ffmpeg_runner import _runner_platform_kwargs

logger = logging.getLogger(__name__)

# Stderr ffmpeg ssim typique :
#   [Parsed_ssim_2 @ 0x...] SSIM Y:0.862134 (8.636...) U:0.94... V:0.93... All:0.884... (9.369)
_RE_SSIM_Y = re.compile(r"SSIM[^\n]*?Y:([\d.]+)")
_RE_SSIM_ALL = re.compile(r"All:([\d.]+)")


@dataclass(frozen=True)
class SsimSelfRefResult:
    """Resultat de l'analyse SSIM self-referential."""

    ssim_y: float  # -1.0 = non applicable/erreur, sinon 0.0-1.0
    ssim_all: float  # -1.0 = non applicable/erreur, sinon 0.0-1.0
    upscale_verdict: str
    # "native" | "ambiguous" | "upscale_fake"
    # | "not_applicable_resolution" | "not_applicable_animation"
    # | "not_applicable_duration" | "disabled" | "error"
    confidence: float  # 0.0-1.0


def classify_ssim_verdict(ssim_y: float) -> Tuple[str, float]:
    """Classifie le score SSIM Y en verdict + confiance.

    >= 0.95 : upscale_fake (0.85)
    >= 0.90 : ambiguous    (0.60)
    <  0.90 : native       (0.90)
    """
    if ssim_y >= SSIM_SELF_REF_FAKE_THRESHOLD:
        return ("upscale_fake", 0.85)
    if ssim_y >= SSIM_SELF_REF_AMBIGUOUS_THRESHOLD:
        return ("ambiguous", 0.60)
    return ("native", 0.90)


def build_ssim_self_ref_command(
    ffmpeg_path: str,
    media_path: str,
    start_offset_s: float,
    duration_s: float,
) -> List[str]:
    """Construit la commande ffmpeg filter_complex pour SSIM self-referential.

    Split -> downscale 1080p bicubic -> upscale 4K bicubic -> SSIM contre l'original.
    """
    return [
        ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-ss",
        str(float(start_offset_s)),
        "-i",
        str(media_path),
        "-t",
        str(float(duration_s)),
        "-filter_complex",
        ("[0:v]split=2[a][b];[a]scale=1920:1080:flags=bicubic,scale=3840:2160:flags=bicubic[ref];[b][ref]ssim"),
        "-f",
        "null",
        "-v",
        "info",
        "-",
    ]


def compute_ssim_self_ref(
    ffmpeg_path: str,
    media_path: str,
    duration_s: float,
    video_height: int,
    *,
    is_animation: bool = False,
    segment_duration_s: float = SSIM_SELF_REF_SEGMENT_DURATION_S,
    timeout_s: float = SSIM_SELF_REF_TIMEOUT_S,
) -> SsimSelfRefResult:
    """Calcule le SSIM self-referential pour detecter les fake 4K.

    Returns:
        SsimSelfRefResult avec ssim_y/all + verdict + confidence.
    """
    # Skip early (pas de ffmpeg inutile)
    if int(video_height) < SSIM_SELF_REF_MIN_HEIGHT:
        return SsimSelfRefResult(-1.0, -1.0, "not_applicable_resolution", 0.0)
    if is_animation:
        return SsimSelfRefResult(-1.0, -1.0, "not_applicable_animation", 0.0)
    if float(duration_s) < float(segment_duration_s) + 30.0:
        return SsimSelfRefResult(-1.0, -1.0, "not_applicable_duration", 0.0)
    if not ffmpeg_path or not media_path:
        return SsimSelfRefResult(-1.0, -1.0, "error", 0.0)

    start_offset = max(0.0, (float(duration_s) - float(segment_duration_s)) / 2.0)
    cmd = build_ssim_self_ref_command(ffmpeg_path, media_path, start_offset, segment_duration_s)

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
        logger.warning("ssim_self_ref: ffmpeg timeout apres %ss sur %s", timeout_s, media_path)
        return SsimSelfRefResult(-1.0, -1.0, "error", 0.0)
    except OSError as exc:
        logger.warning("ssim_self_ref: ffmpeg OSError sur %s: %s", media_path, exc)
        return SsimSelfRefResult(-1.0, -1.0, "error", 0.0)

    if cp.returncode != 0:
        logger.warning("ssim_self_ref: ffmpeg returncode=%d sur %s", cp.returncode, media_path)
        return SsimSelfRefResult(-1.0, -1.0, "error", 0.0)

    stderr = cp.stderr or ""
    return _parse_ssim_stderr(stderr)


def _parse_ssim_stderr(stderr: str) -> SsimSelfRefResult:
    """Parse la sortie stderr du filtre SSIM pour extraire Y + All."""
    if not stderr:
        return SsimSelfRefResult(-1.0, -1.0, "error", 0.0)

    m_all = _RE_SSIM_ALL.search(stderr)
    m_y = _RE_SSIM_Y.search(stderr)
    if not m_y and not m_all:
        return SsimSelfRefResult(-1.0, -1.0, "error", 0.0)

    try:
        ssim_y = float(m_y.group(1)) if m_y else -1.0
    except (ValueError, TypeError):
        ssim_y = -1.0
    try:
        ssim_all = float(m_all.group(1)) if m_all else -1.0
    except (ValueError, TypeError):
        ssim_all = -1.0

    # Le verdict se base sur Y (luminance) qui reflete le mieux les HF visibles
    score_for_verdict = ssim_y if ssim_y >= 0 else ssim_all
    if score_for_verdict < 0:
        return SsimSelfRefResult(ssim_y, ssim_all, "error", 0.0)

    verdict, confidence = classify_ssim_verdict(score_for_verdict)
    return SsimSelfRefResult(ssim_y=ssim_y, ssim_all=ssim_all, upscale_verdict=verdict, confidence=confidence)
