"""Vision embeddings (V4.2 SCAFFOLD) — extraction keyframes + embeddings DINOv3/CLIP.

Pipeline a haut niveau (futur runtime V4.2) :
    1. extract_keyframes(video_path, n=10) : ffmpeg subprocess direct -> JPEG frames.
    2. embed_frames(frames)                : ONNX Runtime CPU -> List[np.ndarray] (vecteurs).
    3. Agregation (mean pooling)           : un embedding par film, stocke dans vec_films_hash
       (cf cinesort/infra/vector_search/sqlite_vec_adapter.py).

Memoires user appliquees :
    - subprocess direct > wrappers Python : ffmpeg lance via `tracked_run()`
      (cinesort.domain._runners), pas via imageio/moviepy.
    - PAS DE BUNDLE DL au 1er usage : le modele ONNX (DINOv3-small ~80MB OU
      OpenCLIP ViT-B/32 ~150MB) doit etre dans le bundle PyInstaller (cf
      docs/internal/notes/vision_models.md, +120MB accepte).
    - perceptual != quality : ces embeddings sont une "signature visuelle"
      distincte du quality_score. Module logique en `domain/`, modele ONNX
      lui-meme en `infra/integrations/dinov3_model.py` (load_model lazy).
    - Code robuste aux binaires absents : si ffmpeg/ONNX manquent, lever
      VisionEmbeddingUnavailableError explicite, pas crash silencieux.

Architecture (import-linter) : ce module est en `cinesort/domain/`. Il ne
peut PAS importer `app/`, `infra/`, `ui/`. L'exception est
`cinesort.domain._runners.tracked_run` qui vit deja en domain (cf
pattern des autres modules perceptuels, e.g. perceptual/ffmpeg_runner.py
qui importe _runners). La charge effective du modele ONNX se fait via une
fonction injectee depuis l'appelant (couche app), pour rester pure cote
domain.

V4.2 status : SCAFFOLD uniquement. Aucun appel runtime tant que la
feature flag `visual_similarity` n'est pas activee.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

import numpy as np

from cinesort.domain._runners import tracked_run

logger = logging.getLogger(__name__)


# Feature flag domain-level (mirror de l'infra). Mis a True une fois le
# modele ONNX bundle et la pipeline runtime validee.
VISUAL_SIMILARITY_FEATURE_FLAG: bool = False

# Constantes par defaut (alignees avec le modele DINOv3-small documente).
DEFAULT_KEYFRAMES_COUNT: int = 10
DEFAULT_EMBEDDING_DIM: int = 384  # DINOv3-small ; OpenCLIP ViT-B/32 = 512
DEFAULT_FRAME_TIMEOUT_S: float = 20.0
# Skip 5% au debut/fin pour ignorer generiques/logos studio.
DEFAULT_SKIP_PERCENT: int = 5


class VisionEmbeddingUnavailableError(RuntimeError):
    """Levee si ffmpeg ou ONNX Runtime ne sont pas utilisables."""


# ---------------------------------------------------------------------------
# Extraction de keyframes (subprocess ffmpeg direct)
# ---------------------------------------------------------------------------


def _compute_timestamps(
    duration_s: float,
    n: int,
    skip_percent: int = DEFAULT_SKIP_PERCENT,
) -> List[float]:
    """Calcule n timestamps uniformes en ignorant les bordures.

    Reproduit la logique de `perceptual.frame_extraction.compute_timestamps`
    en version simplifiee (scaffold, pas de gestion films courts).
    """
    dur = max(0.0, float(duration_s))
    if dur <= 0 or n <= 0:
        return []
    skip_pct = max(0, min(20, int(skip_percent)))
    skip_s = dur * skip_pct / 100.0
    useful = dur - 2.0 * skip_s
    if useful <= 0:
        skip_s = 0.0
        useful = dur
    step = useful / n
    return [round(skip_s + i * step + step / 2.0, 3) for i in range(n)]


def _runner_platform_kwargs() -> dict:
    """Subprocess kwargs Windows : pas de console flash."""
    if os.name != "nt":
        return {}
    kwargs: dict = {"creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0))}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
    si.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
    kwargs["startupinfo"] = si
    return kwargs


def extract_keyframes(
    video_path: str | Path,
    n: int = DEFAULT_KEYFRAMES_COUNT,
    *,
    duration_s: Optional[float] = None,
    ffmpeg_path: Optional[str] = None,
    timeout_s: float = DEFAULT_FRAME_TIMEOUT_S,
) -> List[bytes]:
    """Extrait n keyframes JPEG via subprocess ffmpeg direct.

    Args:
        video_path: Chemin vers le fichier video source.
        n: Nombre de keyframes desirees (clampe entre 1 et 50).
        duration_s: Duree connue (ffprobe). Si None, scaffold retourne [].
            Le runtime V4.2 appellera ffprobe en amont (cf perceptual).
        ffmpeg_path: Chemin explicite vers ffmpeg.exe (sinon `ffmpeg` sur PATH).
        timeout_s: Timeout par extraction unitaire.

    Returns:
        List[bytes] : chaque element est un JPEG en memoire. Vide si erreur.

    Raises:
        VisionEmbeddingUnavailableError: si ffmpeg n'est pas executable.

    Note: PAS encore appele en runtime (feature flag OFF). Le call site
    futur passera par `app/` qui injectera ffmpeg_path depuis settings.
    """
    if not VISUAL_SIMILARITY_FEATURE_FLAG:
        return []
    if duration_s is None or duration_s <= 0:
        logger.debug("extract_keyframes: duration inconnue, scaffold no-op")
        return []

    binary = ffmpeg_path or "ffmpeg"
    count = max(1, min(50, int(n)))
    timestamps = _compute_timestamps(duration_s, count)
    if not timestamps:
        return []

    frames: List[bytes] = []
    src = str(video_path)
    plat = _runner_platform_kwargs()
    for ts in timestamps:
        # -ss avant -i = seek rapide (keyframe la plus proche), suffisant
        # pour une signature visuelle (pas besoin de frame-exact).
        cmd = [
            binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(ts),
            "-i",
            src,
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "-",
        ]
        try:
            res = tracked_run(
                cmd,
                capture_output=True,
                timeout=timeout_s,
                check=False,
                **plat,
            )
        except FileNotFoundError as exc:
            raise VisionEmbeddingUnavailableError(f"ffmpeg introuvable: {binary}") from exc
        except subprocess.TimeoutExpired:
            logger.warning("extract_keyframes: timeout sur ts=%.3f", ts)
            continue
        if res.returncode != 0 or not res.stdout:
            logger.debug("extract_keyframes: rc=%s ts=%.3f", res.returncode, ts)
            continue
        frames.append(bytes(res.stdout))
    return frames


# ---------------------------------------------------------------------------
# Embedding des frames via ONNX Runtime
# ---------------------------------------------------------------------------


def embed_frames(
    frames: Sequence[bytes],
    *,
    model_loader: Optional[Callable[[], Any]] = None,
    embedding_dim: int = DEFAULT_EMBEDDING_DIM,
) -> List[np.ndarray]:
    """Calcule un embedding par frame via ONNX Runtime CPU.

    Args:
        frames: Liste de JPEG en memoire (sortie de `extract_keyframes`).
        model_loader: Callable retournant une session ONNX prete (par defaut
            None = scaffold no-op). Le runtime V4.2 injectera
            `cinesort.infra.integrations.dinov3_model.load_model` depuis la
            couche app/ pour rester pur cote domain (pas d'import infra ici).
        embedding_dim: Dimension attendue. Garde-fou pour shape mismatch.

    Returns:
        List[np.ndarray] de shape (embedding_dim,), un par frame. Vide si
        feature flag OFF ou si model_loader None.

    Raises:
        VisionEmbeddingUnavailableError: si le modele ne peut etre charge.

    Note: la logique reelle (decode JPEG -> tensor normalise -> session.run)
    sera ajoutee en V4.2 runtime. Le scaffold valide juste la signature et
    le contrat de retour pour les tests d'integration en amont.
    """
    if not VISUAL_SIMILARITY_FEATURE_FLAG:
        return []
    if not frames:
        return []
    if model_loader is None:
        logger.debug("embed_frames: pas de model_loader (scaffold no-op)")
        return []

    try:
        _session = model_loader()
    except Exception as exc:  # noqa: BLE001 - scaffold, contrat ouvert
        raise VisionEmbeddingUnavailableError(f"chargement modele vision impossible: {exc}") from exc

    # Scaffold : retourner des vecteurs zeros de la bonne shape. Le runtime
    # V4.2 fera le decode + forward effectif.
    return [np.zeros(embedding_dim, dtype=np.float32) for _ in frames]


def aggregate_embeddings(embeddings: Sequence[np.ndarray]) -> Optional[np.ndarray]:
    """Mean pool sur n embeddings frame -> 1 embedding film, L2-normalise.

    Permet de stocker UN seul vecteur par film dans `vec_films_hash` (cf
    sqlite_vec_adapter). La L2-normalisation rend le produit scalaire
    equivalent a la cosine similarity (cf `cosine_similarity` infra).
    """
    if not embeddings:
        return None
    stacked = np.stack([np.asarray(e, dtype=np.float32) for e in embeddings], axis=0)
    pooled = stacked.mean(axis=0)
    norm = float(np.linalg.norm(pooled))
    if norm < 1e-8:
        return pooled
    return (pooled / norm).astype(np.float32)
