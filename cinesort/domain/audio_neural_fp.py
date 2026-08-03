"""Neural audio fingerprint — scaffold R&D V4.3.

Bounded context : signal audio neuronal complementaire a Chromaprint
(`domain/perceptual/audio_fingerprint.py`) pour la detection de
doublons / re-encodes ou Chromaprint faiblit.

Etat : **SCAFFOLD R&D, PAS d'integration prod**. Feature flag
`audio_neural` DESACTIVE par defaut. Aucune dependance ajoutee a
`pyproject.toml` (pas de torch, pas de panns-inference). L'inference
reelle sera plug-and-play via ONNX (`onnxruntime` deja present pour
LPIPS) une fois l'audit licence valide (cf
`docs/internal/notes/neural_audio_licences.md`).

Choix licence (resume) :
- panns-inference (MIT) -> retenu, export ONNX pour eviter torch.
- wav2vec2 (MIT) -> fallback general.
- neural-music-fp (AGPLv3) -> REJETE (incompatible distribution
  proprietaire).

Pattern architectural :
- Module pur `domain/` -> ne peut PAS importer `app`, `infra`, `ui`
  (contract `domain_pure` verrouille par import-linter).
- Pas de subprocess externe ici (le binaire `fpcalc.exe` reste dans
  `audio_fingerprint.py`). Le neural fp est une inference Python
  in-process via onnxruntime.
- Code robuste a l'absence du modele ONNX : log warning + feature
  desactivee, jamais d'erreur bloquante (pattern Chromaprint).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# --- Feature flag (V4.3 R&D, OFF par defaut) ---------------------------------
# Tant que ce flag reste False, aucune fonction de ce module ne doit etre
# appelee depuis app/infra/ui. La fusion ponderee dans `duplicate_*.py`
# doit court-circuiter ce signal si `AUDIO_NEURAL_ENABLED` est False.
AUDIO_NEURAL_ENABLED: bool = False


# --- Ponderation fusion (V4.3, calibrable) -----------------------------------
# Score doublon final = somme ponderee de 3 signaux independants :
#   - Chromaprint (audio classique, fpcalc.exe)             poids 0.30
#   - PANNs / wav2vec2 (audio neuronal, ce module)          poids 0.30
#   - Video perceptuel (composite_score, LPIPS, mel, ssim)  poids 0.40
# Total = 1.0. Ces poids sont des defaults R&D, ils seront recalibres
# sur biblio virtuelle (1000 films) avant tout passage en prod.
FUSION_WEIGHT_CHROMAPRINT: float = 0.30
FUSION_WEIGHT_NEURAL: float = 0.30
FUSION_WEIGHT_VIDEO: float = 0.40


@dataclass(frozen=True)
class NeuralFingerprint:
    """Embedding audio neuronal d'un fichier video.

    `embedding` est une liste de floats (dimension 2048 pour PANNs Cnn14,
    768 pour wav2vec2-base). On evite numpy ici pour rester dans `domain/`
    pur (numpy est de toute facon transitif via onnxruntime cote infra).

    `model_id` est l'identifiant du modele ayant produit l'embedding
    (ex. "panns_cnn14_v1" / "wav2vec2_base_960h_v1"). Sert a invalider
    les embeddings obsoletes lors d'un upgrade modele.
    """

    embedding: tuple[float, ...]
    model_id: str
    duration_s: float


def panns_inference_wrapper(
    audio_path: str,
    *,
    model_path: Optional[str] = None,
    segment_offset_s: float = 30.0,
    segment_duration_s: float = 60.0,
) -> Optional[NeuralFingerprint]:
    """Wrapper d'inference PANNs (Cnn14) via ONNX runtime — SCAFFOLD.

    Strategie ONNX :
        Le modele PANNs Cnn14 (PyTorch, MIT) est exporte offline cote dev
        en `.onnx` puis bundle dans `assets/models/panns_cnn14.onnx`. A
        runtime, on charge le `.onnx` via onnxruntime (deja dependance
        pour LPIPS) et on infere SANS dependance torch. Cela evite +1.2GB
        de bundle PyTorch.

    Args:
        audio_path: Chemin absolu vers le fichier video / audio. Le
            scaffold n'extrait pas encore le segment audio (ce sera fait
            via `ffmpeg_runner` du sous-package `perceptual/` une fois la
            feature activee).
        model_path: Chemin vers `panns_cnn14.onnx`. Si None, utilise la
            resolution standard `assets/models/` (sys._MEIPASS-aware,
            patron de `resolve_fpcalc_path`).
        segment_offset_s: Offset du segment a analyser (skip generique).
        segment_duration_s: Duree du segment (compromis precision/CPU).

    Returns:
        `NeuralFingerprint` si l'inference reussit, `None` si feature
        desactivee / modele absent / erreur (log warning, jamais raise).

    TODO V4.3 :
        - Implementer extraction segment via ffmpeg subprocess (16kHz mono).
        - Charger onnxruntime.InferenceSession (CPUExecutionProvider).
        - Run inference -> embedding 2048-d.
        - Tests unitaires avec fixture audio courte (5s sinus).
    """
    if not AUDIO_NEURAL_ENABLED:
        logger.debug(
            "audio_neural disabled (feature flag OFF), skipping panns inference for %s",
            audio_path,
        )
        return None

    # Scaffold : aucune inference reelle. Le squelette est volontairement
    # vide pour eviter qu'un appelant pense que la feature marche.
    logger.warning(
        "panns_inference_wrapper appele alors que le scaffold V4.3 n'est pas "
        "encore implemente (audio_path=%s, model_path=%s, segment=[%.1fs+%.1fs]). "
        "Retour None.",
        audio_path,
        model_path,
        segment_offset_s,
        segment_duration_s,
    )
    return None


def fusion_score(
    chromaprint_score: float,
    panns_score: float,
    video_score: float,
    *,
    weight_chromaprint: float = FUSION_WEIGHT_CHROMAPRINT,
    weight_neural: float = FUSION_WEIGHT_NEURAL,
    weight_video: float = FUSION_WEIGHT_VIDEO,
) -> float:
    """Fusion ponderee des 3 signaux de similarite pour la detection doublon.

    Chaque score est attendu dans `[0.0, 1.0]` (0 = totalement different,
    1 = identique). Les poids par defaut suivent la calibration R&D V4.3
    (0.3 + 0.3 + 0.4). Le video pese plus car il est le plus robuste aux
    re-encodes (LPIPS + mel + ssim_self_ref) et c'est le signal historique.

    Comportement :
        - Si `AUDIO_NEURAL_ENABLED` est False, le poids `weight_neural`
          est redistribue proportionnellement sur chromaprint + video,
          pour preserver une echelle [0,1] et eviter les regressions sur
          le scoring legacy. Backward compat ABSOLUE.
        - Si un score est NaN / hors [0,1], il est clampe a [0,1] avant
          calcul (log debug). Pas de raise.

    Args:
        chromaprint_score: Similarite Chromaprint (fpcalc) dans [0,1].
        panns_score: Similarite embeddings PANNs (cosine -> [0,1]).
        video_score: Composite perceptuel video dans [0,1].
        weight_*: Override des poids (calibration A/B).

    Returns:
        Score fusionne dans [0,1]. Seuil de decision doublon a calibrer
        cote `duplicate_multi_signal.py` (typiquement >= 0.85 confirmed,
        >= 0.70 probable).
    """
    # Clamp defensif (memoire utilisateur : code robuste).
    cp = max(0.0, min(1.0, chromaprint_score))
    pn = max(0.0, min(1.0, panns_score))
    vd = max(0.0, min(1.0, video_score))

    if not AUDIO_NEURAL_ENABLED:
        # Redistribuer le poids neural sur les 2 signaux actifs, en
        # preservant leur ratio relatif. Backward compat : sans neural,
        # le calcul retombe sur l'ancienne fusion chromaprint+video.
        total_active = weight_chromaprint + weight_video
        if total_active <= 0:
            logger.debug("fusion_score: poids actifs nuls (audio_neural OFF), retour 0.0")
            return 0.0
        w_cp = weight_chromaprint / total_active
        w_vd = weight_video / total_active
        return cp * w_cp + vd * w_vd

    total = weight_chromaprint + weight_neural + weight_video
    if total <= 0:
        logger.debug("fusion_score: somme des poids nulle, retour 0.0")
        return 0.0

    # Normalisation defensive si l'appelant ne respecte pas somme=1.0.
    w_cp = weight_chromaprint / total
    w_pn = weight_neural / total
    w_vd = weight_video / total
    return cp * w_cp + pn * w_pn + vd * w_vd


__all__ = [
    "AUDIO_NEURAL_ENABLED",
    "FUSION_WEIGHT_CHROMAPRINT",
    "FUSION_WEIGHT_NEURAL",
    "FUSION_WEIGHT_VIDEO",
    "NeuralFingerprint",
    "fusion_score",
    "panns_inference_wrapper",
]
