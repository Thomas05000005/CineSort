# Fix audit 2026-05-25 (v1.5.5) Vague K : parser professionnel des noms de release
# pour servir de fallback au scoring quand le probe est PARTIAL/FAILED.
"""Parse les noms de fichiers de release scene pour extraire les specs.

Inspire par les conventions de release groups (scene, P2P, encodages perso).
Patterns detectes :
- Resolution : 2160p, 4K, UHD, 1080p, 720p, 480p, 576p, SD
- Codec : x265, x264, H.265, H.264, HEVC, AVC, AV1, VP9, MPEG-2
- Bit depth : 10bit, 10-bit, 12bit
- HDR : DV, Dolby Vision, DOVI, HDR10+, HDR10, HDR, HLG
- Source : BluRay, BDRip, BRRip, WEB-DL, WEBRip, HDTV, REMUX, UHD-BD
- Audio : DTS-HD, DTS-X, DTS:X, TrueHD, Atmos, FLAC, AC3, DD5.1, DDP5.1, EAC3, AAC
- Channels : 7.1, 5.1, 2.0, 2.1
- Release group : -GROUP at end
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class ReleaseNameInfo:
    """Specs extraites du nom de fichier de release."""

    resolution_hint: str = ""  # "2160p", "1080p", ...
    width_hint: int = 0
    height_hint: int = 0
    codec_hint: str = ""  # "hevc", "h264", "av1"
    bit_depth_hint: int = 0  # 8, 10, 12
    hdr_hint: str = ""  # "dv", "hdr10_plus", "hdr10", "hlg", "sdr"
    dolby_vision_profile_hint: int = 0  # 5, 7, 8 si detectable
    source_hint: str = ""  # "bluray", "remux", "webdl", "webrip", "hdtv"
    # #771 : UNIQUEMENT des codecs PORTEURS. "atmos" / "dts_x" sont des couches
    # objet posees SUR un codec (TrueHD, EAC3, DTS-HD MA) et n'ont jamais leur
    # place ici : elles ont leurs propres drapeaux ci-dessous.
    audio_codec_hint: str = ""  # "truehd", "dts_hd_ma", "eac3", "ac3", "aac"
    audio_channels_hint: str = ""  # "7.1", "5.1", "2.0"
    audio_is_atmos: bool = False
    audio_is_dts_x: bool = False
    audio_is_lossless: bool = False  # TrueHD, FLAC, DTS-HD MA, PCM
    release_group: str = ""
    extras: List[str] = field(default_factory=list)  # autres tags
    # Fix audit 2026-05-26 (v1.5.6) Vague L : flag CAM/TS/SCREENER detecte
    # INDEPENDAMMENT de source_hint. Une release "X.CAM.2160p.REMUX" doit
    # rester marquee CAM meme si un token source superieur (REMUX/BluRay)
    # coexiste : source_hint s'arrete au premier match et ratait le CAM.
    is_cam: bool = False
    cam_token: str = ""  # "cam", "ts", "telesync", "screener", "tc"


# Ordre important : motifs plus specifiques en premier.
#
# Le `HD` du motif 720p exige des separateurs NON-tiret des deux cotes.
# `\bHD\b(?!R)` ne suffisait pas : un tiret est une frontiere de mot, donc le
# `HD` de `DTS-HD.MA` etait encadre de deux `\b`, et le lookahead ne le rejetait
# pas (le caractere suivant est un point). Toute release sans token de
# resolution mais avec une piste `DTS-HD*` — ou un `HD-DVD` — ressortait alors en
# 720p / 1280x720, valeurs inventees. Mesure :
#
#     Heat.1995.REMUX.BluRay.DTS-HD.MA.5.1-FraMeSToR.mkv  ->  720p  1280x720
#
# `TrueHD`, `HDR` et `HDTV` etaient deja exclus (pas de frontiere, ou lookahead).
# La classe `[\w-]` ajoute le seul cas qui manquait : le tiret. Un `Movie-HD-GRP`
# perd son indice, ce qui est le sens SUR — ne rien deduire plutot que deduire
# faux, d'autant que ce `HD`-la est indiscernable d'un nom de groupe.
_PATTERNS_RESOLUTION = [
    (r"\b2160p\b|\b4[Kk]\b|\bUHD\b", "2160p", 3840, 2160),
    (r"\b1080[pi]\b|\bFHD\b", "1080p", 1920, 1080),
    (r"\b720[pi]\b|(?<![\w-])HD(?![\w-])", "720p", 1280, 720),
    (r"\b576[pi]\b", "576p", 720, 576),
    (r"\b480[pi]\b", "480p", 720, 480),
]

_PATTERNS_CODEC = [
    (r"\b[xh]\.?265\b|\bHEVC\b", "hevc"),
    (r"\b[xh]\.?264\b|\bAVC\b", "h264"),
    (r"\bAV1\b", "av1"),
    (r"\bVP9\b", "vp9"),
    (r"\bMPEG-?2\b", "mpeg2"),
    (r"\bXviD\b|\bDivX\b", "xvid"),
]

_PATTERN_BIT_DEPTH = re.compile(r"\b(8|10|12)[ \-]?bits?\b", re.IGNORECASE)

# DV doit etre verifie avant HDR10 (DV implique souvent HDR10 en plus).
#
# Le lookahead `(?!\.?\s*[Dd])` a ete RETIRE. Il se voulait un garde « pas DVD »,
# mais `\bDV\b` en tient DEJA lieu : dans `DVD`, `DVDRip`, `DVDScr` ou `HDV`, le
# caractere qui suit `DV` est un caractere de mot, donc il n'y a AUCUNE frontiere
# a cet endroit et `\bDV\b` ne matche pas. Le lookahead n'ecartait donc rien
# qu'il fallait ecarter — il ecartait `DV` suivi d'un token commencant par `D`,
# c'est-a-dire les formes les plus repandues du nom de release. Mesure :
#
#   Dune.2021.2160p.WEB-DL.DV.DDP5.1.H265-GRP.mkv          ->  hdr_hint = ''
#   Heat.1995.2160p.REMUX.DV.DTS-HD.MA.5.1-FraMeSToR.mkv    ->  hdr_hint = ''
#   Movie.2021.2160p.DV.HDR10.DDP5.1-GRP.mkv                ->  hdr_hint = 'dv'
#
# Le troisieme passe parce que le token suivant commence par `H` : c'est
# exactement la forme du seul test qui couvrait ce motif
# (`test_parse_uhd_dv_hdr_bluray_dts_hd_x265`, « 2160p DV HDR BluRay »), d'ou un
# vert permanent sur une detection qui ne marchait qu'une fois sur deux.
#
# Consequence en aval : `quality_score._merge_probe_with_name_hints` ne pose
# `hdr_dolby_vision` que si `hdr_hint == "dv"`. Sur un probe PARTIAL/FAILED — le
# seul cas ou ce parser sert — le film perdait donc tout l'apport HDR de son
# score.
_PATTERNS_HDR = [
    (r"\bDolby[\. ]?Vision\b|\bDoVi\b|\bDOVI\b", "dv"),
    # Le lookahead restant a ete retire par le MEME argument que celui qui motive
    # ce correctif : `\b` en tient deja lieu, et il est STRICTEMENT plus fort —
    # la frontiere de mot exige un non-mot, donc exclut aussi `_`, que
    # `(?![A-Za-z0-9])` autorisait. Verifie par comparaison exhaustive des deux
    # motifs sur un caractere avant et un caractere apres : 15 561 cas, ZERO
    # divergence. Le garder aurait laisse dans le code un garde mort, exactement
    # le defaut que cette PR corrige.
    (r"\bDV\b", "dv"),  # `\bDV\b` exclut deja DVD/DVDRip/HDV
    (r"\bHDR10\+|\bHDR10P\b|\bHDR\+\b", "hdr10_plus"),
    (r"\bHDR10\b|\bHDR\b", "hdr10"),
    (r"\bHLG\b", "hlg"),
]

_PATTERNS_SOURCE = [
    (r"\bREMUX\b", "remux"),
    (r"\bUHD-?BD\b|\bUHDBD\b", "bluray"),
    (r"\bBlu-?Ray\b|\bBDRip\b|\bBRRip\b|\bBDR\b|\bBD-?Rip\b", "bluray"),
    (r"\bWEB-?DL\b|\bWEB-?DLRip\b", "webdl"),
    (r"\bWEBRip\b|\bWEB-?Rip\b|\bWEB\b", "webrip"),
    (r"\bHDTV\b|\bPDTV\b|\bDSR\b", "hdtv"),
    (r"\bDVDRip\b|\bDVD\b|\bDVD-?R\b|\bDVDR\b", "dvd"),
    (r"\bCAM\b|\bTS\b|\bTC\b|\bSCR\b", "cam"),
]

# Ordre important : codecs/tags specifiques en premier (atmos avant truehd, etc.)
# Le flag final indique si le codec est lossless (lecture stricte).
_PATTERNS_AUDIO = [
    (r"\bAtmos\b", "atmos", True),
    (r"\bDTS[: \-]?X\b", "dts_x", True),
    (r"\bDTS-?HD\.?MA\b|\bDTS-?HD\sMA\b", "dts_hd_ma", True),
    (r"\bDTS-?HD\.?HRA?\b|\bDTS-?HD\sHRA?\b", "dts_hd_hra", False),
    (r"\bDTS-?HD\b", "dts_hd", False),
    (r"\bTrueHD\b|\bTrue-?HD\b", "truehd", True),
    (r"\bFLAC\b", "flac", True),
    (r"\bPCM\b|\bLPCM\b", "pcm", True),
    (r"\bDTS\b", "dts", False),
    (r"\bE-?AC-?3\b|\bDDP[0-9]?\b|\bDolby\sDigital\sPlus\b", "eac3", False),
    (r"\bAC-?3\b|\bDD[0-9]?\b|\bDolby\sDigital\b", "ac3", False),
    (r"\bAAC\b", "aac", False),
    (r"\bMP3\b", "mp3", False),
]

# Fix audit 2026-05-26 (v1.5.6) Vague L : detection CAM/TS/SCREENER INDEPENDANTE
# de source_hint. Liste de tokens "qualite de captation degradee" avec leur
# label normalise. Detecte meme si un token source superieur coexiste.
# \bTS\b et \bTC\b sont risques (faux positifs : "TS" peut etre une initiale)
# mais en pratique sur un nom de release ils signalent TeleSync/TeleCine.
_PATTERNS_CAM = [
    (r"\bTELESYNC\b", "telesync"),
    (r"\bTELECINE\b", "telecine"),
    (r"\bSCREENER\b|\bSCR\b|\bDVDSCR\b|\bBDSCR\b", "screener"),
    (r"\bCAMRIP\b|\bHDCAM\b|\bCAM\b", "cam"),
    (r"\bHDTS\b|\bTS\b", "ts"),
    (r"\bTC\b", "tc"),
    (r"\bWORKPRINT\b|\bWP\b", "workprint"),
]


_PATTERN_CHANNELS = re.compile(r"\b(?:7\.1|5\.1|5\.0|2\.1|2\.0|1\.0|6\.1)\b")

# Release group : tag final apres dernier tiret. Tolere extension de fichier.
_PATTERN_GROUP = re.compile(r"-([A-Za-z0-9_]+)(?:\.[A-Za-z0-9]{2,4})?$")


def parse_release_name(name: str) -> ReleaseNameInfo:
    """Parse un nom de fichier de release et extrait toutes les specs.

    Tolerant aux casses et separateurs (espaces, points, tirets). Retourne
    un ReleaseNameInfo vide si name est vide ou None.
    """
    info = ReleaseNameInfo()
    if not name:
        return info

    text = str(name)

    # Resolution
    for pattern, label, w, h in _PATTERNS_RESOLUTION:
        if re.search(pattern, text, re.IGNORECASE):
            info.resolution_hint = label
            info.width_hint = w
            info.height_hint = h
            break

    # Codec
    for pattern, codec in _PATTERNS_CODEC:
        if re.search(pattern, text, re.IGNORECASE):
            info.codec_hint = codec
            break

    # Bit depth (explicite ou heuristique)
    bd_match = _PATTERN_BIT_DEPTH.search(text)
    if bd_match:
        info.bit_depth_hint = int(bd_match.group(1))
    elif info.codec_hint in {"hevc", "av1"} and info.resolution_hint == "2160p":
        # Heuristique : 4K HEVC/AV1 sont quasi systematiquement encodes en 10-bit.
        info.bit_depth_hint = 10

    # HDR (DV en premier, puis HDR10+ avant HDR10)
    for pattern, hdr in _PATTERNS_HDR:
        if re.search(pattern, text, re.IGNORECASE):
            info.hdr_hint = hdr
            break

    # DV profile (5, 7, 8) - rare dans le nom mais parfois present
    dv_profile = re.search(r"DV\s*P?(?:rofile)?\s*(5|7|8)", text, re.IGNORECASE)
    if dv_profile:
        info.dolby_vision_profile_hint = int(dv_profile.group(1))

    # AUDIT 2026-06-10/11 (REAL 2/2 + R2.3) : retirer l'extension de fichier finale
    # AVANT la detection source ET cam. Le caller passe le nom AVEC extension
    # (str(row.video)) et `\bTS\b` matchait l'extension `.ts` (MPEG-TS legitime),
    # dans _PATTERNS_CAM (is_cam=True -> tier cape Bronze + facteur -30) ET dans
    # _PATTERNS_SOURCE (source_hint="cam"). Un vrai token TS/TC de release est en
    # milieu de nom, jamais l'extension finale.
    text_no_ext = re.sub(r"\.[A-Za-z0-9]{1,4}$", "", text)

    # Source
    for pattern, source in _PATTERNS_SOURCE:
        if re.search(pattern, text_no_ext, re.IGNORECASE):
            info.source_hint = source
            break

    # Fix audit 2026-05-26 (v1.5.6) Vague L : detection CAM/TS/SCREENER
    # INDEPENDANTE. Contrairement a source_hint (qui break au premier match et
    # ratait CAM si REMUX/BluRay precedait), on scanne TOUTE la liste CAM et on
    # garde le premier token degrade trouve. Si un CAM est detecte, on force
    # aussi source_hint="cam" : un fichier CAM EST une captation degradee, peu
    # importe le mensonge "REMUX/BluRay" colle dans le nom.
    for pattern, cam_tok in _PATTERNS_CAM:
        if re.search(pattern, text_no_ext, re.IGNORECASE):
            info.is_cam = True
            info.cam_token = cam_tok
            info.source_hint = "cam"
            break

    # Audio : premier match wins pour codec/lossless, mais atmos/dts_x sont
    # cumulatifs (peuvent coexister avec TrueHD ou DTS-HD MA).
    #
    # #771 : "Atmos" et "DTS:X" sont des COUCHES objet, pas des codecs porteurs.
    # Elles ne prennent donc PAS le slot `audio_codec_hint`. Avant ce correctif
    # elles le prenaient — et comme "atmos" est le PREMIER motif de la liste,
    # deux consequences :
    #   1. la branche de repli atmos -> truehd (plus bas) etait INATTEIGNABLE,
    #      `audio_codec_hint` valant deja "atmos" en sortie de boucle ;
    #   2. pire, une release lossy typique du web
    #      ("Dune.Part.Two.2024.2160p.WEB-DL.DDP5.1.Atmos.H.265-FLUX") ressortait
    #      en codec="atmos" + audio_is_lossless=True, donc mappee sur TrueHD par
    #      `quality_score._NAME_AUDIO_CODEC_TO_PROBE` : un EAC3 lossy score comme
    #      un TrueHD lossless. Le porteur reel (eac3) est desormais retenu.
    for pattern, codec, lossless in _PATTERNS_AUDIO:
        if not re.search(pattern, text, re.IGNORECASE):
            continue
        if codec == "atmos":
            info.audio_is_atmos = True
            continue
        if codec == "dts_x":
            info.audio_is_dts_x = True
            continue
        if not info.audio_codec_hint:
            info.audio_codec_hint = codec
            info.audio_is_lossless = lossless

    # Si atmos detecte mais aucun codec porteur trouve, defaulter sur truehd
    # (atmos sans precision est typiquement TrueHD Atmos). Desormais ATTEIGNABLE.
    if info.audio_is_atmos and not info.audio_codec_hint:
        info.audio_codec_hint = "truehd"
        info.audio_is_lossless = True

    # Channels
    ch_match = _PATTERN_CHANNELS.search(text)
    if ch_match:
        info.audio_channels_hint = ch_match.group(0)

    # Release group
    # On nettoie d'abord l'extension de fichier pour eviter qu'elle pollue.
    name_no_ext = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", text)
    g_match = _PATTERN_GROUP.search(name_no_ext)
    if g_match:
        candidate = g_match.group(1)
        # Eviter de prendre un mot generique comme "1080p" si pattern attrape trop.
        # Le group doit etre alphanumeric, longueur >= 2.
        if len(candidate) >= 2 and not candidate.isdigit():
            info.release_group = candidate

    return info
