"""Score perceptuel composite + verdicts croises inter-metriques."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from .constants import (
    BLOCK_NONE,
    BLOCK_SLIGHT,
    BLOCK_MODERATE,
    BLUR_SHARP,
    BLUR_NORMAL,
    BLUR_SOFT,
    BANDING_NONE,
    BANDING_SLIGHT,
    BANDING_MODERATE,
    DNR_BLUR_THRESHOLD,
    DNR_GRAIN_ABSENT_THRESHOLD,
    EFFECTIVE_BITS_EXCELLENT,
    EFFECTIVE_BITS_GOOD,
    EFFECTIVE_BITS_MEDIOCRE,
    ERA_CLASSIC_FILM,
    FAKE_4K_VERDICT_MIN_HEIGHT,
    GLOBAL_WEIGHT_AUDIO,
    GLOBAL_WEIGHT_VIDEO,
    GRAIN_MODERATE,
    PERCEPTUAL_ENGINE_VERSION,
    TEMPORAL_CONSISTENCY_GOOD,
    TEMPORAL_CONSISTENCY_POOR,
    TIER_EXCELLENT,
    TIER_GOOD,
    TIER_MEDIOCRE,
    TIER_REFERENCE,
    VISUAL_WEIGHT_BANDING,
    VISUAL_WEIGHT_BIT_DEPTH,
    VISUAL_WEIGHT_BLOCKINESS,
    VISUAL_WEIGHT_BLUR,
    VISUAL_WEIGHT_GRAIN_VERDICT,
    VISUAL_WEIGHT_TEMPORAL,
)
from .models import AudioPerceptual, GrainAnalysis, PerceptualResult, VideoPerceptual

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scoring visuel
# ---------------------------------------------------------------------------


def compute_visual_score(video: VideoPerceptual, grain: Optional[GrainAnalysis] = None) -> int:
    """Score visuel composite pondere (0-100)."""
    s_block = _score_val_inv(video.blockiness_mean, BLOCK_NONE, BLOCK_SLIGHT, BLOCK_MODERATE)
    s_blur = _score_val_inv(video.blur_mean, BLUR_SHARP, BLUR_NORMAL, BLUR_SOFT)
    s_banding = _score_val_inv(video.banding_mean, BANDING_NONE, BANDING_SLIGHT, BANDING_MODERATE)
    s_bits = _score_bits(video.effective_bits_mean)
    s_grain = grain.score if grain else 50
    s_temporal = _score_temporal(video.temporal_stddev)

    total = (
        s_block * VISUAL_WEIGHT_BLOCKINESS
        + s_blur * VISUAL_WEIGHT_BLUR
        + s_banding * VISUAL_WEIGHT_BANDING
        + s_bits * VISUAL_WEIGHT_BIT_DEPTH
        + s_grain * VISUAL_WEIGHT_GRAIN_VERDICT
        + s_temporal * VISUAL_WEIGHT_TEMPORAL
    ) / 100
    return max(0, min(100, int(round(total))))


# ---------------------------------------------------------------------------
# Scoring audio
# ---------------------------------------------------------------------------


def compute_audio_score(audio: Optional[AudioPerceptual]) -> Optional[int]:
    """Score audio composite pondere (0-100). None si pas de piste."""
    if not audio or audio.track_index < 0:
        return None
    # Si audio_score deja calcule par audio_perceptual.py, le reutiliser
    return audio.audio_score


# ---------------------------------------------------------------------------
# Score global
# ---------------------------------------------------------------------------


def compute_global_score(visual_score: int, audio_score: Optional[int]) -> int:
    """Score perceptuel global : video 60 % + audio 40 %. 100% video si pas d'audio."""
    if audio_score is None:
        return visual_score
    total = (visual_score * GLOBAL_WEIGHT_VIDEO + audio_score * GLOBAL_WEIGHT_AUDIO) / 100
    return max(0, min(100, int(round(total))))


# ---------------------------------------------------------------------------
# Tier
# ---------------------------------------------------------------------------


def determine_tier(score: int) -> str:
    """Determine le tier perceptuel depuis un score 0-100."""
    if score >= TIER_REFERENCE:
        return "reference"
    if score >= TIER_EXCELLENT:
        return "excellent"
    if score >= TIER_GOOD:
        return "bon"
    if score >= TIER_MEDIOCRE:
        return "mediocre"
    return "degrade"


# ---------------------------------------------------------------------------
# Verdicts croises
# ---------------------------------------------------------------------------


def detect_cross_verdicts(
    video: Optional[VideoPerceptual],
    grain: Optional[GrainAnalysis],
    audio: Optional[AudioPerceptual],
    *,
    encode_warnings: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """Detecte les verdicts croises inter-metriques."""
    verdicts: List[Dict[str, str]] = []
    if not video:
        return verdicts

    block = video.blockiness_mean
    blur = video.blur_mean
    banding = video.banding_mean
    bits = video.effective_bits_mean
    bd = video.bit_depth_nominal
    h = video.resolution_height
    enc = encode_warnings or []
    gl = grain.grain_level if grain else 0.0
    year = grain.tmdb_year if grain else 0
    lra = audio.loudness_range if audio and audio.loudness_range is not None else 99.0

    # 1. DNR + upscale
    if blur > DNR_BLUR_THRESHOLD and "upscale_suspect" in enc:
        verdicts.append(
            {
                "id": "dnr_upscale_combo",
                "label": "DNR + upscale suspectee",
                "detail": f"Image lissee (blur {blur:.3f}) avec flag upscale — probable upscale avec DNR.",
                "severity": "error",
            }
        )

    # 2. Faux 4K
    if h >= FAKE_4K_VERDICT_MIN_HEIGHT and bits < 8.0 and blur > 0.05:
        verdicts.append(
            {
                "id": "fake_4k",
                "label": "Faux 4K probable",
                "detail": f"Resolution 4K mais bit depth effectif faible ({bits:.1f}) et flou ({blur:.3f}).",
                "severity": "error",
            }
        )

    # 3. Re-compression destructrice
    if block > 40 and banding > 20:
        verdicts.append(
            {
                "id": "lossy_recompress",
                "label": "Re-compression destructrice visible",
                "detail": f"Artefacts de compression (block {block:.0f}) et banding ({banding:.0f}) simultanes.",
                "severity": "warning",
            }
        )

    # 4. Mastering reference
    if block < BLOCK_NONE and blur < 0.02 and banding < BANDING_NONE and bits > 9.0:
        verdicts.append(
            {
                "id": "excellent_mastering",
                "label": "Mastering de reference",
                "detail": "Image nette, sans artefacts, sans banding, 10-bit bien exploite.",
                "severity": "positive",
            }
        )

    # 5. Audio ecrase
    if lra < 5.0:
        verdicts.append(
            {
                "id": "audio_crushed",
                "label": "Audio ecrase (loudness war)",
                "detail": f"Dynamique audio tres comprimee (LRA {lra:.1f} LU).",
                "severity": "warning",
            }
        )

    # 6. Source streaming
    if block > 25 and banding > 15 and lra < 10:
        verdicts.append(
            {
                "id": "streaming_source",
                "label": "Source streaming probable",
                "detail": "Compression video et audio typiques d'une source streaming.",
                "severity": "info",
            }
        )

    # 7. 8-bit insuffisant
    if banding > 15 and bd == 8:
        verdicts.append(
            {
                "id": "8bit_insufficient",
                "label": "Bit depth 8-bit insuffisant",
                "detail": f"Banding visible ({banding:.0f}) sur un encode 8-bit.",
                "severity": "warning",
            }
        )

    # 8. Banding en 10-bit
    if banding > 20 and bd >= 10:
        verdicts.append(
            {
                "id": "banding_10bit",
                "label": "Encode destructif multi-generation",
                "detail": f"Banding ({banding:.0f}) en 10-bit — encode multi-passe ou source degradee.",
                "severity": "warning",
            }
        )

    # 9. DNR suspect pre-2002
    if blur > DNR_BLUR_THRESHOLD and gl < DNR_GRAIN_ABSENT_THRESHOLD and 0 < year < ERA_CLASSIC_FILM:
        verdicts.append(
            {
                "id": "dnr_classic_film",
                "label": "DNR suspect (film pellicule)",
                "detail": f"Film de {year} : flou ({blur:.3f}) sans grain ({gl:.1f}) — DNR probable.",
                "severity": "warning",
            }
        )

    # 10. Grain post-2015 digital
    if gl > GRAIN_MODERATE and year > 2015:
        verdicts.append(
            {
                "id": "noise_digital",
                "label": "Bruit numerique excessif",
                "detail": f"Film de {year} : grain {gl:.1f} anormal pour une source numerique.",
                "severity": "warning",
            }
        )

    return verdicts


# ---------------------------------------------------------------------------
# Orchestrateur final
# ---------------------------------------------------------------------------


def build_perceptual_result(
    video: Optional[VideoPerceptual],
    grain: Optional[GrainAnalysis],
    audio: Optional[AudioPerceptual],
    settings_used: Optional[Dict[str, Any]] = None,
    *,
    encode_warnings: Optional[List[str]] = None,
    analysis_duration_s: float = 0.0,
) -> PerceptualResult:
    """Construit le resultat perceptuel complet."""
    v_score = compute_visual_score(video, grain) if video else 0
    a_score_opt = compute_audio_score(audio)
    g_score = compute_global_score(v_score, a_score_opt)
    a_score = a_score_opt if a_score_opt is not None else 0

    g_tier = determine_tier(g_score)
    verdicts = detect_cross_verdicts(video, grain, audio, encode_warnings=encode_warnings)
    logger.debug(
        "perceptual: visual=%d audio=%s global=%d tier=%s verdicts=%d",
        v_score,
        a_score_opt,
        g_score,
        g_tier,
        len(verdicts),
    )
    return PerceptualResult(
        version=PERCEPTUAL_ENGINE_VERSION,
        ts=time.time(),
        analysis_duration_total_s=analysis_duration_s,
        video=video,
        grain=grain,
        audio=audio,
        visual_score=v_score,
        audio_score=a_score,
        global_score=g_score,
        global_tier=g_tier,
        cross_verdicts=verdicts,
        settings_used=dict(settings_used or {}),
    )


# ---------------------------------------------------------------------------
# Helpers scoring
# ---------------------------------------------------------------------------


def _score_val_inv(val: float, good: float, medium: float, bad: float) -> int:
    """Score inverse : plus la valeur est basse, meilleur c'est."""
    if val < good:
        return 95
    if val < medium:
        return 75
    if val < bad:
        return 50
    return 20


def _score_bits(mean_bits: float) -> int:
    """Score profondeur effective."""
    if mean_bits >= EFFECTIVE_BITS_EXCELLENT:
        return 95
    if mean_bits >= EFFECTIVE_BITS_GOOD:
        return 75
    if mean_bits >= EFFECTIVE_BITS_MEDIOCRE:
        return 50
    return 25


def _score_temporal(stddev: float) -> int:
    """Score consistance temporelle."""
    if stddev < TEMPORAL_CONSISTENCY_GOOD:
        return 90
    if stddev < TEMPORAL_CONSISTENCY_POOR:
        return 60
    return 30
