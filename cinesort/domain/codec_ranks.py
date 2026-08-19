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

VN-F.1 (2026-06-01) : `format_audio_channels` centralise les 3 implementations
divergentes de `_channels_label` (duplicate_compare/naming/audio_analysis). Le
parametre `invalid` permet de preserver les sentinels heterogenes (`"?"` pour
les comparaisons UI, `""` pour interpolation template, `"—"` pour badges).
"""

from __future__ import annotations

from typing import Any, List, Tuple

__all__ = [
    "AUDIO_CODEC_RANK_PATTERNS",
    "AUDIO_CODEC_RANK",
    "format_audio_channels",
]


# ---------------------------------------------------------------------------
# Audio codec ranking — matching par substring (pour badge + selection piste)
# ---------------------------------------------------------------------------
# Format : (pattern_substring, rang, label_canonique)
# Ordre : priorite decroissante (le premier match l'emporte)
# Atmos(6) > TrueHD(5) > DTS-HD MA(4) > EAC3/FLAC/PCM(3) > DTS/DTS-HD HRA/AC3(2) > AAC/MP3/Opus(1)
#
# #807 — DTS-HD HRA (High Resolution Audio) est LOSSY, contrairement a DTS-HD MA
# (Master Audio, lossless). Les motifs HRA sont places AVANT `dts-hd`/`dtshd`
# parce que les deux consommateurs s'arretent au PREMIER motif qui matche : sans
# eux, `dts-hd hra` matchait `dts-hd` et heritait du rang 4 (tier gold, reserve
# au lossless) et surtout du LABEL « DTS-HD MA », faux. Le rang 2 retenu n'est
# pas un arbitrage nouveau : c'est celui que `quality_score` applique deja a HRA
# en trois endroits (`_AUDIO_CANONICAL_RANK_ALIAS['dts-hd hra'] = 'dts'`,
# `_hierarchy_audio_codec_token`, `_is_premium_multichannel_codec`).
#
# PCM / LPCM : le codec n'avait AUCUNE entree dans les deux tables, donc rang 0 —
# soit SOUS l'AAC (1) et le MP3 (1). C'est la meme signature que les etiquettes
# composees de l'ultra-audit 2026-08-03 et que les formes hyphenees de la revue
# PR#854, toutes deux corrigees par un alias. Le rang 3 n'est pas un arbitrage
# nouveau : c'est celui de FLAC, l'autre lossless de ces tables, et
# `release_name_parser._PATTERNS_AUDIO` declare deja PCM/LPCM `lossless=True`.
# Le motif couvre les variantes ffprobe (`pcm_s16le`, `pcm_s24le`, `pcm_bluray`,
# `pcm_dvd`), le `Format` MediaInfo (`PCM`) et l'etiquette que le fallback par le
# nom synthetise lui-meme (`_NAME_AUDIO_CODEC_TO_PROBE["pcm"] = "pcm"`).

AUDIO_CODEC_RANK_PATTERNS: List[Tuple[str, int, str]] = [
    ("atmos", 6, "Atmos"),  # Atmos dans codec OU title
    ("truehd", 5, "TrueHD"),
    ("dts-hd hra", 2, "DTS-HD HRA"),  # lossy — AVANT le `dts-hd` generique
    ("dtshd hra", 2, "DTS-HD HRA"),
    ("dts-hd", 4, "DTS-HD MA"),
    ("dtshd", 4, "DTS-HD MA"),
    ("eac3", 3, "EAC3"),
    ("e-ac-3", 3, "EAC3"),
    ("flac", 3, "FLAC"),
    ("pcm", 3, "PCM"),  # lossless non compresse — couvre lpcm / pcm_s24le / pcm_bluray
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
    # PCM : lossless non compresse, meme rang que FLAC (cf. le commentaire de
    # AUDIO_CODEC_RANK_PATTERNS). Ce lookup est EXACT : les variantes ffprobe
    # (`pcm_s24le`, `pcm_bluray`) sont ramenees a "pcm" par
    # `quality_score._canonical_audio_codec` avant d'arriver ici.
    "pcm": 3,
    "dts": 2,
    "ac3": 2,
    "eac3": 2,
    "aac": 1,
    "mp3": 1,
    "opus": 1,
}


# ---------------------------------------------------------------------------
# Formatage canaux audio — sortie lisible (badge UI, comparaison, naming)
# ---------------------------------------------------------------------------


def format_audio_channels(
    channels: Any,
    *,
    invalid: str = "?",
    mono_label: str = "",
    bucketize: bool = False,
) -> str:
    """Formate un nombre de canaux audio en label lisible.

    Args:
        channels: nombre de canaux (int, str, None toleres).
        invalid: sentinel renvoye si `channels` est nul, negatif ou invalide.
            Les 3 appelants historiques utilisent des sentinels differents :
            - `"?"` dans duplicate_compare (comparaison UI)
            - `""` dans naming (interpolation template)
            - `"—"` dans audio_analysis (badge audio)
        mono_label: label renvoye pour `channels == 1` (defaut `""` comme avant
            la centralisation pour duplicate_compare/naming ; audio_analysis
            passe `"1.0"`). Si vide, retourne `invalid` pour `channels == 1`.
        bucketize: si True (mode badge audio_analysis), regroupe les valeurs
            non-canoniques sur le bucket inferieur (>=8 -> "7.1", >=6 -> "5.1",
            >=2 -> "2.0"). Si False (mode strict duplicate_compare/naming),
            renvoie `"{n}ch"` pour 3,4,5,7,9+ canaux.

    Returns:
        - `"2.0"`, `"5.1"`, `"7.1"` pour les configurations canoniques.
        - `"{n}ch"` pour les autres comptes valides quand `bucketize=False`.
        - bucket le plus proche par valeur inferieure quand `bucketize=True`.
        - `invalid` pour les valeurs <= 0 ou non parsables.
    """
    try:
        ch = int(channels or 0)
    except (TypeError, ValueError):
        return invalid
    if ch <= 0:
        return invalid
    if ch == 1:
        return mono_label or invalid
    if bucketize:
        if ch >= 8:
            return "7.1"
        if ch >= 6:
            return "5.1"
        if ch >= 2:
            return "2.0"
        # ch == 1 deja traite plus haut ; fallback defensif
        return mono_label or invalid
    if ch == 2:
        return "2.0"
    if ch == 6:
        return "5.1"
    if ch == 8:
        return "7.1"
    return f"{ch}ch"
