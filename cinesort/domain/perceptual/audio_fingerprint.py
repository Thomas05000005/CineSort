"""Fingerprint audio Chromaprint via fpcalc.exe (§3 v7.5.0).

Appel direct de fpcalc.exe en subprocess (pas de dependance pyacoustid).
Le binaire est embarque dans assets/tools/fpcalc.exe. Code robuste a son
absence : log warning + feature desactivee, jamais d'erreur bloquante.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from .constants import (
    AUDIO_FINGERPRINT_MIN_FILE_DURATION_S,
    AUDIO_FINGERPRINT_SEGMENT_DURATION_S,
    AUDIO_FINGERPRINT_SEGMENT_OFFSET_S,
    AUDIO_FINGERPRINT_SIMILARITY_CONFIRMED,
    AUDIO_FINGERPRINT_SIMILARITY_POSSIBLE,
    AUDIO_FINGERPRINT_SIMILARITY_PROBABLE,
    AUDIO_FINGERPRINT_TIMEOUT_S,
)
from cinesort.infra.subprocess_safety import tracked_run

from .ffmpeg_runner import _runner_platform_kwargs

logger = logging.getLogger(__name__)


def resolve_fpcalc_path() -> Optional[str]:
    """Resout le chemin vers fpcalc.exe.

    Ordre de recherche :
    1. assets/tools/fpcalc.exe relatif au binaire PyInstaller (sys._MEIPASS)
    2. assets/tools/fpcalc.exe relatif au repo (mode dev)
    3. shutil.which("fpcalc") (systeme)

    Returns:
        Chemin absolu si trouve, None sinon (feature desactivee avec warning).
    """
    exe_name = "fpcalc.exe" if os.name == "nt" else "fpcalc"

    candidates: List[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "assets" / "tools" / exe_name)

    # Mode dev : remonter depuis ce fichier jusqu'a la racine du repo
    here = Path(__file__).resolve()
    repo_root = here.parents[3]  # cinesort/domain/perceptual/ -> repo root
    candidates.append(repo_root / "assets" / "tools" / exe_name)

    for c in candidates:
        if c.is_file():
            return str(c)

    which = shutil.which("fpcalc")
    if which:
        return which

    logger.warning("fpcalc.exe introuvable : fingerprint audio desactive")
    return None


def compute_audio_fingerprint(
    media_path: str,
    duration_s: float,
    *,
    fpcalc_path: Optional[str] = None,
    timeout_s: float = AUDIO_FINGERPRINT_TIMEOUT_S,
) -> Optional[str]:
    """Calcule le fingerprint Chromaprint d'un segment audio.

    Args:
        media_path: chemin du fichier video/audio.
        duration_s: duree totale du fichier (pour decider offset).
        fpcalc_path: None = auto-detection via resolve_fpcalc_path.
        timeout_s: timeout du sous-process fpcalc.

    Returns:
        Fingerprint encode base64 (chaine compacte), ou None en cas d'erreur.
        Le binaire fingerprint = liste d'entiers 32-bit little-endian.

    Strategie de segment :
        - Si duration_s < AUDIO_FINGERPRINT_MIN_FILE_DURATION_S : tout le fichier.
        - Sinon : segment [OFFSET=60s, DURATION=120s].
    """
    fpcalc = fpcalc_path or resolve_fpcalc_path()
    if not fpcalc:
        return None

    if duration_s > 0 and duration_s < AUDIO_FINGERPRINT_MIN_FILE_DURATION_S:
        length = max(1.0, float(duration_s))
        offset = 0.0
    else:
        length = float(AUDIO_FINGERPRINT_SEGMENT_DURATION_S)
        offset = float(AUDIO_FINGERPRINT_SEGMENT_OFFSET_S)

    # Note: fpcalc 1.5.1 n'a pas d'option de seek (-ss). On prend les
    # premieres `length` secondes du fichier. L'offset strict via pipe
    # ffmpeg reste possible si on constate beaucoup de faux negatifs sur
    # des films a generique long (raffinement v7.6.0+).
    _ = offset  # documente mais non utilise pour l'instant
    cmd = [
        fpcalc,
        "-json",
        "-raw",
        "-length",
        str(int(length)),
        str(media_path),
    ]

    try:
        platform_kwargs = _runner_platform_kwargs()
        cp = tracked_run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout_s)),
            encoding="utf-8",
            errors="replace",
            **platform_kwargs,
        )
    except subprocess.TimeoutExpired:
        logger.warning("fpcalc timeout apres %ss sur %s", timeout_s, media_path)
        return None
    except OSError as exc:
        logger.warning("fpcalc OSError sur %s: %s", media_path, exc)
        return None

    if cp.returncode != 0:
        logger.warning(
            "fpcalc returncode=%d sur %s: %s",
            cp.returncode,
            media_path,
            (cp.stderr or "").strip()[:200],
        )
        return None

    try:
        data = json.loads(cp.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("fpcalc stdout non-JSON sur %s: %s", media_path, exc)
        return None

    fp_raw = data.get("fingerprint")
    if not isinstance(fp_raw, list) or not fp_raw:
        logger.warning("fpcalc fingerprint vide sur %s", media_path)
        return None

    try:
        ints = [int(x) & 0xFFFFFFFF for x in fp_raw]
    except (TypeError, ValueError) as exc:
        logger.warning("fpcalc fingerprint non numerique sur %s: %s", media_path, exc)
        return None

    return _encode_fingerprint(ints)


def compare_audio_fingerprints(fp_a: Optional[str], fp_b: Optional[str]) -> Optional[float]:
    """Compare 2 fingerprints Chromaprint (distance de Hamming normalisee).

    Args:
        fp_a, fp_b: chaines base64 produites par compute_audio_fingerprint.

    Returns:
        Similarite 0.0-1.0, ou None si l'un est None/mal forme.

    Algo : pour chaque entier 32-bit aligne, popcount(a[i] ^ b[i]), somme,
    normalise par total_bits = 32 * min(len). Retourne 1.0 - hamming/total.
    """
    if fp_a is None or fp_b is None:
        return None
    try:
        ia = _decode_fingerprint(fp_a)
        ib = _decode_fingerprint(fp_b)
    except (ValueError, TypeError):
        return None
    if not ia or not ib:
        return None

    common = min(len(ia), len(ib))
    if common == 0:
        return None

    hamming = 0
    for i in range(common):
        hamming += (ia[i] ^ ib[i]).bit_count()
    total_bits = common * 32
    return 1.0 - (hamming / total_bits)


def classify_fingerprint_similarity(similarity: Optional[float]) -> str:
    """Classifie la similarite en verdict humain-lisible.

    Returns:
        "confirmed" (>=0.90) | "probable" (>=0.75) | "possible" (>=0.50) |
        "different" (<0.50) | "unknown" (None).
    """
    if similarity is None:
        return "unknown"
    if similarity >= AUDIO_FINGERPRINT_SIMILARITY_CONFIRMED:
        return "confirmed"
    if similarity >= AUDIO_FINGERPRINT_SIMILARITY_PROBABLE:
        return "probable"
    if similarity >= AUDIO_FINGERPRINT_SIMILARITY_POSSIBLE:
        return "possible"
    return "different"


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------


def _encode_fingerprint(fp_ints: List[int]) -> str:
    """Encode une liste d'entiers 32-bit en base64 compact (little-endian)."""
    buf = struct.pack(f"<{len(fp_ints)}I", *fp_ints)
    return base64.b64encode(buf).decode("ascii")


def _decode_fingerprint(fp_b64: str) -> List[int]:
    """Decode une chaine base64 en liste d'entiers 32-bit little-endian.

    Raises ValueError si la chaine est mal formee.
    """
    if not isinstance(fp_b64, str) or not fp_b64:
        return []
    raw = base64.b64decode(fp_b64, validate=True)
    if len(raw) % 4 != 0:
        raise ValueError("longueur de fingerprint non alignee sur 32 bits")
    n = len(raw) // 4
    if n == 0:
        return []
    return list(struct.unpack(f"<{n}I", raw))
