"""Pipeline doublons V2.4 — orchestration fusion Chromaprint + videohash.

Bounded context : couche `app/` qui orchestre les signaux domain
(`audio_fingerprint`, `video_hash`, `fusion_score`) pour produire une
detection de doublons plus robuste qu'avec Chromaprint seul.

Backward compat ABSOLUE :
- Pipeline existant `check_duplicates` legacy (run_flow_support.py) =
  INCHANGE. Aucun import, aucun appel modifie en aval.
- Tout passe par le feature flag `CINESORT_FUSION_DOUBLONS` (off par
  defaut) qui controle :
    * l'exposition de l'endpoint `check_duplicates_fusion` cote UI,
    * l'activation reelle du calcul fusion (sinon retour stub vide).

Pattern architectural :
- Couche `app/` -> peut importer `domain/` (pas l'inverse) et `infra/`.
- Ne touche PAS aux helpers legacy de `plan_support.py` (find_duplicate_targets).
- Reutilise les artefacts deja calcules dans le plan run (fingerprints
  Chromaprint stockes par perceptual pipeline) pour ne pas re-lancer
  fpcalc — performance et coherence avec le reste de l'app.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from cinesort.domain.fusion_score import (
    DEFAULT_AUDIO_WEIGHT,
    DEFAULT_VIDEO_WEIGHT,
    FusionResult,
    compute_fusion,
)
from cinesort.domain.perceptual.audio_fingerprint import compare_audio_fingerprints
from cinesort.domain.video_hash import (
    compute_phash_per_frame,
    extract_video_thumbnails,
    videohash_distance,
)

logger = logging.getLogger(__name__)


# --- Feature flag ------------------------------------------------------------
# Env var d'activation. OFF par defaut (toute valeur != 1/true/yes/on/debug
# desactive). Permet a la fois :
#   - aux developpeurs de tester en local sans toucher au code,
#   - a la UI d'exposer un toggle settings qui passe CINESORT_FUSION_DOUBLONS=1
#     pour la session courante.
_FUSION_ENV_VAR = "CINESORT_FUSION_DOUBLONS"
_TRUTHY = {"1", "true", "yes", "on", "debug"}


def is_fusion_enabled() -> bool:
    """Retourne True si le feature flag fusion doublons est actif.

    Pure lecture env (pas de side-effects), peut etre appele autant de fois
    que necessaire. Si la valeur est invalide ou absente, retourne False
    (backward compat ABSOLUE : pipeline legacy uniquement).
    """
    v = str(os.environ.get(_FUSION_ENV_VAR, "")).strip().lower()
    return v in _TRUTHY


@dataclass
class FilmFusionInput:
    """Donnees d'entree minimales par film pour le calcul fusion.

    Attributes:
        row_id : identifiant du film dans le plan run.
        video_path : chemin absolu du fichier video (pour ffmpeg pHash).
        duration_s : duree totale (utilisee pour repartir thumbnails).
        chromaprint : fingerprint Chromaprint deja calcule (base64) ou None.
    """

    row_id: str
    video_path: str
    duration_s: float
    chromaprint: Optional[str]


@dataclass
class FusionPair:
    """Resultat fusion pour une paire de films."""

    row_a: str
    row_b: str
    fusion: FusionResult


def compute_fusion_for_pair(
    a: FilmFusionInput,
    b: FilmFusionInput,
    *,
    audio_weight: float = DEFAULT_AUDIO_WEIGHT,
    video_weight: float = DEFAULT_VIDEO_WEIGHT,
    ffmpeg_path: Optional[str] = None,
    thumbnail_count: int = 10,
) -> Optional[FusionPair]:
    """Calcule la fusion pour une paire de films.

    Args:
        a, b : FilmFusionInput (row_id, video_path, duration, chromaprint).
        audio_weight, video_weight : ponderation fusion (cf fusion_score).
        ffmpeg_path : chemin ffmpeg (None = auto-detection).
        thumbnail_count : N frames a comparer (default 10).

    Returns:
        FusionPair si au moins un signal est dispo, None sinon.
        En cas d'erreur partielle (ffmpeg absent, fingerprint manquant),
        le signal correspondant est mis a None et la fusion s'adapte.
    """
    # Signal 1 : Chromaprint (similarite [0, 1]).
    audio_sim: Optional[float] = None
    if a.chromaprint and b.chromaprint:
        audio_sim = compare_audio_fingerprints(a.chromaprint, b.chromaprint)

    # Signal 2 : videohash perceptual.
    # Pour eviter le double calcul, on extrait les hash une seule fois par
    # film. Dans un usage batch (N films), l'appelant doit cacher cela —
    # ici on calcule pour la paire isole.
    video_sim: Optional[float] = None
    try:
        frames_a = extract_video_thumbnails(
            a.video_path,
            a.duration_s,
            n=thumbnail_count,
            ffmpeg_path=ffmpeg_path,
        )
        frames_b = extract_video_thumbnails(
            b.video_path,
            b.duration_s,
            n=thumbnail_count,
            ffmpeg_path=ffmpeg_path,
        )
        h_a = compute_phash_per_frame(frames_a) if frames_a else b""
        h_b = compute_phash_per_frame(frames_b) if frames_b else b""
        if h_a and h_b:
            dist = videohash_distance(h_a, h_b)
            if dist is not None:
                video_sim = 1.0 - dist
    except OSError as exc:
        # ffmpeg absent / fichier corrompu : signal video = None, fusion
        # retombe sur audio uniquement.
        logger.warning(
            "video hash failed pour paire (%s, %s): %s",
            a.row_id,
            b.row_id,
            exc,
        )

    fusion = compute_fusion(
        audio_sim,
        video_sim,
        audio_weight=audio_weight,
        video_weight=video_weight,
    )
    if fusion is None:
        return None
    return FusionPair(row_a=a.row_id, row_b=b.row_id, fusion=fusion)


def compute_fusion_for_groups(
    candidate_groups: List[List[FilmFusionInput]],
    *,
    audio_weight: float = DEFAULT_AUDIO_WEIGHT,
    video_weight: float = DEFAULT_VIDEO_WEIGHT,
    ffmpeg_path: Optional[str] = None,
    thumbnail_count: int = 10,
) -> List[FusionPair]:
    """Calcule la fusion pour des groupes de films candidats doublons.

    Strategie : pour chaque groupe (issu du regroupement legacy par
    title/year/edition), on calcule la fusion sur toutes les paires
    internes. Le cache videohash par film evite N appels ffmpeg par
    paire (1 par film, partage entre toutes ses paires du groupe).

    Args:
        candidate_groups : liste de groupes, chaque groupe = liste de
            FilmFusionInput (>= 2 elements pour generer des paires).
        audio_weight, video_weight, ffmpeg_path, thumbnail_count : cf
            compute_fusion_for_pair.

    Returns:
        Liste des FusionPair pour toutes les paires intra-groupe.
        Backward compat : retourne [] si aucun groupe ou si feature flag off.
    """
    if not is_fusion_enabled():
        # Backward compat : meme si l'appelant entre ici par erreur, on ne
        # calcule rien tant que le flag n'est pas active.
        return []

    out: List[FusionPair] = []

    # Cache des videohash par row_id pour eviter le double appel ffmpeg
    # quand un film appartient a plusieurs paires d'un meme groupe.
    hash_cache: Dict[str, bytes] = {}

    def _videohash_for(film: FilmFusionInput) -> bytes:
        if film.row_id in hash_cache:
            return hash_cache[film.row_id]
        try:
            frames = extract_video_thumbnails(
                film.video_path,
                film.duration_s,
                n=thumbnail_count,
                ffmpeg_path=ffmpeg_path,
            )
            h = compute_phash_per_frame(frames) if frames else b""
        except OSError as exc:
            logger.warning("video hash failed pour %s: %s", film.row_id, exc)
            h = b""
        hash_cache[film.row_id] = h
        return h

    for group in candidate_groups:
        if not group or len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a = group[i]
                b = group[j]

                audio_sim: Optional[float] = None
                if a.chromaprint and b.chromaprint:
                    audio_sim = compare_audio_fingerprints(a.chromaprint, b.chromaprint)

                h_a = _videohash_for(a)
                h_b = _videohash_for(b)
                video_sim: Optional[float] = None
                if h_a and h_b:
                    dist = videohash_distance(h_a, h_b)
                    if dist is not None:
                        video_sim = 1.0 - dist

                fusion = compute_fusion(
                    audio_sim,
                    video_sim,
                    audio_weight=audio_weight,
                    video_weight=video_weight,
                )
                if fusion is None:
                    continue
                out.append(FusionPair(row_a=a.row_id, row_b=b.row_id, fusion=fusion))

    return out


def serialize_fusion_pairs(pairs: List[FusionPair]) -> List[Dict[str, Any]]:
    """Serialise une liste de FusionPair en payload JSON-safe.

    Forme retour adaptee a un endpoint API REST (ne contient que des types
    primitifs). Le caller UI peut afficher score, verdict, et la
    decomposition audio/video.
    """
    out: List[Dict[str, Any]] = []
    for p in pairs:
        out.append(
            {
                "row_a": p.row_a,
                "row_b": p.row_b,
                "score": p.fusion.score,
                "verdict": p.fusion.verdict,
                "audio_score": p.fusion.audio_score,
                "video_score": p.fusion.video_score,
                "audio_weight": p.fusion.audio_weight,
                "video_weight": p.fusion.video_weight,
            }
        )
    return out
