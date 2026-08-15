"""P2.1 : mode explain-score — transparence complète du scoring CinemaLux.

Le score final CineSort est calculé en deux étapes :
  1. Des `factors` (liste de deltas par catégorie) modifient 3 sous-scores :
     `video_sub`, `audio_sub`, `extras_sub` (chacun 0..100 après clamp).
  2. Un score pondéré final = (video_sub * w_video + audio_sub * w_audio
                               + extras_sub * w_extras) / total_weight.

Le module quality_score produit déjà des `factors` bruts, un `narrative` court
et les top_positive/top_negative. Ce module enrichit cette sortie avec :

- `weighted_delta` par factor (impact réel sur le score final, pas juste sur
  le sous-score) — c'est ce que l'utilisateur veut vraiment voir.
- `direction` ("+" / "-" / "=") pour simplifier l'UI.
- `categories` — breakdown agrégé par catégorie (subscore, weight, contribution
  au score final, counts positive/negative).
- `baseline` — seuils des tiers + distance_to_next_tier + next_tier.
- `narrative_rich` — 2-3 phrases FR complètes qui expliquent le score.
- `suggestions` — actions actionables pour améliorer le score (selon les pénalités).

Tout est stateless et déterministe — testable unitairement.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from cinesort.domain.tiers_helpers import normalize_tiers as _normalize_tiers

# --- Libellés catégories (utilisés dans narrative + UI) -----------------

_CATEGORY_LABELS_FR: Dict[str, str] = {
    "video": "Vidéo",
    "audio": "Audio",
    "extras": "Extras",
    "custom": "Règle personnalisée",
    "probe": "Sonde technique",
    "perceptual": "Analyse perceptuelle",
}


# --- Suggestions actionables liées à des pénalités connues --------------

# Chaque entrée : (match label substring, suggestion FR).
# Si un factor négatif correspond, la suggestion est proposée.
#
# ÉTAT MESURÉ (audit NUANCE N05, 2026-08-03) — 4 motifs ne matchent AUCUN
# libellé émis par `quality_score.py` (comptage sur les littéraux du module) :
#   - "bitrate bas"      : le scorer écrit "Debit trop faible pour {res} (…)"  (L919)
#   - "hdr 8bit"         : le scorer écrit "HDR detecte avec profondeur 8 bits" (L928)
#   - "langue manquante" : aucun libellé équivalent (le plus proche, "Pas de VO
#                          detectee" L1027, ne veut PAS dire la même chose)
#   - "récent" (accentué): le libellé est "Film recent ({year}) en definition
#                          standard" — mais il est capté juste après par
#                          "standard", donc AUCUNE suggestion n'est perdue.
# "commentary" est mort lui aussi, sans effet : "commentaire" est testé avant
# dans la même boucle qui `break` et émet exactement le même texte.
# Non corrigé DÉLIBÉRÉMENT : aucune UI ne lit `suggestions` (le front n'appelle
# même pas get_quality_report ; seules sortent la clé `score_explanation_full`
# de l'export JSON et un appel API scripté), et réaligner les motifs sur les
# libellés FR recréerait à l'identique le couplage fragile qui a pourri ici.
# Le vrai correctif est de clé sur une métadonnée de factor, pas sur une
# sous-chaîne de libellé — refonte à arbitrer, pas une rustine.
_SUGGESTION_RULES: List[tuple[str, str]] = [
    ("upscale", "Remplacer par une source native à la résolution annoncée (éviter les upscales)."),
    ("re-encode", "Chercher une version REMUX ou avec un bitrate plus élevé (≥ 15 Mbps en 1080p)."),
    ("4k light", "Pour du 4K authentique, viser au moins 35 Mbps (REMUX preferentiel)."),
    ("bitrate bas", "Bitrate insuffisant pour la résolution — upgrade recommandée."),
    ("hdr 8bit", "Le HDR requiert 10 bits. Chercher une source 10-bit correctement encodée."),
    ("commentaire", "Ajouter une piste audio principale (film avec seulement un commentaire)."),
    ("commentary", "Ajouter une piste audio principale (film avec seulement un commentaire)."),
    ("langue manquante", "Ajouter les pistes audio dans les langues attendues."),
    ("sous-titre", "Ajouter des sous-titres dans les langues attendues."),
    ("récent", "Pour un film récent, viser au moins du 1080p HEVC ou AV1."),
    ("standard", "Upgrader vers une meilleure résolution (1080p ou 4K)."),
]


def _classify_direction(delta: int) -> str:
    if delta > 0:
        return "+"
    if delta < 0:
        return "-"
    return "="


def _resolve_weight(weights: Dict[str, Any], key: str, default: int) -> int:
    """Résout UN poids de catégorie, indépendamment des deux autres (#656).

    Trois règles, dans cet ordre :

    - clef absente **ou** `None` → `default` (l'absence n'est pas une valeur) ;
    - clef présente et castable → sa valeur, **y compris `0`** : un poids nul
      est une valeur sentinelle légitime que ce module s'interdit de masquer
      (cf. audit 2026-05-21, `_compute_category_contribution` ci-dessous). Le
      raccourci `int(weights.get(k, d) or d)` est donc PROSCRIT : `0 or 60`
      vaut 60, il ressusciterait un poids délibérément mis à zéro ;
    - clef présente et non castable → `default`, sans toucher aux autres clefs.

    Le `try/except` groupé d'avant réinitialisait les TROIS poids dès qu'une
    seule clef valait `None` : `{"video": None, "audio": 300, "extras": 100}`
    retombait sur 60/30/10 — les poids audio/extras légitimes étaient jetés
    alors que seul `video` était à corriger.
    """
    raw = weights.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _compute_category_contribution(
    category: str,
    subscore: int,
    weights: Dict[str, Any],
) -> Dict[str, Any]:
    """Retourne {subscore, weight, weight_pct, contribution} pour une catégorie.

    `contribution` = subscore × weight / total_weight ; c'est ce que la
    catégorie apporte au score final.
    """
    # Défauts `0` ici (et non 60/30/10) : sans poids déclaré, cette fonction
    # doit rendre une contribution explicitement nulle plutôt qu'inventer une
    # répartition — cf. le bloc `sum_weights <= 0` ci-dessous.
    w_video = _resolve_weight(weights, "video", 0)
    w_audio = _resolve_weight(weights, "audio", 0)
    w_extras = _resolve_weight(weights, "extras", 0)

    weight_map = {"video": w_video, "audio": w_audio, "extras": w_extras}
    weight = weight_map.get(category, 0)

    sum_weights = w_video + w_audio + w_extras
    if sum_weights <= 0:
        # Config invalide : tous les poids sont 0/negatifs. On retourne des
        # contributions explicitement nulles plutot que de masquer l'erreur
        # avec un clamp `max(1, ...)` qui donnerait weight_pct=100% pour
        # weight=0. Cf audit Claude 2026-05-21 (categorie 2 - sentinel value
        # confusion).
        return {
            "subscore": int(subscore),
            "weight": int(weight),
            "weight_pct": 0.0,
            "contribution": 0.0,
        }

    return {
        "subscore": int(subscore),
        "weight": int(weight),
        "weight_pct": round(100.0 * weight / sum_weights, 1),
        "contribution": round(float(subscore) * weight / sum_weights, 1),
    }


def _weighted_delta_for_factor(
    factor: Dict[str, Any],
    weights: Dict[str, Any],
) -> float:
    """Calcule l'impact réel du delta sur le score final.

    video/audio/extras deltas sont pondérés par leur poids normalisé.
    Les catégories "custom", "probe", "perceptual" sont considérées comme
    s'appliquant directement au sous-score dominant (video) pour l'estimation —
    elles sont déjà injectées dans video_sub dans compute_quality_score.
    """
    delta = int(factor.get("delta") or 0)
    if delta == 0:
        return 0.0

    # #656 : résolution PAR CLEF. Défauts 60/30/10 (contrat propre à cette
    # fonction : un factor a toujours un impact pondéré, même sur un profil
    # sans poids déclarés), mais une clef `None`/invalide ne jette plus les
    # deux autres.
    w_video = _resolve_weight(weights, "video", 60)
    w_audio = _resolve_weight(weights, "audio", 30)
    w_extras = _resolve_weight(weights, "extras", 10)
    total = max(1, w_video + w_audio + w_extras)

    category = str(factor.get("category") or "video").lower()
    if category == "audio":
        w = w_audio
    elif category == "extras":
        w = w_extras
    else:
        # video / custom / probe / perceptual → appliqué sur video_sub
        w = w_video

    return round(delta * w / total, 2)


def _build_categories_breakdown(
    factors: List[Dict[str, Any]],
    subscores: Dict[str, int],
    weights: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Regroupe les factors par catégorie et calcule un breakdown complet."""
    breakdown: Dict[str, Dict[str, Any]] = {}
    for cat in ("video", "audio", "extras"):
        # custom/probe/perceptual sont injectés dans video_sub par compute_quality_score,
        # donc on les compte dans la catégorie video pour la cohérence d'affichage.
        if cat == "video":
            cat_factors = [
                f for f in factors if str(f.get("category") or "").lower() in ("video", "custom", "probe", "perceptual")
            ]
        else:
            cat_factors = [f for f in factors if str(f.get("category") or "").lower() == cat]
        positive = sum(1 for f in cat_factors if int(f.get("delta") or 0) > 0)
        negative = sum(1 for f in cat_factors if int(f.get("delta") or 0) < 0)
        sub_val = int(subscores.get(cat, 0) or 0)
        contrib = _compute_category_contribution(cat, sub_val, weights)
        breakdown[cat] = {
            **contrib,
            "label": _CATEGORY_LABELS_FR.get(cat, cat),
            "factors_count": len(cat_factors),
            "positive_count": positive,
            "negative_count": negative,
        }
    return breakdown


def _compute_baseline(
    score: int,
    tier: str,
    tiers: Dict[str, Any],
) -> Dict[str, Any]:
    """Distance au tier supérieur + résumé des seuils."""
    # SCORE-01 (Vague M, M-06) : utiliser tiers_helpers.normalize_tiers pour
    # aligner les defaults sur la calibration biblio reelle v1.5.7 (70/66/55/40).
    # Avant : defaults 85/68/54/30 (legacy pre-v1.5.5) qui divergeaient de
    # quality_score.default_quality_profile() -> distance_to_next_tier faux pour
    # les profils sans seuils explicites.
    normalized = _normalize_tiers(tiers)
    plat = normalized["platinum"]
    gold = normalized["gold"]
    silver = normalized["silver"]
    bronze = normalized["bronze"]

    thresholds = {
        "Platinum": plat,
        "Gold": gold,
        "Silver": silver,
        "Bronze": bronze,
    }
    order = [("Reject", 0), ("Bronze", bronze), ("Silver", silver), ("Gold", gold), ("Platinum", plat)]

    next_tier: Optional[str] = None
    distance: Optional[int] = None
    # BUG-EXPLAIN-BASELINE-CAP (Lot D 2026-07) : raisonner depuis le tier
    # AFFICHE (deja plafonne/ajuste par quality_score : cap probe FAILED ->
    # Silver, cap CAM -> Bronze, hierarchy VP-B) et non depuis le score seul.
    # Sinon un film cape Silver avec score >= seuil Platinum repondait
    # next_tier=null ("aucun tier superieur") en contradiction avec le tier
    # montre a l'utilisateur. distance peut valoir 0 dans ce cas : le blocage
    # n'est pas une question de points (garde securite), cf _generate_suggestions.
    tier_index = {name.lower(): i for i, (name, _) in enumerate(order)}
    displayed_idx = tier_index.get(str(tier or "").strip().lower())
    if displayed_idx is not None:
        if displayed_idx + 1 < len(order):
            next_name, next_threshold = order[displayed_idx + 1]
            next_tier = next_name
            distance = max(0, next_threshold - score)
    else:
        # Tier non canonique/inconnu : fallback historique base sur le score.
        for name, threshold in order:
            if threshold > score:
                next_tier = name
                distance = max(0, threshold - score)
                break

    return {
        "tier_thresholds": thresholds,
        "next_tier": next_tier,
        "distance_to_next_tier": distance,
    }


def _generate_suggestions(
    negative_factors: List[Dict[str, Any]],
    tier: str,
    baseline: Dict[str, Any],
) -> List[str]:
    """Suggestions actionables basées sur les pénalités détectées."""
    suggestions: List[str] = []
    seen: set[str] = set()

    for f in negative_factors:
        label = str(f.get("label") or "").lower()
        for pattern, text in _SUGGESTION_RULES:
            if pattern in label and text not in seen:
                suggestions.append(text)
                seen.add(text)
                break

    # Si pas de suggestion spécifique mais distance faible au tier supérieur → suggestion générique.
    # BUG-EXPLAIN-BASELINE-CAP : distance == 0 signifie tier plafonné par une
    # garde sécurité (score déjà au-dessus du seuil) — une amélioration de
    # points n'y changerait rien, donc pas de suggestion générique trompeuse.
    distance = baseline.get("distance_to_next_tier")
    next_tier = baseline.get("next_tier")
    if not suggestions and distance is not None and 1 <= distance <= 5 and next_tier:
        suggestions.append(
            f"Score à {distance} point(s) du tier {next_tier} — une légère amélioration audio ou vidéo suffirait."
        )

    return suggestions


def _generate_rich_narrative(
    score: int,
    tier: str,
    top_positive: List[Dict[str, Any]],
    top_negative: List[Dict[str, Any]],
    categories: Dict[str, Dict[str, Any]],
    baseline: Dict[str, Any],
) -> str:
    """Génère 1-3 phrases FR qui expliquent clairement le score."""
    parts: List[str] = []

    # Phrase 1 : verdict global
    parts.append(f"Score {score}/100 ({tier}).")

    # Phrase 2 : meilleure + pire catégorie
    cat_items = [(k, v) for k, v in categories.items() if v.get("weight", 0) > 0]
    if cat_items:
        best_cat = max(cat_items, key=lambda x: x[1]["subscore"])
        worst_cat = min(cat_items, key=lambda x: x[1]["subscore"])
        if best_cat[0] != worst_cat[0]:
            parts.append(
                f"La {best_cat[1]['label'].lower()} est le point fort ({best_cat[1]['subscore']}/100), "
                f"la {worst_cat[1]['label'].lower()} le point à surveiller ({worst_cat[1]['subscore']}/100)."
            )
        else:
            parts.append(f"Profil technique homogène autour de la {best_cat[1]['label'].lower()}.")

    # Phrase 3 : principaux facteurs
    if top_positive and top_negative:
        pos_labels = ", ".join(str(f.get("label")) for f in top_positive[:2])
        neg_labels = ", ".join(str(f.get("label")) for f in top_negative[:2])
        parts.append(f"Atouts : {pos_labels}. Freins : {neg_labels}.")
    elif top_positive:
        pos_labels = ", ".join(str(f.get("label")) for f in top_positive[:3])
        parts.append(f"Points forts : {pos_labels}. Aucun frein majeur.")
    elif top_negative:
        neg_labels = ", ".join(str(f.get("label")) for f in top_negative[:3])
        parts.append(f"Freins principaux : {neg_labels}.")

    # Phrase 4 : distance au tier supérieur si pertinent
    distance = baseline.get("distance_to_next_tier")
    next_tier = baseline.get("next_tier")
    if distance is not None and distance > 0 and distance <= 10 and next_tier:
        parts.append(f"À {distance} point(s) du tier {next_tier}.")

    return " ".join(parts)


def build_rich_explanation(
    *,
    score: int,
    tier: str,
    factors: List[Dict[str, Any]],
    subscores: Dict[str, int],
    weights: Dict[str, Any],
    tier_thresholds: Dict[str, Any],
) -> Dict[str, Any]:
    """Fonction principale — enrichit l'explanation brute avec pondération + narrative.

    Args:
        score : score final 0..100.
        tier : tier calculé (Platinum/Gold/Silver/Bronze/Reject).
        factors : liste des deltas catégorisés (existant dans quality_score).
        subscores : {"video": int, "audio": int, "extras": int}.
        weights : {"video": int, "audio": int, "extras": int} du profil.
        tier_thresholds : {"platinum": 70, "gold": 66, ...} du profil.
            L'exemple porte la grille CANONIQUE (`DEFAULT_TIER_THRESHOLDS`).
            Il donnait 85/68/54/30 — la grille pre-v1.5.5, celle-la meme dont
            le commentaire de `normalize_tiers` ci-dessus dit qu'elle a rendu
            `distance_to_next_tier` faux. Un exemple de docstring se recopie.

    Returns:
        Dict avec narrative, top_positive, top_negative, factors (enrichis),
        categories, baseline, suggestions.
    """
    # Enrichir chaque factor avec weighted_delta + direction
    enriched: List[Dict[str, Any]] = []
    for f in factors:
        delta = int(f.get("delta") or 0)
        enriched.append(
            {
                **f,
                "weighted_delta": _weighted_delta_for_factor(f, weights),
                "direction": _classify_direction(delta),
            }
        )

    # top_positive / top_negative (sur weighted_delta, plus juste que delta brut)
    positive = sorted(
        [f for f in enriched if f["weighted_delta"] > 0],
        key=lambda x: x["weighted_delta"],
        reverse=True,
    )[:5]
    negative = sorted(
        [f for f in enriched if f["weighted_delta"] < 0],
        key=lambda x: x["weighted_delta"],
    )[:5]

    categories = _build_categories_breakdown(enriched, subscores, weights)
    baseline = _compute_baseline(score, tier, tier_thresholds)
    suggestions = _generate_suggestions(negative, tier, baseline)
    narrative = _generate_rich_narrative(score, tier, positive, negative, categories, baseline)

    return {
        "narrative": narrative,
        "top_positive": positive[:3],  # conserver top 3 pour backward compat
        "top_negative": negative[:3],
        "factors": enriched,
        "categories": categories,
        "baseline": baseline,
        "suggestions": suggestions,
    }


__all__ = ["build_rich_explanation"]
