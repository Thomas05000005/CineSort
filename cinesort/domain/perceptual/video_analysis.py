"""Analyse video perceptuelle — filtres ffmpeg + analyse pixel stdlib."""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict, List

from .constants import (
    BLOCK_NONE,
    BLOCK_SLIGHT,
    BLOCK_MODERATE,
    BLOCK_SEVERE,
    BLUR_SHARP,
    BLUR_NORMAL,
    BLUR_SOFT,
    BLUR_VERY_SOFT,
    BANDING_NONE,
    BANDING_SLIGHT,
    BANDING_MODERATE,
    BT2020_THRESHOLDS_MULTIPLIER,
    BW_SATURATION_THRESHOLD,
    DARK_SCENE_Y_AVG_THRESHOLD,
    EFFECTIVE_BITS_EXCELLENT,
    EFFECTIVE_BITS_GOOD,
    EFFECTIVE_BITS_MEDIOCRE,
    TEMPORAL_CONSISTENCY_GOOD,
    TEMPORAL_CONSISTENCY_POOR,
    TIER_REFERENCE,
    TIER_EXCELLENT,
    TIER_GOOD,
    TIER_MEDIOCRE,
    VISUAL_WEIGHT_BLOCKINESS,
    VISUAL_WEIGHT_BLUR,
    VISUAL_WEIGHT_BANDING,
    VISUAL_WEIGHT_BIT_DEPTH,
    VISUAL_WEIGHT_GRAIN_VERDICT,
    VISUAL_WEIGHT_TEMPORAL,
)
from .ffmpeg_runner import run_ffmpeg_text
from .models import VideoPerceptual

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex pour parser la sortie ffmpeg (stderr)
# ---------------------------------------------------------------------------

_RE_YAVG = re.compile(r"YAVG=(\d+)")
_RE_YMIN = re.compile(r"YMIN=(\d+)")
_RE_YMAX = re.compile(r"YMAX=(\d+)")
_RE_SATAVG = re.compile(r"SATAVG=(\d+)")
_RE_TOUT = re.compile(r"TOUT=([\d.]+)")
_RE_VREP = re.compile(r"VREP=([\d.]+)")
_RE_BLOCK = re.compile(r"block[_:]?\s*([\d.]+)", re.IGNORECASE)
_RE_BLUR = re.compile(r"blur[_:]?\s*([\d.]+)", re.IGNORECASE)

# FPS par defaut si non fourni
_DEFAULT_FPS = 24.0


# ---------------------------------------------------------------------------
# Filtres ffmpeg single-pass
# ---------------------------------------------------------------------------


def run_filter_graph(
    ffmpeg_path: str,
    media_path: str,
    duration_s: float,
    *,
    sample_count: int = 200,
    fps: float = _DEFAULT_FPS,
    timeout_s: float = 120.0,
) -> List[Dict[str, Any]]:
    """Execute signalstats + blockdetect + blurdetect en un seul pass.

    Retourne une liste de dicts par frame echantillonnee :
    ``{y_avg, y_min, y_max, sat_avg, tout, vrep, blockiness, blur}``.
    """
    if not ffmpeg_path or not media_path or duration_s <= 0:
        return []

    total_frames = max(1, int(duration_s * max(1.0, float(fps))))
    step = max(1, total_frames // max(1, int(sample_count)))

    vf = f"select='not(mod(n\\,{step}))',signalstats=stat=tout+vrep,blockdetect,blurdetect"

    cmd = [
        ffmpeg_path,
        "-i",
        str(media_path),
        "-vf",
        vf,
        "-f",
        "null",
        "-v",
        "info",
        "-an",
        "-sn",
        "-",
    ]

    rc, _stdout, stderr = run_ffmpeg_text(cmd, timeout_s)
    if rc != 0 and not stderr:
        logger.debug("run_filter_graph ffmpeg rc=%d", rc)
        return []

    return _parse_filter_output(stderr)


def _parse_filter_output(stderr: str) -> List[Dict[str, Any]]:
    """Parse la sortie stderr du filtre graph en metriques par frame."""
    results: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}

    for line in stderr.splitlines():
        # signalstats contient toutes les metriques video d'une frame
        m_yavg = _RE_YAVG.search(line)
        if m_yavg:
            # Nouvelle frame signalstats : sauver la precedente si complete
            if current.get("_has_signal"):
                results.append(_finalize_frame(current))
                current = {}
            current["y_avg"] = int(m_yavg.group(1))
            current["_has_signal"] = True
            m = _RE_YMIN.search(line)
            current["y_min"] = int(m.group(1)) if m else 0
            m = _RE_YMAX.search(line)
            current["y_max"] = int(m.group(1)) if m else 255
            m = _RE_SATAVG.search(line)
            current["sat_avg"] = int(m.group(1)) if m else 0
            m = _RE_TOUT.search(line)
            current["tout"] = float(m.group(1)) if m else 0.0
            m = _RE_VREP.search(line)
            current["vrep"] = float(m.group(1)) if m else 0.0
            continue

        # blockdetect
        if "block" in line.lower() and "blockdetect" in line.lower():
            m = _RE_BLOCK.search(line)
            if m:
                current["blockiness"] = float(m.group(1))
            continue

        # blurdetect
        if "blur" in line.lower() and "blurdetect" in line.lower():
            m = _RE_BLUR.search(line)
            if m:
                current["blur"] = float(m.group(1))

    # Derniere frame
    if current.get("_has_signal"):
        results.append(_finalize_frame(current))

    return results


def _finalize_frame(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise un dict brut en metriques de frame propres."""
    return {
        "y_avg": raw.get("y_avg", 0),
        "y_min": raw.get("y_min", 0),
        "y_max": raw.get("y_max", 255),
        "sat_avg": raw.get("sat_avg", 0),
        "tout": raw.get("tout", 0.0),
        "vrep": raw.get("vrep", 0.0),
        "blockiness": raw.get("blockiness", 0.0),
        "blur": raw.get("blur", 0.0),
    }


# ---------------------------------------------------------------------------
# Analyse pixel — histogramme luminance
# ---------------------------------------------------------------------------


def luminance_histogram(pixels: List[int], bit_depth: int = 8) -> List[int]:
    """Histogramme des valeurs Y (0-255 ou 0-1023)."""
    max_val = 1024 if bit_depth >= 10 else 256
    hist = [0] * max_val
    for p in pixels:
        idx = min(max(0, p), max_val - 1)
        hist[idx] += 1
    return hist


# ---------------------------------------------------------------------------
# Analyse pixel — variance locale par blocs
# ---------------------------------------------------------------------------


def block_variance_stats(
    pixels: List[int],
    width: int,
    height: int,
    block_size: int = 16,
    bit_depth: int = 8,
) -> Dict[str, float]:
    """Variance par bloc 16x16 : detail vs aplats."""
    w, h, bs = int(width), int(height), int(block_size)
    if w < bs or h < bs or not pixels:
        return {"mean_variance": 0.0, "median_variance": 0.0, "flat_ratio": 1.0, "detail_ratio": 0.0}

    variances: List[float] = []
    for by in range(0, h - bs + 1, bs):
        for bx in range(0, w - bs + 1, bs):
            block: List[int] = []
            for dy in range(bs):
                start = (by + dy) * w + bx
                block.extend(pixels[start : start + bs])
            n = len(block)
            if n == 0:
                continue
            mean = sum(block) / n
            var = sum((x - mean) ** 2 for x in block) / n
            variances.append(var)

    if not variances:
        return {"mean_variance": 0.0, "median_variance": 0.0, "flat_ratio": 1.0, "detail_ratio": 0.0}

    variances.sort()
    mean_var = sum(variances) / len(variances)
    median_var = variances[len(variances) // 2]

    # Seuil plat adapte au bit depth
    flat_thresh = 400.0 if bit_depth >= 10 else 25.0
    flat_count = sum(1 for v in variances if v < flat_thresh)
    flat_ratio = flat_count / len(variances)

    return {
        "mean_variance": round(mean_var, 2),
        "median_variance": round(median_var, 2),
        "flat_ratio": round(flat_ratio, 4),
        "detail_ratio": round(1.0 - flat_ratio, 4),
    }


# ---------------------------------------------------------------------------
# Analyse pixel — detection banding
# ---------------------------------------------------------------------------


def detect_banding(histogram: List[int], min_gap: int = 3) -> Dict[str, Any]:
    """Detecte le banding par gaps dans l'histogramme."""
    h_len = len(histogram)
    if h_len < 20:
        return {"score": 0, "gap_count": 0, "avg_gap": 0.0, "worst_gap": 0}

    # Ignorer les 10 % extremes (clipped blacks / whites)
    start = h_len // 10
    end = h_len - h_len // 10
    region = histogram[start:end]

    total_pixels = sum(region)
    if total_pixels == 0:
        return {"score": 0, "gap_count": 0, "avg_gap": 0.0, "worst_gap": 0}

    # Bins "remplis" : > 0.01 % de la distribution uniforme
    threshold = total_pixels / len(region) * 0.01
    filled = [i for i, c in enumerate(region) if c > threshold]

    if len(filled) < 2:
        return {"score": 0, "gap_count": 0, "avg_gap": 0.0, "worst_gap": 0}

    # Mesurer les gaps entre bins remplis consecutifs
    gaps: List[int] = []
    for i in range(1, len(filled)):
        gap = filled[i] - filled[i - 1] - 1
        if gap >= min_gap:
            gaps.append(gap)

    if not gaps:
        return {"score": 0, "gap_count": 0, "avg_gap": 0.0, "worst_gap": 0}

    avg_gap = sum(gaps) / len(gaps)
    worst_gap = max(gaps)

    # Score : densite de gaps × taille moyenne, cap a 100
    gap_density = len(gaps) / max(len(filled), 1)
    score = min(100, int(gap_density * avg_gap * 10))

    return {
        "score": score,
        "gap_count": len(gaps),
        "avg_gap": round(avg_gap, 1),
        "worst_gap": worst_gap,
    }


# ---------------------------------------------------------------------------
# Analyse pixel — bit depth effectif
# ---------------------------------------------------------------------------


def effective_bit_depth(histogram: List[int], bit_depth: int = 8) -> Dict[str, Any]:
    """Nombre de niveaux Y distincts reellement utilises."""
    max_levels = 1024 if bit_depth >= 10 else 256
    total_pixels = sum(histogram)
    if total_pixels == 0:
        return {"mean_bits": 0.0, "distinct_levels": 0, "total_levels": max_levels, "utilization_pct": 0.0}

    # Seuil bruit : 0.001 % du total
    threshold = total_pixels * 0.00001
    distinct = sum(1 for c in histogram if c > threshold)

    eff_bits = math.log2(max(distinct, 1))
    utilization_pct = distinct / max_levels * 100

    return {
        "mean_bits": round(eff_bits, 2),
        "distinct_levels": distinct,
        "total_levels": max_levels,
        "utilization_pct": round(utilization_pct, 1),
    }


# ---------------------------------------------------------------------------
# Consistance temporelle
# ---------------------------------------------------------------------------


def compute_temporal_consistency(filter_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Ecart-type de blockiness et blur entre frames echantillonnees."""
    if not filter_results:
        return {"block_stddev": 0.0, "blur_stddev": 0.0, "verdict": "unknown", "score": 50}

    blocks = [f.get("blockiness", 0.0) for f in filter_results]
    blurs = [f.get("blur", 0.0) for f in filter_results]

    block_std = _stddev(blocks)
    blur_std = _stddev(blurs)

    # Verdict base sur la moyenne des deux stddevs
    avg_std = (block_std + blur_std * 100) / 2.0  # blur est sur 0-1, normaliser
    if avg_std < TEMPORAL_CONSISTENCY_GOOD:
        verdict = "consistent"
        score = 90
    elif avg_std < TEMPORAL_CONSISTENCY_POOR:
        verdict = "variable"
        score = 60
    else:
        verdict = "unstable"
        score = 30

    return {
        "block_stddev": round(block_std, 2),
        "blur_stddev": round(blur_std, 4),
        "verdict": verdict,
        "score": score,
    }


# ---------------------------------------------------------------------------
# Scoring par metrique (0-100)
# ---------------------------------------------------------------------------


def _score_blockiness(mean: float, multiplier: float = 1.0) -> int:
    """Score de blockiness : 0 = degoutant, 100 = parfait."""
    # Seuils ajustes par le multiplicateur BT.2020
    s_none = BLOCK_NONE * multiplier
    s_slight = BLOCK_SLIGHT * multiplier
    s_mod = BLOCK_MODERATE * multiplier
    s_sev = BLOCK_SEVERE * multiplier
    if mean < s_none:
        return 95
    if mean < s_slight:
        return 75
    if mean < s_mod:
        return 50
    if mean < s_sev:
        return 25
    return 10


def _score_blur(mean: float, multiplier: float = 1.0) -> int:
    """Score de blur : 0 = flou, 100 = net."""
    s_sharp = BLUR_SHARP * multiplier
    s_norm = BLUR_NORMAL * multiplier
    s_soft = BLUR_SOFT * multiplier
    s_vsoft = BLUR_VERY_SOFT * multiplier
    if mean < s_sharp:
        return 95
    if mean < s_norm:
        return 80
    if mean < s_soft:
        return 55
    if mean < s_vsoft:
        return 30
    return 10


def _score_banding(mean_score: float, multiplier: float = 1.0) -> int:
    """Score de banding : 0 = posterise, 100 = doux."""
    s_none = BANDING_NONE * multiplier
    s_slight = BANDING_SLIGHT * multiplier
    s_mod = BANDING_MODERATE * multiplier
    if mean_score < s_none:
        return 95
    if mean_score < s_slight:
        return 75
    if mean_score < s_mod:
        return 45
    return 15


def _score_effective_bits(mean_bits: float) -> int:
    """Score de profondeur effective."""
    if mean_bits >= EFFECTIVE_BITS_EXCELLENT:
        return 95
    if mean_bits >= EFFECTIVE_BITS_GOOD:
        return 75
    if mean_bits >= EFFECTIVE_BITS_MEDIOCRE:
        return 50
    return 25


# ---------------------------------------------------------------------------
# Orchestrateur video
# ---------------------------------------------------------------------------


def analyze_video_frames(
    frames_data: List[Dict[str, Any]],
    filter_results: List[Dict[str, Any]],
    bit_depth: int = 8,
    color_space: str = "bt709",
    dark_weight: float = 1.5,
    width: int = 0,
    height: int = 0,
) -> VideoPerceptual:
    """Orchestre l'analyse pixel + filtres et retourne un VideoPerceptual."""
    result = VideoPerceptual(
        bit_depth_nominal=bit_depth,
        color_space=color_space,
        resolution_width=width,
        resolution_height=height,
    )
    if not frames_data and not filter_results:
        return result

    cs_lower = str(color_space).lower()
    multiplier = BT2020_THRESHOLDS_MULTIPLIER if "2020" in cs_lower or "bt2020" in cs_lower else 1.0

    pixel_agg = _aggregate_pixel_metrics(frames_data, bit_depth, width, height, dark_weight)
    _aggregate_filter_metrics(result, filter_results)
    _apply_pixel_aggregates(result, pixel_agg)

    # Detection N&B
    result.is_bw = result.saturation_avg < BW_SATURATION_THRESHOLD

    # Scenes sombres
    y_avgs = pixel_agg["y_avgs"]
    dark_count = sum(1 for y in (y_avgs or [result.y_avg_mean]) if y < DARK_SCENE_Y_AVG_THRESHOLD)
    total_y = len(y_avgs) or 1
    result.dark_frame_count = dark_count
    result.dark_frame_pct = (dark_count / total_y * 100) if total_y > 0 else 0.0

    # Consistance temporelle + scoring
    temporal = compute_temporal_consistency(filter_results)
    result.temporal_stddev = temporal["block_stddev"]
    _compute_visual_score(result, multiplier, temporal["score"])
    logger.debug(
        "video: blockiness=%.2f blur=%.3f banding=%.1f score=%d",
        result.blockiness_mean,
        result.blur_mean,
        result.banding_mean,
        result.visual_score or 0,
    )
    return result


def _aggregate_pixel_metrics(
    frames_data: List[Dict[str, Any]],
    bit_depth: int,
    width: int,
    height: int,
    dark_weight: float,
) -> Dict[str, Any]:
    """Analyse pixel de chaque frame extraite."""
    banding_scores: List[float] = []
    bit_depths_list: List[float] = []
    variances: List[float] = []
    flat_ratios: List[float] = []
    y_avgs: List[float] = []
    weights: List[float] = []

    for fd in frames_data:
        pixels = fd.get("pixels", [])
        fw, fh = fd.get("width", width), fd.get("height", height)
        y_avg = fd.get("y_avg", 128.0)
        y_avgs.append(y_avg)
        weights.append(dark_weight if y_avg < DARK_SCENE_Y_AVG_THRESHOLD else 1.0)
        if pixels:
            hist = luminance_histogram(pixels, bit_depth)
            banding_scores.append(detect_banding(hist)["score"])
            bit_depths_list.append(effective_bit_depth(hist, bit_depth)["mean_bits"])
            bv = block_variance_stats(pixels, fw, fh, bit_depth=bit_depth)
            variances.append(bv["mean_variance"])
            flat_ratios.append(bv["flat_ratio"])

    return {
        "banding": banding_scores,
        "bits": bit_depths_list,
        "variances": variances,
        "flat_ratios": flat_ratios,
        "y_avgs": y_avgs,
        "weights": weights,
    }


def _aggregate_filter_metrics(result: VideoPerceptual, filter_results: List[Dict[str, Any]]) -> None:
    """Remplit les metriques du VideoPerceptual depuis les resultats de filtre."""
    f_blocks = [fr.get("blockiness", 0.0) for fr in filter_results]
    f_blurs = [fr.get("blur", 0.0) for fr in filter_results]

    if f_blocks:
        sorted_b = sorted(f_blocks)
        result.blockiness_mean = _mean(f_blocks)
        result.blockiness_median = sorted_b[len(sorted_b) // 2]
        result.blockiness_stddev = _stddev(f_blocks)
    if f_blurs:
        sorted_bl = sorted(f_blurs)
        result.blur_mean = _mean(f_blurs)
        result.blur_median = sorted_bl[len(sorted_bl) // 2]
        result.blur_stddev = _stddev(f_blurs)

    f_yavgs = [fr.get("y_avg", 0) for fr in filter_results]
    f_sats = [fr.get("sat_avg", 0) for fr in filter_results]
    f_touts = [fr.get("tout", 0.0) for fr in filter_results]
    f_vreps = [fr.get("vrep", 0.0) for fr in filter_results]
    if f_yavgs:
        result.y_avg_mean = _mean(f_yavgs)
    if f_sats:
        result.saturation_avg = _mean(f_sats)
    if f_touts:
        result.tout_mean = _mean(f_touts)
    if f_vreps:
        result.vrep_mean = _mean(f_vreps)


def _apply_pixel_aggregates(result: VideoPerceptual, agg: Dict[str, Any]) -> None:
    """Applique les metriques pixel agregees au VideoPerceptual."""
    result.frames_analyzed = len(agg["y_avgs"])
    if agg["banding"]:
        result.banding_mean = _weighted_mean(agg["banding"], agg["weights"])
    if agg["bits"]:
        result.effective_bits_mean = _mean(agg["bits"])
    if agg["variances"]:
        result.variance_mean = _mean(agg["variances"])
    if agg["flat_ratios"]:
        result.flat_ratio = _mean(agg["flat_ratios"])


def _compute_visual_score(result: VideoPerceptual, multiplier: float, temporal_score: int) -> None:
    """Calcule le score visuel composite et le tier (mute result en place).

    Note : le score final affiche/persiste est recalcule autoritairement
    par compute_visual_score(video, grain) dans build_perceptual_result
    avec le vrai grain.score (au lieu du 50 hardcode ici).
    Ce calcul intermediaire reste utile car :
    - composite_score_v2._score_from_visual lit result.visual_score
    - les logs debug exposent ce score
    - la persistence DB stocke ce champ via _perceptual_mixin
    """
    s_block = _score_blockiness(result.blockiness_mean, multiplier)
    s_blur = _score_blur(result.blur_mean, multiplier)
    s_banding = _score_banding(result.banding_mean, multiplier)
    s_bits = _score_effective_bits(result.effective_bits_mean)
    s_grain = 50  # Grain sera remplace par composite_score en Phase V
    visual = (
        s_block * VISUAL_WEIGHT_BLOCKINESS
        + s_blur * VISUAL_WEIGHT_BLUR
        + s_banding * VISUAL_WEIGHT_BANDING
        + s_bits * VISUAL_WEIGHT_BIT_DEPTH
        + s_grain * VISUAL_WEIGHT_GRAIN_VERDICT
        + temporal_score * VISUAL_WEIGHT_TEMPORAL
    ) / 100
    result.visual_score = max(0, min(100, int(round(visual))))

    if result.visual_score >= TIER_REFERENCE:
        result.visual_tier = "reference"
    elif result.visual_score >= TIER_EXCELLENT:
        result.visual_tier = "excellent"
    elif result.visual_score >= TIER_GOOD:
        result.visual_tier = "bon"
    elif result.visual_score >= TIER_MEDIOCRE:
        result.visual_tier = "mediocre"
    else:
        result.visual_tier = "degrade"
    # Cf issue #51 : pas de return car la signature declare -> None et le
    # caller (analyze_video_frames) n'utilise pas la valeur. Le return
    # result mort precedent suggerait a tort une fonction pure.


# ---------------------------------------------------------------------------
# Helpers statistiques
# ---------------------------------------------------------------------------


def _mean(values: List[float]) -> float:
    """Moyenne arithmetique."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _stddev(values: List[float]) -> float:
    """Ecart-type (population)."""
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))


def _weighted_mean(values: List[float], weights: List[float]) -> float:
    """Moyenne ponderee. Si pas de poids, moyenne simple."""
    if not values:
        return 0.0
    if not weights or len(weights) != len(values):
        return sum(values) / len(values)
    total_w = sum(weights)
    if total_w == 0:
        return sum(values) / len(values)
    return sum(v * w for v, w in zip(values, weights)) / total_w
