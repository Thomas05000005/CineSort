"""P4.1 : calibration perceptuelle basée sur feedback utilisateur.

Principe : l'utilisateur peut indiquer pour un film son "tier attendu"
(Platinum/Gold/Silver/Bronze/Reject) ET éventuellement pointer une catégorie
(video/audio/extras) qu'il juge mal évaluée.

Ce module agrège les feedbacks accumulés et détecte :
- Biais systémique : score calculé en moyenne trop haut ou trop bas ?
- Biais par catégorie : quelle catégorie sous-pondérée ou sur-pondérée ?
- Suggestion : ajustement de poids recommandé (tous signes gardés,
  bornés sur [1, 90] par catégorie).

Tout est pur — pas d'I/O, testable unitairement.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


# Ordre des tiers (du plus bas au plus haut), pour calculer les deltas ordinaux.
_TIER_ORDER = ["Reject", "Bronze", "Silver", "Gold", "Platinum"]


def tier_ordinal(tier: str) -> int:
    """Retourne le rang du tier (0 = Reject, 4 = Platinum). -1 si inconnu."""
    t = str(tier or "").strip().title()
    # Accepter les alias legacy
    legacy = {"Premium": "Platinum", "Bon": "Gold", "Moyen": "Silver", "Mauvais": "Reject", "Faible": "Bronze"}
    t = legacy.get(t, t)
    try:
        return _TIER_ORDER.index(t)
    except ValueError:
        return -1


def compute_tier_delta(computed_tier: str, user_tier: str) -> int:
    """Retourne la différence ordinale user_tier - computed_tier.

    +1 = user pense Gold pour Silver calculé (score sous-évalué).
    -1 = user pense Silver pour Gold calculé (score sur-évalué).
    0 = accord.
    """
    o_user = tier_ordinal(user_tier)
    o_comp = tier_ordinal(computed_tier)
    if o_user < 0 or o_comp < 0:
        return 0
    return o_user - o_comp


def analyze_feedback_bias(feedbacks: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Agrège une liste de feedbacks pour détecter le biais global.

    Chaque feedback : {computed_tier, user_tier, tier_delta, category_focus, ...}.

    Retourne :
        {
          "total_feedbacks": int,
          "accord_pct": float,     # % de feedbacks à delta 0
          "mean_delta": float,     # moyenne des deltas (négatif = système sur-évalue)
          "bias_direction": "underscore"|"overscore"|"neutral",
          "bias_strength": "strong"|"moderate"|"weak"|"none",
          "category_bias": {"video": N, "audio": N, "extras": N}  # nb feedbacks par catégorie pointée
        }
    """
    fbs = list(feedbacks)
    total = len(fbs)
    if total == 0:
        return {
            "total_feedbacks": 0,
            "accord_pct": 0.0,
            "mean_delta": 0.0,
            "bias_direction": "neutral",
            "bias_strength": "none",
            "category_bias": {"video": 0, "audio": 0, "extras": 0},
        }

    deltas = [int(fb.get("tier_delta") or 0) for fb in fbs]
    accord = sum(1 for d in deltas if d == 0)
    mean_delta = sum(deltas) / total

    # Direction : si mean positive, utilisateurs voient souvent leurs films MEILLEURS que le calcul
    # → système sous-évalue (underscore). Si mean négative → sur-évalue (overscore).
    if abs(mean_delta) < 0.15:
        direction = "neutral"
    elif mean_delta > 0:
        direction = "underscore"
    else:
        direction = "overscore"

    abs_mean = abs(mean_delta)
    if abs_mean >= 1.0:
        strength = "strong"
    elif abs_mean >= 0.5:
        strength = "moderate"
    elif abs_mean >= 0.15:
        strength = "weak"
    else:
        strength = "none"

    cat_bias = {"video": 0, "audio": 0, "extras": 0}
    for fb in fbs:
        cat = str(fb.get("category_focus") or "").lower()
        if cat in cat_bias:
            cat_bias[cat] += 1

    return {
        "total_feedbacks": total,
        "accord_pct": round(100.0 * accord / total, 1),
        "mean_delta": round(mean_delta, 2),
        "bias_direction": direction,
        "bias_strength": strength,
        "category_bias": cat_bias,
    }


def suggest_weight_adjustment(
    bias_report: Dict[str, Any],
    current_weights: Dict[str, int],
) -> Optional[Dict[str, Any]]:
    """Propose un ajustement de poids basé sur le biais.

    Logique simple :
      - Si bias neutre ou weak → pas de suggestion.
      - Sinon, identifier la catégorie la plus mentionnée dans category_bias.
      - Si bias_direction == "underscore" (utilisateur voit plus haut que calculé)
        → augmenter le poids de la catégorie pointée de 5 points (clamp 1-90).
      - Si "overscore" → diminuer de 5 points (clamp 1-90).
      - Rééquilibrer pour que la somme reste constante (réduire proportionnellement
        les autres poids).

    Retourne None si aucune suggestion applicable, sinon dict avec
    `{from: weights, to: weights, rationale: str}`.
    """
    strength = bias_report.get("bias_strength")
    direction = bias_report.get("bias_direction")
    if strength in ("weak", "none") or direction == "neutral":
        return None

    cat_bias = bias_report.get("category_bias") or {}
    # Catégorie la plus pointée
    if not cat_bias:
        return None
    focus = max(cat_bias.items(), key=lambda kv: kv[1])
    focus_cat, focus_count = focus
    if focus_count == 0:
        return None

    try:
        w_video = int(current_weights.get("video", 60) or 60)
        w_audio = int(current_weights.get("audio", 30) or 30)
        w_extras = int(current_weights.get("extras", 10) or 10)
    except (TypeError, ValueError):
        return None

    weights = {"video": w_video, "audio": w_audio, "extras": w_extras}
    total_before = sum(weights.values())

    delta = 5 if direction == "underscore" else -5
    new_focus = max(1, min(90, weights[focus_cat] + delta))
    actual_delta = new_focus - weights[focus_cat]
    if actual_delta == 0:
        return None

    # Rééquilibrer : on ajoute/retire actual_delta sur les autres catégories au prorata
    others = [c for c in weights if c != focus_cat]
    others_total = sum(weights[c] for c in others)
    new_weights: Dict[str, int] = {focus_cat: new_focus}
    remaining = -actual_delta
    if others_total > 0:
        for c in others:
            share = int(round(remaining * weights[c] / others_total))
            new_weights[c] = max(1, min(90, weights[c] + share))
    else:
        for c in others:
            new_weights[c] = weights[c]

    # Normaliser : repartir le diff sur les autres categories en respectant
    # les bornes [1, 90]. La distribution proportionnelle peut introduire un
    # delta a cause de l'arrondi entier (banker's rounding) et des clamps.
    # Si toutes les autres sont au clamp et le diff persiste, l'invariant
    # somme=total_before ne peut etre maintenu : on retourne None.
    diff = total_before - sum(new_weights.values())
    if diff != 0:
        for cat in others:
            if diff == 0:
                break
            old = new_weights[cat]
            adjusted = max(1, min(90, old + diff))
            diff -= adjusted - old
            new_weights[cat] = adjusted
        if diff != 0:
            return None

    direction_label = "augmenté" if actual_delta > 0 else "diminué"
    rationale = (
        f"Biais {strength} détecté ({direction}) avec {bias_report.get('total_feedbacks')} "
        f"feedback(s). La catégorie '{focus_cat}' est pointée {focus_count} fois. "
        f"Poids '{focus_cat}' {direction_label} de {abs(actual_delta)} ({weights[focus_cat]} → {new_focus})."
    )
    return {
        "from": weights,
        "to": new_weights,
        "rationale": rationale,
        "focus_category": focus_cat,
    }


__all__ = [
    "tier_ordinal",
    "compute_tier_delta",
    "analyze_feedback_bias",
    "suggest_weight_adjustment",
]
