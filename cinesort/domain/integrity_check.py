"""Verification d'integrite des fichiers video — header magic bytes.

Verifie que les premiers octets du fichier correspondent au format attendu
d'apres l'extension. Detecte les fichiers tronques, corrompus ou renommes.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

# Nombre d'octets a lire pour la verification
_HEADER_READ_SIZE = 1024

# --- Magic bytes par format -----------------------------------------------

# MKV / WebM : EBML header
_MAGIC_MKV = bytes([0x1A, 0x45, 0xDF, 0xA3])

# MP4 / MOV : "ftyp" a l'offset 4
_MAGIC_FTYP = b"ftyp"
_MAGIC_FTYP_OFFSET = 4

# AVI : "RIFF" a l'offset 0 + "AVI " a l'offset 8
_MAGIC_RIFF = b"RIFF"
_MAGIC_AVI = b"AVI "
_MAGIC_AVI_OFFSET = 8

# WMV / ASF : 16 octets d'en-tete
_MAGIC_WMV = bytes([0x30, 0x26, 0xB2, 0x75, 0x8E, 0x66, 0xCF, 0x11])

# MPEG-TS : sync byte 0x47 repete a intervalle regulier.
#
# Ni la taille de paquet ni le decalage initial ne sont garantis :
#  - 188 : MPEG-2 TS nu (ISO/IEC 13818-1), sync a l'offset 0 ;
#  - 192 : source packet BDAV/M2TS = TP_extra_header de 4 octets (2 bits de
#          copy permission + horodatage d'arrivee 30 bits a 27 MHz) SUIVI du
#          paquet TS de 188 octets. C'est le conteneur des Blu-ray et des
#          camescopes AVCHD, donc de TOUT `.m2ts` / `.mts` : le sync y est a
#          l'offset 4, pas 0 ;
#  - 204 : TS + 16 octets de parite Reed-Solomon (captures DVB).
# Ce sont exactement les trois tailles que FFmpeg sonde dans
# libavformat/mpegts.c (TS_PACKET_SIZE / TS_DVHS_PACKET_SIZE /
# TS_FEC_PACKET_SIZE) ; son `analyze()` totalise les sync par offset
# `i % packet_size`, c.-a-d. cherche lui aussi le decalage initial.
_TS_SYNC_BYTE = 0x47
_TS_PACKET_SIZE = 188
_TS_M2TS_PACKET_SIZE = 192
_TS_FEC_PACKET_SIZE = 204
_TS_PACKET_SIZES = (_TS_PACKET_SIZE, _TS_M2TS_PACKET_SIZE, _TS_FEC_PACKET_SIZE)
_TS_SYNC_COUNT = 3  # verifier 3 sync bytes

# Extensions supportees par la verification
_EXT_TO_FORMAT: Dict[str, str] = {
    ".mkv": "mkv",
    ".webm": "mkv",
    ".mp4": "mp4",
    ".m4v": "mp4",
    ".mov": "mp4",
    ".avi": "avi",
    ".ts": "ts",
    ".m2ts": "ts",
    ".mts": "ts",
    ".wmv": "wmv",
    ".asf": "wmv",
}


def check_header(path: Path) -> Tuple[bool, str]:
    """Verifie que le header du fichier correspond au format attendu.

    Retourne (is_valid, detail) :
    - (True, "ok") — header valide
    - (True, "skipped") — extension non reconnue, skip silencieux
    - (False, "empty_file") — fichier vide
    - (False, "file_too_small") — trop petit pour verifier
    - (False, "header_mismatch") — magic bytes ne correspondent pas
    - (False, "read_error") — erreur de lecture (permission, etc.)
    """
    ext = path.suffix.lower()
    fmt = _EXT_TO_FORMAT.get(ext)
    if fmt is None:
        return True, "skipped"

    try:
        data = _read_header(path)
    except (OSError, PermissionError) as exc:
        logger.debug("Integrity read error %s: %s", path, exc)
        return False, "read_error"

    if len(data) == 0:
        return False, "empty_file"

    if fmt == "mkv":
        return _check_mkv(data)
    if fmt == "mp4":
        return _check_mp4(data)
    if fmt == "avi":
        return _check_avi(data)
    if fmt == "ts":
        return _check_ts(data)
    if fmt == "wmv":
        return _check_wmv(data)

    return True, "skipped"


def _read_header(path: Path) -> bytes:
    """Lit les premiers octets du fichier."""
    with open(path, "rb") as f:
        return f.read(_HEADER_READ_SIZE)


def _check_mkv(data: bytes) -> Tuple[bool, str]:
    if len(data) < len(_MAGIC_MKV):
        return False, "file_too_small"
    if data[: len(_MAGIC_MKV)] == _MAGIC_MKV:
        return True, "ok"
    return False, "header_mismatch"


def _check_mp4(data: bytes) -> Tuple[bool, str]:
    needed = _MAGIC_FTYP_OFFSET + len(_MAGIC_FTYP)
    if len(data) < needed:
        return False, "file_too_small"
    if data[_MAGIC_FTYP_OFFSET : _MAGIC_FTYP_OFFSET + len(_MAGIC_FTYP)] == _MAGIC_FTYP:
        return True, "ok"
    return False, "header_mismatch"


def _check_avi(data: bytes) -> Tuple[bool, str]:
    needed = _MAGIC_AVI_OFFSET + len(_MAGIC_AVI)
    if len(data) < needed:
        return False, "file_too_small"
    if (
        data[: len(_MAGIC_RIFF)] == _MAGIC_RIFF
        and data[_MAGIC_AVI_OFFSET : _MAGIC_AVI_OFFSET + len(_MAGIC_AVI)] == _MAGIC_AVI
    ):
        return True, "ok"
    return False, "header_mismatch"


def _check_ts(data: bytes) -> Tuple[bool, str]:
    """Verifie `_TS_SYNC_COUNT` sync bytes 0x47 alignes sur un layout TS connu.

    Un layout est un couple (decalage initial, taille de paquet). On essaie
    chaque taille de `_TS_PACKET_SIZES` et, pour chacune, chaque decalage de
    0 a taille-1 : un flux qui commence au milieu d'un paquet (capture coupee)
    a forcement sa premiere frontiere de paquet a moins d'une taille de paquet
    du debut, donc cette plage est exhaustive. C'est ce qui rattrape le M2TS
    (sync a l'offset 4) sans coder ce 4 en dur.

    Le prix de cette recherche est un risque de faux positif sur des octets
    aleatoires : ~584 couples testes a 2**-24 chacun, soit ~5e-5. Negligeable
    devant le defaut corrige, qui declarait corrompu 100 % des `.m2ts`/`.mts`
    valides.

    On ne rend `header_mismatch` que si TOUS les layouts ont pu etre testes :
    si l'en-tete lu est trop court pour en eliminer un, le verdict honnete est
    `file_too_small`, pas une accusation de corruption.
    """
    all_layouts_tested = True
    for size in _TS_PACKET_SIZES:
        span = (_TS_SYNC_COUNT - 1) * size
        for base in range(size):
            if len(data) < base + span + 1:
                # `needed` croit avec `base` : les decalages suivants de cette
                # taille sont hors de portee eux aussi.
                all_layouts_tested = False
                break
            if all(data[base + i * size] == _TS_SYNC_BYTE for i in range(_TS_SYNC_COUNT)):
                return True, "ok"
    if not all_layouts_tested:
        return False, "file_too_small"
    return False, "header_mismatch"


def _check_wmv(data: bytes) -> Tuple[bool, str]:
    if len(data) < len(_MAGIC_WMV):
        return False, "file_too_small"
    if data[: len(_MAGIC_WMV)] == _MAGIC_WMV:
        return True, "ok"
    return False, "header_mismatch"


# --- Verification fin de fichier (tail check) --------------------------------

_TAIL_READ_SIZE = 4096
_MOOV_SCAN_SIZE = 65536  # 64 KB pour chercher l'atome moov en debut de fichier


def check_tail(path: Path) -> Tuple[bool, str]:
    """Verifie la fin du fichier pour detecter les troncatures.

    - MP4/MOV : cherche l'atome 'moov' dans le header ou le tail
    - MKV : verifie que le fichier ne se termine pas par des octets nuls
    - Autres formats : skip (retourne True)
    """
    ext = path.suffix.lower()
    fmt = _EXT_TO_FORMAT.get(ext)
    if fmt not in ("mp4", "mkv"):
        return True, "skipped"

    try:
        size = os.path.getsize(path)
        if size < _TAIL_READ_SIZE:
            return True, "fichier trop petit pour tail check"

        with open(path, "rb") as f:
            if fmt == "mp4":
                # Chercher l'atome moov dans le header (64 KB)
                header = f.read(min(size, _MOOV_SCAN_SIZE))
                if b"moov" in header:
                    return True, "ok"
                # Chercher dans les derniers 4 KB
                f.seek(-_TAIL_READ_SIZE, 2)
                tail = f.read()
                if b"moov" in tail:
                    return True, "ok"
                logger.info("integrity: tail MP4 %s -> moov absent (possiblement tronque)", path.name)
                return False, "atome moov absent (MP4 possiblement tronque)"

            elif fmt == "mkv":
                f.seek(-min(_TAIL_READ_SIZE, size), 2)
                tail = f.read()
                if tail == b"\x00" * len(tail):
                    logger.info("integrity: tail MKV %s -> fin nulle (possiblement tronque)", path.name)
                    return False, "fin de fichier nulle (MKV possiblement tronque)"
                return True, "ok"

    except (OSError, PermissionError) as exc:
        return False, f"erreur lecture tail: {exc}"

    return True, "ok"
