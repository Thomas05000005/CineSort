"""Detection grain / DNR avec verdict contextualise par les metadonnees TMDb."""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from .constants import (
    DNR_BLUR_THRESHOLD,
    ERA_CLASSIC_FILM,
    ERA_TRANSITION,
    BUDGET_HIGH,
    GRAIN_LIGHT,
    GRAIN_MODERATE,
    GRAIN_NONE,
    GRAIN_UNIFORMITY_ARTIFICIAL,
    GRAIN_UNIFORMITY_NATURAL,
    MAJOR_STUDIOS,
)
from .models import GrainAnalysis

# Seuil de variance pour considerer un bloc comme "plat" (analyse grain)
_FLAT_VAR_THRESH_8BIT = 100.0
_FLAT_VAR_THRESH_10BIT = 1600.0


# ---------------------------------------------------------------------------
# Estimation du grain
# ---------------------------------------------------------------------------


def estimate_grain(
    pixels: List[int],
    width: int,
    height: int,
    block_size: int = 16,
    bit_depth: int = 8,
) -> Dict[str, Any]:
    """Estime le niveau de grain dans les zones plates d'une frame.

    Retourne ``{grain_level, grain_uniformity, flat_zone_count}``.
    """
    w, h, bs = int(width), int(height), int(block_size)
    if w < bs or h < bs or not pixels:
        return {"grain_level": 0.0, "grain_uniformity": 1.0, "flat_zone_count": 0}

    flat_thresh = _FLAT_VAR_THRESH_10BIT if bit_depth >= 10 else _FLAT_VAR_THRESH_8BIT
    flat_stddevs: List[float] = []

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
            if var < flat_thresh:
                flat_stddevs.append(math.sqrt(var))

    if not flat_stddevs:
        return {"grain_level": 0.0, "grain_uniformity": 1.0, "flat_zone_count": 0}

    mean_std = sum(flat_stddevs) / len(flat_stddevs)
    # Uniformite : faible variation entre les stddevs = grain tres regulier (suspect)
    if mean_std > 0.01:
        std_of_std = math.sqrt(sum((s - mean_std) ** 2 for s in flat_stddevs) / len(flat_stddevs))
        uniformity = 1.0 - min(1.0, std_of_std / mean_std)
    else:
        uniformity = 1.0

    return {
        "grain_level": round(mean_std, 3),
        "grain_uniformity": round(uniformity, 3),
        "flat_zone_count": len(flat_stddevs),
    }


# ---------------------------------------------------------------------------
# Classification ere de production
# ---------------------------------------------------------------------------


def classify_film_era(year: Optional[int]) -> str:
    """Classifie l'ere de production d'un film."""
    if not year or int(year) <= 0:
        return "unknown"
    y = int(year)
    if y < ERA_CLASSIC_FILM:
        return "classic_film"
    if y < ERA_TRANSITION:
        return "transition"
    return "digital"


def is_major_studio(companies: List[str]) -> bool:
    """True si au moins une company est un studio majeur."""
    return any(str(c).strip() in MAJOR_STUDIOS for c in companies or [])


# ---------------------------------------------------------------------------
# Orchestrateur grain / DNR
# ---------------------------------------------------------------------------


def analyze_grain(
    frames_data: List[Dict[str, Any]],
    video_blur_mean: float = 0.0,
    tmdb_metadata: Optional[Dict[str, Any]] = None,
    bit_depth: int = 8,
    tmdb_year: int = 0,
) -> GrainAnalysis:
    """Analyse le grain et produit un verdict contextualise.

    ``tmdb_metadata`` doit contenir ``genres``, ``budget``, ``production_companies``
    (retourne par ``TmdbClient.get_movie_metadata_for_perceptual``).
    """
    result = GrainAnalysis(tmdb_year=tmdb_year, score=50)
    meta = tmdb_metadata or {}

    # --- Metadata TMDb ---
    genres: List[str] = meta.get("genres", [])
    budget: int = int(meta.get("budget") or 0)
    companies: List[str] = meta.get("production_companies", [])

    result.tmdb_genres = list(genres)
    result.tmdb_budget = budget
    result.is_animation = any("animation" in str(g).lower() for g in genres)
    result.film_era = classify_film_era(tmdb_year)
    result.is_major_studio = is_major_studio(companies)

    # --- Estimation grain sur toutes les frames ---
    grain_levels: List[float] = []
    grain_uniformities: List[float] = []
    flat_zone_total = 0

    for fd in frames_data:
        pixels = fd.get("pixels", [])
        fw = fd.get("width", 0)
        fh = fd.get("height", 0)
        if not pixels:
            continue
        ge = estimate_grain(pixels, fw, fh, bit_depth=bit_depth)
        grain_levels.append(ge["grain_level"])
        grain_uniformities.append(ge["grain_uniformity"])
        flat_zone_total += ge["flat_zone_count"]

    if grain_levels:
        result.grain_level = round(sum(grain_levels) / len(grain_levels), 3)
    if grain_uniformities:
        result.grain_uniformity = round(sum(grain_uniformities) / len(grain_uniformities), 3)
    result.flat_zone_count = flat_zone_total

    # --- Animation : skip ---
    if result.is_animation:
        result.verdict = "not_applicable"
        result.verdict_label = "Non applicable (animation)"
        result.verdict_detail = "L'analyse grain/DNR est desactivee pour les films d'animation (aplats normaux)."
        result.verdict_confidence = 0.90
        result.score = 50
        return result

    # --- Verdict contextualise ---
    blur = float(video_blur_mean)
    gl = result.grain_level
    gu = result.grain_uniformity
    era = result.film_era

    # Confiance de base
    confidence = 0.60
    if era != "unknown":
        confidence += 0.10
    if budget > 0:
        confidence += 0.05
    if companies:
        confidence += 0.05
    if flat_zone_total >= 50:
        confidence += 0.10

    if era == "classic_film":
        _verdict_classic(result, gl, gu, blur, confidence)
    elif era == "digital":
        _verdict_digital(result, gl, gu, confidence)
    elif era == "transition":
        _verdict_transition(result, gl, gu, blur, confidence)
    else:
        _verdict_unknown(result, gl, gu, blur, confidence)

    # Ajustement score selon budget / studio (attente plus haute)
    if result.is_major_studio and result.score > 30:
        result.score = max(0, result.score - 5)
    if budget >= BUDGET_HIGH and result.score > 30:
        result.score = max(0, result.score - 5)

    result.verdict_confidence = round(min(0.99, confidence), 2)
    logger.debug("grain: verdict=%s grain_level=%.1f era=%s", result.verdict, result.grain_level, era)
    return result


# ---------------------------------------------------------------------------
# Verdicts par ere
# ---------------------------------------------------------------------------


def _verdict_classic(r: GrainAnalysis, gl: float, gu: float, blur: float, confidence: float) -> None:
    """Verdict pour film pre-2002 (pellicule attendue)."""
    # Uniformite artificielle : seulement si du grain est reellement present
    if gl >= GRAIN_NONE and gu > GRAIN_UNIFORMITY_ARTIFICIAL:
        r.verdict = "grain_artificiel_suspect"
        r.verdict_label = "Grain artificiel suspect"
        r.verdict_detail = (
            f"Film de {r.tmdb_year} : le grain detecte (niveau {gl:.1f}) est anormalement uniforme "
            f"(uniformite {gu:.2f}) — possible ajout de grain en post-production."
        )
        r.artificial_grain_suspect = True
        r.score = 40
        return

    if gl >= GRAIN_MODERATE and gu < GRAIN_UNIFORMITY_NATURAL:
        r.verdict = "grain_naturel_preserve"
        r.verdict_label = "Grain naturel preserve"
        r.verdict_detail = (
            f"Film de {r.tmdb_year} tourne sur pellicule. Le grain detecte (niveau {gl:.1f}) "
            "est coherent avec un scan de qualite respectueux du media d'origine."
        )
        r.score = 85
        return

    if gl < GRAIN_NONE and blur > DNR_BLUR_THRESHOLD:
        r.verdict = "dnr_suspect"
        r.verdict_label = "DNR suspect — lissage excessif"
        r.verdict_detail = (
            f"Film de {r.tmdb_year} tourne sur pellicule, mais le grain est absent "
            f"(niveau {gl:.1f}) avec un flou eleve ({blur:.3f}). "
            "Reduction de bruit numerique (DNR) probable — perte de details."
        )
        r.dnr_suspect = True
        r.score = 25
        return

    if gl < GRAIN_NONE:
        r.verdict = "grain_absent_suspect"
        r.verdict_label = "Grain absent (inhabituel)"
        r.verdict_detail = (
            f"Film de {r.tmdb_year} tourne sur pellicule, mais le grain est absent "
            f"(niveau {gl:.1f}) sans flou anormal. Source atypique ou scan specifique."
        )
        r.score = 55
        return

    # Cas intermediaire : grain present mais pas exceptionnel
    r.verdict = "grain_present"
    r.verdict_label = "Grain present"
    r.verdict_detail = f"Film de {r.tmdb_year} : grain detecte (niveau {gl:.1f}), coherent avec l'ere pellicule."
    r.score = 70


def _verdict_digital(r: GrainAnalysis, gl: float, gu: float, confidence: float) -> None:
    """Verdict pour film post-2012 (source numerique)."""
    if gl > GRAIN_MODERATE:
        r.verdict = "bruit_numerique_excessif"
        r.verdict_label = "Bruit numerique excessif"
        r.verdict_detail = (
            f"Film de {r.tmdb_year} tourne en numerique. Le bruit detecte (niveau {gl:.1f}) "
            "est anormal pour une source digitale — encode de mauvaise qualite ou capteur mediocre."
        )
        r.score = 30
        return

    if gl < GRAIN_LIGHT:
        r.verdict = "image_propre_normal"
        r.verdict_label = "Image propre — normal"
        r.verdict_detail = (
            f"Film de {r.tmdb_year} tourne en numerique. Image propre (niveau {gl:.1f}), "
            "normal pour une camera numerique moderne."
        )
        r.score = 80
        return

    # Grain leger en digital : acceptable
    r.verdict = "grain_leger_digital"
    r.verdict_label = "Grain leger (digital)"
    r.verdict_detail = (
        f"Film de {r.tmdb_year} : leger grain detecte (niveau {gl:.1f}). "
        "Acceptable pour du contenu numerique, possiblement ajoute en post-production."
    )
    r.score = 65


def _verdict_transition(r: GrainAnalysis, gl: float, gu: float, blur: float, confidence: float) -> None:
    """Verdict pour film 2002-2012 (transition film/digital)."""
    # Memes verdicts que classic mais confiance reduite
    if gl >= GRAIN_NONE and gu > GRAIN_UNIFORMITY_ARTIFICIAL:
        r.verdict = "grain_artificiel_suspect"
        r.verdict_label = "Grain artificiel suspect"
        r.verdict_detail = (
            f"Film de {r.tmdb_year} (ere de transition). Grain anormalement uniforme (uniformite {gu:.2f})."
        )
        r.artificial_grain_suspect = True
        r.score = 45
        return

    if gl >= GRAIN_MODERATE:
        r.verdict = "grain_present"
        r.verdict_label = "Grain present"
        r.verdict_detail = (
            f"Film de {r.tmdb_year} (ere de transition). Grain detecte (niveau {gl:.1f}) — "
            "coherent si tourne sur pellicule."
        )
        r.score = 70
        return

    if gl < GRAIN_NONE and blur > DNR_BLUR_THRESHOLD:
        r.verdict = "dnr_suspect"
        r.verdict_label = "DNR possible"
        r.verdict_detail = (
            f"Film de {r.tmdb_year} : grain absent (niveau {gl:.1f}) avec flou ({blur:.3f}). "
            "DNR possible si source pellicule."
        )
        r.dnr_suspect = True
        r.score = 35
        return

    r.verdict = "image_propre_normal"
    r.verdict_label = "Image propre"
    r.verdict_detail = f"Film de {r.tmdb_year} (ere de transition). Image propre (niveau {gl:.1f})."
    r.score = 70


def _verdict_unknown(r: GrainAnalysis, gl: float, gu: float, blur: float, confidence: float) -> None:
    """Verdict sans metadata d'annee — seuils standards, confiance basse."""
    if gl > GRAIN_MODERATE:
        r.verdict = "grain_present"
        r.verdict_label = "Grain present"
        r.verdict_detail = f"Annee inconnue. Grain detecte (niveau {gl:.1f})."
        r.score = 60
    elif gl < GRAIN_NONE and blur > DNR_BLUR_THRESHOLD:
        r.verdict = "dnr_suspect"
        r.verdict_label = "DNR possible"
        r.verdict_detail = f"Annee inconnue. Grain absent avec flou ({blur:.3f}) — DNR possible."
        r.dnr_suspect = True
        r.score = 40
    else:
        r.verdict = "indetermine"
        r.verdict_label = "Indetermine"
        r.verdict_detail = f"Annee inconnue, grain niveau {gl:.1f}. Verdict non conclusif."
        r.score = 50


# ---------------------------------------------------------------------------
# §15 v7.5.0 — Grain Intelligence v2 (section phare)
# ---------------------------------------------------------------------------


def analyze_grain_v2(
    frames_data: List[Dict[str, Any]],
    video_blur_mean: float = 0.0,
    tmdb_metadata: Optional[Dict[str, Any]] = None,
    bit_depth: int = 8,
    tmdb_year: int = 0,
    av1_grain_info: Optional[Any] = None,
    video_height: int = 0,
) -> GrainAnalysis:
    """Version 2 enrichie de analyze_grain (§15).

    Ajoute :
      - Classification ere v2 (6 bandes + 70mm exception)
      - Signature attendue par contexte (ere + genres + companies)
      - Classification nature grain (film vs encode vs post_added)
      - Detection DNR partiel
      - Bonus AV1 AFGS1 si metadata presente
      - Contexte historique FR pour l'UI

    Args:
        av1_grain_info: Av1FilmGrainInfo optionnel (§15 av1_grain_metadata).
        video_height: utilise pour la detection format 70mm.

    Returns:
        GrainAnalysis enrichi (18 nouveaux champs).
    """
    import numpy as np

    from .grain_classifier import classify_grain_nature, detect_partial_dnr
    from .grain_signatures import (
        classify_film_era_v2,
        detect_film_format_hint,
        get_expected_grain_signature,
    )

    # 1. Analyse existante v1 (conservee pour backward compat)
    result = analyze_grain(frames_data, video_blur_mean, tmdb_metadata, bit_depth, tmdb_year)

    # 2. Format hint (70mm) + ere v2
    tmdb_runtime = int((tmdb_metadata or {}).get("runtime") or 0)
    tmdb_keywords = list((tmdb_metadata or {}).get("keywords") or [])
    film_format = detect_film_format_hint(int(video_height or 0), tmdb_runtime, tmdb_keywords, int(tmdb_year or 0))
    era_v2 = classify_film_era_v2(int(tmdb_year or 0), film_format=film_format)
    result.film_era_v2 = era_v2
    result.film_format_detected = film_format

    # 3. Signature attendue
    genres = list((tmdb_metadata or {}).get("genres") or [])
    companies = list((tmdb_metadata or {}).get("production_companies") or [])
    budget = int((tmdb_metadata or {}).get("budget") or 0)
    country = (tmdb_metadata or {}).get("origin_country")
    signature = get_expected_grain_signature(
        era_v2,
        genres=genres,
        budget=budget,
        companies=companies,
        country=country,
    )
    result.expected_grain_level = float(signature["level_mean"])
    result.expected_grain_tolerance = float(signature["level_tolerance"])
    result.expected_grain_uniformity_max = float(signature["uniformity_max"])
    result.signature_label = str(signature["label"])

    # 4. Preparation frames pour les analyses FFT/correlation
    frames_y: List[np.ndarray] = []
    for f in frames_data or []:
        if not isinstance(f, dict):
            continue
        pixels = f.get("pixels")
        w = int(f.get("width") or 0)
        h = int(f.get("height") or 0)
        if not pixels or w <= 0 or h <= 0:
            continue
        expected = w * h
        if len(pixels) < expected:
            continue
        try:
            arr = np.asarray(pixels[:expected], dtype=np.float64).reshape(h, w)
            frames_y.append(arr)
        except (ValueError, TypeError):
            continue

    # 5. Classification nature grain (si >= 3 frames valides)
    if len(frames_y) >= 3:
        nature_verdict = classify_grain_nature(frames_y, frames_rgb=None)
        result.grain_nature = nature_verdict.nature
        result.grain_nature_confidence = nature_verdict.confidence
        result.temporal_correlation = nature_verdict.temporal_corr
        result.spatial_lag8_ratio = nature_verdict.spatial_lag8_ratio
        result.spatial_lag16_ratio = nature_verdict.spatial_lag16_ratio
        result.cross_color_correlation = nature_verdict.cross_color_corr

    # 6. DNR partiel (baseline depuis signature)
    baseline = float(signature["texture_variance_baseline"])
    if frames_y:
        dnr_verdict = detect_partial_dnr(frames_y, result.grain_level, baseline)
        result.is_partial_dnr = dnr_verdict.is_partial_dnr
        result.texture_loss_ratio = dnr_verdict.texture_loss_ratio
        result.texture_variance_actual = dnr_verdict.texture_actual
        result.texture_variance_baseline = dnr_verdict.texture_baseline

    # 7. Bonus AV1 AFGS1 : score visuel +15 si encodage grain-respectueux
    if av1_grain_info is not None and getattr(av1_grain_info, "present", False):
        result.av1_afgs1_present = True
        from .constants import GRAIN_AV1_AFGS1_BONUS

        result.score = min(100, int(result.score) + GRAIN_AV1_AFGS1_BONUS)

    # 8. Contexte historique FR pour l'UI
    result.historical_context_fr = build_grain_historical_context(result, era_v2, signature, tmdb_metadata)

    return result


def build_grain_historical_context(
    grain: GrainAnalysis,
    era: str,
    signature: Dict[str, Any],
    tmdb_metadata: Optional[Dict[str, Any]],
) -> str:
    """Genere un bloc texte FR pour afficher dans la modale UI.

    Format : 6-8 lignes avec mesures + interpretation humaine.
    """
    lines: List[str] = []
    era_labels = {
        "16mm_era": "Ere 16mm/35mm classique (avant 1980)",
        "35mm_classic": "Ere 35mm classique (1980-1999)",
        "late_film": "Fin de l'ere pellicule (1999-2006)",
        "transition": "Transition pellicule/numerique (2006-2013)",
        "digital_modern": "Numerique moderne (2013-2021)",
        "digital_hdr_era": "Numerique HDR (2021+)",
        "large_format_classic": "Grand format classique (70mm / IMAX Film)",
        "unknown": "Ere de production inconnue",
    }
    lines.append(f"Contexte : {era_labels.get(era, era)}")

    if grain.film_format_detected:
        lines.append(f"Format detecte : {grain.film_format_detected}")

    expected = float(signature.get("level_mean", 0.0))
    tolerance = float(signature.get("level_tolerance", 0.5))
    lines.append(f"Grain attendu : {expected:.1f} +/- {tolerance:.1f} (profil '{signature.get('label', 'default')}')")
    lines.append(f"Grain mesure : {grain.grain_level:.1f}")

    deviation = grain.grain_level - expected
    if abs(deviation) <= tolerance:
        lines.append("-> Conforme a l'ere, qualite grain preservee.")
    elif deviation > tolerance:
        lines.append(f"-> Grain superieur a l'attendu (+{deviation:.1f}) : possible post-add ou encode noise.")
    else:
        lines.append(f"-> Grain inferieur ({deviation:.1f}) : DNR possible, texture reduite.")

    nature_labels = {
        "film_grain": "grain argentique authentique",
        "encode_noise": "bruit de compression (pas film grain)",
        "post_added": "grain artificiel post-ajoute",
        "ambiguous": "signal ambigu",
        "unknown": "non classifie (frames insuffisantes)",
    }
    if grain.grain_nature != "unknown":
        lines.append(
            f"Nature : {nature_labels.get(grain.grain_nature, grain.grain_nature)} "
            f"(confiance {grain.grain_nature_confidence:.0%})"
        )

    if grain.is_partial_dnr:
        lines.append(f"ALERTE DNR partiel : {int(grain.texture_loss_ratio * 100)}% de texture perdue.")

    if grain.av1_afgs1_present:
        lines.append("Bonus : AV1 Film Grain Synthesis (AFGS1) detecte — encodage grain-respectueux.")

    return "\n".join(lines)
