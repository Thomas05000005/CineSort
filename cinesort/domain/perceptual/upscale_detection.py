"""Fake 4K / upscale detection via FFT 2D (§7 v7.5.0).

Principe : une 4K native contient des details fins qui se traduisent par de
l'energie dans les hautes frequences spatiales. Un upscale bicubique 1080p
-> 4K n'ajoute pas de HF authentiques -> ratio HF/total faible.

Complementaire de §13 SSIM self-ref :
  - SSIM detecte les upscales bicubiques simples (95% des cas)
  - FFT 2D detecte aussi les upscales IA (HF synthetiques incoherentes)

Combinaison pour verdict final robuste (2 signaux independants).
"""

from __future__ import annotations

import logging
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .constants import (
    FAKE_4K_FFT_HF_CUTOFF_RATIO,
    FAKE_4K_FFT_MIN_VARIANCE,
    FAKE_4K_FFT_MIN_Y_AVG,
    FAKE_4K_FFT_THRESHOLD_AMBIGUOUS,
    FAKE_4K_FFT_THRESHOLD_NATIVE,
    FAKE_4K_MIN_HEIGHT,
    SSIM_SELF_REF_FAKE_THRESHOLD,
)

logger = logging.getLogger(__name__)


def compute_fft_hf_ratio(
    pixels: List[int],
    width: int,
    height: int,
    hf_cutoff_ratio: float = FAKE_4K_FFT_HF_CUTOFF_RATIO,
) -> float:
    """Calcule le ratio energie HF / totale via FFT 2D.

    Args:
        pixels: liste de pixels luminance (Y plan) de longueur width * height.
        width, height: dimensions de la frame.
        hf_cutoff_ratio: seuil frequentiel (0.25 = dernier quart de Nyquist).

    Returns:
        Ratio 0.0-1.0. 0.0 si erreur ou pixels invalides.
    """
    w, h = int(width), int(height)
    if w <= 0 or h <= 0:
        return 0.0
    expected = w * h
    if not pixels or len(pixels) < expected:
        return 0.0

    try:
        frame_y = np.asarray(pixels[:expected], dtype=np.float64).reshape(h, w)
    except (ValueError, TypeError):
        return 0.0

    try:
        spectrum = np.fft.fftshift(np.fft.fft2(frame_y))
    except (ValueError, FloatingPointError):
        return 0.0

    magnitude = np.abs(spectrum)

    # Masque HF : anneau exterieur (distance > hf_cutoff * min(h,w)/2)
    cy, cx = h // 2, w // 2
    y, x = np.ogrid[:h, :w]
    distance = np.sqrt((y - cy) ** 2 + (x - cx) ** 2)
    max_radius = min(h, w) / 2.0
    hf_mask = distance > (hf_cutoff_ratio * max_radius)

    magnitude_sq = magnitude * magnitude
    total_energy = float(np.sum(magnitude_sq))
    if total_energy <= 0.0:
        return 0.0
    hf_energy = float(np.sum(magnitude_sq[hf_mask]))
    return hf_energy / total_energy


def is_frame_usable_for_fft(
    pixels: List[int],
    width: int,
    height: int,
    y_avg: float,
    variance: Optional[float] = None,
) -> bool:
    """Filtre les frames non utilisables pour l'analyse FFT.

    Exclut :
      - pixels tronques (len < width * height * 0.9)
      - frames trop sombres (y_avg < FAKE_4K_FFT_MIN_Y_AVG)
      - frames uniformes (variance < FAKE_4K_FFT_MIN_VARIANCE)
    """
    w, h = int(width), int(height)
    if w <= 0 or h <= 0:
        return False
    expected = w * h
    if not pixels or len(pixels) < int(expected * 0.9):
        return False
    if float(y_avg) < FAKE_4K_FFT_MIN_Y_AVG:
        return False
    if variance is not None and float(variance) < FAKE_4K_FFT_MIN_VARIANCE:
        return False
    return True


def compute_fft_hf_ratio_median(
    frames_data: List[Dict[str, Any]],
    video_width: int,
    video_height: int,
) -> Optional[float]:
    """Calcule le ratio HF/Total median sur les frames utilisables.

    Args:
        frames_data: frames extraites (dicts avec pixels, width, height, y_avg).
        video_width, video_height: resolution native (reference).

    Returns:
        Mediane des ratios (0.0-1.0), ou None si < 2 frames utilisables.
    """
    if not frames_data:
        return None

    ratios: List[float] = []
    for frame in frames_data:
        if not isinstance(frame, dict):
            continue
        pixels = frame.get("pixels")
        if not isinstance(pixels, list):
            continue
        fw = int(frame.get("width") or video_width or 0)
        fh = int(frame.get("height") or video_height or 0)
        y_avg = float(frame.get("y_avg") or 0.0)
        variance = frame.get("variance")
        if not is_frame_usable_for_fft(pixels, fw, fh, y_avg, variance):
            continue
        ratio = compute_fft_hf_ratio(pixels, fw, fh)
        if ratio > 0:
            ratios.append(ratio)

    if len(ratios) < 2:
        return None
    return float(median(ratios))


def classify_fake_4k_fft(
    fft_hf_ratio: Optional[float],
    video_height: int,
    is_animation: bool,
) -> Tuple[str, float]:
    """Classifie le ratio FFT en verdict textuel.

    Verdicts §7 seul :
      "not_applicable_resolution" : height < FAKE_4K_MIN_HEIGHT (conf 0)
      "not_applicable_animation"  : is_animation (conf 0)
      "insufficient_frames"       : ratio is None (conf 0)
      "4k_native"                 : ratio >= 0.18 (conf 0.85)
      "ambiguous_2k_di"           : 0.08 <= ratio < 0.18 (conf 0.60)
      "fake_4k_bicubic"           : ratio < 0.08 (conf 0.90)

    Returns:
        (verdict, confidence) confidence en 0.0-1.0.
    """
    if int(video_height) < FAKE_4K_MIN_HEIGHT:
        return ("not_applicable_resolution", 0.0)
    if is_animation:
        return ("not_applicable_animation", 0.0)
    if fft_hf_ratio is None:
        return ("insufficient_frames", 0.0)
    if fft_hf_ratio >= FAKE_4K_FFT_THRESHOLD_NATIVE:
        return ("4k_native", 0.85)
    if fft_hf_ratio >= FAKE_4K_FFT_THRESHOLD_AMBIGUOUS:
        return ("ambiguous_2k_di", 0.60)
    return ("fake_4k_bicubic", 0.90)


def combine_fake_4k_verdicts(
    fft_ratio: Optional[float],
    ssim_self_ref: Optional[float],
) -> Tuple[str, float]:
    """Combine les verdicts FFT (§7) + SSIM self-ref (§13).

    Args:
        fft_ratio: ratio FFT median, None si non applicable.
        ssim_self_ref: score SSIM Y 0.0-1.0, None ou -1 si non calcule.

    Returns:
        "fake_4k_confirmed" : les 2 concluent fake (conf 0.95)
        "fake_4k_probable"  : un seul conclut fake (conf 0.70)
        "4k_native"         : aucun ne conclut fake (conf 0.90)
        "ambiguous"         : les 2 sont indisponibles (conf 0.30)
    """
    # Normalise : SSIM peut etre None ou -1 (flag "non calcule")
    ssim_available = ssim_self_ref is not None and ssim_self_ref >= 0
    fft_available = fft_ratio is not None

    if not fft_available and not ssim_available:
        return ("ambiguous", 0.30)

    fft_says_fake = fft_available and fft_ratio < FAKE_4K_FFT_THRESHOLD_AMBIGUOUS
    ssim_says_fake = ssim_available and ssim_self_ref >= SSIM_SELF_REF_FAKE_THRESHOLD

    if fft_says_fake and ssim_says_fake:
        return ("fake_4k_confirmed", 0.95)
    if fft_says_fake or ssim_says_fake:
        return ("fake_4k_probable", 0.70)
    return ("4k_native", 0.90)
