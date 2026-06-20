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

from typing import Any, Dict, List, Optional, Tuple

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


# ---------------------------------------------------------------------------
# VN-B.2 : reconciliation V1 vs V2 + display_tier explicite
# ---------------------------------------------------------------------------

# Echelle canonique V2 (lowercase). Single source of truth pour le frontend.
# Correspond aux classes CSS --tier-{name} (hex colors INVARIANTES).
TIER_V2_CANONICAL: List[str] = ["platinum", "gold", "silver", "bronze", "reject"]

# Mapping V1 (Capitalized: Platinum/Gold/Silver/Bronze/Reject + legacy
# Premium/Bon/Moyen/Faible/Mauvais) -> V2 canonical (lowercase).
# Note : V1 et V2 partagent les MEMES noms canoniques (Platinum->platinum)
# malgre des SEUILS differents (70/66/55/40 vs 90/80/65/50). La
# reconciliation est donc une simple normalisation de casse + alias legacy,
# pas un recalcul de score.
_V1_TO_V2_CANONICAL: Dict[str, str] = {
    "Platinum": "platinum",
    "Gold": "gold",
    "Silver": "silver",
    "Bronze": "bronze",
    "Reject": "reject",
}


def to_canonical_v2_tier(raw: Any) -> str:
    """Normalise n'importe quelle valeur de tier vers l'echelle V2 lowercase.

    Accepte :
    - V2 lowercase : platinum/gold/silver/bronze/reject (pass-through)
    - V1 Capitalized : Platinum/Gold/Silver/Bronze/Reject (lowercase)
    - Legacy : Premium/Bon/Moyen/Faible/Mauvais (via normalize_tier_string)
    - Vide / None / inconnu : "" (le caller decide du fallback)

    >>> to_canonical_v2_tier("platinum")
    'platinum'
    >>> to_canonical_v2_tier("Platinum")
    'platinum'
    >>> to_canonical_v2_tier("Premium")
    'platinum'
    >>> to_canonical_v2_tier("")
    ''
    >>> to_canonical_v2_tier(None)
    ''
    """
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    low = s.lower()
    if low in TIER_V2_CANONICAL:
        return low
    canonical_v1 = normalize_tier_string(s)
    if canonical_v1 in _V1_TO_V2_CANONICAL:
        return _V1_TO_V2_CANONICAL[canonical_v1]
    return ""


def reconcile_display_tier(
    perc_tier_v2: Any = None,
    qual_tier_v1: Any = None,
    default: str = "unknown",
) -> Tuple[str, str]:
    """Reconciliation explicite V1/V2 -> (display_tier, source).

    Strategie : V2 prioritaire (echelle moderne 90/80/65/50). Fallback V1
    (70/66/55/40, label Capitalized) normalise vers V2 lowercase. Sans
    donnee, retourne (default, "fallback").

    Returns:
        (display_tier, source) ou source ∈ {
            "perceptual",   # perc.global_tier_v2 utilise (V2 vraie)
            "quality_v1",   # qual.tier (Capitalized) mappe en lowercase
            "quality_v2",   # qual.tier deja en lowercase V2 (rare)
            "fallback",     # aucune donnee, default utilise
        }

    NOTE : V1 et V2 ont des SEUILS differents (un film a 75/100 est Platinum
    en V1 mais Silver en V2). On NE recalcule PAS depuis le score, on garde
    le tier source tel quel apres normalisation de casse. C'est une
    approximation acceptable car le but du fallback est d'afficher QUELQUE
    chose tant que le user n'a pas lance l'analyse perceptuelle V2 (qui
    coute ~1h pour 853 films) - la valeur sera raffinee a posteriori.

    >>> reconcile_display_tier("platinum", "Bronze")
    ('platinum', 'perceptual')
    >>> reconcile_display_tier(None, "Gold")
    ('gold', 'quality_v1')
    >>> reconcile_display_tier(None, "gold")
    ('gold', 'quality_v2')
    >>> reconcile_display_tier(None, None)
    ('unknown', 'fallback')
    """
    # 1. V2 perceptual prioritaire
    v2 = to_canonical_v2_tier(perc_tier_v2)
    if v2:
        return v2, "perceptual"

    # 2. V1 quality_report : detection casse pour distinguer V1 / V2 deja lowercase
    if qual_tier_v1 is not None:
        raw = str(qual_tier_v1).strip()
        if raw:
            canonical = to_canonical_v2_tier(raw)
            if canonical:
                # Si la valeur source etait deja en lowercase ET match V2
                # canonical, on l'attribue a "quality_v2" pour debug (cas rare
                # mais documente). Sinon (Capitalized/Premium/etc.) -> quality_v1.
                if raw == raw.lower() and raw in TIER_V2_CANONICAL:
                    return canonical, "quality_v2"
                return canonical, "quality_v1"

    # 3. Fallback
    return default, "fallback"


# ---------------------------------------------------------------------------
# VP-B (Vague P) : hierarchie qualite multi-axes (inspire TRaSH/Radarr 2026)
# ---------------------------------------------------------------------------
#
# Principe "Quality Trumps All" : certaines dimensions techniques (resolution,
# codec, HDR, audio, release_group) imposent un PLANCHER de tier ou un
# PLAFOND, independamment du score numerique calcule. Exemple :
#
#   - Un fichier 2160p HDR10+ mesure (probe) ne peut PAS finir en Bronze
#     meme si son audio est moyen -> floor Gold sur dimension resolution.
#   - Un fichier 720p ne peut PAS finir en Platinum meme avec audio premium
#     -> ceiling Silver sur dimension resolution.
#
# Cette logique est entierement OPT-IN (toggle hierarchy_config.enabled=False
# par defaut). Quand desactive, ``apply_tier_hierarchy`` retourne le tier
# d'entree sans modification (no-op strict). Le but : preserver le scoring
# V1 existant sur les biblio reelles deja calibrees (memo fix #4 ROADMAP
# Vague P : eviter de redistribuer 30-40% des tiers sans validation user).
#
# IMPORTANT : cette logique agit UNIQUEMENT sur les tiers V1 (quality_score).
# Elle NE TOUCHE PAS le pipeline perceptual V2 (composite_score_v2, 766 LOC)
# qui possede sa propre echelle V2 (memo feedback_cinesort_design :
# ``perceptual_reports != quality_reports``).
#
# IMPORTANT 2 : cette logique s'execute AVANT ``cap_tier`` (FAILED/CAM) qui
# reste l'autorite finale de securite. Un fichier probe FAILED reste
# plafonne Silver meme si la hierarchie tentait de le pousser Platinum.

# Defaults TRaSH/Radarr 2026 "Quality Trumps All" - DESACTIVES par defaut.
# Les dimensions sont listees par ordre de priorite (la PREMIERE dimension
# qui declenche un floor/ceiling l'emporte). L'utilisateur peut re-ordonner
# via l'UI parametres (drag-and-drop, fix #4 ROADMAP).
DEFAULT_HIERARCHY_DIMENSIONS_ORDER: List[str] = [
    "resolution",
    "video_codec",
    "hdr",
    "audio",
    "release_group",
]

# Planchers de tier par dimension. Format : { dimension_value : tier_floor }.
# Un floor "Gold" signifie que le tier final ne pourra PAS etre inferieur a
# Gold pour cette valeur de dimension. Les valeurs absentes du mapping ne
# declenchent aucun floor (no-op).
#
# Source : TRaSH-Guides Radarr v3.x "Custom Format Groups" (2026 reference
# community Radarr/Sonarr). Adaptee a l'echelle CineSort 4 tiers
# (Platinum/Gold/Silver/Bronze).
DEFAULT_HIERARCHY_RESOLUTION_FLOORS: Dict[str, str] = {
    # 2160p mesure (probe) = certitude UHD -> Gold minimum.
    # NOTE : "2160p_probe" (avec suffixe) distingue probe verifie du fallback
    # nom de release (qui peut mentir : "4K" dans le nom + 1080p reel).
    "2160p_probe": "Gold",
}

DEFAULT_HIERARCHY_RESOLUTION_CEILINGS: Dict[str, str] = {
    # 720p ne peut pas etre Platinum (memo TRaSH 2026 : la resolution
    # est determinante pour l'UHD).
    "720p": "Silver",
    "SD": "Bronze",
}

DEFAULT_HIERARCHY_CODEC_FLOORS: Dict[str, str] = {
    # Pas de codec floor par defaut (AV1/HEVC sont des bonus mais pas
    # un floor a eux seuls - une encode HEVC 720p reste 720p).
}

DEFAULT_HIERARCHY_HDR_FLOORS: Dict[str, str] = {
    # Dolby Vision sur film 2160p mesure -> Gold floor (couvert par
    # resolution_floors si combine). DV seul ne sera applique qu'en
    # presence de probe verifie.
    "dolby_vision": "Gold",
    "hdr10_plus": "Silver",
}

DEFAULT_HIERARCHY_AUDIO_FLOORS: Dict[str, str] = {
    # TrueHD Atmos lossless + multicanal premium -> Gold floor.
    "truehd_atmos": "Gold",
}

DEFAULT_HIERARCHY_GROUP_FLOORS: Dict[str, str] = {
    # Pas de release_group floor par defaut (a calibrer par user).
}


def default_hierarchy_config() -> Dict[str, Any]:
    """Retourne le default hierarchy_config : DESACTIVE, defaults TRaSH 2026.

    Le profil utilisateur peut surcharger n'importe quelle cle via
    ``validate_quality_profile`` (section ``tier_hierarchy``).

    >>> cfg = default_hierarchy_config()
    >>> cfg["enabled"]
    False
    >>> cfg["order"]
    ['resolution', 'video_codec', 'hdr', 'audio', 'release_group']
    """
    return {
        "enabled": False,
        "order": list(DEFAULT_HIERARCHY_DIMENSIONS_ORDER),
        "resolution_floors": dict(DEFAULT_HIERARCHY_RESOLUTION_FLOORS),
        "resolution_ceilings": dict(DEFAULT_HIERARCHY_RESOLUTION_CEILINGS),
        "codec_floors": dict(DEFAULT_HIERARCHY_CODEC_FLOORS),
        "hdr_floors": dict(DEFAULT_HIERARCHY_HDR_FLOORS),
        "audio_floors": dict(DEFAULT_HIERARCHY_AUDIO_FLOORS),
        "group_floors": dict(DEFAULT_HIERARCHY_GROUP_FLOORS),
    }


def normalize_hierarchy_config(raw: Any) -> Dict[str, Any]:
    """Normalise un hierarchy_config user vers la shape canonique.

    Les profils legacy SANS cle ``tier_hierarchy`` recoivent le default
    (enabled=False) - garantit la backward compat ABSOLUE V1 (AC-1 VP-B).

    Les profils avec ``tier_hierarchy`` partiel (ex: juste ``enabled=True``)
    voient leurs champs manquants completes par les defaults TRaSH 2026.

    Les tiers floor/ceiling sont normalises via ``normalize_tier_string``
    (Premium -> Platinum, etc.). Les entrees avec tier invalide sont
    droppees silencieusement (caller peut detecter via comparaison).

    >>> normalize_hierarchy_config(None)["enabled"]
    False
    >>> normalize_hierarchy_config({"enabled": True})["enabled"]
    True
    >>> normalize_hierarchy_config({"enabled": True})["order"]
    ['resolution', 'video_codec', 'hdr', 'audio', 'release_group']
    """
    out = default_hierarchy_config()
    if not isinstance(raw, dict):
        return out

    # enabled : strict bool (default False si non interpretable).
    raw_enabled = raw.get("enabled")
    if isinstance(raw_enabled, bool):
        out["enabled"] = raw_enabled
    elif isinstance(raw_enabled, (int, str)):
        # Tolerance "True"/"true"/1/"1" pour les profils YAML/CLI.
        s = str(raw_enabled).strip().lower()
        out["enabled"] = s in ("true", "1", "yes", "on")

    # order : liste de dimensions canoniques, filtre les inconnues.
    raw_order = raw.get("order")
    if isinstance(raw_order, list):
        filtered = [
            str(d).strip().lower()
            for d in raw_order
            if isinstance(d, str) and str(d).strip().lower() in DEFAULT_HIERARCHY_DIMENSIONS_ORDER
        ]
        # Si user a fourni une liste non vide ET valide, on l'utilise tel
        # quel (meme partielle). Sinon fallback default.
        if filtered:
            out["order"] = filtered

    # Floors/ceilings par dimension : merge avec defaults TRaSH 2026.
    for key in (
        "resolution_floors",
        "resolution_ceilings",
        "codec_floors",
        "hdr_floors",
        "audio_floors",
        "group_floors",
    ):
        raw_section = raw.get(key)
        if isinstance(raw_section, dict):
            # Merge : user > default. Normalise les noms de tier.
            # Les release groups (group_floors) sont insensibles a la casse :
            # 'FraMeSToR', 'framestor', 'FRAMESTOR' sont equivalents cote config,
            # coherent avec quality_score qui lowercase le release_group en input.
            for k, v in raw_section.items():
                canonical_tier = normalize_tier_string(v)
                if canonical_tier:
                    canonical_key = (
                        str(k).strip().lower()
                        if key == "group_floors"
                        else str(k)
                    )
                    out[key][canonical_key] = canonical_tier

    return out


def _floor_tier(current: str, floor: str) -> str:
    """Plancher le tier ``current`` a ``floor`` (jamais en dessous de floor).

    Coherent avec ``cap_tier`` mais en sens INVERSE : ``cap_tier`` plafonne
    vers le BAS (jamais au-dessus), ``_floor_tier`` plancher vers le HAUT
    (jamais en dessous). Utilise ``tier_order`` (index plus PETIT = tier
    plus HAUT).

    >>> _floor_tier("Bronze", "Gold")
    'Gold'
    >>> _floor_tier("Platinum", "Gold")
    'Platinum'
    >>> _floor_tier("Silver", "Silver")
    'Silver'
    """
    canonical_cur = normalize_tier_string(current) or str(current or "")
    canonical_floor = normalize_tier_string(floor) or str(floor or "")
    if (
        canonical_cur not in TIER_ORDER_BEST_FIRST
        or canonical_floor not in TIER_ORDER_BEST_FIRST
    ):
        return canonical_cur
    cur_idx = TIER_ORDER_BEST_FIRST.index(canonical_cur)
    floor_idx = TIER_ORDER_BEST_FIRST.index(canonical_floor)
    # Index plus PETIT = tier plus HAUT. On garde le plus PETIT.
    return TIER_ORDER_BEST_FIRST[min(cur_idx, floor_idx)]


def apply_tier_hierarchy(
    tier_pondere: str,
    dimensions: Dict[str, Any],
    hierarchy_config: Optional[Dict[str, Any]] = None,
) -> Tuple[str, List[Dict[str, str]]]:
    """Applique la hierarchie qualite multi-axes au tier calcule par le score.

    Args:
        tier_pondere: Tier calcule par le scoring V1 (apres ``_determine_tier``
            + custom_rules ``force_tier``). Ex: "Bronze", "Gold", "Premium"
            (legacy accepte via ``normalize_tier_string``).
        dimensions: Dict des dimensions techniques observees sur le fichier :
            - ``resolution_label`` (str) : "2160p" | "1080p" | "720p" | "SD"
            - ``resolution_source`` (str) : "probe" | "name_fallback" | "unknown"
            - ``video_codec`` (str) : "hevc" | "av1" | "avc" | ...
            - ``hdr`` (str) : "dolby_vision" | "hdr10_plus" | "hdr10" | ""
            - ``audio_codec`` (str) : "truehd_atmos" | "dts_hd_ma" | "dts" | ...
            - ``release_group`` (str) : nom du groupe (optionnel)
        hierarchy_config: Config user (default OFF si None).

    Returns:
        (tier_final, applied_decisions) ou applied_decisions est la liste des
        decisions qui ont modifie le tier (audit trail pour UI/logs).

        Si ``hierarchy_config["enabled"] == False`` : retourne
        ``(tier_pondere_normalized, [])`` - no-op strict.

    NOTE : cette fonction ne plafonne PAS par ``cap_tier`` securite
    (FAILED/CAM) - c'est la responsabilite du caller (quality_score).
    Apres cette fonction, le caller DOIT appeler ``cap_tier`` pour preserver
    AC-2 (memo VP-B : ``_cap_tier`` securite reste autorite finale).

    >>> # default OFF : no-op
    >>> apply_tier_hierarchy("Bronze", {"resolution_label": "2160p"}, None)
    ('Bronze', [])
    >>> # enabled mais resolution non probe : pas de floor (declaratif)
    >>> cfg = default_hierarchy_config()
    >>> cfg["enabled"] = True
    >>> apply_tier_hierarchy(
    ...     "Bronze",
    ...     {"resolution_label": "2160p", "resolution_source": "name_fallback"},
    ...     cfg,
    ... )
    ('Bronze', [])
    >>> # enabled + 2160p probe : floor Gold applique
    >>> tier, dec = apply_tier_hierarchy(
    ...     "Bronze",
    ...     {"resolution_label": "2160p", "resolution_source": "probe"},
    ...     cfg,
    ... )
    >>> tier
    'Gold'
    >>> dec[0]["dimension"]
    'resolution'
    """
    # Normalisation entree (tolerance legacy Premium/Bon/Moyen).
    tier_canonical = normalize_tier_string(tier_pondere) or str(tier_pondere or "")
    if tier_canonical not in TIER_ORDER_BEST_FIRST:
        # Tier inconnu : retour tel quel sans toucher (safe default).
        return tier_canonical, []

    cfg = normalize_hierarchy_config(hierarchy_config)
    if not cfg.get("enabled"):
        # AC-1 VP-B : default OFF = no-op strict.
        return tier_canonical, []

    if not isinstance(dimensions, dict):
        dimensions = {}

    applied: List[Dict[str, str]] = []
    current_tier = tier_canonical

    for dimension in cfg["order"]:
        # === Resolution ===
        if dimension == "resolution":
            res_label = str(dimensions.get("resolution_label") or "").strip()
            res_source = str(dimensions.get("resolution_source") or "").strip()
            # Floor : utilise cle "{label}_probe" si source=probe pour
            # distinguer probe verifie du fallback nom (declaratif).
            if res_label and res_source == "probe":
                key_probe = f"{res_label}_probe"
                floor = cfg["resolution_floors"].get(key_probe)
                if floor:
                    new_tier = _floor_tier(current_tier, floor)
                    if new_tier != current_tier:
                        applied.append({
                            "dimension": "resolution",
                            "type": "floor",
                            "value": key_probe,
                            "from": current_tier,
                            "to": new_tier,
                        })
                        current_tier = new_tier
            # Floor (declaratif, fallback nom accepte) : on autorise aussi
            # les floors sans suffixe _probe pour le cas user opt-in qui
            # ne veut PAS exiger le probe verifie.
            if res_label:
                floor = cfg["resolution_floors"].get(res_label)
                if floor:
                    new_tier = _floor_tier(current_tier, floor)
                    if new_tier != current_tier:
                        applied.append({
                            "dimension": "resolution",
                            "type": "floor",
                            "value": res_label,
                            "from": current_tier,
                            "to": new_tier,
                        })
                        current_tier = new_tier
            # Ceiling : plafonne vers le BAS (utilise cap_tier helper).
            if res_label:
                ceil = cfg["resolution_ceilings"].get(res_label)
                if ceil:
                    new_tier = cap_tier(current_tier, ceil)
                    if new_tier != current_tier:
                        applied.append({
                            "dimension": "resolution",
                            "type": "ceiling",
                            "value": res_label,
                            "from": current_tier,
                            "to": new_tier,
                        })
                        current_tier = new_tier

        # === Codec ===
        elif dimension == "video_codec":
            codec = str(dimensions.get("video_codec") or "").strip().lower()
            if codec:
                floor = cfg["codec_floors"].get(codec)
                if floor:
                    new_tier = _floor_tier(current_tier, floor)
                    if new_tier != current_tier:
                        applied.append({
                            "dimension": "video_codec",
                            "type": "floor",
                            "value": codec,
                            "from": current_tier,
                            "to": new_tier,
                        })
                        current_tier = new_tier

        # === HDR ===
        elif dimension == "hdr":
            hdr = str(dimensions.get("hdr") or "").strip().lower()
            if hdr:
                floor = cfg["hdr_floors"].get(hdr)
                if floor:
                    new_tier = _floor_tier(current_tier, floor)
                    if new_tier != current_tier:
                        applied.append({
                            "dimension": "hdr",
                            "type": "floor",
                            "value": hdr,
                            "from": current_tier,
                            "to": new_tier,
                        })
                        current_tier = new_tier

        # === Audio ===
        elif dimension == "audio":
            audio = str(dimensions.get("audio_codec") or "").strip().lower()
            if audio:
                floor = cfg["audio_floors"].get(audio)
                if floor:
                    new_tier = _floor_tier(current_tier, floor)
                    if new_tier != current_tier:
                        applied.append({
                            "dimension": "audio",
                            "type": "floor",
                            "value": audio,
                            "from": current_tier,
                            "to": new_tier,
                        })
                        current_tier = new_tier

        # === Release group ===
        elif dimension == "release_group":
            grp = str(dimensions.get("release_group") or "").strip().lower()
            if grp:
                floor = cfg["group_floors"].get(grp)
                if floor:
                    new_tier = _floor_tier(current_tier, floor)
                    if new_tier != current_tier:
                        applied.append({
                            "dimension": "release_group",
                            "type": "floor",
                            "value": grp,
                            "from": current_tier,
                            "to": new_tier,
                        })
                        current_tier = new_tier

    return current_tier, applied


# API publique reservee future Vague S : les helpers suivants restent definis
# (et restent importables explicitement par leur nom + utilises en interne /
# tests) mais sont retires de ``__all__`` car aucun caller prod ne les utilise
# encore en v7.7.0. Ils seront re-exposes quand la Vague S (UI premium badges,
# affichage seuils dynamiques, plafonnement custom_rules) les consommera :
#   - tier_label_fr   : libelle FR long ("Platine"/"Or"/...) - future UI badges
#   - is_premium_tier : decision rapide Platinum/Gold - future UI premium badge
#   - tier_min_score  : seuil dynamique d'un tier - future UI parametres
#   - cap_tier        : plafonnement explicite (utilise en INTERNE par
#                       apply_tier_hierarchy ligne 749, donc fonction conservee)
# Backward compat ABSOLUE : les fonctions restent inchangees, seul __all__
# (qui ne controle que ``from tiers_helpers import *``) est reduit. Les
# imports nommes existants (tests, futurs callers) continuent de fonctionner.
__all__ = [
    "TIER_ORDER_BEST_FIRST",
    "TIER_ORDER_WORST_FIRST",
    "TIER_V2_CANONICAL",
    "DEFAULT_TIER_THRESHOLDS",
    "DEFAULT_HIERARCHY_DIMENSIONS_ORDER",
    "DEFAULT_HIERARCHY_RESOLUTION_FLOORS",
    "DEFAULT_HIERARCHY_RESOLUTION_CEILINGS",
    "DEFAULT_HIERARCHY_CODEC_FLOORS",
    "DEFAULT_HIERARCHY_HDR_FLOORS",
    "DEFAULT_HIERARCHY_AUDIO_FLOORS",
    "DEFAULT_HIERARCHY_GROUP_FLOORS",
    "normalize_tier_string",
    "normalize_tiers",
    "tier_order",
    "tier_ordinal",
    # tier_label_fr : reservee future Vague S (UI badges FR)
    # is_premium_tier : reservee future Vague S (UI premium badge)
    # tier_min_score : reservee future Vague S (UI parametres)
    "determine_tier",
    # cap_tier : utilisee en INTERNE par apply_tier_hierarchy mais aucun
    # caller prod externe en v7.7.0 - reservee future Vague S
    "to_canonical_v2_tier",
    "reconcile_display_tier",
    "default_hierarchy_config",
    "normalize_hierarchy_config",
    "apply_tier_hierarchy",
]
