"""Signatures grain par ere et contexte (§15 v7.5.0).

Table de connaissances editee a la main :
  - 6 bandes d'ere (+ large_format_classic pour 70mm)
  - 5 regles d'exception matchees en ordre de specificite
    (animation, studios animation majeurs, 16mm horror, Nolan, A24)

La table est concue pour etre enrichie progressivement via les retours
utilisateurs. Pas de calibration ML — verdicts editoriaux argumentes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .constants import (
    GRAIN_ERA_V2,
    GRAIN_PROFILE_BY_ERA_V2,
    GRAIN_SIGNATURES_EXCEPTIONS,
)


def classify_film_era_v2(
    year: int,
    film_format: Optional[str] = None,
) -> str:
    """Classifie l'ere de production en 6 bandes + exception 70mm.

    Args:
        year: annee de production TMDb (0 ou < 0 -> "unknown").
        film_format: optionnel ; "70mm" force la bande "large_format_classic".

    Returns:
        Une des cles de GRAIN_ERA_V2 ou "large_format_classic" ou "unknown".
    """
    if film_format and str(film_format).lower() in ("70mm", "imax_film", "large_format"):
        return "large_format_classic"
    try:
        y = int(year)
    except (TypeError, ValueError):
        return "unknown"
    if y <= 0:
        return "unknown"
    # Parcourir dans l'ordre d'insertion (Python 3.7+ garantit)
    for era_name, threshold in GRAIN_ERA_V2.items():
        if y < threshold:
            return era_name
    return "unknown"


def detect_film_format_hint(
    video_height: int,
    tmdb_runtime_min: int,
    tmdb_keywords: List[str],
    year: int,
) -> Optional[str]:
    """Heuristique pour flagger format 70mm / IMAX Film.

    Indices :
      - tmdb keyword contient "70mm" ou "imax film"
      - resolution native > 4320p + annee < 2000 (scan archive IMAX)
      - runtime > 150 min ET annee < 1990 (epopee 70mm probable)

    Returns:
        "70mm" ou None.
    """
    kws = [str(k).lower() for k in (tmdb_keywords or [])]
    for kw in kws:
        if "70mm" in kw or "imax film" in kw or "large format" in kw:
            return "70mm"
    try:
        h = int(video_height or 0)
        rt = int(tmdb_runtime_min or 0)
        y = int(year or 0)
    except (TypeError, ValueError):
        return None
    if h > 4320 and 0 < y < 2000:
        return "70mm"
    if rt > 150 and 0 < y < 1990:
        return "70mm"
    return None


def _rule_matches(
    rule: Dict[str, Any],
    era: str,
    genres: List[str],
    budget: int,
    companies: List[str],
    country: Optional[str],
) -> bool:
    """Teste si une regle d'exception matche le contexte."""
    # era
    rule_era = rule.get("era")
    if rule_era is not None and rule_era != "*":
        if rule_era != era:
            return False
    rule_era_any = rule.get("era_any")
    if rule_era_any and era not in rule_era_any:
        return False

    # genres_any (match si au moins un genre du film est dans la liste)
    rule_genres = rule.get("genres_any")
    if rule_genres:
        genres_low = [str(g).strip().lower() for g in (genres or [])]
        rule_low = [str(g).strip().lower() for g in rule_genres]
        if not any(rg in genres_low for rg in rule_low):
            return False

    # companies_any
    rule_companies = rule.get("companies_any")
    if rule_companies:
        companies_low = [str(c).strip().lower() for c in (companies or [])]
        rule_low = [str(c).strip().lower() for c in rule_companies]
        if not any(rc in companies_low for rc in rule_low):
            return False

    # budget_min / budget_max
    try:
        b = int(budget or 0)
    except (TypeError, ValueError):
        b = 0
    if "budget_min" in rule and b < int(rule["budget_min"]):
        return False
    if "budget_max" in rule and b > int(rule["budget_max"]):
        return False

    # country
    rule_country = rule.get("country")
    if rule_country and str(country or "").lower() != str(rule_country).lower():
        return False

    return True


def get_expected_grain_signature(
    era: str,
    genres: Optional[List[str]] = None,
    budget: int = 0,
    companies: Optional[List[str]] = None,
    country: Optional[str] = None,
) -> Dict[str, Any]:
    """Retourne la signature grain attendue pour ce contexte.

    Cascade :
      1. Premiere regle matchante dans GRAIN_SIGNATURES_EXCEPTIONS (ordre = priorite)
      2. GRAIN_PROFILE_BY_ERA_V2[era] (fallback par defaut)

    Returns:
        Dict {level_mean, level_tolerance, uniformity_max,
              texture_variance_baseline, label}.
    """
    genres_list = list(genres or [])
    companies_list = list(companies or [])

    for rule in GRAIN_SIGNATURES_EXCEPTIONS:
        if _rule_matches(rule, era, genres_list, budget, companies_list, country):
            return {
                "level_mean": float(rule.get("level_mean", 0.0)),
                "level_tolerance": float(rule.get("level_tolerance", 0.5)),
                "uniformity_max": float(rule.get("uniformity_max", 0.90)),
                "texture_variance_baseline": float(rule.get("texture_variance_baseline", 120.0)),
                "label": str(rule.get("label", "custom_rule")),
            }

    # Fallback : profil par ere (ou profil digital_modern si ere unknown)
    profile = GRAIN_PROFILE_BY_ERA_V2.get(era) or GRAIN_PROFILE_BY_ERA_V2["digital_modern"]
    return {
        "level_mean": float(profile["level_mean"]),
        "level_tolerance": float(profile["level_tolerance"]),
        "uniformity_max": float(profile["uniformity_max"]),
        "texture_variance_baseline": float(profile["texture_variance_baseline"]),
        "label": f"default_{era}_profile",
    }
