"""Comparaison qualite des doublons — determine le meilleur fichier video.

Compare deux (ou N) fichiers video en fonction de criteres techniques
ponderes : resolution, HDR, codec video, codec audio, canaux audio,
bitrate (si meme codec). Retourne un verdict et une explication.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from cinesort.domain.codec_ranks import (
    AUDIO_CODEC_RANK as _AUDIO_CODEC_RANK,
)
from cinesort.domain.codec_ranks import (
    format_audio_channels as _format_audio_channels,
)

# Source unique de la derivation « codec de base + variante -> etiquette
# canonique » (le probe ffprobe range 'DTS-HD MA' dans `profile`, pas dans
# `codec`). Le home naturel serait `codec_ranks`, hors perimetre de ce
# correctif : on importe le scorer plutot que de dupliquer la regle, la
# divergence entre ces deux modules ayant deja produit un bug (R8-039).
from cinesort.domain.quality_score import (
    _AUDIO_CANONICAL_RANK_ALIAS,
    _canonical_audio_codec,
)

# Echelle largeur-primaire, source UNIQUE du depot. Ce module en portait une
# recopie (les seuils 3800/2100, 1900/1000, 1280/680 ecrits en dur) : cf. le
# correctif #5 de `_resolution_height`.
from cinesort.domain.resolution_class import (
    RES_720P,
    RES_1080P,
    RES_2160P,
    RES_SD,
    classify_resolution,
)

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

# Etiquette canonique (`metrics.detected.resolution`, cf. resolution_class)
# -> hauteur de reference de la classe. Utilise quand l'appelant fournit deja
# le verdict canonique plutot que des dimensions.
#
# Fix ultra-audit 2026-08-31 (#5) : cette table est desormais lue DANS LES DEUX
# SENS. `_resolution_height` encode (bande -> valeur comparee) et
# `_resolution_label` decode (valeur comparee -> etiquette affichee). Tant
# qu'il n'y a qu'UNE table, « meme etiquette » et « meme valeur » ne peuvent
# plus diverger — c'est exactement ce qui avait diverge.
_CANONICAL_LABEL_RANK = {RES_2160P: 2160, RES_1080P: 1080, RES_720P: 720}
_RANK_TO_CANONICAL_LABEL = {height: label for label, height in _CANONICAL_LABEL_RANK.items()}

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

# _AUDIO_CODEC_RANK : dict[str, int] importe depuis cinesort.domain.codec_ranks
# (lookup exact, semantique differente du ranking par substring du badge audio)


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
        # int() truncate vers 0 (symetrique), contrairement a `//` qui floor
        # vers -inf et biaisait en faveur de B sur petites differences.
        delta = max(-10, min(10, int((pa - pb) / 5)))  # normalise sur ±10
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

    winner, _explanation = determine_winner(criteria)

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
            _channels_value(aa),
            _channels_value(ab),
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
            label="Taille (estimée)",
            value_a=_human_size(size_a),
            value_b=_human_size(size_b),
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


def _to_positive_int(value: Any) -> int:
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _resolution_height(video: Dict[str, Any]) -> Optional[int]:
    """Valeur comparee pour le critere « Resolution » : la CLASSE, pas la hauteur brute.

    Fix ultra-audit 2026-08-03. Deux defauts distincts sont corriges ici.

    1. On comparait la hauteur BRUTE du flux. Deux crops du meme film --
       1920x800 et 1920x816, tous deux affiches « 720p vs 720p » dans la table
       des criteres -- produisaient un delta de 30 points (le poids PLEIN du
       critere) en faveur du second, et le comparateur recommandait d'archiver
       le fichier 6,7x mieux debite. Idem 1920x1080 vs 1920x1088 (padding
       mod-16), affiches « 1080p vs 1080p ». Le verdict n'est pas seulement
       affiche : l'ecran Doublons expose « Auto-decider tous » qui transforme
       `comparison.winner` en decision pour tous les groupes d'un clic, et les
       perdants partent en _review/_duplicates_user_decided/ a l'apply. Le delta
       suit desormais exactement l'etiquette affichee : meme classe => egalite.

    2. La classe se decidait sur la seule hauteur, alors que le fix bug 178
       (`quality_score._resolution_label`, 15/15 echantillons ffprobe reels
       1920x[784-818] = de vrais 1080p) a etabli que la LARGEUR est le critere
       principal : un 1080p scope 2.35:1 mesure 1920x800 et n'est pas un 720p.
       On accepte donc `width`, ainsi qu'une etiquette canonique deja calculee
       (`resolution` / `resolution_label`), des que l'appelant les fournit.

    En dessous de 720p on garde la hauteur brute : elle reste discriminante
    entre SD (576 / 480 / 360) et l'affichage historique est preserve.
    """
    label = str(video.get("resolution") or video.get("resolution_label") or "").strip().lower()
    if label in _CANONICAL_LABEL_RANK:
        return _CANONICAL_LABEL_RANK[label]
    # Fix ultra-audit 2026-08-31 (#5) : les trois seuils etaient RECOPIES ici.
    # Ils vivent une seule fois, dans `resolution_class` — le module ecrit pour
    # ca, et que `quality_score._resolution_label` interroge deja.
    band = classify_resolution(video.get("width"), video.get("height"))
    if band in _CANONICAL_LABEL_RANK:
        return _CANONICAL_LABEL_RANK[band]
    if band == RES_SD:
        # En dessous de 720p on garde la hauteur BRUTE : elle reste
        # discriminante entre SD (576 / 480 / 360). `_resolution_label` la rend
        # telle quelle, sinon l'affichage nierait l'ecart qu'on vient de noter.
        return _to_positive_int(video.get("height")) or None
    # Aucune dimension exploitable : seul un verdict deja ecrit peut trancher.
    return 480 if label in {"sd", "480p"} else None


def _resolution_label(h: Optional[int]) -> str:
    """Decode EXACTEMENT la valeur produite par `_resolution_height`.

    Fix ultra-audit 2026-08-31 (#5). Cette fonction re-classait la valeur recue
    avec des seuils HAUTEUR (`h >= 480 -> "480p"`), alors que `_resolution_height`
    y depose soit une bande canonique (2160/1080/720), soit la hauteur BRUTE
    d'un flux SD. Toute la plage [480..679] s'affichait donc « 480p » : deux SD
    compares -- 720x576 (PAL) contre 720x480 (NTSC) -- sortaient
    « 480p vs 480p » avec un delta de +30, le POIDS PLEIN du critere. La table
    des criteres annoncait une egalite que le verdict contredisait, et l'ecran
    Doublons transforme ce verdict en decision de masse (« Auto-decider tous »),
    les perdants partant en _review/_duplicates_user_decided/.

    L'encodage et le decodage partagent desormais `_CANONICAL_LABEL_RANK` :
    meme etiquette <=> meme valeur comparee <=> delta nul.
    """
    if h is None:
        return "?"
    label = _RANK_TO_CANONICAL_LABEL.get(h)
    return label if label else f"{h}p"


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
    """Rang du codec video, ou `None` si on ne sait pas le situer.

    2026-08-29 : cette fonction rendait `.get(codec, 0)`. Or 0 n'est pas une
    absence de rang, c'est le rang le PLUS BAS — sous `xvid` et `divx`, qui
    valent 1. Tout codec reel absent de la table de dix etiquettes perdait donc
    systematiquement contre un DivX : mesure du jour, `vc1` (Blu-ray),
    `mpeg2video` (DVD), `vp9`, `prores`, `wmv3` et `msmpeg4v3` rendaient tous 0.

    CONSEQUENCE MESUREE, sur un probe construit par `_build_pseudo_probe`
    (le seul producteur de probes de ce comparateur) :

        A = Blu-ray VC-1 1080p 25,0 Mbps 21,0 Go
        B = DivX         1080p  1,5 Mbps  1,3 Go
        -> critere codec : A='?' B='xvid' gagnant=B, -15 points
        -> verdict global : « Garder B, archiver A »

    Le comparateur recommandait d'archiver le Blu-ray au profit du DivX, en
    affichant les deux debits juste a cote. Et « Auto-decider tous » applique ce
    verdict en masse.

    Le remede n'INVENTE aucun rang : donner une place a VC-1 ou MPEG-2 est un
    arbitrage produit, pas une correction de defaut. Il se contente de
    distinguer « inconnu » de « pire » — distinction que la fonction faisait
    deja pour un codec VIDE. `_compare_criterion` rend alors `unknown` a 0
    point, chemin deja exerce par le cas du codec absent.

    NE PAS etendre ce remede au saut du bitrate entre codecs differents : il est
    DELIBERE et garde par `test_different_codec_skip_bitrate`. Comparer 5 Mbps
    de HEVC a 20 Mbps de h264 n'a pas de sens.

    Garde : `tests/test_duplicate_compare.py::CodecHorsTableTests`.
    """
    codec = str(video.get("codec") or "").strip().lower()
    if not codec:
        return None
    return _VIDEO_CODEC_RANK.get(codec)


def _video_codec_label(rank: Optional[int]) -> str:
    return {4: "av1", 3: "hevc", 2: "x264", 1: "xvid"}.get(rank or 0, "?")


def _audio_codec_rank_value(audio: Dict[str, Any]) -> Optional[int]:
    """Rang du codec audio, sur l'etiquette CANONIQUE.

    Fix ultra-audit 2026-08-03. Le pseudo-probe du comparateur est reconstruit
    depuis `metrics.detected.audio_best_codec`, qui porte desormais l'etiquette
    canonique ('dts-hd ma', 'truehd atmos', 'dts:x'). Un lookup exact sur
    `AUDIO_CODEC_RANK` renverrait 0 (sous AAC) pour les etiquettes composees :
    on reutilise donc la meme derivation que le scorer (source unique, cf.
    R8-039 qui avait deja du realigner ces deux fonctions apres une divergence
    constatee sur 113 films).

    2026-09-04 : le repli portait encore `.get(..., 0)`, alors que `0` n'est pas
    une absence de rang mais le rang le PLUS BAS — sous l'AAC et le MP3, qui
    valent 1. C'est mot pour mot le defaut corrige le 2026-08-29 sur la fonction
    SOEUR `_video_codec_rank_value`, vingt lignes plus haut dans ce fichier ;
    l'audio etait le dernier des trois rangs du comparateur a confondre encore
    « inconnu » et « pire » (`_hdr_rank_value` s'abstient deja).

    Tout codec dont l'etiquette canonique n'est ni une cle de `AUDIO_CODEC_RANK`
    ni un de ses alias tombait donc a 0. Cas interne au depot : `mlp` (Meridian
    Lossless Packing) est declare SANS PERTE par `codec_ranks.est_lossless`
    (:171) et n'a d'entree dans aucune des deux tables — le meme codec valait
    donc « lossless » d'un cote et « pire que l'AAC » de l'autre.

    Le remede n'INVENTE aucun rang : donner une place a `mlp` est un arbitrage
    produit, que `codec_ranks` signale lui-meme comme « un ecart a instruire »
    (:148-152). Il se contente de distinguer « inconnu » de « pire ».
    `_compare_criterion` rend alors `unknown` a 0 point — chemin deja exerce par
    le cas du codec ABSENT, juste au-dessus.

    Les deux autres lecteurs de cette fonction coercent deja `or 0` parce qu'ils
    TRIENT (`_best_audio`, `_compute_single_score`) et exigent un ordre total :
    leur comportement est inchange. Seul le critere compare change, et c'est
    celui qui alimente « Auto-decider tous ».

    Garde : `tests/test_duplicate_compare.py::CodecAudioHorsTableTests`.
    """
    if not isinstance(audio, dict) or not audio.get("codec"):
        return None
    canonical = _canonical_audio_codec(audio)
    if not canonical:
        return None
    rank = _AUDIO_CODEC_RANK.get(canonical)
    if rank is None:
        alias = _AUDIO_CANONICAL_RANK_ALIAS.get(canonical)
        rank = _AUDIO_CODEC_RANK.get(alias) if alias else None
    return rank


def _audio_codec_label(rank: Optional[int]) -> str:
    return {5: "truehd", 4: "dts-hd ma", 3: "flac", 2: "ac3", 1: "aac"}.get(rank or 0, "?")


def _channels_value(audio: Dict[str, Any]) -> Optional[int]:
    """Nombre de canaux compare, ou `None` quand le probe n'en porte AUCUN.

    Fix ultra-audit 2026-08-31 (#20). Le site d'appel coercait
    `int(audio.get("channels") or 0)` AVANT `_compare_criterion`, ce qui rendait
    la garde d'abstention de cette derniere (`val is None -> winner='unknown',
    delta=0`) strictement INATTEIGNABLE pour ce critere : une absence de mesure
    devenait un 0, c'est-a-dire la PIRE valeur possible.

    Mesure : A = AC3 5.1, B sans aucune piste audio exploitable ->
    `value_a='5.1'  value_b='?'  winner='a'  points_delta=+10`, soit le poids
    PLEIN du critere en faveur de A, avec « ? » affiche juste a cote. Meme
    signature que `.get(cle, 0)` de `_video_codec_rank_value` (2026-08-29), qui
    distinguait deja « inconnu » de « pire ». Sur un chemin qui deplace des
    fichiers, l'absence de connaissance doit produire un refus de trancher.
    """
    if not isinstance(audio, dict):
        return None
    try:
        ch = int(audio.get("channels") or 0)
    except (TypeError, ValueError):
        return None
    return ch if ch > 0 else None


def _channels_label(ch: Optional[int]) -> str:
    """VN-F.1 : delegue a `codec_ranks.format_audio_channels` (sentinel `?`)."""
    return _format_audio_channels(ch, invalid="?")


def _bitrate_label(br: Optional[int]) -> str:
    if not br or br <= 0:
        return "?"
    # R8-099 (filet F4) : le bitrate est TOUJOURS en bits/s (invariant probe,
    # cf to_optional_bitrate). Division INCONDITIONNELLE /1000 (même anti-pattern
    # bps/kbps que R8-038 pour l'audio) ; l'ancien seuil > 10000 affichait un flux
    # < 10000 bps comme « <N> kbps » au lieu de quelques kbps.
    kbps = br // 1000
    if kbps >= 1000:
        # #826 : la SECONDE division entiere effacait la partie kbps. Cette
        # etiquette est affichee cote a cote dans la table de criteres du
        # comparateur de doublons (duplicate-comparator-modal.js) : 8 500 kbps
        # et 8 000 kbps s'y affichaient tous deux « 8 Mbps », donc le critere
        # « Bitrate » designait un gagnant que ses deux valeurs disaient egales.
        # Une decimale suffit a rendre l'ecart lisible.
        return f"{kbps / 1000:.1f} Mbps"
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


def _human_size(n: int) -> str:
    """AUDIT 2026-06-14 (R6-D) : taille lisible pour la table criteres du
    comparateur (avant : octets bruts type "1610612736")."""
    n = int(n or 0)
    if n <= 0:
        return "?"
    units = ["o", "Ko", "Mo", "Go", "To"]
    size = float(n)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{int(size)} {units[idx]}" if idx == 0 else f"{size:.1f} {units[idx]}"


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
