"""Extraction de frames representatives pour l'analyse perceptuelle."""

from __future__ import annotations

import logging
import struct
from typing import Any, Dict, List, Optional

from .constants import (
    FRAME_DOWNSCALE_THRESHOLD,
    FRAME_MIN_INTER_DIFF,
    FRAME_MIN_VARIANCE_8BIT,
    FRAME_MIN_VARIANCE_10BIT,
    FRAME_REPLACEMENT_ATTEMPTS,
)
from .ffmpeg_runner import run_ffmpeg_binary
from .scene_detection import (
    detect_scene_keyframes,
    merge_hybrid_timestamps,
    should_skip_scene_detection,
)

logger = logging.getLogger(__name__)

# Timeout par extraction de frame unique (secondes)
_FRAME_EXTRACT_TIMEOUT_S = 30.0

# Nombre minimum de frames meme pour un film tres court
_MIN_FRAMES_SHORT_FILM = 3
_SHORT_FILM_DURATION_S = 120.0  # < 2 minutes


# ---------------------------------------------------------------------------
# Calcul des timestamps
# ---------------------------------------------------------------------------


def compute_timestamps(
    duration_s: float,
    frames_count: int = 10,
    skip_percent: int = 5,
) -> List[float]:
    """Calcule des timestamps deterministes, uniformement repartis.

    Les premiers et derniers ``skip_percent`` % de la duree sont ignores
    (generiques, logos studio). Le nombre de frames est clampe entre 5 et 50,
    sauf pour les films tres courts (< 2 min) ou le minimum est 3.
    """
    dur = max(0.0, float(duration_s))
    if dur <= 0:
        return []

    skip_pct = max(0, min(20, int(skip_percent)))
    is_short = dur < _SHORT_FILM_DURATION_S

    # Clamper le nombre de frames
    if is_short:
        count = max(_MIN_FRAMES_SHORT_FILM, min(50, int(frames_count)))
    else:
        count = max(5, min(50, int(frames_count)))

    skip_s = dur * skip_pct / 100.0
    useful = dur - 2.0 * skip_s
    if useful <= 0:
        # Duree trop courte pour le skip demande : utiliser toute la duree
        skip_s = 0.0
        useful = dur

    # Adapter le nombre de frames si on en demande plus que la duree le permet
    # (eviter des timestamps espaces de < 1s)
    max_reasonable = max(_MIN_FRAMES_SHORT_FILM, int(useful))
    count = min(count, max_reasonable)

    step = useful / count
    timestamps = [round(skip_s + i * step + step / 2.0, 3) for i in range(count)]
    # S'assurer qu'aucun timestamp ne depasse la duree
    return [t for t in timestamps if t < dur]


# ---------------------------------------------------------------------------
# Parsing des frames brutes
# ---------------------------------------------------------------------------


def parse_raw_frame(data: bytes, width: int, height: int, bit_depth: int = 8) -> List[int]:
    """Parse les bytes bruts d'une frame Y en liste de pixels.

    - 8-bit  (pix_fmt gray)    : chaque byte = valeur Y 0-255.
    - 10-bit (pix_fmt gray16le): chaque paire = uint16 LE, shift >> 6 pour 0-1023.
    Retourne une liste vide si les donnees sont tronquees.
    """
    w, h = int(width), int(height)
    if w <= 0 or h <= 0:
        return []

    if bit_depth >= 10:
        expected = w * h * 2
        if len(data) < expected:
            return []
        raw = struct.unpack(f"<{w * h}H", data[:expected])
        return [min(v >> 6, 1023) for v in raw]

    # 8-bit
    expected = w * h
    if len(data) < expected:
        return []
    return list(data[:expected])


# ---------------------------------------------------------------------------
# Validation de frame
# ---------------------------------------------------------------------------


def is_valid_frame(pixels: List[int], width: int, height: int, bit_depth: int = 8) -> bool:
    """Verifie qu'une frame n'est pas noire, vide ou tronquee."""
    expected_count = int(width) * int(height)
    if len(pixels) < int(expected_count * 0.9):
        return False
    if not pixels:
        return False

    n = len(pixels)
    mean = sum(pixels) / n
    variance = sum((p - mean) ** 2 for p in pixels) / n

    threshold = FRAME_MIN_VARIANCE_10BIT if bit_depth >= 10 else FRAME_MIN_VARIANCE_8BIT
    return variance >= threshold


# ---------------------------------------------------------------------------
# Difference inter-frame
# ---------------------------------------------------------------------------


def compute_inter_frame_diff(pixels_a: List[int], pixels_b: List[int]) -> float:
    """Difference moyenne absolue entre deux frames (meme taille)."""
    n = min(len(pixels_a), len(pixels_b))
    if n == 0:
        return 0.0
    total = sum(abs(a - b) for a, b in zip(pixels_a[:n], pixels_b[:n]))
    return total / n


# ---------------------------------------------------------------------------
# Extraction d'une frame unique
# ---------------------------------------------------------------------------


def extract_single_frame(
    ffmpeg_path: str,
    media_path: str,
    timestamp: float,
    width: int,
    height: int,
    bit_depth: int = 8,
    timeout_s: float = _FRAME_EXTRACT_TIMEOUT_S,
) -> bytes:
    """Extrait une frame Y brute via ffmpeg.

    Si ``width`` > FRAME_DOWNSCALE_THRESHOLD, un filtre ``scale=1920:-1`` est
    applique pour reduire la charge d'analyse pixel (les filtres ffmpeg Phase 2-B
    tourneront sur la resolution native).
    """
    pix_fmt = "gray16le" if bit_depth >= 10 else "gray"

    cmd = [
        ffmpeg_path,
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        str(media_path),
    ]

    # Downscale 4K+ pour l'analyse pixel
    if int(width) > FRAME_DOWNSCALE_THRESHOLD:
        cmd += ["-vf", "scale=1920:-1"]

    cmd += [
        "-frames:v",
        "1",
        "-f",
        "rawvideo",
        "-pix_fmt",
        pix_fmt,
        "-v",
        "error",
        "pipe:1",
    ]

    rc, stdout, stderr = run_ffmpeg_binary(cmd, timeout_s)
    if rc != 0:
        logger.debug("ffmpeg frame extraction failed rc=%d ts=%.3f stderr=%s", rc, timestamp, stderr[:200])
        return b""
    return stdout


# ---------------------------------------------------------------------------
# Orchestrateur : extraction de frames representatives
# ---------------------------------------------------------------------------


def extract_representative_frames(
    ffmpeg_path: str,
    media_path: str,
    duration_s: float,
    width: int,
    height: int,
    bit_depth: int = 8,
    *,
    frames_count: int = 10,
    skip_percent: int = 5,
    timeout_s: float = _FRAME_EXTRACT_TIMEOUT_S,
    scene_detection_enabled: bool = True,
) -> List[Dict[str, Any]]:
    """Extrait des frames representatives, avec validation et diversite.

    Retourne une liste de dicts ``{timestamp, pixels, width, height, y_avg}``.
    Les frames noires, tronquees ou trop similaires sont ecartees et remplacees
    si possible (jusqu'a ``FRAME_REPLACEMENT_ATTEMPTS`` tentatives par frame).

    §4 v7.5.0 : si ``scene_detection_enabled`` et duree >= 180 s, un scan
    ffmpeg detecte les keyframes de changement de scene et fusionne 50%/50%
    avec les timestamps uniformes (timestamps "interessants" privilegies).
    """
    if not ffmpeg_path or not media_path or duration_s <= 0:
        return []

    uniform_ts = compute_timestamps(duration_s, frames_count, skip_percent)
    if not uniform_ts:
        return []

    timestamps = uniform_ts
    if not should_skip_scene_detection(duration_s, scene_detection_enabled):
        keyframes = detect_scene_keyframes(ffmpeg_path, media_path)
        if keyframes:
            merged = merge_hybrid_timestamps(uniform_ts, keyframes, target_count=len(uniform_ts))
            if merged:
                timestamps = merged
                logger.info(
                    "scene_detection: %d keyframes -> %d ts hybride",
                    len(keyframes),
                    len(timestamps),
                )

    # Dimensions effectives apres eventuel downscale
    if int(width) > FRAME_DOWNSCALE_THRESHOLD:
        eff_w = 1920
        eff_h = max(1, int(round(int(height) * 1920 / int(width))))
    else:
        eff_w = int(width)
        eff_h = int(height)

    accepted: List[Dict[str, Any]] = []
    skipped = 0
    dur = float(duration_s)

    for ts in timestamps:
        frame = _try_extract_valid_frame(
            ffmpeg_path,
            media_path,
            ts,
            eff_w,
            eff_h,
            bit_depth,
            dur,
            timeout_s,
            accepted,
        )
        if frame is not None:
            accepted.append(frame)
        else:
            skipped += 1

    logger.debug(
        "Frames extraites: %d/%d demandees, %d omises — %s",
        len(accepted),
        len(timestamps),
        skipped,
        media_path,
    )
    return accepted


def _try_extract_valid_frame(
    ffmpeg_path: str,
    media_path: str,
    timestamp: float,
    eff_w: int,
    eff_h: int,
    bit_depth: int,
    duration_s: float,
    timeout_s: float,
    already_accepted: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Tente d'extraire une frame valide et diversifiee, avec remplacements."""
    # Tentative sur le timestamp principal + decalages
    offsets = [0.0] + [
        (i + 1) * duration_s * 0.02 * sign for i in range(FRAME_REPLACEMENT_ATTEMPTS) for sign in (1.0, -1.0)
    ]
    # Limiter aux premiers 1 + FRAME_REPLACEMENT_ATTEMPTS essais
    offsets = offsets[: 1 + FRAME_REPLACEMENT_ATTEMPTS]

    for offset in offsets:
        ts = timestamp + offset
        if ts < 0 or ts >= duration_s:
            continue

        raw = extract_single_frame(ffmpeg_path, media_path, ts, eff_w, eff_h, bit_depth, timeout_s)
        if not raw:
            continue

        pixels = parse_raw_frame(raw, eff_w, eff_h, bit_depth)
        if not pixels:
            continue

        if not is_valid_frame(pixels, eff_w, eff_h, bit_depth):
            continue

        # Verifier la diversite par rapport aux frames deja acceptees
        if _is_too_similar(pixels, already_accepted):
            continue

        n = len(pixels)
        y_avg = sum(pixels) / n if n > 0 else 0.0
        return {
            "timestamp": round(ts, 3),
            "pixels": pixels,
            "width": eff_w,
            "height": eff_h,
            "y_avg": round(y_avg, 2),
        }

    return None


def _is_too_similar(pixels: List[int], accepted: List[Dict[str, Any]]) -> bool:
    """Verifie si une frame est trop similaire a celles deja acceptees."""
    for frame in accepted:
        diff = compute_inter_frame_diff(pixels, frame["pixels"])
        if diff < FRAME_MIN_INTER_DIFF:
            return True
    return False
