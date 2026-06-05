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

from cinesort.domain._runners import tracked_run

from .constants import (
    AUDIO_FINGERPRINT_MIN_FILE_DURATION_S,
    AUDIO_FINGERPRINT_SEGMENT_DURATION_S,
    AUDIO_FINGERPRINT_SEGMENT_OFFSET_S,
    AUDIO_FINGERPRINT_SIMILARITY_CONFIRMED,
    AUDIO_FINGERPRINT_SIMILARITY_POSSIBLE,
    AUDIO_FINGERPRINT_SIMILARITY_PROBABLE,
    AUDIO_FINGERPRINT_TIMEOUT_S,
)
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
    ffmpeg_path: Optional[str] = None,
    track_index: int = 0,
    timeout_s: float = AUDIO_FINGERPRINT_TIMEOUT_S,
) -> Optional[str]:
    """Calcule le fingerprint Chromaprint d'un segment audio.

    Args:
        media_path: chemin du fichier video/audio.
        duration_s: duree totale du fichier (pour decider offset).
        fpcalc_path: None = auto-detection via resolve_fpcalc_path.
        ffmpeg_path: chemin ffmpeg pour seek strict (-ss) via pipe stdin
            quand un offset > 0 est utilise. None = pas de seek (fallback
            sur les premieres secondes du fichier, comportement <= v7.5).
        track_index: index de la piste audio a fingerprinter (default 0).
            Utilise uniquement en mode pipe ffmpeg (`-map 0:a:{track_index}`)
            pour s'aligner sur l'index choisi par les autres analyses
            perceptuelles (loudnorm/astats/clipping). En mode direct fpcalc
            (offset == 0 ou ffmpeg_path absent), ignore car fpcalc choisit
            seul sa piste (stream 0 par defaut). Backward compat preservee.
        timeout_s: timeout du sous-process fpcalc.

    Returns:
        Fingerprint encode base64 (chaine compacte), ou None en cas d'erreur.
        Le binaire fingerprint = liste d'entiers 32-bit little-endian.

    Strategie de segment :
        - Si duration_s < AUDIO_FINGERPRINT_MIN_FILE_DURATION_S : tout le fichier.
        - Sinon : segment [OFFSET=60s, DURATION=120s] — necessite ffmpeg_path
          pour respecter l'offset (sinon fallback sur premieres secondes).

    MEGA-HOTFIX audio_fingerprint_offset : avant ce fix, l'offset etait
    calcule puis ignore (`_ = offset`), donc fpcalc analysait les 120
    premieres secondes du fichier — souvent saturees de logos studios
    (Universal, Marvel, Disney...) communs a tous les films, generant
    de faux positifs doublons. Maintenant, si `ffmpeg_path` est fourni
    on pipe `ffmpeg -ss OFFSET -t LENGTH ... | fpcalc -` pour analyser
    le vrai contenu narratif.
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

    # Strategie d'execution :
    # - offset == 0 OU ffmpeg_path absent : appel direct fpcalc (backward compat).
    # - offset > 0 ET ffmpeg_path present : pipe ffmpeg (seek strict) -> fpcalc -.
    use_seek_pipe = offset > 0.0 and bool(ffmpeg_path)

    if not use_seek_pipe:
        # Comportement historique : fpcalc lit le fichier directement, sans
        # seek (limite de fpcalc 1.5.1 qui n'a pas d'option -ss native).
        # Conserve pour les fichiers courts (offset = 0) et comme fallback
        # quand ffmpeg n'est pas disponible (defense en profondeur).
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

        stdout_text = cp.stdout
    else:
        # MEGA-HOTFIX : pipe ffmpeg seek -> fpcalc stdin pour respecter offset.
        # ffmpeg -ss avant -i = seek rapide (input seeking, peu precis mais
        # acceptable a +/-1s pour un fingerprint de 120s). Output WAV PCM
        # 16-bit stereo 44.1kHz, format natif consomme par fpcalc.
        stdout_text = _run_ffmpeg_pipe_fpcalc(
            ffmpeg_path=ffmpeg_path,  # type: ignore[arg-type]
            fpcalc_path=fpcalc,
            media_path=str(media_path),
            offset_s=offset,
            length_s=length,
            timeout_s=float(timeout_s),
            track_index=int(track_index),
        )
        if stdout_text is None:
            return None

    try:
        data = json.loads(stdout_text)
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


def _run_ffmpeg_pipe_fpcalc(
    *,
    ffmpeg_path: str,
    fpcalc_path: str,
    media_path: str,
    offset_s: float,
    length_s: float,
    timeout_s: float,
    track_index: int = 0,
) -> Optional[str]:
    """Pipe ffmpeg (-ss seek + WAV stdout) -> fpcalc (stdin -) et retourne stdout JSON.

    Strategie :
        ffmpeg -nostdin -ss OFFSET -t LENGTH -i media -map 0:a:IDX
               -vn -ac 2 -ar 44100 -f wav -loglevel error -
            | fpcalc -json -raw -length LENGTH -

    Cleanup garanti via tracked_popen pour les deux process. Si ffmpeg
    echoue (binaire absent, fichier corrompu), retourne None et log warning.

    `track_index` aligne la piste audio fingerprintee avec celle utilisee
    par loudnorm/astats/clipping (`select_best_audio_track`), pour eviter
    que deux films identiques aux pistes default differentes generent des
    fingerprints divergents.
    """
    # Service-locator domain : evite la violation d'architecture
    # (domain -> infra) detectee par import-linter.
    from cinesort.domain._runners import tracked_popen

    int_offset = max(0, int(offset_s))
    int_length = max(1, int(length_s))
    int_track = max(0, int(track_index))

    ffmpeg_cmd = [
        ffmpeg_path,
        "-nostdin",
        "-ss",
        str(int_offset),
        "-t",
        str(int_length),
        "-i",
        media_path,
        "-map",
        f"0:a:{int_track}",
        "-vn",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-f",
        "wav",
        "-loglevel",
        "error",
        "-",
    ]
    fpcalc_cmd = [
        fpcalc_path,
        "-json",
        "-raw",
        "-length",
        str(int_length),
        "-",
    ]

    platform_kwargs = _runner_platform_kwargs()
    safe_timeout = max(1.0, float(timeout_s))

    try:
        with tracked_popen(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **platform_kwargs,
        ) as ffmpeg_proc:
            with tracked_popen(
                fpcalc_cmd,
                stdin=ffmpeg_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **platform_kwargs,
            ) as fpcalc_proc:
                # Important : fermer notre cote du pipe pour que fpcalc voie EOF
                # quand ffmpeg se termine. Sinon deadlock potentiel.
                if ffmpeg_proc.stdout is not None:
                    ffmpeg_proc.stdout.close()
                try:
                    fp_stdout_bytes, fp_stderr_bytes = fpcalc_proc.communicate(
                        timeout=safe_timeout
                    )
                except subprocess.TimeoutExpired:
                    logger.warning(
                        "fpcalc (pipe ffmpeg) timeout apres %ss sur %s",
                        timeout_s,
                        media_path,
                    )
                    return None
                fpcalc_rc = fpcalc_proc.returncode

                # Attendre la fin de ffmpeg pour eviter zombie + recuperer stderr.
                try:
                    _, ff_stderr_bytes = ffmpeg_proc.communicate(timeout=safe_timeout)
                except subprocess.TimeoutExpired:
                    logger.warning(
                        "ffmpeg (pipe fpcalc) timeout apres %ss sur %s",
                        timeout_s,
                        media_path,
                    )
                    return None
                ffmpeg_rc = ffmpeg_proc.returncode
    except OSError as exc:
        logger.warning(
            "pipe ffmpeg|fpcalc OSError sur %s: %s (fallback indisponible)",
            media_path,
            exc,
        )
        return None

    if ffmpeg_rc != 0:
        ff_err = (ff_stderr_bytes or b"").decode("utf-8", errors="replace").strip()
        logger.warning(
            "ffmpeg pipe returncode=%d sur %s (offset=%ss, length=%ss): %s",
            ffmpeg_rc,
            media_path,
            int_offset,
            int_length,
            ff_err[:200],
        )
        # On ne return PAS ici : si fpcalc a quand meme produit du JSON valide
        # sur les bytes pre-erreur, on peut l'utiliser. Mais si fpcalc a aussi
        # echoue, on tombera dans le check juste apres.

    if fpcalc_rc != 0:
        fp_err = (fp_stderr_bytes or b"").decode("utf-8", errors="replace").strip()
        logger.warning(
            "fpcalc (pipe) returncode=%d sur %s: %s",
            fpcalc_rc,
            media_path,
            fp_err[:200],
        )
        return None

    try:
        return (fp_stdout_bytes or b"").decode("utf-8", errors="replace")
    except (UnicodeDecodeError, AttributeError) as exc:
        logger.warning("fpcalc (pipe) decode stdout failed sur %s: %s", media_path, exc)
        return None


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
