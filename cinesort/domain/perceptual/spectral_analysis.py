"""Analyse spectrale audio (§9 v7.5.0) — detection lossy via spectral rolloff.

Principe : les encodeurs lossy eliminent les hautes frequences au-dessus d'un
seuil (ex: MP3 128 = 16 kHz, FLAC = 22 kHz). On extrait un segment audio mono
PCM via ffmpeg, on calcule un spectrogramme FFT avec numpy, et on mesure la
frequence de coupure par spectral rolloff 85% (plus robuste que "derniere freq
au-dessus du bruit").

Cross-check avec codec (HE-AAC/SBR = verdict ambigu), sample rate (Nyquist),
et ere de production (FLAC vintage avec cutoff 19-20 kHz = natif OK).
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from .constants import (
    SPECTRAL_CUTOFF_LOSSLESS,
    SPECTRAL_CUTOFF_LOSSY_HIGH,
    SPECTRAL_CUTOFF_LOSSY_MID,
    SPECTRAL_FFT_OVERLAP,
    SPECTRAL_FFT_WINDOW_SIZE,
    SPECTRAL_MIN_RMS_DB,
    SPECTRAL_ROLLOFF_PCT,
    SPECTRAL_SAMPLE_RATE,
    SPECTRAL_SEGMENT_DURATION_S,
    SPECTRAL_SEGMENT_OFFSET_S,
    SPECTRAL_TIMEOUT_S,
)
from cinesort.domain._runners import tracked_run

from .ffmpeg_runner import _runner_platform_kwargs

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpectralResult:
    """Resultat de l'analyse spectrale."""

    cutoff_hz: float  # 0.0 si echec
    lossy_verdict: str
    # "lossless" | "lossy_high" | "lossy_mid" | "lossy_low"
    # | "lossy_ambiguous_sbr" | "lossless_native_nyquist"
    # | "lossless_vintage_master" | "silent_segment" | "error" | "unknown"
    confidence: float  # 0.0-1.0
    rms_db: float  # pour debug, -inf si silence complet


def extract_audio_segment(
    ffmpeg_path: str,
    media_path: str,
    track_index: int,
    *,
    offset_s: float = SPECTRAL_SEGMENT_OFFSET_S,
    duration_s: float = SPECTRAL_SEGMENT_DURATION_S,
    sample_rate: int = SPECTRAL_SAMPLE_RATE,
    timeout_s: float = SPECTRAL_TIMEOUT_S,
) -> Optional[np.ndarray]:
    """Extrait un segment audio mono PCM float32 via ffmpeg.

    Commande :
        ffmpeg -ss OFFSET -t DURATION -i MEDIA -map 0:a:IDX -ac 1 -ar SR -f f32le -

    Returns:
        np.ndarray 1D dtype=float32, ou None si erreur/timeout/data vide.
    """
    if not ffmpeg_path or not media_path:
        return None

    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-ss",
        str(float(offset_s)),
        "-t",
        str(float(duration_s)),
        "-i",
        str(media_path),
        "-map",
        f"0:a:{int(track_index)}?",
        "-ac",
        "1",
        "-ar",
        str(int(sample_rate)),
        "-f",
        "f32le",
        "-v",
        "error",
        "-",
    ]

    try:
        platform_kwargs = _runner_platform_kwargs()
        cp = tracked_run(
            cmd,
            capture_output=True,
            timeout=max(1.0, float(timeout_s)),
            **platform_kwargs,
        )
    except subprocess.TimeoutExpired:
        logger.warning("spectral: ffmpeg timeout apres %ss sur %s", timeout_s, media_path)
        return None
    except OSError as exc:
        logger.warning("spectral: ffmpeg OSError sur %s: %s", media_path, exc)
        return None

    if cp.returncode != 0:
        logger.warning(
            "spectral: ffmpeg returncode=%d sur %s: %s",
            cp.returncode,
            media_path,
            (cp.stderr or b"").decode("utf-8", errors="replace").strip()[:200],
        )
        return None

    raw = cp.stdout or b""
    if len(raw) < 4:
        return None

    # Ignore les octets residuels si la longueur n'est pas multiple de 4
    usable = len(raw) - (len(raw) % 4)
    samples = np.frombuffer(raw[:usable], dtype="<f4").astype(np.float32, copy=False)
    if samples.size == 0:
        return None
    return samples


def compute_spectrogram(
    samples: np.ndarray,
    *,
    window_size: int = SPECTRAL_FFT_WINDOW_SIZE,
    overlap: float = SPECTRAL_FFT_OVERLAP,
) -> np.ndarray:
    """Calcule la magnitude moyenne par frequence via FFT + Hann window.

    Args:
        samples: np.ndarray 1D (float32/float64).
        window_size: taille fenetre FFT (puissance de 2 recommandee).
        overlap: fraction d'overlap entre blocs (0.5 = 50%).

    Returns:
        np.ndarray 1D de longueur window_size//2+1, magnitudes moyennes.
        Retourne un array vide si samples est trop court (< window_size).
    """
    if samples is None or samples.size < window_size:
        return np.zeros(0, dtype=np.float64)

    ws = int(window_size)
    hop = max(1, int(ws * (1.0 - float(overlap))))
    n_frames = (len(samples) - ws) // hop + 1
    if n_frames <= 0:
        return np.zeros(0, dtype=np.float64)

    hann = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(ws) / (ws - 1))
    # Accumule les magnitudes bloc par bloc (moyenne incrementale)
    acc = np.zeros(ws // 2 + 1, dtype=np.float64)
    for i in range(n_frames):
        start = i * hop
        block = samples[start : start + ws].astype(np.float64, copy=False) * hann
        acc += np.abs(np.fft.rfft(block))
    acc /= float(n_frames)
    return acc


def find_cutoff_hz(
    spec_mean: np.ndarray,
    sample_rate: int,
    *,
    rolloff_pct: float = SPECTRAL_ROLLOFF_PCT,
) -> float:
    """Trouve la frequence de cutoff par spectral rolloff.

    Returns:
        Frequence en Hz au-dela de laquelle `rolloff_pct` de l'energie est
        deja accumulee. 0.0 si spec_mean vide ou tout-zero.
    """
    if spec_mean is None or spec_mean.size == 0:
        return 0.0
    power = np.square(spec_mean.astype(np.float64, copy=False))
    total = power.sum()
    if total <= 0.0:
        return 0.0
    cum = np.cumsum(power)
    threshold = float(rolloff_pct) * float(total)
    idx = int(np.searchsorted(cum, threshold))
    idx = min(idx, len(spec_mean) - 1)
    # Resolution frequentielle : Nyquist / (N-1)
    nyquist = float(sample_rate) / 2.0
    return idx * (nyquist / max(1, len(spec_mean) - 1))


def compute_rms_db(samples: np.ndarray) -> float:
    """RMS en dBFS (reference 1.0 = 0 dB). Retourne -inf pour silence total."""
    if samples is None or samples.size == 0:
        return float("-inf")
    sq = np.square(samples.astype(np.float64, copy=False))
    mean_sq = float(sq.mean())
    if mean_sq <= 0.0:
        return float("-inf")
    rms = np.sqrt(mean_sq)
    # Epsilon 1e-10 (au lieu de 1e-20 trop petit) : reste calculable en
    # float64 sans underflow, et 20*log10(1e-10) = -200 dBFS reste un
    # plancher physique acceptable pour l'audio. Cf issue #31.
    return 20.0 * float(np.log10(rms + 1e-10))


def classify_cutoff(
    cutoff_hz: float,
    rms_db: float,
    codec: str,
    sample_rate: int,
    film_era: str = "unknown",
) -> Tuple[str, float]:
    """Classifie le verdict lossy/lossless avec cross-checks.

    Priorite :
      1. Silence (rms < MIN_RMS_DB)
      2. HE-AAC / SBR : verdict ambigu (SBR reconstruit les HF)
      3. Sample rate bas : Nyquist limitant, verdict natif
      4. Seuils de cutoff avec tolerance vintage pour classic_film

    Returns:
        (verdict, confidence) ; confidence en 0.0-1.0.
    """
    if rms_db < SPECTRAL_MIN_RMS_DB:
        return ("silent_segment", 0.5)

    codec_l = (codec or "").strip().lower()
    if "he-aac" in codec_l or "he_aac" in codec_l or "heaac" in codec_l or "aac_he" in codec_l:
        return ("lossy_ambiguous_sbr", 0.95)

    nyquist = float(sample_rate) / 2.0
    if nyquist > 0 and cutoff_hz >= nyquist - 500.0:
        return ("lossless_native_nyquist", 0.90)

    if cutoff_hz >= SPECTRAL_CUTOFF_LOSSLESS:
        return ("lossless", 0.92)

    if cutoff_hz >= SPECTRAL_CUTOFF_LOSSY_HIGH:
        # Tolerance masters vintage : FLAC classique peut avoir cutoff 19.5-20k
        if film_era == "classic_film" and cutoff_hz >= 19500:
            return ("lossless_vintage_master", 0.75)
        return ("lossy_high", 0.88)

    if cutoff_hz >= SPECTRAL_CUTOFF_LOSSY_MID:
        return ("lossy_mid", 0.90)

    return ("lossy_low", 0.95)


def analyze_spectral(
    ffmpeg_path: str,
    media_path: str,
    track_index: int,
    duration_total_s: float,
    *,
    codec: str = "",
    sample_rate: int = 48000,
    film_era: str = "unknown",
    offset_s: float = SPECTRAL_SEGMENT_OFFSET_S,
    duration_s: float = SPECTRAL_SEGMENT_DURATION_S,
) -> SpectralResult:
    """Orchestre l'analyse spectrale complete.

    Returns:
        SpectralResult(cutoff_hz, verdict, confidence, rms_db).
        En cas d'echec : cutoff_hz=0, verdict="error", confidence=0.
    """
    # Adapter offset/duration aux fichiers courts
    if duration_total_s > 0:
        if duration_total_s < offset_s + duration_s:
            # Fichier trop court pour l'offset standard : on prend tout
            offset_s = 0.0
            duration_s = max(1.0, float(duration_total_s))

    samples = extract_audio_segment(
        ffmpeg_path,
        media_path,
        track_index,
        offset_s=offset_s,
        duration_s=duration_s,
        sample_rate=SPECTRAL_SAMPLE_RATE,
    )
    if samples is None or samples.size == 0:
        return SpectralResult(cutoff_hz=0.0, lossy_verdict="error", confidence=0.0, rms_db=float("-inf"))

    rms_db = compute_rms_db(samples)

    # Rapide guard sur silence : on skippe FFT si le signal est vraiment nul
    if rms_db < SPECTRAL_MIN_RMS_DB:
        return SpectralResult(cutoff_hz=0.0, lossy_verdict="silent_segment", confidence=0.5, rms_db=rms_db)

    spec_mean = compute_spectrogram(samples)
    if spec_mean.size == 0:
        return SpectralResult(cutoff_hz=0.0, lossy_verdict="error", confidence=0.0, rms_db=rms_db)

    cutoff_hz = find_cutoff_hz(spec_mean, SPECTRAL_SAMPLE_RATE)
    verdict, confidence = classify_cutoff(
        cutoff_hz,
        rms_db,
        codec=codec,
        sample_rate=sample_rate,
        film_era=film_era,
    )
    return SpectralResult(
        cutoff_hz=float(cutoff_hz),
        lossy_verdict=verdict,
        confidence=confidence,
        rms_db=rms_db,
    )
