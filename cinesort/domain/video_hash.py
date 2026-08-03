"""Video hash perceptual (V2.4 — fusion doublons).

Bounded context : signal video perceptuel complementaire a Chromaprint
(`domain/perceptual/audio_fingerprint.py`) pour la detection de doublons
(meme film, encodages differents). Le module extrait N thumbnails
equi-espacees via ffmpeg, calcule un pHash 64-bit par frame, et expose
une distance normalisee [0, 1].

Pattern architectural :
- Module pur `domain/` -> ne peut PAS importer `app`, `infra`, `ui`
  (contract `domain_pure` verrouille par import-linter).
- Subprocess via `tracked_run` du service-locator `_runners` (idem
  audio_fingerprint.py), pas d'import direct de `cinesort.infra`.
- Code robuste a l'absence de ffmpeg : log warning + retourne None /
  liste vide, jamais d'erreur bloquante (pattern Chromaprint).
- Aucune dependance binaire ajoutee (Pillow + struct stdlib uniquement).

Feature flag : controle par `cinesort/app/duplicate_pipeline.py` derriere
`CINESORT_FUSION_DOUBLONS` (OFF par defaut, backward compat ABSOLUE).
"""

from __future__ import annotations

import logging
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

from cinesort.domain._runners import tracked_run

logger = logging.getLogger(__name__)


# --- Constantes calibration --------------------------------------------------
# Nombre de thumbnails extraits par defaut (10 frames equi-espacees couvrent
# bien la dynamique narrative sans saturer ffmpeg). Augmentable si necessaire
# via parametre `n` de `extract_video_thumbnails`.
DEFAULT_THUMBNAIL_COUNT = 10

# Taille de la grille pHash (8x8 = 64 bits, standard pHash difference). Choix
# aligne sur la litterature (Marr / Hadmard / DCT-based). 16x16 (256 bits)
# divise par 4 la tolerance bruit/recompression — pas utile ici.
PHASH_GRID_SIZE = 8

# Skip les N premieres secondes (logos studio) et les N dernieres (generique).
# Aligne avec AUDIO_FINGERPRINT_SEGMENT_OFFSET_S (60s) du fingerprint Chromaprint.
DEFAULT_VIDEO_SKIP_HEAD_S = 60.0
DEFAULT_VIDEO_SKIP_TAIL_S = 60.0

# Timeout par extraction ffmpeg (par frame). Genereux pour les fichiers 4K
# encodes en HEVC qui peuvent etre lents a seeker.
FFMPEG_FRAME_TIMEOUT_S = 30.0


def resolve_ffmpeg_path() -> Optional[str]:
    """Resout le chemin vers ffmpeg.exe (meme strategie que fpcalc).

    Ordre de recherche :
    1. assets/tools/ffmpeg.exe relatif au binaire PyInstaller (sys._MEIPASS)
    2. assets/tools/ffmpeg.exe relatif au repo (mode dev)
    3. shutil.which("ffmpeg") (systeme)

    Returns:
        Chemin absolu si trouve, None sinon (feature desactivee avec warning).
    """
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"

    candidates: List[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "assets" / "tools" / exe_name)

    here = Path(__file__).resolve()
    repo_root = here.parents[2]  # cinesort/domain/ -> repo root
    candidates.append(repo_root / "assets" / "tools" / exe_name)

    for c in candidates:
        if c.is_file():
            return str(c)

    which = shutil.which("ffmpeg")
    if which:
        return which

    logger.warning("ffmpeg introuvable : video hash desactive")
    return None


def extract_video_thumbnails(
    video_path: str,
    duration_s: float,
    *,
    n: int = DEFAULT_THUMBNAIL_COUNT,
    ffmpeg_path: Optional[str] = None,
    skip_head_s: float = DEFAULT_VIDEO_SKIP_HEAD_S,
    skip_tail_s: float = DEFAULT_VIDEO_SKIP_TAIL_S,
    timeout_s: float = FFMPEG_FRAME_TIMEOUT_S,
) -> List[bytes]:
    """Extrait N thumbnails equi-espacees d'un fichier video via ffmpeg.

    Strategie :
    - Skip `skip_head_s` (logos studio) et `skip_tail_s` (generique).
    - Repartit N timestamps uniformement dans la fenetre utile.
    - Extraction PGM grayscale 8x8 directement (downsample par ffmpeg
      `-vf scale=8x8` + `-pix_fmt gray`) pour minimiser le decodage.
    - tracked_run pour chaque frame (cleanup zombie garanti).

    Args:
        video_path: chemin du fichier video.
        duration_s: duree totale (pour repartir les frames). Si <= 0 ou
            inferieure a `skip_head_s + skip_tail_s + 10s`, on bypass le skip.
        n: nombre de thumbnails (default DEFAULT_THUMBNAIL_COUNT=10).
        ffmpeg_path: None = auto-detection via resolve_ffmpeg_path.
        skip_head_s / skip_tail_s : zones a ignorer en debut/fin de film.
        timeout_s: timeout par extraction frame.

    Returns:
        Liste de N bytes (chaque frame = 64 bytes PGM 8x8 grayscale).
        Liste vide si ffmpeg absent, duree invalide, ou erreur globale.
        Frame manquante = simplement absente (pas de None dans la liste).
    """
    ffmpeg = ffmpeg_path or resolve_ffmpeg_path()
    if not ffmpeg:
        return []

    if n <= 0:
        return []

    useful_duration = float(duration_s) - float(skip_head_s) - float(skip_tail_s)
    if useful_duration < 10.0:
        # Film trop court (ou duree invalide) : on prend toute la duree sans skip.
        start = 0.0
        end = max(1.0, float(duration_s))
    else:
        start = float(skip_head_s)
        end = float(duration_s) - float(skip_tail_s)

    # Repartit N timestamps : 1er = start + delta/2, dernier = end - delta/2,
    # pour eviter les bords pile.
    span = max(0.001, end - start)
    delta = span / float(n)
    timestamps = [start + delta * (i + 0.5) for i in range(n)]

    frames: List[bytes] = []
    grid = int(PHASH_GRID_SIZE)

    with tempfile.TemporaryDirectory(prefix="cs_vhash_") as tmpdir:
        for idx, ts in enumerate(timestamps):
            out_path = Path(tmpdir) / f"frame_{idx:02d}.pgm"
            cmd = [
                ffmpeg,
                "-nostdin",
                "-ss",
                f"{ts:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-vf",
                f"scale={grid}:{grid}",
                "-pix_fmt",
                "gray",
                "-f",
                "image2",
                "-loglevel",
                "error",
                "-y",
                str(out_path),
            ]
            try:
                cp = tracked_run(
                    cmd,
                    capture_output=True,
                    text=False,
                    timeout=max(1.0, float(timeout_s)),
                )
            except subprocess.TimeoutExpired:
                logger.warning(
                    "ffmpeg frame timeout (%ss, ts=%.1f) sur %s",
                    timeout_s,
                    ts,
                    video_path,
                )
                continue
            except OSError as exc:
                logger.warning("ffmpeg OSError sur %s (ts=%.1f): %s", video_path, ts, exc)
                continue

            if cp.returncode != 0:
                # Frame manquee : on continue, l'algo phash tolere une liste
                # partielle (compute_phash_per_frame retournera moins de hash).
                continue

            try:
                raw_pgm = out_path.read_bytes()
            except OSError as exc:
                logger.warning("read pgm failed sur %s: %s", out_path, exc)
                continue

            pixels = _parse_pgm_grayscale(raw_pgm, expected_w=grid, expected_h=grid)
            if pixels is not None:
                frames.append(pixels)

    return frames


def compute_phash_per_frame(frames: List[bytes]) -> bytes:
    """Calcule un pHash 64-bit pour chaque frame, retourne la concatenation.

    Algorithme pHash difference (dHash variant) :
    - Chaque frame est deja en 8x8 grayscale (DEFAULT 64 pixels octets).
    - Pour chaque ligne, on compare 8 pixels adjacents -> 7 bits / ligne x 8
      lignes = 56 bits. On complete avec 8 bits de comparaison col/col
      (premier vs dernier pixel par ligne) pour atteindre 64 bits.

    Args:
        frames: liste de bytes (64 pixels = 8x8 grayscale chacun).

    Returns:
        Bytes concatenes : len(frames) * 8 octets (1 hash 64-bit / frame).
        Vide si frames est vide ou toutes les frames ont une taille invalide.
    """
    if not frames:
        return b""

    grid = int(PHASH_GRID_SIZE)
    expected_size = grid * grid

    out = bytearray()
    for pixels in frames:
        if not isinstance(pixels, (bytes, bytearray)) or len(pixels) != expected_size:
            continue
        hash_64 = _dhash_64bit(pixels, grid)
        out.extend(struct.pack("<Q", hash_64))
    return bytes(out)


def videohash_distance(h1: Optional[bytes], h2: Optional[bytes]) -> Optional[float]:
    """Distance normalisee entre deux video-hash, dans [0.0, 1.0].

    Algorithme : Hamming popcount par hash 64-bit, somme, divise par
    le nombre total de bits compares (min(len) * 64).

    Args:
        h1, h2: bytes produits par `compute_phash_per_frame`. Longueur
            attendue = multiple de 8 (1 hash 64-bit / frame).

    Returns:
        Distance dans [0.0, 1.0] (0.0 = identique, 1.0 = totalement different).
        None si l'un est None / vide / mal forme.
    """
    if h1 is None or h2 is None:
        return None
    if not isinstance(h1, (bytes, bytearray)) or not isinstance(h2, (bytes, bytearray)):
        return None
    if len(h1) == 0 or len(h2) == 0:
        return None
    if len(h1) % 8 != 0 or len(h2) % 8 != 0:
        return None

    n1 = len(h1) // 8
    n2 = len(h2) // 8
    common = min(n1, n2)
    if common == 0:
        return None

    try:
        ints1 = list(struct.unpack(f"<{n1}Q", bytes(h1)))[:common]
        ints2 = list(struct.unpack(f"<{n2}Q", bytes(h2)))[:common]
    except struct.error:
        return None

    hamming = 0
    for a, b in zip(ints1, ints2):
        hamming += (a ^ b).bit_count()
    total_bits = common * 64
    return float(hamming) / float(total_bits)


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------


def _parse_pgm_grayscale(raw: bytes, *, expected_w: int, expected_h: int) -> Optional[bytes]:
    """Parse PGM binaire P5 (1 octet/pixel grayscale), retourne les pixels.

    Format PGM P5 :
        P5\n
        <width> <height>\n
        <maxval>\n
        <raw pixel bytes>

    Tolere des commentaires `# ...\n` apres le magic. Retourne None si la
    taille extraite ne correspond pas a expected_w * expected_h.
    """
    if not raw or not raw.startswith(b"P5"):
        return None

    # Decoupe l'en-tete : 4 tokens texte (P5, w, h, maxval) suivis du raw.
    # On itere octet par octet pour gerer les commentaires.
    pos = 2  # apres "P5"
    tokens: List[bytes] = []
    cur = bytearray()
    in_comment = False
    while pos < len(raw) and len(tokens) < 3:
        c = raw[pos : pos + 1]
        pos += 1
        if in_comment:
            if c == b"\n":
                in_comment = False
            continue
        if c == b"#":
            in_comment = True
            if cur:
                tokens.append(bytes(cur))
                cur = bytearray()
            continue
        if c in (b" ", b"\t", b"\r", b"\n"):
            if cur:
                tokens.append(bytes(cur))
                cur = bytearray()
            continue
        cur.extend(c)

    if cur and len(tokens) < 3:
        tokens.append(bytes(cur))

    if len(tokens) < 3:
        return None
    try:
        w = int(tokens[0])
        h = int(tokens[1])
        maxval = int(tokens[2])
    except (TypeError, ValueError):
        return None

    if w != expected_w or h != expected_h or maxval > 255:
        return None

    pixels = raw[pos:]
    if len(pixels) < expected_w * expected_h:
        return None
    return bytes(pixels[: expected_w * expected_h])


def _dhash_64bit(pixels: bytes, grid: int) -> int:
    """Calcule un dHash 64-bit a partir d'une grille grayscale grid x grid.

    Strategie : 7 bits par ligne (comparaison pixel[col] > pixel[col+1])
    sur les 8 lignes = 56 bits, complete par 8 bits de comparaison
    colonne premiere vs derniere par ligne. Total = 64 bits.
    """
    if grid <= 1:
        return 0

    h: int = 0
    bit = 0
    for row in range(grid):
        base = row * grid
        for col in range(grid - 1):
            if pixels[base + col] > pixels[base + col + 1]:
                h |= 1 << bit
            bit += 1
            if bit >= 64:
                return h

    # Complement : compare premier vs dernier pixel de chaque ligne (8 bits).
    for row in range(grid):
        if bit >= 64:
            break
        base = row * grid
        if pixels[base] > pixels[base + grid - 1]:
            h |= 1 << bit
        bit += 1

    return h
