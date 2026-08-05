"""Analyse audio approfondie — format, canaux, commentaire, doublons.

Analyse les pistes audio d'un fichier video pour produire un badge
audio hierarchique et detecter les pistes commentaire / doublons suspects.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from cinesort.domain.codec_ranks import (
    AUDIO_CODEC_RANK_PATTERNS as _CODEC_RANK,
)
from cinesort.domain.codec_ranks import (
    format_audio_channels as _format_audio_channels,
)

logger = logging.getLogger(__name__)

# --- Hierarchie des formats audio (rang → label) --------------------------
# Atmos(6) > TrueHD(5) > DTS-HD MA(4) > EAC3/FLAC(3) > DTS/DTS-HD HRA/AC3(2) > AAC/MP3(1)
# Definition centralisee dans cinesort.domain.codec_ranks._CODEC_RANK reste
# l'alias local utilise par _classify_codec.

# Tier par rang — labels canoniques (compatibles badge.js / dashboard)
# Atmos/TrueHD = platinum, DTS-HD MA/EAC3/FLAC = gold, DTS/AC3 = silver, AAC/MP3/inconnu = bronze
_TIER_MAP = {6: "platinum", 5: "platinum", 4: "gold", 3: "gold", 2: "silver", 1: "bronze", 0: "bronze"}


def analyze_audio(audio_tracks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyse les pistes audio et retourne un rapport detaille."""
    if not audio_tracks:
        return {
            "best_format": "Aucun",
            "best_channels": "—",
            "badge_label": "Aucun audio",
            "badge_tier": "bronze",
            "tracks_count": 0,
            "has_commentary": False,
            "duplicate_tracks": [],
            "languages": [],
        }

    best_rank = 0
    best_label = "Inconnu"
    best_channels = 0
    has_commentary = False
    languages: List[str] = []

    for track in audio_tracks:
        codec = str(track.get("codec") or "").strip().lower()
        title = str(track.get("title") or "").strip().lower()
        channels = int(track.get("channels") or 0)
        lang = str(track.get("language") or "").strip().lower()
        is_comm = bool(track.get("is_commentary"))

        if is_comm:
            has_commentary = True

        if lang and lang not in languages:
            languages.append(lang)

        # Determiner le rang de cette piste
        rank, label = _classify_codec(codec, title)
        if rank > best_rank or (rank == best_rank and channels > best_channels):
            best_rank = rank
            best_label = label
            best_channels = channels

    # Doublons suspects
    duplicate_tracks = _find_duplicate_tracks(audio_tracks)

    # Coherence des tags langue
    missing_lang_count, incomplete_langs = _check_language_coherence(audio_tracks)

    ch_label = _channels_label(best_channels)
    logger.debug(
        "audio: best=%s (%s), commentary=%s, dupes=%d", best_label, ch_label, has_commentary, len(duplicate_tracks)
    )
    return {
        "best_format": best_label,
        "best_channels": ch_label,
        "badge_label": f"{best_label} {ch_label}".strip(),
        "badge_tier": _TIER_MAP.get(best_rank, "bronze"),
        "tracks_count": len(audio_tracks),
        "has_commentary": has_commentary,
        "duplicate_tracks": duplicate_tracks,
        "languages": languages,
        "missing_language_count": missing_lang_count,
        "incomplete_languages": incomplete_langs,
    }


def _classify_codec(codec: str, title: str) -> Tuple[int, str]:
    """Determine le rang et le label d'un codec audio."""
    combined = f"{codec} {title}"

    # Cas special Atmos : c'est du TrueHD avec metadonnees JOC
    if "truehd" in codec and "atmos" in combined:
        return 6, "Atmos"

    # #807 — le cas special « DTS-HD » a disparu : il retournait exactement ce
    # que la table `_CODEC_RANK` produit deja (les motifs `dts-hd` / `dtshd` y
    # precedent `dts`), donc il ne faisait que court-circuiter la table. Depuis
    # que celle-ci distingue DTS-HD HRA (lossy, rang 2) de DTS-HD MA (lossless,
    # rang 4), ce court-circuit renvoyait le LABEL FAUX « DTS-HD MA » et le tier
    # gold pour un flux HRA. Une seule source de verite : la table.
    for pattern, rank, label in _CODEC_RANK:
        if pattern == "atmos":
            continue  # Deja traite ci-dessus
        if pattern in codec:
            return rank, label

    return 0, "Inconnu"


def _channels_label(channels: int) -> str:
    """Formate le nombre de canaux en label lisible.

    VN-F.1 : delegue a `codec_ranks.format_audio_channels` (badge tier, sentinel
    `—`, mode `bucketize=True` qui aligne 3/4/5 -> "2.0", 7 -> "5.1", 9+ -> "7.1",
    et `mono_label="1.0"` pour l'historique badge).
    """
    return _format_audio_channels(channels, invalid="—", mono_label="1.0", bucketize=True)


def _find_duplicate_tracks(tracks: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Detecte les pistes en double suspectes (meme langue, meme codec, 2+ occurrences).

    Ignore les paires normales de compatibilite (TrueHD + AC3 fallback).
    """
    # Grouper par langue
    by_lang: Dict[str, List[str]] = {}
    for t in tracks:
        if bool(t.get("is_commentary")):
            continue  # Ignorer les pistes commentaire
        lang = str(t.get("language") or "unknown").strip().lower()
        codec = str(t.get("codec") or "").strip().lower()
        if not codec:
            continue
        by_lang.setdefault(lang, []).append(codec)

    duplicates: List[Dict[str, str]] = []
    for lang, codecs in by_lang.items():
        if len(codecs) <= 1:
            continue
        # Un doublon suspect = un MEME codec present 2+ fois sur la meme langue.
        # Deux codecs differents (ex. TrueHD + AC3 fallback) donnent counts={a:1,b:1}
        # et ne sont donc jamais flagues : aucune liste d'exemption necessaire.
        counts: Dict[str, int] = {}
        for c in codecs:
            counts[c] = counts.get(c, 0) + 1
        for codec_name, count in counts.items():
            if count >= 2:
                duplicates.append({"language": lang, "codec": codec_name, "count": str(count)})

    return duplicates


# --- Valeurs traitees comme absence de langue ---
_MISSING_LANG_VALUES = frozenset({"", "und", "unk", "unknown", "none"})


def _check_language_coherence(tracks: List[Dict[str, Any]]) -> Tuple[int, bool]:
    """Verifie la coherence des tags langue sur les pistes audio.

    Retourne (missing_count, incomplete) :
    - missing_count : nombre de pistes sans langue valide (hors commentaires)
    - incomplete : True si certaines pistes sont taguees et d'autres non (hors commentaires)
    """
    tagged = 0
    missing = 0
    for t in tracks:
        if bool(t.get("is_commentary")):
            continue
        lang = str(t.get("language") or "").strip().lower()
        if lang in _MISSING_LANG_VALUES:
            missing += 1
        else:
            tagged += 1
    total = tagged + missing
    incomplete = total > 0 and missing > 0 and tagged > 0
    return missing, incomplete
