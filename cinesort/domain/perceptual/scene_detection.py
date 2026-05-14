"""Detection de keyframes de scene via ffmpeg (§4 v7.5.0).

Utilise le filtre `select='gt(scene,threshold)'` + `showinfo` de ffmpeg,
avec downsampling temporel (2 fps) et spatial (640 px largeur) pour rester
rapide meme sur des films 4K de 3h.

Strategie hybride : fusionne les keyframes detectees avec les timestamps
uniformes existants (50/50 par defaut). L'echantillonnage resultant est
biais vers des frames "interessantes" tout en gardant une couverture
temporelle uniforme.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from typing import List

from .constants import (
    SCENE_DETECTION_DEDUP_TOLERANCE_S,
    SCENE_DETECTION_FPS_ANALYSIS,
    SCENE_DETECTION_HYBRID_RATIO,
    SCENE_DETECTION_MAX_KEYFRAMES,
    SCENE_DETECTION_MIN_FILE_DURATION_S,
    SCENE_DETECTION_SCALE_WIDTH,
    SCENE_DETECTION_THRESHOLD,
    SCENE_DETECTION_TIMEOUT_S,
)
from cinesort.domain._runners import tracked_run

from .ffmpeg_runner import _runner_platform_kwargs

logger = logging.getLogger(__name__)

# ffmpeg showinfo emet des lignes comme :
#   [Parsed_showinfo_0 @ 0x...] n:  12 pts:123456 pts_time:5.123 duration:... scene_score:0.42
# Le scene_score n'est pas toujours present (versions plus anciennes) ;
# on le capture quand il l'est, sinon on utilise un fallback 1.0.
_RE_PTS_TIME = re.compile(r"pts_time:(\d+\.?\d*)")
_RE_SCENE_SCORE = re.compile(r"scene_score:([-\d.]+)")


@dataclass(frozen=True)
class SceneKeyframe:
    """Un keyframe de changement de scene detecte par ffmpeg."""

    timestamp_s: float
    score: float  # 0.0-1.0 (scene_score), fallback 1.0 si non fourni


def detect_scene_keyframes(
    ffmpeg_path: str,
    media_path: str,
    *,
    threshold: float = SCENE_DETECTION_THRESHOLD,
    fps_analysis: int = SCENE_DETECTION_FPS_ANALYSIS,
    scale_width: int = SCENE_DETECTION_SCALE_WIDTH,
    max_keyframes: int = SCENE_DETECTION_MAX_KEYFRAMES,
    timeout_s: float = SCENE_DETECTION_TIMEOUT_S,
) -> List[SceneKeyframe]:
    """Detecte les keyframes de changement de scene via ffmpeg.

    Args:
        ffmpeg_path: chemin de ffmpeg.
        media_path: chemin du fichier media.
        threshold: score minimum pour considerer un changement de scene.
        fps_analysis: fps auquel scanner le film (downsample temporel).
        scale_width: largeur cible pour le scan (downsample spatial).
        max_keyframes: cap sur le nombre de keyframes retournes.
        timeout_s: timeout du sous-process ffmpeg.

    Returns:
        Liste triee par timestamp croissant, <= max_keyframes entrees.
        Liste vide si echec ou aucun keyframe detecte.
    """
    if not ffmpeg_path or not media_path:
        return []

    vf = f"scale={int(scale_width)}:-1,select='gt(scene,{float(threshold)})',showinfo"
    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-i",
        str(media_path),
        "-r",
        str(int(fps_analysis)),
        "-vf",
        vf,
        "-f",
        "null",
        "-v",
        "info",
        "-",
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
        logger.warning("scene_detection: timeout apres %ss sur %s", timeout_s, media_path)
        return []
    except OSError as exc:
        logger.warning("scene_detection: OSError sur %s: %s", media_path, exc)
        return []

    if cp.returncode not in (0, 1):
        # ffmpeg peut retourner 1 sur un flux court, tolere. Autre = erreur reelle.
        logger.warning("scene_detection: returncode=%d sur %s", cp.returncode, media_path)
        return []

    stderr = cp.stderr or ""
    if not stderr:
        return []

    keyframes = _parse_showinfo_stderr(stderr)
    if not keyframes:
        return []

    # Si trop de keyframes : garde les `max_keyframes` meilleurs par score,
    # puis re-trie par timestamp.
    if len(keyframes) > max_keyframes:
        keyframes.sort(key=lambda k: k.score, reverse=True)
        keyframes = keyframes[:max_keyframes]

    keyframes.sort(key=lambda k: k.timestamp_s)
    return keyframes


def merge_hybrid_timestamps(
    uniform_timestamps: List[float],
    keyframes: List[SceneKeyframe],
    target_count: int,
    *,
    dedup_tolerance_s: float = SCENE_DETECTION_DEDUP_TOLERANCE_S,
    hybrid_ratio: float = SCENE_DETECTION_HYBRID_RATIO,
) -> List[float]:
    """Fusionne timestamps uniformes et keyframes en mode hybride.

    Args:
        uniform_timestamps: timestamps uniformes (de compute_timestamps).
        keyframes: keyframes detectes (peut etre vide).
        target_count: nombre total de frames souhaitees au final.
        dedup_tolerance_s: distance min entre un uniforme et un keyframe.
        hybrid_ratio: proportion de keyframes (0.5 = 50%).

    Returns:
        Liste de timestamps triee croissant, <= target_count entrees.
        Si pas de keyframes : retourne uniform_timestamps inchanges (clamp target).
    """
    if not keyframes:
        return list(uniform_timestamps[: int(target_count)])

    target = max(1, int(target_count))
    ratio = max(0.0, min(1.0, float(hybrid_ratio)))
    count_keyframes = max(1, int(round(target * ratio)))
    count_uniform = max(0, target - count_keyframes)

    # Top N keyframes par score (deja trie par ts apres detect ; on trie par score ici)
    sorted_kf = sorted(keyframes, key=lambda k: k.score, reverse=True)
    picked_kf_ts = [k.timestamp_s for k in sorted_kf[:count_keyframes]]

    # Uniformes : prendre les N premiers (deja uniformement repartis). Si on en
    # prend moins que disponibles, echantillonner avec un step >= 1.
    if count_uniform == 0 or not uniform_timestamps:
        picked_uniform_ts: List[float] = []
    elif count_uniform >= len(uniform_timestamps):
        picked_uniform_ts = list(uniform_timestamps)
    else:
        step = len(uniform_timestamps) / count_uniform
        picked_uniform_ts = [uniform_timestamps[int(i * step)] for i in range(count_uniform)]

    # Merge + dedup : un uniforme est rejete s'il est trop proche d'un keyframe
    # (on privilegie la keyframe, plus informative).
    merged: List[float] = list(picked_kf_ts)
    for ts in picked_uniform_ts:
        if all(abs(ts - kf) >= dedup_tolerance_s for kf in picked_kf_ts):
            merged.append(ts)

    merged.sort()

    # Clamp au target final au cas ou le dedup en aurait laisse passer trop
    return merged[:target]


def should_skip_scene_detection(duration_s: float, setting_enabled: bool) -> bool:
    """True si on doit skip la scene detection.

    Raisons :
        - setting desactive par l'utilisateur
        - duree < SCENE_DETECTION_MIN_FILE_DURATION_S (overhead > benefice)
    """
    if not setting_enabled:
        return True
    if float(duration_s) < SCENE_DETECTION_MIN_FILE_DURATION_S:
        return True
    return False


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------


def _parse_showinfo_stderr(stderr: str) -> List[SceneKeyframe]:
    """Parse stderr ffmpeg/showinfo en SceneKeyframe.

    Tolerant aux variations de format entre versions de ffmpeg. Chaque ligne
    qui contient un pts_time est consideree ; le scene_score est optionnel
    (fallback 1.0).
    """
    keyframes: List[SceneKeyframe] = []
    for line in stderr.splitlines():
        if "Parsed_showinfo" not in line and "showinfo" not in line:
            continue
        m_ts = _RE_PTS_TIME.search(line)
        if not m_ts:
            continue
        try:
            ts = float(m_ts.group(1))
        except (ValueError, TypeError):
            continue
        if ts < 0:
            continue
        score = 1.0
        m_sc = _RE_SCENE_SCORE.search(line)
        if m_sc:
            try:
                score = max(0.0, min(1.0, float(m_sc.group(1))))
            except (ValueError, TypeError):
                score = 1.0
        keyframes.append(SceneKeyframe(timestamp_s=ts, score=score))
    return keyframes
