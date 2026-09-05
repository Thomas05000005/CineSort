"""Comparaison perceptuelle profonde entre 2 fichiers du meme film."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

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
    if common_w <= 0 or common_h <= 0:
        # Probe incomplet (largeur inconnue) : sans resolution cible, ffmpeg
        # sortirait chaque frame en natif et la comparaison serait faussee
        # (cf issue #559). Mieux vaut ne rien extraire.
        return []

    # Bit depth commun : utiliser 8-bit pour la comparaison (normalise)
    bd = 8

    aligned: List[Dict[str, Any]] = []
    for ts in timestamps:
        raw_a = extract_single_frame(ffmpeg_path, path_a, ts, common_w, common_h, bd, timeout_s)
        raw_b = extract_single_frame(ffmpeg_path, path_b, ts, common_w, common_h, bd, timeout_s)
        if not raw_a or not raw_b:
            continue

        # parse_raw_frame retourne directement un np.ndarray (B3, suppression
        # double copie bytes -> List[int] -> ndarray pour gain memoire ~50%).
        pixels_a = parse_raw_frame(raw_a, common_w, common_h, bd)
        pixels_b = parse_raw_frame(raw_b, common_w, common_h, bd)
        if pixels_a.size == 0 or pixels_b.size == 0:
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


def compute_pixel_diff(pixels_a: Any, pixels_b: Any) -> Optional[Dict[str, float]]:
    """Difference pixel-a-pixel entre deux frames.

    Cf issue #74 : vectorise via numpy (~50x speedup sur frame 1920x1080).
    Les valeurs retournees sont strictement identiques a la version pure Python
    (memes arrondis, meme algo de mediane via tri partiel).

    Accepte ``np.ndarray`` (preferable, zero-copy via parse_raw_frame B3) ou
    ``List[int]`` (legacy, fixtures de tests).
    """
    if len(pixels_a) != len(pixels_b) or len(pixels_a) == 0:
        return None

    a = np.asarray(pixels_a, dtype=np.int64)
    b = np.asarray(pixels_b, dtype=np.int64)
    diffs = np.abs(a - b)
    n = int(diffs.size)
    mean_d = float(diffs.mean())
    max_d = int(diffs.max())
    # Median Python original = sorted_d[n // 2] (mediane "haute" pour n pair).
    # np.partition garde ce comportement sans tri complet.
    median_d = int(np.partition(diffs, n // 2)[n // 2])
    if n > 1:
        # ddof=0 (population stddev) pour matcher math.sqrt(sum((d - mean) ** 2) / n)
        stddev_d = float(diffs.std(ddof=0))
    else:
        stddev_d = 0.0

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
    divergence = sum(abs(a / total_a - b / total_b) for a, b in zip(hist_a, hist_b, strict=False)) / 2.0

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
    *,
    measured_a: bool = True,
    measured_b: bool = True,
) -> Dict[str, Any]:
    """Compare deux valeurs numeriques avec seuil tie.

    #923 : un cote NON MESURE ne peut pas gagner. Pour blockiness / blur /
    banding, `higher_is_better=False` et la valeur de repli est 0.0 : le
    fichier dont l'analyse ffmpeg a echoue remportait donc automatiquement
    « Artefacts » et « Nettete » contre n'importe quelle copie reellement
    mesuree, et ces faux points forts se retrouvaient dans la recommandation
    d'archivage. Sans mesure des deux cotes, le critere ne departage plus.
    """
    delta = value_a - value_b
    ref = max(abs(value_a), abs(value_b), 0.001)
    delta_pct = abs(delta) / ref * 100

    if not (measured_a and measured_b):
        winner = "tie"
    elif delta_pct < _TIE_PCT:
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
        "measured_a": bool(measured_a),
        "measured_b": bool(measured_b),
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


def _metric_measured(video: Dict[str, Any], metric: str, value_key: str) -> bool:
    """#923 — le critere `metric` du rapport `video` repose-t-il sur une mesure ?

    Meme regle que `VideoPerceptual.is_measured` : une valeur non nulle prouve
    la mesure, seul 0.0 est ambigu. La cle `measured` est absente des rapports
    persistes AVANT ce correctif — on retombe alors sur la valeur, ce qui rend
    le verdict correct sur l'historique aussi, sans re-scan.
    """
    block = video.get(metric) or {}
    flag = block.get("measured")
    if flag is not None:
        return bool(flag)
    return float(block.get(value_key) or 0.0) != 0.0


def _visual_coverage(video: Dict[str, Any]) -> Optional[float]:
    """Part du score visuel adossee a une mesure. None si l'info manque."""
    raw = video.get("visual_confidence")
    if raw is None:
        return None
    return max(0.0, min(1.0, float(raw)))


def _clipping_measured(clip: Dict[str, Any]) -> bool:
    """#508 — `total_segments == 0` EST le contrat de « clipping non mesure ».

    Ce contrat n'est pas invente ici : `analyze_clipping_segments` rend
    `{total_segments: 0, clipping_pct: 0.0, verdict: "unknown"}` sur chacun de
    ses trois chemins d'echec, et `audio_perceptual._compute_audio_score` teste
    deja `total_segments > 0` avant de scorer (garde R8-098, « une mesure ratee
    mappait vers la valeur la plus flatteuse »). Ce module etait le second
    lecteur de `clipping_pct`, et le seul a ne pas porter la garde.

    Meme repli que `_metric_measured` pour les rapports anterieurs a la cle :
    une valeur non nulle ne peut venir que d'une mesure, seul 0.0 est ambigu.
    """
    if int(clip.get("total_segments") or 0) > 0:
        return True
    return float(clip.get("clipping_pct") or 0.0) != 0.0


def _build_audio_criteria(audio_a: Dict[str, Any], audio_b: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Les trois criteres audio, sous la meme garde « non mesure » que le video.

    #923 a pose `measured_a`/`measured_b` sur les criteres VIDEO et s'est
    arrete la. Les trois metriques audio portent pourtant le meme piege, et
    `audio_perceptual._compute_audio_score` fait deja la distinction pour les
    trois (`if lra is not None`, `if nf is not None`, `total_segments > 0`) :

    - `loudness_range` et `noise_floor` sont `Optional[float] = None` dans
      `AudioPerceptual` — `or 0` confondait donc « pas de mesure » avec 0 ;
    - `clipping_pct` vaut 0.0 par defaut, et `higher_is_better=False` : c'est
      la valeur PARFAITE. Le fichier dont l'analyse de clipping a echoue
      remportait « Clipping » contre une copie reellement mesuree, et ce faux
      point fort partait dans la recommandation d'archivage.
    """
    ebu_a = audio_a.get("ebu_r128") or {}
    ebu_b = audio_b.get("ebu_r128") or {}
    astats_a = audio_a.get("astats") or {}
    astats_b = audio_b.get("astats") or {}
    clip_a = audio_a.get("clipping") or {}
    clip_b = audio_b.get("clipping") or {}
    return [
        compare_criterion(
            ebu_a.get("loudness_range") or 0,
            ebu_b.get("loudness_range") or 0,
            "Dynamique audio (LRA)",
            higher_is_better=True,
            measured_a=ebu_a.get("loudness_range") is not None,
            measured_b=ebu_b.get("loudness_range") is not None,
        ),
        compare_criterion(
            astats_a.get("noise_floor") or 0,
            astats_b.get("noise_floor") or 0,
            "Bruit de fond (noise floor)",
            higher_is_better=False,
            measured_a=astats_a.get("noise_floor") is not None,
            measured_b=astats_b.get("noise_floor") is not None,
        ),
        compare_criterion(
            clip_a.get("clipping_pct") or 0,
            clip_b.get("clipping_pct") or 0,
            "Clipping",
            higher_is_better=False,
            measured_a=_clipping_measured(clip_a),
            measured_b=_clipping_measured(clip_b),
        ),
    ]


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
            measured_a=_metric_measured(va, "blockiness", "mean"),
            measured_b=_metric_measured(vb, "blockiness", "mean"),
        ),
        compare_criterion(
            va.get("blur", {}).get("mean", 0),
            vb.get("blur", {}).get("mean", 0),
            "Nettete (blur)",
            higher_is_better=False,
            measured_a=_metric_measured(va, "blur", "mean"),
            measured_b=_metric_measured(vb, "blur", "mean"),
        ),
        compare_criterion(
            va.get("banding", {}).get("mean_score", 0),
            vb.get("banding", {}).get("mean_score", 0),
            "Banding",
            higher_is_better=False,
            measured_a=_metric_measured(va, "banding", "mean_score"),
            measured_b=_metric_measured(vb, "banding", "mean_score"),
        ),
        compare_criterion(
            va.get("effective_bit_depth", {}).get("mean_bits", 0),
            vb.get("effective_bit_depth", {}).get("mean_bits", 0),
            "Profondeur effective",
            higher_is_better=True,
            measured_a=_metric_measured(va, "effective_bit_depth", "mean_bits"),
            measured_b=_metric_measured(vb, "effective_bit_depth", "mean_bits"),
        ),
        compare_criterion(
            va.get("local_variance", {}).get("mean_variance", 0),
            vb.get("local_variance", {}).get("mean_variance", 0),
            "Detail (variance)",
            higher_is_better=True,
            measured_a=_metric_measured(va, "local_variance", "mean_variance"),
            measured_b=_metric_measured(vb, "local_variance", "mean_variance"),
        ),
    ]

    # Criteres audio — meme garde « non mesure » que les criteres video (#923).
    criteria += _build_audio_criteria(aa, ab_audio)

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

    # #923 : un score global n'est comparable qu'a couverture de mesure egale.
    # Moins un fichier est mesure, plus son score converge vers les criteres
    # « faciles » (resolution, metadonnees) et remonte : le fichier dont
    # l'analyse a echoue — typiquement un fichier corrompu — pouvait donc
    # sortir GAGNANT, et la recommandation invitait a archiver la copie saine.
    # Tant que la partie manquante n'a pas ete mesuree, on ne conclut pas.
    cov_a, cov_b = _visual_coverage(va), _visual_coverage(vb)
    less_measured = ""
    if cov_a is not None and cov_b is not None and cov_a != cov_b:
        less_measured = "a" if cov_a < cov_b else "b"

    # Le gagnant putatif est-il justement celui qu'on a le moins mesure ?
    inconclusive = bool(less_measured) and less_measured == ("a" if delta > 0 else "b")

    # Gagnant global
    if inconclusive:
        winner = "tie"
        winner_label = (
            f"Comparaison non concluante : l'analyse du fichier {less_measured.upper()} est incomplete "
            "(criteres non mesures)."
        )
    elif abs(delta) < 5:
        winner = "tie"
        winner_label = "Qualite equivalente, differences marginales"
    elif delta > 0:
        winner = "a"
        winner_label = "Fichier A est globalement superieur"
    else:
        winner = "b"
        winner_label = "Fichier B est globalement superieur"

    # Recommendation
    if inconclusive:
        recommendation = (
            f"Le fichier {less_measured.upper()} obtient le meilleur score, mais une partie de ses criteres "
            "n'a PAS pu etre mesuree (analyse ffmpeg incomplete) : son avance n'est pas demontree. "
            "Relancer l'analyse avant d'archiver quoi que ce soit."
        )
    else:
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
        # #923 : « tie » par egalite mesuree n'est pas « tie » faute de mesure.
        "inconclusive": inconclusive,
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
