"""Hierarchies centralisees des codecs audio et video.

Ce module centralise les rangs des codecs utilises dans :
- audio_analysis.py        (badge audio, classification substring + label)
- perceptual/audio_perceptual.py (selection meilleure piste, substring sans label)
- duplicate_compare.py     (comparaison qualite, lookup exact par dict)

Les structures sont volontairement differentes parce que les usages le sont :
- AUDIO_CODEC_RANK_PATTERNS : liste (pattern, rang, label) pour matching substring
  (utilise par audio_analysis._classify_codec et audio_perceptual.select_best_audio_track)
- AUDIO_CODEC_RANK          : dict {codec_exact: rang} pour lookup exact via .get()
  (utilise par duplicate_compare._audio_codec_rank_value)

Note : les rangs entre les deux structures divergent volontairement.
Dans la comparaison de doublons (duplicate_compare), atmos et truehd partagent
le meme rang (5) car un fichier "atmos" est techniquement un truehd avec
metadonnees JOC, alors que dans le badge audio (audio_analysis), atmos a un
rang superieur (6) pour distinguer visuellement le badge utilisateur.
De meme, eac3 vaut 3 dans le ranking badge (au-dessus d'ac3) mais 2 dans le
ranking duplicate (a egalite avec ac3) pour eviter de favoriser eac3 sur ac3
lors d'une comparaison de qualite reelle.
"""

from __future__ import annotations

from typing import List, Tuple

__all__ = [
    "AUDIO_CODEC_RANK_PATTERNS",
    "AUDIO_CODEC_RANK",
]


# ---------------------------------------------------------------------------
# Audio codec ranking — matching par substring (pour badge + selection piste)
# ---------------------------------------------------------------------------
# Format : (pattern_substring, rang, label_canonique)
# Ordre : priorite decroissante (le premier match l'emporte)
# Atmos(6) > TrueHD(5) > DTS-HD MA(4) > EAC3/FLAC(3) > DTS/AC3(2) > AAC/MP3/Opus(1)

AUDIO_CODEC_RANK_PATTERNS: List[Tuple[str, int, str]] = [
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


# ---------------------------------------------------------------------------
# Audio codec ranking — lookup exact par dict (pour comparaison de doublons)
# ---------------------------------------------------------------------------
# Format : {codec_exact: rang}
# TrueHD/Atmos partagent rang 5 (Atmos = TrueHD + JOC en pratique).
# EAC3 partage rang 2 avec AC3/DTS pour ne pas le favoriser injustement.

AUDIO_CODEC_RANK: dict[str, int] = {
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
