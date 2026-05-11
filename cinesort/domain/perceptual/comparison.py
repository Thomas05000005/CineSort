"""Comparaison perceptuelle profonde entre 2 fichiers du meme film."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from .constants import (
    FRAME_DOWNSCALE_THRESHOLD,
)
from .frame_extraction import (
    compute_timestamps,
    extract_single_frame,
    is_valid_frame,
    parse_raw_frame,
)
from .video_analysis import (
    block_variance_stats,
    detect_banding,
    luminance_histogram,
)

# Seuil tie : delta < 5 % du max des deux valeurs
_TIE_PCT = 5.0


# ---------------------------------------------------------------------------
# Extraction de frames alignees
# ---------------------------------------------------------------------------


def extract_aligned_frames(
    ffmpeg_path: str,
    path_a: str,
    path_b: str,
    duration_a: float,
    duration_b: float,
    width_a: int,
    height_a: int,
    width_b: int,
    height_b: int,
    bit_depth_a: int = 8,
    bit_depth_b: int = 8,
    frames_count: int = 20,
    skip_percent: int = 5,
    timeout_s: float = 30.0,
) -> List[Dict[str, Any]]:
    """Extrait des frames alignees temporellement depuis deux fichiers.

    Les timestamps sont bases sur la plus courte des deux durees.
    Les deux frames sont downscalees a la plus petite resolution commune.
    """
    dur = min(float(duration_a), float(duration_b))
    if dur <= 0:
        return []

    timestamps = compute_timestamps(dur, frames_count, skip_percent)
    if not timestamps:
        return []

    # Resolution commune : min des deux widths
    common_w = min(int(width_a), int(width_b))
    if common_w > FRAME_DOWNSCALE_THRESHOLD:
        common_w = 1920
    common_h_a = max(1, int(round(int(height_a) * common_w / max(1, int(width_a)))))
    common_h_b = max(1, int(round(int(height_b) * common_w / max(1, int(width_b)))))
    # Prendre la plus petite hauteur pour uniformiser
    common_h = min(common_h_a, common_h_b)

    # Bit depth commun : utiliser 8-bit pour la comparaison (normalise)
    bd = 8

    aligned: List[Dict[str, Any]] = []
    for ts in timestamps:
        raw_a = extract_single_frame(ffmpeg_path, path_a, ts, common_w, common_h, bd, timeout_s)
        raw_b = extract_single_frame(ffmpeg_path, path_b, ts, common_w, common_h, bd, timeout_s)
        if not raw_a or not raw_b:
            continue

        pixels_a = parse_raw_frame(raw_a, common_w, common_h, bd)
        pixels_b = parse_raw_frame(raw_b, common_w, common_h, bd)
        if not pixels_a or not pixels_b:
            continue

        if not is_valid_frame(pixels_a, common_w, common_h, bd):
            continue
        if not is_valid_frame(pixels_b, common_w, common_h, bd):
            continue

        aligned.append(
            {
                "timestamp": round(ts, 3),
                "pixels_a": pixels_a,
                "pixels_b": pixels_b,
                "width": common_w,
                "height": common_h,
            }
        )

    return aligned


# ---------------------------------------------------------------------------
# Diff pixel
# ---------------------------------------------------------------------------


def compute_pixel_diff(pixels_a: List[int], pixels_b: List[int]) -> Optional[Dict[str, float]]:
    """Difference pixel-a-pixel entre deux frames."""
    if len(pixels_a) != len(pixels_b) or not pixels_a:
        return None

    diffs = [abs(a - b) for a, b in zip(pixels_a, pixels_b)]
    n = len(diffs)
    mean_d = sum(diffs) / n
    max_d = max(diffs)
    sorted_d = sorted(diffs)
    median_d = sorted_d[n // 2]
    stddev_d = math.sqrt(sum((d - mean_d) ** 2 for d in diffs) / n) if n > 1 else 0.0

    return {
        "mean_diff": round(mean_d, 2),
        "stddev_diff": round(stddev_d, 2),
        "max_diff": max_d,
        "median_diff": median_d,
    }


# ---------------------------------------------------------------------------
# Comparaison histogrammes
# ---------------------------------------------------------------------------


def compare_histograms(hist_a: List[int], hist_b: List[int]) -> Dict[str, Any]:
    """Divergence entre deux histogrammes et determination du plus detaille."""
    total_a = sum(hist_a)
    total_b = sum(hist_b)
    if total_a == 0 or total_b == 0:
        return {"divergence": 0.0, "levels_a": 0, "levels_b": 0, "detail_winner": "tie"}

    # Divergence normalisee
    divergence = sum(abs(a / total_a - b / total_b) for a, b in zip(hist_a, hist_b)) / 2.0

    # Niveaux distincts (seuil bruit 0.001 %)
    thresh_a = total_a * 0.00001
    thresh_b = total_b * 0.00001
    levels_a = sum(1 for c in hist_a if c > thresh_a)
    levels_b = sum(1 for c in hist_b if c > thresh_b)

    if levels_a > levels_b * 1.05:
        winner = "a"
    elif levels_b > levels_a * 1.05:
        winner = "b"
    else:
        winner = "tie"

    return {
        "divergence": round(divergence, 4),
        "levels_a": levels_a,
        "levels_b": levels_b,
        "detail_winner": winner,
    }


# ---------------------------------------------------------------------------
# Comparaison par frame
# ---------------------------------------------------------------------------


def compare_per_frame(
    frames_aligned: List[Dict[str, Any]],
    bit_depth: int = 8,
) -> List[Dict[str, Any]]:
    """Compare chaque paire de frames alignees sur plusieurs metriques."""
    results: List[Dict[str, Any]] = []

    for frame in frames_aligned:
        pa = frame["pixels_a"]
        pb = frame["pixels_b"]
        w = frame["width"]
        h = frame["height"]
        ts = frame["timestamp"]

        pd = compute_pixel_diff(pa, pb)

        hist_a = luminance_histogram(pa, bit_depth)
        hist_b = luminance_histogram(pb, bit_depth)
        hc = compare_histograms(hist_a, hist_b)

        var_a = block_variance_stats(pa, w, h, bit_depth=bit_depth)
        var_b = block_variance_stats(pb, w, h, bit_depth=bit_depth)

        band_a = detect_banding(hist_a)
        band_b = detect_banding(hist_b)

        results.append(
            {
                "timestamp": ts,
                "pixel_diff": pd,
                "histogram": hc,
                "variance_a": var_a.get("mean_variance", 0),
                "variance_b": var_b.get("mean_variance", 0),
                "banding_a": band_a.get("score", 0),
                "banding_b": band_b.get("score", 0),
            }
        )

    return results


# ---------------------------------------------------------------------------
# Comparaison d'un critere
# ---------------------------------------------------------------------------


def compare_criterion(
    value_a: float,
    value_b: float,
    criterion_name: str,
    higher_is_better: bool = True,
) -> Dict[str, Any]:
    """Compare deux valeurs numeriques avec seuil tie."""
    delta = value_a - value_b
    ref = max(abs(value_a), abs(value_b), 0.001)
    delta_pct = abs(delta) / ref * 100

    if delta_pct < _TIE_PCT:
        winner = "tie"
    elif higher_is_better:
        winner = "a" if delta > 0 else "b"
    else:
        winner = "a" if delta < 0 else "b"

    return {
        "criterion": criterion_name,
        "value_a": round(value_a, 3),
        "value_b": round(value_b, 3),
        "winner": winner,
        "delta": round(abs(delta), 3),
        "delta_pct": round(delta_pct, 1),
    }


# ---------------------------------------------------------------------------
# Rapport de comparaison
# ---------------------------------------------------------------------------


_LPIPS_VERDICT_FR = {
    "identical": "Les 2 fichiers sont visuellement quasi-identiques.",
    "very_similar": "Tres similaires — probablement meme source, encodes differents.",
    "similar": "Similaires — meme film, possiblement versions ou masters differents.",
    "different": "Differents — versions distinctes (theatrical vs extended ?) ou remaster couleur.",
    "very_different": "Tres differents — attention, possible erreur de comparaison.",
    "insufficient_data": "Donnees insuffisantes pour evaluation perceptuelle apprise.",
}


def _build_lpips_criterion(lpips_result: Any) -> Optional[Dict[str, Any]]:
    """Genere un critere LPIPS au format build_comparison_report."""
    if lpips_result is None:
        return None
    dist = getattr(lpips_result, "distance_median", None)
    verdict = getattr(lpips_result, "verdict", "insufficient_data")
    if dist is None:
        return None
    return {
        "criterion": "Distance perceptuelle apprise (LPIPS)",
        "value_a": "reference",
        "value_b": f"{dist:.3f} ({verdict})",
        "winner": "tie",  # LPIPS mesure la similarite, pas la qualite
        "delta": round(float(dist), 3),
        "delta_pct": 0.0,
        "detail_fr": _LPIPS_VERDICT_FR.get(verdict, ""),
        "n_pairs": int(getattr(lpips_result, "n_pairs_evaluated", 0)),
    }


def build_comparison_report(
    perceptual_a: Dict[str, Any],
    perceptual_b: Dict[str, Any],
    per_frame_results: List[Dict[str, Any]],
    path_a: str,
    path_b: str,
    lpips_result: Optional[Any] = None,
) -> Dict[str, Any]:
    """Construit le rapport de comparaison complet entre deux fichiers."""
    va = perceptual_a.get("video_perceptual") or {}
    vb = perceptual_b.get("video_perceptual") or {}
    aa = perceptual_a.get("audio_perceptual") or {}
    ab_audio = perceptual_b.get("audio_perceptual") or {}

    # Criteres video (lower is better pour block, blur, banding)
    criteria = [
        compare_criterion(
            va.get("blockiness", {}).get("mean", 0),
            vb.get("blockiness", {}).get("mean", 0),
            "Artefacts (blockiness)",
            higher_is_better=False,
        ),
        compare_criterion(
            va.get("blur", {}).get("mean", 0),
            vb.get("blur", {}).get("mean", 0),
            "Nettete (blur)",
            higher_is_better=False,
        ),
        compare_criterion(
            va.get("banding", {}).get("mean_score", 0),
            vb.get("banding", {}).get("mean_score", 0),
            "Banding",
            higher_is_better=False,
        ),
        compare_criterion(
            va.get("effective_bit_depth", {}).get("mean_bits", 0),
            vb.get("effective_bit_depth", {}).get("mean_bits", 0),
            "Profondeur effective",
            higher_is_better=True,
        ),
        compare_criterion(
            va.get("local_variance", {}).get("mean_variance", 0),
            vb.get("local_variance", {}).get("mean_variance", 0),
            "Detail (variance)",
            higher_is_better=True,
        ),
    ]

    # Criteres audio
    ebu_a = aa.get("ebu_r128") or {}
    ebu_b = ab_audio.get("ebu_r128") or {}
    astats_a = aa.get("astats") or {}
    astats_b = ab_audio.get("astats") or {}
    clip_a = aa.get("clipping") or {}
    clip_b = ab_audio.get("clipping") or {}

    criteria += [
        compare_criterion(
            ebu_a.get("loudness_range") or 0,
            ebu_b.get("loudness_range") or 0,
            "Dynamique audio (LRA)",
            higher_is_better=True,
        ),
        compare_criterion(
            astats_a.get("noise_floor") or 0,
            astats_b.get("noise_floor") or 0,
            "Bruit de fond (noise floor)",
            higher_is_better=False,
        ),
        compare_criterion(
            clip_a.get("clipping_pct") or 0, clip_b.get("clipping_pct") or 0, "Clipping", higher_is_better=False
        ),
    ]

    # §11 v7.5.0 — LPIPS (similarite perceptuelle apprise, pas gagnant mais info)
    lpips_crit = _build_lpips_criterion(lpips_result)
    if lpips_crit is not None:
        criteria.append(lpips_crit)

    # Agreger per-frame
    pixel_diffs = [f["pixel_diff"]["mean_diff"] for f in per_frame_results if f.get("pixel_diff")]
    hist_divs = [f["histogram"]["divergence"] for f in per_frame_results if f.get("histogram")]
    mean_pixel_diff = sum(pixel_diffs) / len(pixel_diffs) if pixel_diffs else 0.0
    mean_hist_div = sum(hist_divs) / len(hist_divs) if hist_divs else 0.0

    # Scores globaux
    score_a = int(perceptual_a.get("global_score") or 0)
    score_b = int(perceptual_b.get("global_score") or 0)
    delta = score_a - score_b

    # Gagnant global
    if abs(delta) < 5:
        winner = "tie"
        winner_label = "Qualite equivalente, differences marginales"
    elif delta > 0:
        winner = "a"
        winner_label = "Fichier A est globalement superieur"
    else:
        winner = "b"
        winner_label = "Fichier B est globalement superieur"

    # Recommendation
    recommendation = _build_recommendation(criteria, winner, path_a, path_b, delta)

    # Criteria summary
    criteria_summary = [
        {"criterion": c["criterion"], "winner": c["winner"], "delta": f"{c['delta']:.1f}"} for c in criteria
    ]

    return {
        "file_a": path_a,
        "file_b": path_b,
        "score_a": score_a,
        "score_b": score_b,
        "score_delta": abs(delta),
        "winner": winner,
        "winner_label": winner_label,
        "recommendation": recommendation,
        "criteria": criteria,
        "criteria_summary": criteria_summary,
        "frames_compared": len(per_frame_results),
        "direct_comparison": {
            "pixel_diff_mean": round(mean_pixel_diff, 2),
            "histogram_divergence_mean": round(mean_hist_div, 4),
            "frames_detail": [
                {
                    "timestamp": f["timestamp"],
                    "pixel_diff_mean": f["pixel_diff"]["mean_diff"] if f.get("pixel_diff") else 0,
                    "variance_a": f.get("variance_a", 0),
                    "variance_b": f.get("variance_b", 0),
                    "banding_a": f.get("banding_a", 0),
                    "banding_b": f.get("banding_b", 0),
                }
                for f in per_frame_results
            ],
        },
    }


def _build_recommendation(
    criteria: List[Dict[str, Any]],
    winner: str,
    path_a: str,
    path_b: str,
    delta: int,
) -> str:
    """Genere une recommendation textuelle en francais."""
    if winner == "tie":
        return "Les deux fichiers sont de qualite equivalente. Les differences mesurees sont dans la marge d'erreur."

    better = "A" if winner == "a" else "B"
    worse = "B" if winner == "a" else "A"

    # Points forts du gagnant
    wins = [c["criterion"] for c in criteria if c["winner"] == winner]
    losses = [c["criterion"] for c in criteria if c["winner"] != winner and c["winner"] != "tie"]

    parts = [f"Le fichier {better} est globalement superieur (delta {abs(delta)} points)."]
    if wins:
        parts.append(f"Points forts : {', '.join(wins[:4])}.")
    if losses:
        parts.append(f"Le fichier {worse} est meilleur sur : {', '.join(losses[:3])}.")

    return " ".join(parts)
