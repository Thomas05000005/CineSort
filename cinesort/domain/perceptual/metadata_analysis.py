"""Metadata filters (§8 v7.5.0) — interlacing + crop + judder + IMAX.

4 analyses video basees sur des filtres ffmpeg natifs :
  - idet          : detection d'entrelacement (TFF/BFF/progressive)
  - cropdetect    : detection de bandes noires (letterbox/pillarbox/windowbox)
  - mpdecimate    : detection de judder / pulldown 3:2
  - IMAX          : derive des methodes precedentes + resolution + TMDb keywords

Les 3 filtres ffmpeg sont designees pour tourner en parallele via §1
(ThreadPool). IMAX est derive sans cout supplementaire.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .constants import (
    CROPDETECT_LIMIT,
    CROPDETECT_ROUND,
    CROPDETECT_SEGMENT_DURATION_S,
    IDET_INTERLACE_RATIO_THRESHOLD,
    IDET_SEGMENT_DURATION_S,
    IMAX_AR_DIGITAL_MAX,
    IMAX_AR_DIGITAL_MIN,
    IMAX_AR_FULL_FRAME_MAX,
    IMAX_AR_FULL_FRAME_MIN,
    IMAX_EXPANSION_AR_DELTA,
    IMAX_EXPANSION_SEGMENTS_COUNT,
    IMAX_NATIVE_RESOLUTION_MIN_HEIGHT,
    MPDECIMATE_JUDDER_HEAVY,
    MPDECIMATE_JUDDER_LIGHT,
    MPDECIMATE_JUDDER_PULLDOWN,
    MPDECIMATE_SEGMENT_DURATION_S,
)
from cinesort.infra.subprocess_safety import tracked_run

from .ffmpeg_runner import _runner_platform_kwargs

logger = logging.getLogger(__name__)

# Regex precompiles
_RE_IDET_MULTI = re.compile(
    r"Multi frame detection:\s*TFF:\s*(\d+)\s*BFF:\s*(\d+)\s*Progressive:\s*(\d+)\s*Undetermined:\s*(\d+)"
)
_RE_CROP = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")
_RE_MPDECIMATE_DROP = re.compile(r"\bdrop\s+pts")
_RE_MPDECIMATE_KEEP = re.compile(r"\bkeep\s+pts")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InterlaceInfo:
    detected: bool
    interlace_type: str  # "progressive" | "tff" | "bff" | "mixed" | "unknown"
    tff_count: int
    bff_count: int
    progressive_count: int


@dataclass(frozen=True)
class CropSegment:
    start_s: float
    crop_w: int
    crop_h: int
    crop_x: int
    crop_y: int
    aspect_ratio: float


@dataclass(frozen=True)
class CropInfo:
    has_bars: bool
    verdict: str  # full_frame|letterbox_2_35|letterbox_2_39|pillarbox|windowbox|letterbox_other|unknown
    detected_w: int
    detected_h: int
    aspect_ratio: float
    segments: List[CropSegment] = field(default_factory=list)


@dataclass(frozen=True)
class JudderInfo:
    drop_count: int
    keep_count: int
    drop_ratio: float
    verdict: str  # judder_none|judder_light|pulldown_3_2_suspect|judder_heavy


@dataclass(frozen=True)
class ImaxInfo:
    is_imax: bool
    imax_type: str
    # "none" | "full_frame_143" | "digital_190" | "expansion"
    # | "native_high_resolution" | "tmdb_keyword"
    confidence: float
    aspect_ratios_observed: List[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ffmpeg helper
# ---------------------------------------------------------------------------


def _run_ffmpeg_filter(cmd: List[str], timeout_s: float) -> Optional[str]:
    """Execute ffmpeg et retourne stderr texte, ou None en cas d'echec."""
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
        logger.warning("metadata_filter: ffmpeg timeout apres %ss", timeout_s)
        return None
    except OSError as exc:
        logger.warning("metadata_filter: OSError %s", exc)
        return None

    if cp.returncode not in (0, 1):
        logger.warning("metadata_filter: ffmpeg returncode=%d", cp.returncode)
        return None
    return cp.stderr or ""


# ---------------------------------------------------------------------------
# 8.1 Interlacing (idet)
# ---------------------------------------------------------------------------


def _parse_idet_stderr(stderr: str) -> InterlaceInfo:
    m = _RE_IDET_MULTI.search(stderr or "")
    if not m:
        return InterlaceInfo(False, "unknown", 0, 0, 0)
    tff = int(m.group(1))
    bff = int(m.group(2))
    prog = int(m.group(3))
    total = tff + bff + prog
    if total <= 0:
        return InterlaceInfo(False, "unknown", tff, bff, prog)
    interlaced_ratio = (tff + bff) / total
    detected = interlaced_ratio > IDET_INTERLACE_RATIO_THRESHOLD
    if not detected:
        return InterlaceInfo(False, "progressive", tff, bff, prog)
    # Determine dominant type
    if tff >= bff * 2:
        return InterlaceInfo(True, "tff", tff, bff, prog)
    if bff >= tff * 2:
        return InterlaceInfo(True, "bff", tff, bff, prog)
    return InterlaceInfo(True, "mixed", tff, bff, prog)


def detect_interlacing(
    ffmpeg_path: str,
    media_path: str,
    duration_s: float,
    *,
    segment_duration_s: float = IDET_SEGMENT_DURATION_S,
    timeout_s: float = 30.0,
) -> InterlaceInfo:
    """Detecte l'entrelacement via `ffmpeg -vf idet` sur 30s."""
    if not ffmpeg_path or not media_path or duration_s <= 0:
        return InterlaceInfo(False, "unknown", 0, 0, 0)

    start = min(30.0, max(0.0, duration_s * 0.05))
    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-ss",
        str(start),
        "-i",
        str(media_path),
        "-t",
        str(float(segment_duration_s)),
        "-vf",
        "idet",
        "-an",
        "-f",
        "null",
        "-v",
        "info",
        "-",
    ]
    stderr = _run_ffmpeg_filter(cmd, timeout_s)
    if stderr is None:
        return InterlaceInfo(False, "unknown", 0, 0, 0)
    return _parse_idet_stderr(stderr)


# ---------------------------------------------------------------------------
# 8.2 Crop (cropdetect)
# ---------------------------------------------------------------------------


def _parse_last_crop(stderr: str) -> Optional[tuple]:
    """Retourne le dernier crop (w, h, x, y) trouve, ou None."""
    if not stderr:
        return None
    matches = _RE_CROP.findall(stderr)
    if not matches:
        return None
    last = matches[-1]
    try:
        return (int(last[0]), int(last[1]), int(last[2]), int(last[3]))
    except (ValueError, TypeError):
        return None


def detect_crop_single_segment(
    ffmpeg_path: str,
    media_path: str,
    start_s: float,
    *,
    duration_s: float = CROPDETECT_SEGMENT_DURATION_S,
    timeout_s: float = 30.0,
) -> Optional[CropSegment]:
    """Lance cropdetect sur un segment, retourne le dernier crop detecte."""
    if not ffmpeg_path or not media_path:
        return None

    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-ss",
        str(float(start_s)),
        "-i",
        str(media_path),
        "-t",
        str(float(duration_s)),
        "-vf",
        f"cropdetect=limit={CROPDETECT_LIMIT}:round={CROPDETECT_ROUND}",
        "-an",
        "-f",
        "null",
        "-v",
        "info",
        "-",
    ]
    stderr = _run_ffmpeg_filter(cmd, timeout_s)
    if stderr is None:
        return None
    parsed = _parse_last_crop(stderr)
    if not parsed:
        return None
    w, h, x, y = parsed
    ar = w / h if h > 0 else 0.0
    return CropSegment(start_s=float(start_s), crop_w=w, crop_h=h, crop_x=x, crop_y=y, aspect_ratio=ar)


def detect_crop_multi_segments(
    ffmpeg_path: str,
    media_path: str,
    duration_s: float,
    *,
    n_segments: int = IMAX_EXPANSION_SEGMENTS_COUNT,
    segment_duration_s: float = CROPDETECT_SEGMENT_DURATION_S,
    timeout_s: float = 30.0,
) -> List[CropSegment]:
    """Lance cropdetect sur N segments repartis (debut/milieu/fin).

    Cf issue #50 : execution parallele via run_parallel_tasks (I/O bound,
    ffmpeg libere le GIL). Gain typique avec N=3 segments : ~15s -> ~5s
    par film. Sur batch 5000 films, ~14 h economisees.

    Ordre des resultats preserve (segment 0/1/2) via tri par cle de tache,
    important pour classify_crop qui compare debut/milieu/fin.
    """
    if duration_s <= 0 or n_segments < 1:
        return []
    n = max(1, int(n_segments))
    total_useful = max(0.0, duration_s - float(segment_duration_s))

    starts: List[float] = []
    for i in range(n):
        if n == 1:
            starts.append(total_useful / 2.0)
        else:
            starts.append((total_useful * i) / (n - 1))

    # Construit les taches indexees pour preserver l'ordre apres parallel
    def _make_task(start_s: float) -> Callable[[], Optional[CropSegment]]:
        def _run() -> Optional[CropSegment]:
            return detect_crop_single_segment(
                ffmpeg_path,
                media_path,
                start_s,
                duration_s=segment_duration_s,
                timeout_s=timeout_s,
            )

        return _run

    tasks: dict[str, Callable[[], Optional[CropSegment]]] = {
        # Cle zero-padded pour tri lexicographique == ordre numerique
        f"crop_{i:02d}": _make_task(starts[i])
        for i in range(n)
    }

    # Import local pour eviter cycle (parallelism importe constants)
    from .parallelism import resolve_max_workers, run_parallel_tasks

    # intent="single_film" cap a 2 workers (suffit pour 3 segments rapides).
    # Le pool fait min(workers, n_tasks) donc on n'over-provisionne pas.
    workers = min(resolve_max_workers(mode="auto", intent="single_film"), n)
    results_map = run_parallel_tasks(tasks, max_workers=workers)

    segments: List[CropSegment] = []
    for key in sorted(results_map.keys()):
        success, value = results_map[key]
        if success and value is not None:
            segments.append(value)
    return segments


def classify_crop(segments: List[CropSegment], orig_w: int, orig_h: int) -> CropInfo:
    """Classifie le crop (letterbox/pillarbox/...) a partir des segments."""
    if not segments or orig_w <= 0 or orig_h <= 0:
        return CropInfo(False, "unknown", 0, 0, 0.0, [])

    # Utilise le premier segment comme reference (stable apres 60s)
    seg = segments[0]
    w, h = seg.crop_w, seg.crop_h
    ar = w / h if h > 0 else 0.0

    if w == orig_w and h == orig_h:
        return CropInfo(False, "full_frame", w, h, ar, segments)

    # Bandes horizontales (letterbox) : largeur preservee, hauteur reduite
    if w >= orig_w - 4 and h < orig_h:  # tolerance ~4px arrondi
        # Prend le seuil standard le plus proche (2.35 vs 2.39)
        d_235 = abs(ar - 2.35)
        d_239 = abs(ar - 2.39)
        if d_235 <= 0.05 and d_235 <= d_239:
            return CropInfo(True, "letterbox_2_35", w, h, ar, segments)
        if d_239 <= 0.05:
            return CropInfo(True, "letterbox_2_39", w, h, ar, segments)
        return CropInfo(True, "letterbox_other", w, h, ar, segments)

    # Bandes verticales (pillarbox) : hauteur preservee, largeur reduite
    if h >= orig_h - 4 and w < orig_w:
        return CropInfo(True, "pillarbox", w, h, ar, segments)

    # Windowbox : les deux dimensions reduites
    return CropInfo(True, "windowbox", w, h, ar, segments)


# ---------------------------------------------------------------------------
# 8.3 Judder / pulldown (mpdecimate)
# ---------------------------------------------------------------------------


def _parse_mpdecimate_stderr(stderr: str) -> tuple:
    """Retourne (drop_count, keep_count)."""
    if not stderr:
        return (0, 0)
    drop = len(_RE_MPDECIMATE_DROP.findall(stderr))
    keep = len(_RE_MPDECIMATE_KEEP.findall(stderr))
    return (drop, keep)


def _classify_judder(drop_ratio: float) -> str:
    if drop_ratio < MPDECIMATE_JUDDER_LIGHT:
        return "judder_none"
    if drop_ratio < MPDECIMATE_JUDDER_PULLDOWN:
        return "judder_light"
    if drop_ratio < MPDECIMATE_JUDDER_HEAVY:
        return "pulldown_3_2_suspect"
    return "judder_heavy"


def detect_judder(
    ffmpeg_path: str,
    media_path: str,
    duration_s: float,
    *,
    segment_duration_s: float = MPDECIMATE_SEGMENT_DURATION_S,
    timeout_s: float = 30.0,
) -> JudderInfo:
    """Detecte judder / pulldown via mpdecimate sur 30s au milieu."""
    if not ffmpeg_path or not media_path or duration_s <= 0:
        return JudderInfo(0, 0, 0.0, "judder_none")

    start = max(0.0, min(60.0, duration_s * 0.3))
    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-ss",
        str(start),
        "-i",
        str(media_path),
        "-t",
        str(float(segment_duration_s)),
        "-vf",
        "mpdecimate",
        "-an",
        "-f",
        "null",
        "-v",
        "info",
        "-",
    ]
    stderr = _run_ffmpeg_filter(cmd, timeout_s)
    if stderr is None:
        return JudderInfo(0, 0, 0.0, "judder_none")

    drop, keep = _parse_mpdecimate_stderr(stderr)
    total = drop + keep
    if total <= 0:
        return JudderInfo(0, 0, 0.0, "judder_none")
    ratio = drop / total
    verdict = _classify_judder(ratio)
    return JudderInfo(drop, keep, ratio, verdict)


# ---------------------------------------------------------------------------
# 8.4 IMAX detection (derive)
# ---------------------------------------------------------------------------


def classify_imax(
    probe_width: int,
    probe_height: int,
    crop_segments: List[CropSegment],
    tmdb_keywords: Optional[List[str]] = None,
) -> ImaxInfo:
    """Classifie IMAX via 4 methodes priorisees.

    Priorite :
      1. Expansion (variabilite aspect ratio segments)
      2. Aspect ratio container (1.43 ou 1.90)
      3. Resolution native > 2600p
      4. TMDb keyword "imax"
    """
    ars = [s.aspect_ratio for s in (crop_segments or []) if s.aspect_ratio > 0]

    # 1. Expansion detected via variabilite AR entre segments
    if len(ars) >= 2:
        delta = max(ars) - min(ars)
        if delta > IMAX_EXPANSION_AR_DELTA:
            return ImaxInfo(True, "expansion", 0.90, ars)

    # 2. Aspect ratio container
    container_ar = probe_width / probe_height if probe_height > 0 else 0.0
    if IMAX_AR_FULL_FRAME_MIN <= container_ar <= IMAX_AR_FULL_FRAME_MAX:
        return ImaxInfo(True, "full_frame_143", 0.85, [container_ar])
    if IMAX_AR_DIGITAL_MIN <= container_ar <= IMAX_AR_DIGITAL_MAX:
        return ImaxInfo(True, "digital_190", 0.75, [container_ar])

    # 3. Resolution native tres elevee
    if probe_height > IMAX_NATIVE_RESOLUTION_MIN_HEIGHT:
        return ImaxInfo(True, "native_high_resolution", 0.70, ars or [container_ar])

    # 4. Cross-check TMDb keywords
    kws = [str(k).lower() for k in (tmdb_keywords or [])]
    if any("imax" in k for k in kws):
        return ImaxInfo(True, "tmdb_keyword", 0.60, ars or [container_ar])

    return ImaxInfo(False, "none", 1.0, ars)
