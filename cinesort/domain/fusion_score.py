"""Fusion score doublons V2.4 — Chromaprint + videohash.

Bounded context : combinaison ponderee des deux signaux independants
de detection de doublons :
  - Chromaprint (audio classique fpcalc.exe, similarite [0, 1])
  - videohash perceptual (8x8 dHash, distance [0, 1] -> similarite = 1 - distance)

Pattern architectural :
- Module pur `domain/` (pas d'import infra/app/ui).
- Backward compat ABSOLUE : aucun appelant existant n'est touche, ce
  module est invoque **uniquement** derriere le feature flag
  `CINESORT_FUSION_DOUBLONS` (off par defaut) via
  `cinesort/app/duplicate_pipeline.py`.
- Weights par defaut : 0.4 audio + 0.6 video (le signal video est plus
  robuste aux re-encodes audio AC3->AAC, voix doublees, etc.).
- Weights configurables (somme libre, normalisation interne) pour
  permettre une calibration UI plus tard sans changer ce module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# --- Ponderations par defaut (V2.4 baseline) ---------------------------------
# Choix : video > audio car les re-encodes audio (DTS->AC3->AAC, doublages,
# pistes commentaires) sont frequents et faussent Chromaprint, alors que
# meme un re-encode video preserve la structure pHash (les frames cles
# restent visuellement equivalentes a +/- 5% pres en dHash).
DEFAULT_AUDIO_WEIGHT = 0.4
DEFAULT_VIDEO_WEIGHT = 0.6

# Seuils verdict humain-lisible (apres fusion).
# Aligne sur classify_fingerprint_similarity de Chromaprint pour coherence UX.
FUSION_CONFIRMED_THRESHOLD = 0.90
FUSION_PROBABLE_THRESHOLD = 0.75
FUSION_POSSIBLE_THRESHOLD = 0.50


@dataclass(frozen=True)
class FusionResult:
    """Resultat de la fusion ponderee.

    Attributes:
        score : score fusionne dans [0.0, 1.0]. 1.0 = identique fort.
        audio_score : signal Chromaprint utilise (echo, peut etre None).
        video_score : signal videohash utilise (echo, peut etre None).
        audio_weight : poids effectif applique au signal audio.
        video_weight : poids effectif applique au signal video.
        verdict : classification humain-lisible.
    """

    score: float
    audio_score: Optional[float]
    video_score: Optional[float]
    audio_weight: float
    video_weight: float
    verdict: str


def compute_fusion(
    chromaprint_score: Optional[float],
    videohash_score: Optional[float],
    *,
    audio_weight: float = DEFAULT_AUDIO_WEIGHT,
    video_weight: float = DEFAULT_VIDEO_WEIGHT,
) -> Optional[FusionResult]:
    """Calcule le score fusionne pondere des deux signaux.

    Args:
        chromaprint_score : similarite Chromaprint [0, 1] ou None si indisponible.
        videohash_score : similarite videohash [0, 1] (= 1 - distance) ou None.
        audio_weight : ponderation audio. Default DEFAULT_AUDIO_WEIGHT (0.4).
        video_weight : ponderation video. Default DEFAULT_VIDEO_WEIGHT (0.6).

    Returns:
        FusionResult si au moins un signal est disponible, None si les deux
        sont None. Les poids sont normalises pour sommer a 1.0 en interne,
        meme si l'appelant fournit des poids arbitraires. Si un signal est
        manquant, son poids est redistribue sur l'autre.

    Backward compat : ne **JAMAIS** appeler cette fonction depuis le
    pipeline doublons legacy. Reserve aux nouveaux pipelines passant par
    le feature flag CINESORT_FUSION_DOUBLONS.
    """
    if chromaprint_score is None and videohash_score is None:
        return None

    # Clamp les signaux dans [0, 1] par defense en profondeur.
    a_score = _clamp_unit(chromaprint_score) if chromaprint_score is not None else None
    v_score = _clamp_unit(videohash_score) if videohash_score is not None else None

    # Normalise les poids (peu importe la somme passee en entree).
    a_w = max(0.0, float(audio_weight))
    v_w = max(0.0, float(video_weight))
    total_w = a_w + v_w
    if total_w <= 0.0:
        # Garde-fou : poids invalides -> on retombe sur les defaults.
        a_w = DEFAULT_AUDIO_WEIGHT
        v_w = DEFAULT_VIDEO_WEIGHT
        total_w = a_w + v_w

    a_w_norm = a_w / total_w
    v_w_norm = v_w / total_w

    # Cas signal manquant : redistribue le poids sur l'autre.
    if a_score is None and v_score is not None:
        eff_a_w = 0.0
        eff_v_w = 1.0
        score = v_score
    elif v_score is None and a_score is not None:
        eff_a_w = 1.0
        eff_v_w = 0.0
        score = a_score
    else:
        # Les deux signaux sont presents.
        assert a_score is not None and v_score is not None
        eff_a_w = a_w_norm
        eff_v_w = v_w_norm
        score = (a_score * eff_a_w) + (v_score * eff_v_w)

    score = _clamp_unit(score)

    return FusionResult(
        score=float(score),
        audio_score=a_score,
        video_score=v_score,
        audio_weight=float(eff_a_w),
        video_weight=float(eff_v_w),
        verdict=classify_fusion_score(score),
    )


def classify_fusion_score(score: Optional[float]) -> str:
    """Classifie un score fusionne en verdict humain-lisible.

    Returns:
        "confirmed" (>=0.90) | "probable" (>=0.75) | "possible" (>=0.50) |
        "different" (<0.50) | "unknown" (None).
    """
    if score is None:
        return "unknown"
    if score >= FUSION_CONFIRMED_THRESHOLD:
        return "confirmed"
    if score >= FUSION_PROBABLE_THRESHOLD:
        return "probable"
    if score >= FUSION_POSSIBLE_THRESHOLD:
        return "possible"
    return "different"


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------


def _clamp_unit(x: float) -> float:
    """Clamp dans [0.0, 1.0] (defense en profondeur contre signaux hors plage)."""
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return float(x)
