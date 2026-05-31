"""Helpers tiers centralises (Vague M / M-06 SCORE-02).

Module dedie pour TOUTE la logique tiers (Platinum / Gold / Silver / Bronze /
Reject) dispersee historiquement dans :

- ``quality_score._determine_tier`` / ``_cap_tier`` / ``_TIER_ORDER``
- ``quality_score.validate_quality_profile`` (normalisation legacy premium/bon/moyen)
- ``explain_score._compute_baseline``
- ``calibration.tier_ordinal`` (alias Premium->Platinum)
- ``ui/api/quality_simulator_support._TIER_ORDER`` (mapping ordinal)
- ``app/export_support._TIER_LABELS`` (mapping label legacy -> canonique)

But : eviter que les seuils par defaut et les alias retro-compat divergent entre
modules (ce qui s'est deja produit : ``_compute_baseline`` utilisait encore
85/68/54/30 alors que la calibration biblio reelle v1.5.7 a aligne tous les
profils sur 70/66/55/40 - cf SCORE-01).

ATTENTION MEMOIRE INVIOLABLE : ce module ne touche PAS aux couleurs hex des
tiers (Platinum/Gold/Silver/Bronze) qui restent definies dans les tokens CSS
(web/shared/tokens.css). Pure logique numerique / labels canoniques.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Constantes canoniques
# ---------------------------------------------------------------------------

# Noms canoniques (v7.2.0+, migration 011). Ordre DU MEILLEUR AU PIRE.
# Coherent avec quality_score._TIER_ORDER (pour _cap_tier).
TIER_ORDER_BEST_FIRST: List[str] = ["Platinum", "Gold", "Silver", "Bronze", "Reject"]

# Ordre inverse (DU PIRE AU MEILLEUR), utilise pour le calcul ordinal numerique
# (Reject=0, Platinum=4). Coherent avec calibration._TIER_ORDER.
TIER_ORDER_WORST_FIRST: List[str] = ["Reject", "Bronze", "Silver", "Gold", "Platinum"]

# Defaults v1.5.7 (calibration biblio reelle 853 films, run 20260530_144631_443).
# Ces valeurs DOIVENT etre identiques a celles de
# ``quality_score.default_quality_profile()["tiers"]`` :
#   Platinum 70 / Gold 66 / Silver 55 / Bronze 40 / (Reject < 40)
DEFAULT_TIER_THRESHOLDS: Dict[str, int] = {
    "platinum": 70,
    "gold": 66,
    "silver": 55,
    "bronze": 40,
}

# Alias retro-compat : noms en MAJUSCULE -> nom canonique CAPITALIZED.
# Couvre l'ancien schema legacy pre-v1.5.5 (Premium/Bon/Moyen/Faible).
_LEGACY_LABEL_ALIASES: Dict[str, str] = {
    "Premium": "Platinum",
    "Bon": "Gold",
    "Moyen": "Silver",
    "Faible": "Bronze",
    "Mauvais": "Reject",
}

# Alias retro-compat sur les CLES de dict tiers (en lower-case).
# Utilise par normalize_tiers pour absorber les profils sauvegardes pre-v1.5.5.
_LEGACY_KEY_ALIASES: Dict[str, str] = {
    "premium": "platinum",
    "bon": "gold",
    "moyen": "silver",
    "faible": "bronze",
}

# Libelles FR longs (utilises par l'UI si besoin de phrases). Le label affiche
# reste le nom canonique anglais (Platinum...) - cf tokens.css invariants.
_TIER_LABEL_FR: Dict[str, str] = {
    "Platinum": "Platine",
    "Gold": "Or",
    "Silver": "Argent",
    "Bronze": "Bronze",
    "Reject": "Rejete",
}


# ---------------------------------------------------------------------------
# Helpers publics
# ---------------------------------------------------------------------------


def normalize_tier_string(raw: Any) -> str:
    """Normalise un nom de tier vers le nom canonique CapitalizedCase.

    Accepte casse libre, espaces, et anciens noms legacy
    (Premium/Bon/Moyen/Faible/Mauvais). Retourne "" si la valeur est vide ou
    ininterpretable - le caller decide du fallback (souvent "Reject").

    >>> normalize_tier_string("premium")
    'Platinum'
    >>> normalize_tier_string("PLATINE")
    'Platinum'
    >>> normalize_tier_string("  Gold  ")
    'Gold'
    >>> normalize_tier_string(None)
    ''
    """
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    # Title case puis lookup alias legacy
    capitalized = s.title()
    if capitalized in _LEGACY_LABEL_ALIASES:
        return _LEGACY_LABEL_ALIASES[capitalized]
    # Tolerance pour les labels FR longs ("Platine" -> "Platinum")
    for canonical, fr_label in _TIER_LABEL_FR.items():
        if capitalized == fr_label:
            return canonical
    if capitalized in TIER_ORDER_BEST_FIRST:
        return capitalized
    return ""


def normalize_tiers(raw_tiers: Any) -> Dict[str, int]:
    """Normalise un dict tiers vers les cles canoniques platinum/gold/silver/bronze.

    Accepte les anciennes cles (premium/bon/moyen/faible) avec leurs alias
    respectifs. Les valeurs manquantes sont completes depuis
    ``DEFAULT_TIER_THRESHOLDS`` (v1.5.7 70/66/55/40).

    Les valeurs sont coercees en int et clamped sur [0, 100]. La validite de
    l'ordre (platinum >= gold >= silver >= bronze) n'est PAS imposee ici - on
    laisse cette responsabilite au validateur de profil (qui retourne un erreur
    explicite). Cette fonction est purement reparatrice/lecture.

    >>> normalize_tiers({"premium": 85, "bon": 70, "moyen": 50, "bronze": 30})
    {'platinum': 85, 'gold': 70, 'silver': 50, 'bronze': 30}
    >>> normalize_tiers({}) == DEFAULT_TIER_THRESHOLDS
    True
    """
    out = dict(DEFAULT_TIER_THRESHOLDS)
    if not isinstance(raw_tiers, dict):
        return out
    # Premiere passe : alias legacy -> canonique.
    # On lit d'abord les canoniques (priorite), puis on remplit avec les alias.
    canonicalized: Dict[str, Any] = {}
    for k, v in raw_tiers.items():
        if not isinstance(k, str):
            continue
        key = k.strip().lower()
        canonical = _LEGACY_KEY_ALIASES.get(key, key)
        # Ne pas ecraser un canonique deja vu par un alias legacy
        if canonical in canonicalized and key in _LEGACY_KEY_ALIASES:
            continue
        canonicalized[canonical] = v
    # Seconde passe : coercion + clamp
    for key in ("platinum", "gold", "silver", "bronze"):
        if key in canonicalized:
            try:
                value = int(canonicalized[key])
            except (TypeError, ValueError):
                value = out[key]
            out[key] = max(0, min(100, value))
    return out


def tier_order(tier: Any) -> int:
    """Retourne l'index du tier dans l'ordre meilleur-vers-pire (Platinum=0, Reject=4).

    Utilise pour le plafonnement (_cap_tier) : un tier plus HAUT a un index plus
    PETIT. Retourne ``len(TIER_ORDER_BEST_FIRST)`` (= 5) pour un tier inconnu,
    ce qui le traite comme pire que Reject - permet a un appelant
    ``max(cur, cap)`` de degrader silencieusement.

    >>> tier_order("Platinum")
    0
    >>> tier_order("Reject")
    4
    >>> tier_order("premium")
    0
    >>> tier_order("???")
    5
    """
    canonical = normalize_tier_string(tier)
    if canonical in TIER_ORDER_BEST_FIRST:
        return TIER_ORDER_BEST_FIRST.index(canonical)
    return len(TIER_ORDER_BEST_FIRST)


def tier_ordinal(tier: Any) -> int:
    """Retourne le rang du tier (0 = Reject, 4 = Platinum). -1 si inconnu.

    Identique semantiquement a ``calibration.tier_ordinal`` historique - sert
    pour le calcul des deltas de feedback (user vs computed).

    >>> tier_ordinal("Platinum")
    4
    >>> tier_ordinal("Reject")
    0
    >>> tier_ordinal("Premium")
    4
    >>> tier_ordinal("???")
    -1
    """
    canonical = normalize_tier_string(tier)
    if canonical in TIER_ORDER_WORST_FIRST:
        return TIER_ORDER_WORST_FIRST.index(canonical)
    return -1


def tier_label_fr(tier: Any) -> str:
    """Retourne le libelle FR long ("Platinum" -> "Platine"). Vide si inconnu.

    >>> tier_label_fr("Platinum")
    'Platine'
    >>> tier_label_fr("premium")
    'Platine'
    >>> tier_label_fr("???")
    ''
    """
    canonical = normalize_tier_string(tier)
    return _TIER_LABEL_FR.get(canonical, "")


def is_premium_tier(tier: Any) -> bool:
    """True si le tier est Platinum ou Gold (haut de gamme).

    Sert pour les decisions UI ou les badges "premium". Les alias legacy sont
    aussi acceptes (Premium -> Platinum).

    >>> is_premium_tier("Platinum")
    True
    >>> is_premium_tier("Gold")
    True
    >>> is_premium_tier("Silver")
    False
    >>> is_premium_tier("Bon")
    True
    """
    return normalize_tier_string(tier) in ("Platinum", "Gold")


def tier_min_score(tier: Any, profile_tiers: Optional[Dict[str, Any]] = None) -> int:
    """Retourne le seuil de score minimum pour atteindre ce tier.

    Si ``profile_tiers`` est fourni, utilise ses seuils (apres normalisation
    legacy). Sinon utilise ``DEFAULT_TIER_THRESHOLDS`` (v1.5.7).

    Pour Reject, retourne 0 (tout score >= 0). Pour un tier inconnu, retourne
    -1 (sentinel).

    >>> tier_min_score("Platinum")
    70
    >>> tier_min_score("Gold")
    66
    >>> tier_min_score("Reject")
    0
    >>> tier_min_score("???")
    -1
    """
    canonical = normalize_tier_string(tier)
    if not canonical:
        return -1
    if canonical == "Reject":
        return 0
    normalized = normalize_tiers(profile_tiers or {})
    return int(normalized.get(canonical.lower(), -1))


def determine_tier(score: int, profile_tiers: Optional[Dict[str, Any]] = None) -> str:
    """Determine le tier canonique a partir d'un score 0..100.

    Equivalent a ``quality_score._determine_tier`` mais utilise la
    normalisation centrale (legacy premium/bon/moyen -> canonique).

    >>> determine_tier(80)
    'Platinum'
    >>> determine_tier(66)
    'Gold'
    >>> determine_tier(40)
    'Bronze'
    >>> determine_tier(39)
    'Reject'
    """
    tiers = normalize_tiers(profile_tiers or {})
    try:
        s = int(score)
    except (TypeError, ValueError):
        return "Reject"
    if s >= tiers["platinum"]:
        return "Platinum"
    if s >= tiers["gold"]:
        return "Gold"
    if s >= tiers["silver"]:
        return "Silver"
    if s >= tiers["bronze"]:
        return "Bronze"
    return "Reject"


def cap_tier(tier: Any, max_tier: Any) -> str:
    """Plafonne ``tier`` a ``max_tier`` (ne remonte jamais vers le haut).

    Coherent avec ``quality_score._cap_tier``. Si l'un des deux est inconnu, on
    retourne ``tier`` tel quel (apres normalisation) - safe default.

    >>> cap_tier("Platinum", "Silver")
    'Silver'
    >>> cap_tier("Bronze", "Silver")
    'Bronze'
    >>> cap_tier("Premium", "Gold")
    'Gold'
    """
    canonical = normalize_tier_string(tier) or str(tier or "")
    canonical_cap = normalize_tier_string(max_tier) or str(max_tier or "")
    if canonical not in TIER_ORDER_BEST_FIRST or canonical_cap not in TIER_ORDER_BEST_FIRST:
        return canonical
    cur = TIER_ORDER_BEST_FIRST.index(canonical)
    cap = TIER_ORDER_BEST_FIRST.index(canonical_cap)
    return TIER_ORDER_BEST_FIRST[max(cur, cap)]


__all__ = [
    "TIER_ORDER_BEST_FIRST",
    "TIER_ORDER_WORST_FIRST",
    "DEFAULT_TIER_THRESHOLDS",
    "normalize_tier_string",
    "normalize_tiers",
    "tier_order",
    "tier_ordinal",
    "tier_label_fr",
    "is_premium_tier",
    "tier_min_score",
    "determine_tier",
    "cap_tier",
]
