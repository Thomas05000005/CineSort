"""Grain classifier (§15 v7.5.0) — nature du grain + DNR partiel.

Coeur technique de §15 : distingue grain argentique authentique, bruit de
compression, et grain post-ajoute en combinant 3 metriques :

  - corr temporelle (film_grain = frames independantes, encode = blocs preserves)
  - autocorr spatiale 8 directions (encode = pics a lag 8/16 correspondant aux
    blocs DCT, film = decroissance isotrope)
  - corr cross-color (film grain touche tous canaux, encode noise decorrele)

Detection DNR partiel : ratio texture_actual / baseline < 0.7 et grain_level
< 1.5 -> DNR agressif suspect.

Les frames doivent etre fournies en np.ndarray 2D (Y luminance).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from .constants import (
    DNR_PARTIAL_GRAIN_LEVEL_MAX,
    DNR_PARTIAL_TEXTURE_RATIO,
    FLAT_ZONE_BLOCK_SIZE,
    FLAT_ZONE_MAX_COUNT,
    FLAT_ZONE_VARIANCE_THRESHOLD,
    GRAIN_CROSS_COLOR_CORR_AUTHENTIC,
    GRAIN_NATURE_WEIGHT_CROSS_COLOR,
    GRAIN_NATURE_WEIGHT_SPATIAL,
    GRAIN_NATURE_WEIGHT_TEMPORAL,
    GRAIN_SPATIAL_LAG_PEAK_RATIO,
    GRAIN_TEMPORAL_CORR_AUTHENTIC,
    GRAIN_TEMPORAL_CORR_ENCODE,
    TEXTURE_ZONE_VARIANCE_MAX,
    TEXTURE_ZONE_VARIANCE_MIN,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GrainNatureVerdict:
    """Verdict sur la nature du grain detecte."""

    nature: str  # "film_grain" | "encode_noise" | "post_added" | "ambiguous" | "unknown"
    confidence: float  # 0.0-1.0
    temporal_corr: float
    spatial_lag8_ratio: float
    spatial_lag16_ratio: float
    cross_color_corr: Optional[float]


@dataclass(frozen=True)
class DnrPartialVerdict:
    """Verdict sur la presence de DNR partiel (debruitage agressif)."""

    is_partial_dnr: bool
    texture_loss_ratio: float
    texture_actual: float
    texture_baseline: float
    detail_fr: str


# ---------------------------------------------------------------------------
# Detection des zones plates
# ---------------------------------------------------------------------------


def find_flat_zones(
    frame_y: np.ndarray,
    block_size: int = FLAT_ZONE_BLOCK_SIZE,
    flat_threshold: float = FLAT_ZONE_VARIANCE_THRESHOLD,
    max_zones: int = FLAT_ZONE_MAX_COUNT,
) -> List[Tuple[int, int, int, int]]:
    """Trouve les blocs a faible variance (zones plates).

    Args:
        frame_y: image luminance 2D (float ou int).
        block_size: cote des blocs carres.
        flat_threshold: variance max pour considerer un bloc plat.
        max_zones: nombre max de zones retournees (les plus plates d'abord).

    Returns:
        Liste de (y, x, h, w). Vide si frame trop petite ou aucune zone plate.
    """
    if frame_y is None or frame_y.ndim != 2:
        return []
    h, w = frame_y.shape
    bs = int(block_size)
    if h < bs or w < bs:
        return []

    arr = frame_y.astype(np.float64, copy=False)
    # Calcul variance par bloc
    candidates: List[Tuple[float, int, int]] = []
    for y in range(0, h - bs + 1, bs):
        for x in range(0, w - bs + 1, bs):
            block = arr[y : y + bs, x : x + bs]
            var = float(np.var(block))
            if var < flat_threshold:
                candidates.append((var, y, x))
    if not candidates:
        return []
    # Garder les N plus plates (variance croissante)
    candidates.sort(key=lambda t: t[0])
    cap = max(1, int(max_zones))
    selected = candidates[:cap]
    return [(y, x, bs, bs) for (_v, y, x) in selected]


# ---------------------------------------------------------------------------
# Correlation temporelle
# ---------------------------------------------------------------------------


def _pearson_corr(a: np.ndarray, b: np.ndarray) -> float:
    """Coefficient Pearson entre 2 arrays 1D ou flatten. Retourne 0 si degenerate."""
    af = a.astype(np.float64, copy=False).ravel()
    bf = b.astype(np.float64, copy=False).ravel()
    if af.size < 2 or bf.size < 2 or af.size != bf.size:
        return 0.0
    mean_a = float(af.mean())
    mean_b = float(bf.mean())
    da = af - mean_a
    db = bf - mean_b
    num = float(np.sum(da * db))
    denom = float(np.sqrt(np.sum(da * da) * np.sum(db * db)))
    if denom <= 0.0:
        return 0.0
    return num / denom


def compute_temporal_correlation(
    frames_y: List[np.ndarray],
    flat_zones_per_frame: List[List[Tuple[int, int, int, int]]],
) -> float:
    """Correlation moyenne du bruit entre frames consecutives.

    Strategie :
      - Pour chaque paire (frame_i, frame_{i+1}) :
          - Pour chaque zone plate intersectant les 2 frames :
              - Calcule le residu (bloc - moyenne du bloc)
              - Correlation Pearson entre residus des 2 frames
      - Moyenne globale des correlations.

    Returns:
        Correlation moyenne 0.0-1.0 (ou borne negative si decorrele).
        0.0 si moins de 2 frames ou aucune zone exploitable.
    """
    if not frames_y or len(frames_y) < 2:
        return 0.0
    correlations: List[float] = []
    n_pairs = len(frames_y) - 1
    for i in range(n_pairs):
        fa = frames_y[i]
        fb = frames_y[i + 1]
        if fa.shape != fb.shape:
            continue
        zones = flat_zones_per_frame[i] if i < len(flat_zones_per_frame) else []
        for y, x, bh, bw in zones:
            y_end = y + bh
            x_end = x + bw
            if y_end > fa.shape[0] or x_end > fa.shape[1]:
                continue
            block_a = fa[y:y_end, x:x_end].astype(np.float64)
            block_b = fb[y:y_end, x:x_end].astype(np.float64)
            res_a = block_a - float(block_a.mean())
            res_b = block_b - float(block_b.mean())
            corr = _pearson_corr(res_a, res_b)
            correlations.append(abs(corr))  # sens anti-correlation = similaire
    if not correlations:
        return 0.0
    return float(np.mean(correlations))


# ---------------------------------------------------------------------------
# Autocorrelation spatiale 8 directions
# ---------------------------------------------------------------------------


# 8 voisins (dy, dx)
_DIRECTIONS_8 = (
    (-1, 0),
    (1, 0),
    (0, -1),
    (0, 1),  # N, S, W, E
    (-1, -1),
    (-1, 1),
    (1, -1),
    (1, 1),  # NW, NE, SW, SE
)


def _autocorr_shift(block: np.ndarray, dy: int, dx: int) -> float:
    """Correlation entre bloc et sa version shiftee de (dy, dx)."""
    h, w = block.shape
    ay = max(0, dy)
    ax = max(0, dx)
    by = max(0, -dy)
    bx = max(0, -dx)
    if ay + by >= h or ax + bx >= w:
        return 0.0
    a = block[ay : h - by, ax : w - bx]
    b = block[by : h - ay, bx : w - ax]
    if a.shape != b.shape or a.size == 0:
        return 0.0
    return _pearson_corr(a, b)


def compute_spatial_autocorr_8dir(
    frame_y: np.ndarray,
    flat_zones: List[Tuple[int, int, int, int]],
    lags: Optional[List[int]] = None,
) -> Dict[int, float]:
    """Autocorrelation 8 directions, moyennee sur les zones plates.

    Pour chaque lag, prend le max de 8 directions (dy, dx) scales par lag :
      corr_lag = moyenne sur zones de max_dir(|pearson(block, shift(block, dy*lag, dx*lag))|)

    Un encode DCT 8x8 laisse des pics a lag 8 (et harmonique lag 16).
    Un grain argentique decrit isotrope -> pas de pics distincts.

    Returns:
        {lag: correlation_moyenne}. {} si aucun bloc exploitable.
    """
    if lags is None:
        lags = [1, 8, 16]
    if frame_y is None or frame_y.ndim != 2 or not flat_zones:
        return {lag: 0.0 for lag in lags}

    arr = frame_y.astype(np.float64, copy=False)
    result: Dict[int, List[float]] = {lag: [] for lag in lags}

    for y, x, bh, bw in flat_zones:
        y_end = y + bh
        x_end = x + bw
        if y_end > arr.shape[0] or x_end > arr.shape[1]:
            continue
        block = arr[y:y_end, x:x_end]
        res = block - float(block.mean())
        for lag in lags:
            vals: List[float] = []
            for dy, dx in _DIRECTIONS_8:
                c = _autocorr_shift(res, dy * lag, dx * lag)
                vals.append(abs(c))
            if vals:
                result[lag].append(float(max(vals)))

    return {lag: (float(np.mean(v)) if v else 0.0) for lag, v in result.items()}


# ---------------------------------------------------------------------------
# Cross-color correlation
# ---------------------------------------------------------------------------


def compute_cross_color_correlation(
    frames_rgb: Optional[List[np.ndarray]],
    flat_zones_per_frame: List[List[Tuple[int, int, int, int]]],
) -> Optional[float]:
    """Correlation moyenne du bruit entre canaux R, G, B.

    Args:
        frames_rgb: liste de frames shape (H, W, 3) ou None/[] si indispo.
        flat_zones_per_frame: zones plates pour chaque frame (memes indices).

    Returns:
        Moyenne des 3 correlations (R-G + G-B + R-B) / 3, ou None si
        frames RGB indisponibles (N&B, pas de RGB, etc.).
    """
    if not frames_rgb:
        return None
    correlations: List[float] = []
    for idx, frame in enumerate(frames_rgb):
        if frame is None or frame.ndim != 3 or frame.shape[2] < 3:
            continue
        zones = flat_zones_per_frame[idx] if idx < len(flat_zones_per_frame) else []
        for y, x, bh, bw in zones:
            y_end = y + bh
            x_end = x + bw
            if y_end > frame.shape[0] or x_end > frame.shape[1]:
                continue
            block = frame[y:y_end, x:x_end].astype(np.float64)
            r = block[:, :, 0] - float(block[:, :, 0].mean())
            g = block[:, :, 1] - float(block[:, :, 1].mean())
            b = block[:, :, 2] - float(block[:, :, 2].mean())
            c_rg = _pearson_corr(r, g)
            c_gb = _pearson_corr(g, b)
            c_rb = _pearson_corr(r, b)
            correlations.append((abs(c_rg) + abs(c_gb) + abs(c_rb)) / 3.0)
    if not correlations:
        return None
    return float(np.mean(correlations))


# ---------------------------------------------------------------------------
# Verdict nature grain
# ---------------------------------------------------------------------------


def classify_grain_nature(
    frames_y: List[np.ndarray],
    frames_rgb: Optional[List[np.ndarray]] = None,
) -> GrainNatureVerdict:
    """Classifie la nature du grain detecte dans les frames.

    Combine 3 metriques (poids 50/30/20) :
      - temporal_corr : faible = film_grain, eleve = encode_noise
      - spatial autocorr lag 8/16 vs lag 1 : pics = encode DCT
      - cross-color : eleve = film (touche tous canaux)

    Si < 3 frames valides -> verdict "unknown" (insufficient_frames).

    Returns:
        GrainNatureVerdict avec verdict + confidence + metriques brutes.
    """
    if not frames_y or len(frames_y) < 3:
        return GrainNatureVerdict(
            nature="unknown",
            confidence=0.0,
            temporal_corr=0.0,
            spatial_lag8_ratio=0.0,
            spatial_lag16_ratio=0.0,
            cross_color_corr=None,
        )

    # Flat zones par frame
    zones_per_frame = [find_flat_zones(f) for f in frames_y]

    # Correlation temporelle
    temporal = compute_temporal_correlation(frames_y, zones_per_frame)

    # Autocorrelation spatiale (moyenne sur toutes les frames)
    lag_values = {1: [], 8: [], 16: []}
    for frame, zones in zip(frames_y, zones_per_frame):
        corrs = compute_spatial_autocorr_8dir(frame, zones, lags=[1, 8, 16])
        for lag in (1, 8, 16):
            lag_values[lag].append(corrs.get(lag, 0.0))
    mean_lag1 = float(np.mean(lag_values[1])) if lag_values[1] else 0.0
    mean_lag8 = float(np.mean(lag_values[8])) if lag_values[8] else 0.0
    mean_lag16 = float(np.mean(lag_values[16])) if lag_values[16] else 0.0
    lag8_ratio = mean_lag8 / mean_lag1 if mean_lag1 > 1e-9 else 0.0
    lag16_ratio = mean_lag16 / mean_lag1 if mean_lag1 > 1e-9 else 0.0

    # Cross-color
    cross_color = compute_cross_color_correlation(frames_rgb, zones_per_frame)

    # Verdicts partiels avec scores signes [-1, +1] (negatif = encode, positif = film)
    # Temporal : low = film (score +), high = encode (score -)
    if temporal < GRAIN_TEMPORAL_CORR_AUTHENTIC:
        temporal_score = 1.0
    elif temporal > GRAIN_TEMPORAL_CORR_ENCODE:
        temporal_score = -1.0
    else:
        # Zone intermediaire : interpolation lineaire
        span = GRAIN_TEMPORAL_CORR_ENCODE - GRAIN_TEMPORAL_CORR_AUTHENTIC
        if span > 0:
            pos = (temporal - GRAIN_TEMPORAL_CORR_AUTHENTIC) / span
            temporal_score = 1.0 - 2.0 * pos
        else:
            temporal_score = 0.0

    # Spatial : peak ratio > 1.3 = encode (score -), < 1.0 = film (score +)
    peak_ratio = max(lag8_ratio, lag16_ratio)
    if peak_ratio >= GRAIN_SPATIAL_LAG_PEAK_RATIO:
        spatial_score = -1.0
    elif peak_ratio <= 0.8:
        spatial_score = 1.0
    else:
        spatial_score = 1.0 - 2.0 * (peak_ratio - 0.8) / (GRAIN_SPATIAL_LAG_PEAK_RATIO - 0.8)

    # Cross-color : high = film (score +)
    if cross_color is None:
        # Redistribuer le poids cross_color sur temporal+spatial (50/50 -> 62.5/37.5)
        w_t = GRAIN_NATURE_WEIGHT_TEMPORAL + GRAIN_NATURE_WEIGHT_CROSS_COLOR * 0.625
        w_s = GRAIN_NATURE_WEIGHT_SPATIAL + GRAIN_NATURE_WEIGHT_CROSS_COLOR * 0.375
        w_c = 0.0
        cross_score = 0.0
    else:
        w_t = GRAIN_NATURE_WEIGHT_TEMPORAL
        w_s = GRAIN_NATURE_WEIGHT_SPATIAL
        w_c = GRAIN_NATURE_WEIGHT_CROSS_COLOR
        if cross_color >= GRAIN_CROSS_COLOR_CORR_AUTHENTIC:
            cross_score = 1.0
        elif cross_color <= 0.2:
            cross_score = -1.0
        else:
            cross_score = 1.0 - 2.0 * (GRAIN_CROSS_COLOR_CORR_AUTHENTIC - cross_color) / (
                GRAIN_CROSS_COLOR_CORR_AUTHENTIC - 0.2
            )

    combined = w_t * temporal_score + w_s * spatial_score + w_c * cross_score

    # Verdict
    if combined >= 0.5:
        nature = "film_grain"
        confidence = min(1.0, 0.6 + combined * 0.4)
    elif combined <= -0.5:
        nature = "encode_noise"
        confidence = min(1.0, 0.6 + abs(combined) * 0.4)
    elif abs(combined) < 0.15:
        # Zone neutre : si spatial_score fortement negatif + temporal eleve
        # -> possible grain post-ajoute (motif artificiel)
        if peak_ratio > 1.1 and temporal > 0.5:
            nature = "post_added"
            confidence = 0.55
        else:
            nature = "ambiguous"
            confidence = 0.40
    else:
        nature = "ambiguous"
        confidence = 0.50

    return GrainNatureVerdict(
        nature=nature,
        confidence=confidence,
        temporal_corr=temporal,
        spatial_lag8_ratio=lag8_ratio,
        spatial_lag16_ratio=lag16_ratio,
        cross_color_corr=cross_color,
    )


# ---------------------------------------------------------------------------
# DNR partiel
# ---------------------------------------------------------------------------


def _texture_zone_variance(frames_y: List[np.ndarray], block_size: int = 16) -> float:
    """Variance moyenne sur les blocs "texture" (entre low et high variance).

    Les zones texture sont des blocs avec variance entre TEXTURE_ZONE_VARIANCE_MIN
    et TEXTURE_ZONE_VARIANCE_MAX (ni totalement plats, ni detail fort). C'est la
    que le DNR fait le plus gros degat.
    """
    if not frames_y:
        return 0.0
    variances: List[float] = []
    for frame in frames_y:
        if frame is None or frame.ndim != 2:
            continue
        h, w = frame.shape
        if h < block_size or w < block_size:
            continue
        arr = frame.astype(np.float64, copy=False)
        for y in range(0, h - block_size + 1, block_size):
            for x in range(0, w - block_size + 1, block_size):
                var = float(np.var(arr[y : y + block_size, x : x + block_size]))
                if TEXTURE_ZONE_VARIANCE_MIN < var < TEXTURE_ZONE_VARIANCE_MAX:
                    variances.append(var)
    if not variances:
        return 0.0
    return float(np.mean(variances))


def detect_partial_dnr(
    frames_y: List[np.ndarray],
    grain_level: float,
    texture_variance_baseline: float,
) -> DnrPartialVerdict:
    """Detecte un DNR partiel (debruitage agressif qui efface la texture).

    Logique :
      - Mesure variance moyenne sur zones texture (pas plat, pas detail)
      - Compare au baseline attendu pour cette ere
      - Si ratio < 0.7 ET grain_level < 1.5 -> DNR partiel probable
    """
    texture_actual = _texture_zone_variance(frames_y)
    baseline = max(1.0, float(texture_variance_baseline))
    if texture_actual <= 0.0:
        return DnrPartialVerdict(
            is_partial_dnr=False,
            texture_loss_ratio=0.0,
            texture_actual=0.0,
            texture_baseline=baseline,
            detail_fr="Donnees texture insuffisantes pour evaluer le DNR.",
        )

    ratio = texture_actual / baseline
    # Clamp a [0, 1] : on parle de "perte", pas de "gain"
    loss = max(0.0, 1.0 - ratio)

    is_dnr = ratio < DNR_PARTIAL_TEXTURE_RATIO and float(grain_level) < DNR_PARTIAL_GRAIN_LEVEL_MAX

    if is_dnr:
        detail = (
            f"Texture residuelle {texture_actual:.0f} vs baseline {baseline:.0f} "
            f"(ratio {ratio:.2f}). Perte ~{int(loss * 100)}% : DNR agressif "
            "probable, la finesse cinema est estompee."
        )
    elif ratio < DNR_PARTIAL_TEXTURE_RATIO:
        detail = f"Texture reduite mais grain preserve ({grain_level:.1f}), pas de DNR suspect."
    else:
        detail = f"Texture normale pour cette ere (ratio {ratio:.2f})."

    return DnrPartialVerdict(
        is_partial_dnr=is_dnr,
        texture_loss_ratio=loss,
        texture_actual=texture_actual,
        texture_baseline=baseline,
        detail_fr=detail,
    )
