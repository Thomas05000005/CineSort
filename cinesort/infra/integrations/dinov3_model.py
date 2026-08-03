"""DinoV3Model : adapter ONNX Runtime CPU pour DINOv3-small (V4.2 SCAFFOLD).

Pattern : adapter infra autour d'un modele ONNX (DINOv3-small ~80MB OU
OpenCLIP ViT-B/32 ~150MB en variante), bundle dans dist/CineSort.exe via
PyInstaller `--add-data` (cf docs/internal/notes/vision_models.md). Le
chargement de la session ONNX est LAZY (premiere methode appelee), pour
eviter le cout (~150ms) si la feature flag `visual_similarity` est OFF.

API publique :
    - load_model()                       : retourne la session ONNX (lazy)
    - cosine_similarity(emb1, emb2)      : similarite cosine entre deux vecteurs
    - reset_cache()                      : pour tests (force re-load)

Memoires user :
    - subprocess direct > wrappers Python : ici onnxruntime natif (PAS de
      torch, pas de transformers, pas de subprocess). Cf docs/internal/notes/
      torch_cpu_strategy.md qui confirme que torch n'est pas une dependance.
    - PAS de bundle DL au 1er usage : le `.onnx` DOIT etre dans le bundle
      PyInstaller (cf vision_models.md, +120MB accepte).
    - Code robuste aux binaires absents : si onnxruntime non installe OU
      .onnx absent, lever VisionModelUnavailableError EXPLICITE (pas crash).
    - perceptual != quality : ce modele produit des embeddings visuels
      distincts du quality score.

Architecture (import-linter) : ce module est en `cinesort/infra/integrations/`,
peut importer cinesort.infra.errors mais PAS cinesort.app / cinesort.ui /
cinesort.domain. La domain layer recoit `load_model` injecte (pattern dans
`cinesort.domain.vision_embedding.embed_frames`).

V4.2 status : SCAFFOLD uniquement. Aucun appel runtime tant que la
feature flag `visual_similarity` n'est pas activee (cf
cinesort/domain/vision_embedding.py:VISUAL_SIMILARITY_FEATURE_FLAG).
"""

from __future__ import annotations

import logging
import math
import os
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np

logger = logging.getLogger(__name__)


# Defauts alignes sur DINOv3-small (cf vision_models.md). Pour OpenCLIP
# ViT-B/32, mettre EMBEDDING_DIM_DEFAULT=512 et MODEL_FILENAME="openclip_vitb32.onnx".
EMBEDDING_DIM_DEFAULT: int = 384
MODEL_FILENAME_DEFAULT: str = "dinov3_small.onnx"
INPUT_SIZE_DEFAULT: int = 224  # ViT standard 224x224

# Cache de la session ONNX (lazy load). None tant que load_model() pas appele.
_session_cache: Optional[Any] = None
_model_path_cache: Optional[Path] = None


class VisionModelUnavailableError(RuntimeError):
    """Levee si onnxruntime ou le fichier .onnx ne sont pas utilisables."""


# ---------------------------------------------------------------------------
# Resolution du chemin modele (compatible PyInstaller bundle)
# ---------------------------------------------------------------------------


def _default_model_path(filename: str = MODEL_FILENAME_DEFAULT) -> Path:
    """Cherche le .onnx a cote de l'exe (PyInstaller) ou dans cinesort/data/.

    Ordre de recherche :
        1. sys._MEIPASS / models / filename     (PyInstaller --add-data)
        2. parent(sys.executable) / models / filename  (exe portable)
        3. cinesort/data/models/filename         (dev mode, repo)
    """
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "models" / filename)
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / "models" / filename)
    # Dev mode : remonter depuis ce fichier jusqu'a cinesort/data/models
    here = Path(__file__).resolve()
    candidates.append(here.parent.parent.parent / "data" / "models" / filename)
    for c in candidates:
        if c.is_file():
            return c
    # Pas trouve : retourner la 1ere candidate (utile pour message d'erreur).
    return candidates[0] if candidates else Path(filename)


# ---------------------------------------------------------------------------
# Chargement lazy de la session ONNX
# ---------------------------------------------------------------------------


def load_model(
    model_path: Optional[str | Path] = None,
    *,
    providers: Optional[Sequence[str]] = None,
) -> Any:
    """Charge (lazy) et retourne une session ONNX prete pour inference.

    Args:
        model_path: Chemin explicite vers le .onnx. Si None, utilise
            `_default_model_path()`.
        providers: Liste d'execution providers ONNX. Defaut CPU uniquement
            (`["CPUExecutionProvider"]`) — la memoire user "PAS DE BUNDLE DL"
            implique aussi : pas de DLL CUDA bundlee.

    Returns:
        `onnxruntime.InferenceSession` (typage Any pour eviter l'import dur).

    Raises:
        VisionModelUnavailableError: si onnxruntime n'est pas importable
            OU si le .onnx est absent du bundle.
    """
    global _session_cache, _model_path_cache

    if _session_cache is not None:
        return _session_cache

    try:
        import onnxruntime as ort  # type: ignore[import-not-found]  # noqa: PLC0415
    except ImportError as exc:
        raise VisionModelUnavailableError("onnxruntime non installe (requis pour DINOv3 embeddings V4.2)") from exc

    resolved = Path(model_path) if model_path else _default_model_path()
    if not resolved.is_file():
        raise VisionModelUnavailableError(
            f"modele ONNX absent: {resolved} (cf docs/internal/notes/vision_models.md pour bundling)"
        )

    provs = list(providers) if providers else ["CPUExecutionProvider"]
    try:
        sess_options = ort.SessionOptions()
        # Limiter le parallelisme intra-op : embeddings batches petits,
        # eviter de monopoliser tous les coeurs (concurrence avec apply).
        sess_options.intra_op_num_threads = max(1, (os.cpu_count() or 4) // 2)
        session = ort.InferenceSession(
            str(resolved),
            sess_options=sess_options,
            providers=provs,
        )
    except Exception as exc:  # noqa: BLE001 - encapsule toute erreur ONNX
        raise VisionModelUnavailableError(f"echec chargement session ONNX {resolved}: {exc}") from exc

    _session_cache = session
    _model_path_cache = resolved
    logger.info("DinoV3 model loaded: %s (providers=%s)", resolved, provs)
    return session


def reset_cache() -> None:
    """Reset le cache de session (utile pour les tests d'integration)."""
    global _session_cache, _model_path_cache
    _session_cache = None
    _model_path_cache = None


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------


def cosine_similarity(emb1: np.ndarray, emb2: np.ndarray) -> float:
    """Similarite cosine entre deux embeddings, dans [-1.0, 1.0].

    Robuste aux entrees :
        - listes Python (converties via np.asarray)
        - vecteurs de norme nulle (retourne 0.0, pas NaN)
        - shapes incompatibles (retourne 0.0 + log debug)

    Si les embeddings sont deja L2-normalises (cf
    `vision_embedding.aggregate_embeddings`), `cosine_similarity` est
    equivalent au produit scalaire — mais cette fonction le calcule
    quand meme explicitement pour rester correcte sur vecteurs non
    normalises.
    """
    a = np.asarray(emb1, dtype=np.float32).ravel()
    b = np.asarray(emb2, dtype=np.float32).ravel()
    if a.size == 0 or b.size == 0 or a.shape != b.shape:
        logger.debug(
            "cosine_similarity: shapes incompat a=%s b=%s",
            a.shape,
            b.shape,
        )
        return 0.0
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na < 1e-8 or nb < 1e-8:
        return 0.0
    dot = float(np.dot(a, b))
    sim = dot / (na * nb)
    # Garde-fou numerique : clamp dans [-1, 1] (peut sortir legerement de
    # l'intervalle pour cause de precision float32).
    if math.isnan(sim) or math.isinf(sim):
        return 0.0
    return max(-1.0, min(1.0, sim))
