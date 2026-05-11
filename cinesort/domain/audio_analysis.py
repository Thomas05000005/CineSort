"""Analyse audio approfondie — format, canaux, commentaire, doublons.

Analyse les pistes audio d'un fichier video pour produire un badge
audio hierarchique et detecter les pistes commentaire / doublons suspects.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# --- Hierarchie des formats audio (rang → label) --------------------------
# Atmos(6) > TrueHD(5) > DTS-HD MA(4) > EAC3/FLAC(3) > DTS/AC3(2) > AAC/MP3(1)

_CODEC_RANK: List[Tuple[str, int, str]] = [
    # (pattern_substring, rang, label) — ordre de priorite decroissant
    ("atmos", 6, "Atmos"),  # Atmos dans codec OU title
    ("truehd", 5, "TrueHD"),
    ("dts-hd", 4, "DTS-HD MA"),
    ("dtshd", 4, "DTS-HD MA"),
    ("eac3", 3, "EAC3"),
    ("e-ac-3", 3, "EAC3"),
    ("flac", 3, "FLAC"),
    ("dts", 2, "DTS"),
    ("ac3", 2, "AC3"),
    ("a_ac3", 2, "AC3"),
    ("aac", 1, "AAC"),
    ("mp3", 1, "MP3"),
    ("opus", 1, "Opus"),
]

# Tier par rang
_TIER_MAP = {6: "premium", 5: "premium", 4: "bon", 3: "bon", 2: "standard", 1: "basique", 0: "basique"}

# Paires codec compat normales (codec_a + codec_b même langue = pas un doublon)
_COMPAT_PAIRS = frozenset(
    {
        ("truehd", "ac3"),
        ("ac3", "truehd"),
        ("truehd", "aac"),
        ("aac", "truehd"),
        ("dts-hd", "dts"),
        ("dts", "dts-hd"),
        ("dtshd", "dts"),
        ("dts", "dtshd"),
        ("eac3", "ac3"),
        ("ac3", "eac3"),
        ("flac", "aac"),
        ("aac", "flac"),
    }
)


def analyze_audio(audio_tracks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyse les pistes audio et retourne un rapport detaille."""
    if not audio_tracks:
        return {
            "best_format": "Aucun",
            "best_channels": "—",
            "badge_label": "Aucun audio",
            "badge_tier": "basique",
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
        "badge_tier": _TIER_MAP.get(best_rank, "basique"),
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

    # DTS-HD MA specifique (avant le match DTS generique)
    if "dts-hd" in codec or "dtshd" in codec:
        if "ma" in codec:
            return 4, "DTS-HD MA"
        return 4, "DTS-HD MA"  # dts-hd = presque toujours MA

    for pattern, rank, label in _CODEC_RANK:
        if pattern == "atmos":
            continue  # Deja traite ci-dessus
        if pattern in codec:
            return rank, label

    return 0, "Inconnu"


def _channels_label(channels: int) -> str:
    """Formate le nombre de canaux en label lisible."""
    if channels >= 8:
        return "7.1"
    if channels >= 6:
        return "5.1"
    if channels >= 2:
        return "2.0"
    if channels == 1:
        return "1.0"
    return "—"


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
        # Verifier si c'est une paire compat normale
        if len(codecs) == 2:
            pair = (codecs[0], codecs[1])
            if pair in _COMPAT_PAIRS:
                continue
        # Compter les occurrences de chaque codec
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
