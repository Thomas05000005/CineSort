"""Seuils de confiance partages backend + frontend (VN-C.1 batch 2).

Avant VN-C.1, les seuils etaient eparpilles avec des valeurs INCOHERENTES :
    - cinesort/domain/quality_score.py        : 75 / 50
    - cinesort/domain/core.py compute_confidence : 80 / 60
    - web/dashboard/views/traitement.js       : 85 / 60
    - web/dashboard/views/library/lib-validation.js : 85 / 60
    - bulk-approve traitement.js              : 90 (hardcode "sure")

Resultat : un label "high" cote backend (>= 75) pouvait s'afficher
"Moyenne" cote UI (< 85). Confusion utilisateur.

Strategie : 1 source unique pour la grille HIGH/MED/LOW. Les seuils
sont alignes sur les valeurs frontend (les plus visibles utilisateur) :
    CONF_HIGH   = 85
    CONF_MEDIUM = 60
    CONF_LOW    = 0  (implicite, anything < CONF_MEDIUM)

NB : le slider Library 70-100 reste un filtre user independant
(seuil d'auto-approbation choisi par l'utilisateur), distinct des
seuils semantiques HIGH/MED/LOW.

Le seuil "sure" du bulk-approve (90 actuellement) reste lui aussi
un parametre UI distinct, plus restrictif que CONF_HIGH = 85.
"""

from __future__ import annotations

from typing import Dict


# Score >= CONF_HIGH      -> label "high"  (UI: Haute / Elevee)
CONF_HIGH: int = 85
# CONF_MEDIUM <= score < CONF_HIGH -> label "med" (UI: Moyenne)
CONF_MEDIUM: int = 60
# score < CONF_MEDIUM     -> label "low"  (UI: Basse / Faible)
CONF_LOW: int = 0


def confidence_label(score: int) -> str:
    """Retourne le label canonique 'high'/'med'/'low' pour un score 0..100.

    Le label est utilise dans le PlanRow (cinesort/domain/core.py) et
    expose en sortie API. Le frontend mappe vers son propre vocabulaire
    UI (Haute / Moyenne / Basse) en consommant le meme score brut.
    """
    try:
        value = int(score or 0)
    except (TypeError, ValueError):
        value = 0
    if value >= CONF_HIGH:
        return "high"
    if value >= CONF_MEDIUM:
        return "med"
    return "low"


def confidence_label_fr(score: int) -> str:
    """Variante FR (Elevee/Moyenne/Faible) — utilisee dans quality_score."""
    try:
        value = int(score or 0)
    except (TypeError, ValueError):
        value = 0
    if value >= CONF_HIGH:
        return "Elevee"
    if value >= CONF_MEDIUM:
        return "Moyenne"
    return "Faible"


def get_confidence_thresholds() -> Dict[str, int]:
    """Dict expose via la facade settings + endpoint REST.

    Le frontend (web/dashboard/core/api.js -> fetchConfidenceThresholds)
    appelle settings.get_confidence_thresholds() puis utilise high/medium
    pour piloter ses badges et filtres.
    """
    return {
        "high": CONF_HIGH,
        "medium": CONF_MEDIUM,
        "low": CONF_LOW,
    }
