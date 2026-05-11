"""§11 v7.5.0 — Distance perceptuelle LPIPS (AlexNet ONNX).

Compare 2 fichiers via un modele LPIPS (Learned Perceptual Image Patch
Similarity) pre-entraine sur AlexNet, expose en ONNX. Produit une distance
par paire de frames alignees ; la mediane donne le verdict global.

Robuste a l'absence d'onnxruntime ou du modele ONNX (feature simplement
desactivee, pas de plantage).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional

import numpy as np

from .constants import (
    LPIPS_DISTANCE_DIFFERENT,
    LPIPS_DISTANCE_IDENTICAL,
    LPIPS_DISTANCE_SIMILAR,
    LPIPS_DISTANCE_VERY_SIMILAR,
    LPIPS_INPUT_SIZE,
    LPIPS_MODEL_PATH,
    LPIPS_N_FRAMES_PAIRS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy loading ONNX Runtime (evite ImportError au module load si absent)
# ---------------------------------------------------------------------------
_ort_available: Optional[bool] = None
_ort_session = None
# Garde-fous : log WARNING UNE SEULE FOIS pour eviter de spammer les logs
# lors d'un batch d'analyses successives sur une installation sans le modele.
_missing_model_warned: bool = False
_missing_ort_warned: bool = False

# Message d'aide affiche quand le modele LPIPS est absent. Cible : utilisateur
# qui a une installation incomplete (.exe corrompu, build amputee, modele
# supprime manuellement). On indique l'action concrete a faire.
_LPIPS_REINSTALL_HINT = (
    "Modele LPIPS introuvable (%s). L'analyse perceptuelle continue sans la "
    "metrique LPIPS. Pour la restaurer : reinstaller CineSort (le modele "
    "lpips_alexnet.onnx ~9.4 MB est embarque dans le bundle officiel)."
)


def _is_ort_available() -> bool:
    global _ort_available, _missing_ort_warned
    if _ort_available is None:
        try:
            import onnxruntime  # noqa: F401  # check availability only

            _ort_available = True
        except ImportError:
            _ort_available = False
            if not _missing_ort_warned:
                logger.warning(
                    "onnxruntime non installe -> LPIPS desactive (reinstaller CineSort pour le restaurer)"
                )
                _missing_ort_warned = True
    return _ort_available


def _resolve_model_path(model_path: str = LPIPS_MODEL_PATH) -> Optional[Path]:
    """Resolve LPIPS ONNX model (bundle ou source), None si absent."""
    candidates = [Path(model_path)]
    import sys

    if getattr(sys, "frozen", False):
        candidates.insert(0, Path(sys._MEIPASS) / model_path)  # type: ignore[attr-defined]
    for p in candidates:
        if p.exists() and p.is_file():
            return p.resolve()
    return None


def _warn_model_missing_once(model_path: str) -> None:
    """Emet un WARNING unique au premier check si le modele LPIPS est absent.

    Idempotent : les appels suivants sont silencieux (jusqu'a un
    `reset_session_cache()`). Permet de signaler le probleme dans les logs
    sans saturer la sortie pendant un batch d'analyses.
    """
    global _missing_model_warned
    if not _missing_model_warned:
        logger.warning(_LPIPS_REINSTALL_HINT, model_path)
        _missing_model_warned = True


def _get_session(model_path: str = LPIPS_MODEL_PATH):
    """Charge paresseusement la session ONNX (1x par process)."""
    global _ort_session
    if _ort_session is not None:
        return _ort_session
    if not _is_ort_available():
        raise RuntimeError("onnxruntime indisponible")
    resolved = _resolve_model_path(model_path)
    if resolved is None:
        # WARNING avec instructions de reinstall (une seule fois par process)
        _warn_model_missing_once(model_path)
        raise FileNotFoundError(f"Modele LPIPS absent : {model_path}")
    import onnxruntime as ort

    _ort_session = ort.InferenceSession(
        str(resolved),
        providers=["CPUExecutionProvider"],
    )
    logger.info("LPIPS ONNX charge (%s)", resolved.name)
    return _ort_session


def reset_session_cache() -> None:
    """Reset le cache de session (utile pour les tests)."""
    global _ort_session, _ort_available, _missing_model_warned, _missing_ort_warned
    _ort_session = None
    _ort_available = None
    _missing_model_warned = False
    _missing_ort_warned = False


# ---------------------------------------------------------------------------
# Resultat
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LpipsResult:
    distance_median: Optional[float]
    distances_per_pair: List[float]
    verdict: str  # identical | very_similar | similar | different | very_different | insufficient_data
    n_pairs_evaluated: int


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_lpips_verdict(distance: Optional[float]) -> str:
    if distance is None:
        return "insufficient_data"
    d = float(distance)
    if d < LPIPS_DISTANCE_IDENTICAL:
        return "identical"
    if d < LPIPS_DISTANCE_VERY_SIMILAR:
        return "very_similar"
    if d < LPIPS_DISTANCE_SIMILAR:
        return "similar"
    if d < LPIPS_DISTANCE_DIFFERENT:
        return "different"
    return "very_different"


# ---------------------------------------------------------------------------
# Pre-traitement
# ---------------------------------------------------------------------------


def _resize_bilinear(img: np.ndarray, target_size: int) -> np.ndarray:
    """Resize 2D array a (target_size, target_size) via interpolation bilineaire."""
    h, w = img.shape
    if h == target_size and w == target_size:
        return img.astype(np.float32)
    y_src = np.linspace(0.0, h - 1, target_size, dtype=np.float32)
    x_src = np.linspace(0.0, w - 1, target_size, dtype=np.float32)
    y0 = np.floor(y_src).astype(np.int64)
    x0 = np.floor(x_src).astype(np.int64)
    y1 = np.minimum(y0 + 1, h - 1)
    x1 = np.minimum(x0 + 1, w - 1)
    wy = (y_src - y0).astype(np.float32)
    wx = (x_src - x0).astype(np.float32)
    img_f = img.astype(np.float32)
    p00 = img_f[np.ix_(y0, x0)]
    p01 = img_f[np.ix_(y0, x1)]
    p10 = img_f[np.ix_(y1, x0)]
    p11 = img_f[np.ix_(y1, x1)]
    top = p00 * (1.0 - wx) + p01 * wx
    bot = p10 * (1.0 - wx) + p11 * wx
    return top * (1.0 - wy[:, None]) + bot * wy[:, None]


def preprocess_frame_for_lpips(
    pixels_y: List[int],
    width: int,
    height: int,
    target_size: int = LPIPS_INPUT_SIZE,
) -> Optional[np.ndarray]:
    """Prepare une frame grayscale pour l'inference LPIPS.

    Etapes :
        1. Reshape pixels_y (luminance Y 8-bit) en (height, width).
        2. Resize bilineaire vers (target_size, target_size).
        3. Convertir Y -> RGB (3 canaux identiques).
        4. Normaliser [0, 255] -> [-1, 1].
        5. (1, 3, target_size, target_size) float32.
    """
    if not pixels_y or width <= 0 or height <= 0:
        return None
    expected = int(width) * int(height)
    if len(pixels_y) != expected:
        return None
    try:
        arr = np.asarray(pixels_y, dtype=np.float32).reshape(int(height), int(width))
    except ValueError:
        return None
    resized = _resize_bilinear(arr, int(target_size))
    normalized = (resized / 127.5) - 1.0
    rgb = np.stack([normalized, normalized, normalized], axis=0)  # (3, H, W)
    return np.expand_dims(rgb, axis=0).astype(np.float32)  # (1, 3, H, W)


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------


def compute_lpips_distance_pair(
    frame_a: np.ndarray,
    frame_b: np.ndarray,
    model_path: str = LPIPS_MODEL_PATH,
) -> Optional[float]:
    """Calcule la distance LPIPS entre 2 frames pre-traitees.

    Returns float [0.0, +inf[ (plus petit = plus similaire) ou None si erreur.
    """
    if frame_a is None or frame_b is None:
        return None
    if frame_a.shape != frame_b.shape:
        return None
    try:
        session = _get_session(model_path)
    except FileNotFoundError:
        # WARNING deja emis par _get_session via _warn_model_missing_once.
        # On retourne None gracieusement (le composite_score_v2 omet alors
        # le sub-score LPIPS, sans casser le pipeline perceptuel).
        return None
    except RuntimeError as exc:
        # onnxruntime absent : WARNING deja emis par _is_ort_available.
        logger.debug("LPIPS indisponible : %s", exc)
        return None

    try:
        inputs = {inp.name: arr for inp, arr in zip(session.get_inputs(), [frame_a, frame_b])}
        outputs = session.run(None, inputs)
    except Exception as exc:
        logger.warning("LPIPS inference erreur : %s", exc)
        return None

    raw = outputs[0]
    try:
        return float(np.asarray(raw).reshape(-1)[0])
    except (IndexError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Orchestrateur (comparaison 2 fichiers via frames alignees)
# ---------------------------------------------------------------------------


def compute_lpips_comparison(
    aligned_frames: List[Dict[str, Any]],
    max_pairs: int = LPIPS_N_FRAMES_PAIRS,
    model_path: str = LPIPS_MODEL_PATH,
) -> LpipsResult:
    """Compare 2 fichiers via LPIPS sur N paires de frames alignees.

    Args:
        aligned_frames: sortie de `extract_aligned_frames` (comparison.py).
            Chaque element doit contenir pixels_a, pixels_b, width, height.
        max_pairs: nombre maximum de paires (mediane).
    """
    if not aligned_frames:
        return LpipsResult(
            distance_median=None,
            distances_per_pair=[],
            verdict="insufficient_data",
            n_pairs_evaluated=0,
        )

    # ONNX runtime absent : _is_ort_available() a deja emis le WARNING.
    if not _is_ort_available():
        return LpipsResult(
            distance_median=None,
            distances_per_pair=[],
            verdict="insufficient_data",
            n_pairs_evaluated=0,
        )
    # Modele ONNX absent (cas rare : .exe corrompu, build incomplet, fichier
    # supprime manuellement). On emet un WARNING unique avec instructions de
    # reinstall et on retourne un resultat degrade plutot que de propager
    # l'erreur jusqu'a l'UI.
    if _resolve_model_path(model_path) is None:
        _warn_model_missing_once(model_path)
        return LpipsResult(
            distance_median=None,
            distances_per_pair=[],
            verdict="insufficient_data",
            n_pairs_evaluated=0,
        )

    selected = aligned_frames[: int(max_pairs)] if max_pairs > 0 else aligned_frames
    distances: List[float] = []

    for frame in selected:
        w = int(frame.get("width", 0))
        h = int(frame.get("height", 0))
        pa = frame.get("pixels_a") or []
        pb = frame.get("pixels_b") or []
        pre_a = preprocess_frame_for_lpips(pa, w, h)
        pre_b = preprocess_frame_for_lpips(pb, w, h)
        if pre_a is None or pre_b is None:
            continue
        d = compute_lpips_distance_pair(pre_a, pre_b, model_path)
        if d is not None and d >= 0:
            distances.append(round(d, 4))

    if not distances:
        return LpipsResult(
            distance_median=None,
            distances_per_pair=[],
            verdict="insufficient_data",
            n_pairs_evaluated=0,
        )

    med = float(median(distances))
    return LpipsResult(
        distance_median=round(med, 4),
        distances_per_pair=distances,
        verdict=classify_lpips_verdict(med),
        n_pairs_evaluated=len(distances),
    )
