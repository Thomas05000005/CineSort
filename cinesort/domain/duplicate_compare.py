"""Comparaison qualite des doublons — determine le meilleur fichier video.

Compare deux (ou N) fichiers video en fonction de criteres techniques
ponderes : resolution, HDR, codec video, codec audio, canaux audio,
bitrate (si meme codec). Retourne un verdict et une explication.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# --- Ponderations des criteres -------------------------------------------
_WEIGHT_RESOLUTION = 30
_WEIGHT_HDR = 20
_WEIGHT_VIDEO_CODEC = 15
_WEIGHT_AUDIO_CODEC = 15
_WEIGHT_AUDIO_CHANNELS = 10
_WEIGHT_BITRATE = 5  # uniquement si meme codec video
_WEIGHT_FILE_SIZE = 0  # informatif, pas de points

# Seuil pour declarer un match nul (tie)
_TIE_THRESHOLD = 5

# --- Rangs pour chaque critere -------------------------------------------
_RESOLUTION_RANK = {2160: 4, 1080: 3, 720: 2, 480: 1}

_HDR_RANK = {"dv": 3, "dolby vision": 3, "hdr10+": 2, "hdr10plus": 2, "hdr10": 1, "sdr": 0, "": 0}

_VIDEO_CODEC_RANK = {
    "av1": 4,
    "hevc": 3,
    "h265": 3,
    "x265": 3,
    "h264": 2,
    "x264": 2,
    "avc": 2,
    "mpeg4": 1,
    "xvid": 1,
    "divx": 1,
}

_AUDIO_CODEC_RANK = {
    "truehd": 5,
    "atmos": 5,
    "dts-hd ma": 4,
    "dtshd": 4,
    "dts-hd": 4,
    "flac": 3,
    "dts": 2,
    "ac3": 2,
    "eac3": 2,
    "aac": 1,
    "mp3": 1,
    "opus": 1,
}


# --- Dataclasses ---------------------------------------------------------


@dataclass
class CriterionResult:
    """Resultat de la comparaison pour un critere unique."""

    name: str  # "resolution", "hdr", etc.
    label: str  # "Resolution", "HDR", etc.
    value_a: str  # "1080p", "HDR10"
    value_b: str
    winner: str  # "a" | "b" | "tie" | "unknown"
    points_delta: int  # positif = A meilleur, negatif = B meilleur


@dataclass
class ComparisonResult:
    """Resultat complet de la comparaison entre deux fichiers."""

    winner: str  # "a" | "b" | "tie"
    winner_label: str  # "Fichier A est meilleur" etc.
    total_score_a: int
    total_score_b: int
    criteria: List[CriterionResult] = field(default_factory=list)
    recommendation: str = ""
    file_a_size: int = 0  # octets
    file_b_size: int = 0
    size_savings: int = 0  # octets economises si on archive le perdant


# --- Comparaison principale ----------------------------------------------


def compare_duplicates(
    probe_a: Optional[Dict[str, Any]],
    probe_b: Optional[Dict[str, Any]],
    quality_a: Optional[Dict[str, Any]] = None,
    quality_b: Optional[Dict[str, Any]] = None,
    *,
    perceptual_score_a: Optional[int] = None,
    perceptual_score_b: Optional[int] = None,
    subtitles_fr_a: bool = False,
    subtitles_fr_b: bool = False,
) -> ComparisonResult:
    """Compare deux fichiers video a partir de leurs donnees probe."""
    criteria = compare_by_criteria(probe_a, probe_b)

    # Critere optionnel : score perceptuel (poids 10)
    if perceptual_score_a is not None and perceptual_score_b is not None:
        pa, pb = int(perceptual_score_a), int(perceptual_score_b)
        delta = max(-10, min(10, (pa - pb) // 5))  # normalise sur ±10
        w = "a" if delta > 0 else "b" if delta < 0 else "tie"
        criteria.append(
            CriterionResult(
                name="perceptual",
                label="Score perceptuel",
                value_a=str(pa),
                value_b=str(pb),
                winner=w,
                points_delta=delta,
            )
        )

    # Critere optionnel : sous-titres FR (poids 5)
    if subtitles_fr_a != subtitles_fr_b:
        delta = 5 if subtitles_fr_a else -5
        w = "a" if subtitles_fr_a else "b"
        criteria.append(
            CriterionResult(
                name="subtitles_fr",
                label="Sous-titres FR",
                value_a="oui" if subtitles_fr_a else "non",
                value_b="oui" if subtitles_fr_b else "non",
                winner=w,
                points_delta=delta,
            )
        )

    winner, explanation = determine_winner(criteria)

    size_a = _file_size(probe_a)
    size_b = _file_size(probe_b)
    loser_size = size_b if winner == "a" else size_a if winner == "b" else 0

    labels = {"a": "Fichier A est meilleur", "b": "Fichier B est meilleur", "tie": "Qualite equivalente"}
    recs = {"a": "Garder A, archiver B", "b": "Garder B, archiver A", "tie": "Qualite equivalente, garder les deux"}

    score_a = sum(max(0, c.points_delta) for c in criteria)
    score_b = sum(max(0, -c.points_delta) for c in criteria)

    logger.debug("compare: winner=%s delta=%d", winner, abs(score_a - score_b))
    return ComparisonResult(
        winner=winner,
        winner_label=labels[winner],
        total_score_a=score_a,
        total_score_b=score_b,
        criteria=criteria,
        recommendation=recs[winner],
        file_a_size=size_a,
        file_b_size=size_b,
        size_savings=loser_size,
    )


def compare_by_criteria(
    probe_a: Optional[Dict[str, Any]],
    probe_b: Optional[Dict[str, Any]],
) -> List[CriterionResult]:
    """Compare deux probes critere par critere. Retourne la liste des resultats."""
    va = (probe_a or {}).get("video") or {}
    vb = (probe_b or {}).get("video") or {}
    aa = _best_audio(probe_a)
    ab = _best_audio(probe_b)

    results: List[CriterionResult] = []

    # 1. Resolution
    results.append(
        _compare_criterion(
            "resolution",
            "Resolution",
            _resolution_height(va),
            _resolution_height(vb),
            _resolution_label,
            _WEIGHT_RESOLUTION,
        )
    )

    # 2. HDR
    results.append(
        _compare_criterion(
            "hdr",
            "HDR",
            _hdr_rank_value(va),
            _hdr_rank_value(vb),
            _hdr_label,
            _WEIGHT_HDR,
        )
    )

    # 3. Codec video
    codec_a = _video_codec_rank_value(va)
    codec_b = _video_codec_rank_value(vb)
    results.append(
        _compare_criterion(
            "video_codec",
            "Codec video",
            codec_a,
            codec_b,
            _video_codec_label,
            _WEIGHT_VIDEO_CODEC,
        )
    )

    # 4. Audio codec
    results.append(
        _compare_criterion(
            "audio_codec",
            "Audio codec",
            _audio_codec_rank_value(aa),
            _audio_codec_rank_value(ab),
            _audio_codec_label,
            _WEIGHT_AUDIO_CODEC,
        )
    )

    # 5. Audio canaux
    results.append(
        _compare_criterion(
            "audio_channels",
            "Canaux audio",
            int(aa.get("channels") or 0),
            int(ab.get("channels") or 0),
            _channels_label,
            _WEIGHT_AUDIO_CHANNELS,
        )
    )

    # 6. Bitrate — uniquement si meme codec video
    same_codec = codec_a is not None and codec_b is not None and codec_a == codec_b and codec_a > 0
    br_a = int(va.get("bitrate") or 0)
    br_b = int(vb.get("bitrate") or 0)
    if same_codec and br_a > 0 and br_b > 0:
        results.append(
            _compare_criterion(
                "bitrate",
                "Bitrate",
                br_a,
                br_b,
                _bitrate_label,
                _WEIGHT_BITRATE,
            )
        )
    else:
        results.append(
            CriterionResult(
                name="bitrate",
                label="Bitrate",
                value_a=_bitrate_label(br_a),
                value_b=_bitrate_label(br_b),
                winner="unknown",
                points_delta=0,
            )
        )

    # 7. Taille fichier (informatif, 0 points)
    size_a = _file_size(probe_a)
    size_b = _file_size(probe_b)
    results.append(
        CriterionResult(
            name="file_size",
            label="Taille",
            value_a=str(size_a),
            value_b=str(size_b),
            winner="tie",
            points_delta=0,
        )
    )

    return results


def determine_winner(criteria: List[CriterionResult]) -> Tuple[str, str]:
    """Determine le gagnant a partir de la somme des deltas ponderes."""
    total = sum(c.points_delta for c in criteria)
    if total > _TIE_THRESHOLD:
        return "a", f"Fichier A gagne avec +{total} points"
    if total < -_TIE_THRESHOLD:
        return "b", f"Fichier B gagne avec +{abs(total)} points"
    return "tie", f"Egalite (delta {total} points, seuil {_TIE_THRESHOLD})"


# --- Ranking pour 3+ fichiers --------------------------------------------


def rank_duplicates(
    files: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Classe N fichiers par score de qualite decroissant.

    Chaque element de *files* doit avoir une cle 'probe' (dict probe normalisee).
    Retourne la liste triee avec un champ 'rank_score' ajoute.
    """
    scored: List[Tuple[int, Dict[str, Any]]] = []
    for f in files:
        probe = f.get("probe") or {}
        score = _compute_single_score(probe)
        enriched = dict(f)
        enriched["rank_score"] = score
        scored.append((score, enriched))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored]


def _compute_single_score(probe: Dict[str, Any]) -> int:
    """Calcule un score absolu pour un seul fichier (pour le classement)."""
    video = probe.get("video") or {}
    audio = _best_audio(probe)

    score = 0
    h = _resolution_height(video)
    if h is not None:
        score += min(h, 2160) * _WEIGHT_RESOLUTION // 2160

    score += (_hdr_rank_value(video) or 0) * _WEIGHT_HDR // 3
    score += (_video_codec_rank_value(video) or 0) * _WEIGHT_VIDEO_CODEC // 4
    score += (_audio_codec_rank_value(audio) or 0) * _WEIGHT_AUDIO_CODEC // 5
    score += min(int(audio.get("channels") or 0), 8) * _WEIGHT_AUDIO_CHANNELS // 8

    return score


# --- Helpers prives -------------------------------------------------------


def _compare_criterion(
    name: str,
    label: str,
    val_a: Optional[int],
    val_b: Optional[int],
    fmt: Any,
    weight: int,
) -> CriterionResult:
    """Compare deux valeurs numeriques pour un critere."""
    str_a = fmt(val_a) if val_a is not None else "?"
    str_b = fmt(val_b) if val_b is not None else "?"

    if val_a is None or val_b is None:
        return CriterionResult(name=name, label=label, value_a=str_a, value_b=str_b, winner="unknown", points_delta=0)

    if val_a > val_b:
        return CriterionResult(name=name, label=label, value_a=str_a, value_b=str_b, winner="a", points_delta=weight)
    if val_b > val_a:
        return CriterionResult(name=name, label=label, value_a=str_a, value_b=str_b, winner="b", points_delta=-weight)
    return CriterionResult(name=name, label=label, value_a=str_a, value_b=str_b, winner="tie", points_delta=0)


def _resolution_height(video: Dict[str, Any]) -> Optional[int]:
    h = video.get("height")
    return int(h) if h and int(h) > 0 else None


def _resolution_label(h: Optional[int]) -> str:
    if h is None:
        return "?"
    if h >= 2160:
        return "2160p"
    if h >= 1080:
        return "1080p"
    if h >= 720:
        return "720p"
    if h >= 480:
        return "480p"
    return f"{h}p"


def _hdr_rank_value(video: Dict[str, Any]) -> Optional[int]:
    if video.get("hdr_dolby_vision"):
        return 3
    if video.get("hdr10_plus"):
        return 2
    if video.get("hdr10"):
        return 1
    # SDR explicite ou pas d'info → 0 (si on a au moins du video info)
    if video.get("height") or video.get("codec"):
        return 0
    return None


def _hdr_label(rank: Optional[int]) -> str:
    return {3: "DV", 2: "HDR10+", 1: "HDR10", 0: "SDR"}.get(rank or 0, "?")


def _video_codec_rank_value(video: Dict[str, Any]) -> Optional[int]:
    codec = str(video.get("codec") or "").strip().lower()
    if not codec:
        return None
    return _VIDEO_CODEC_RANK.get(codec, 0)


def _video_codec_label(rank: Optional[int]) -> str:
    return {4: "av1", 3: "hevc", 2: "x264", 1: "xvid"}.get(rank or 0, "?")


def _audio_codec_rank_value(audio: Dict[str, Any]) -> Optional[int]:
    codec = str(audio.get("codec") or "").strip().lower()
    if not codec:
        return None
    return _AUDIO_CODEC_RANK.get(codec, 0)


def _audio_codec_label(rank: Optional[int]) -> str:
    return {5: "truehd", 4: "dts-hd ma", 3: "flac", 2: "ac3", 1: "aac"}.get(rank or 0, "?")


def _channels_label(ch: Optional[int]) -> str:
    if not ch or ch <= 0:
        return "?"
    if ch == 2:
        return "2.0"
    if ch == 6:
        return "5.1"
    if ch == 8:
        return "7.1"
    return f"{ch}ch"


def _bitrate_label(br: Optional[int]) -> str:
    if not br or br <= 0:
        return "?"
    kbps = br // 1000 if br > 10000 else br
    if kbps >= 1000:
        return f"{kbps // 1000} Mbps"
    return f"{kbps} kbps"


def _best_audio(probe: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Retourne la meilleure piste audio d'un probe."""
    tracks = (probe or {}).get("audio_tracks") or []
    if not tracks:
        return {}
    # Trier par rang codec decroissant, puis canaux decroissant
    best = tracks[0]
    best_rank = _audio_codec_rank_value(best) or 0
    for t in tracks[1:]:
        r = _audio_codec_rank_value(t) or 0
        if r > best_rank or (r == best_rank and int(t.get("channels") or 0) > int(best.get("channels") or 0)):
            best = t
            best_rank = r
    return best


def _file_size(probe: Optional[Dict[str, Any]]) -> int:
    """Extrait la taille du fichier depuis le probe (champ size ou duration heuristique)."""
    if not probe:
        return 0
    # Le champ 'size' n'est pas standard dans NormalizedProbe, utiliser bitrate * duration
    dur = probe.get("duration_s") or 0
    video = probe.get("video") or {}
    br = video.get("bitrate") or 0
    if dur > 0 and br > 0:
        return int(dur * br / 8)
    return 0
