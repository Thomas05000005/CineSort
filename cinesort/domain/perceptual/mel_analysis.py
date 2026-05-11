"""Mel spectrogram (§12 v7.5.0) — 4 analyses audio derivees.

Module pur-numpy (cohérent avec §9 spectral_analysis, §7 upscale_detection).

4 detections sur mel spectrogramme :
  - soft clipping (harmoniques regulieres d'un pic fondamental)
  - shelf MP3 16 kHz (signature historique MP3 : drop > 20 dB au-dela de 16k)
  - trous AAC bas bitrate (bandes dont puissance moy < -80 dB)
  - spectral flatness (rapport geometric/arithmetic mean)

Score composite 0-100 pondere 40/20/30/10, verdict textuel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Tuple

import numpy as np

from .constants import (
    MEL_AAC_HOLE_RATIO_SEVERE,
    MEL_AAC_HOLE_RATIO_WARN,
    MEL_AAC_HOLE_THRESHOLD_DB,
    MEL_AAC_SYNTHETIC_VARIANCE_THRESHOLD,
    MEL_FMAX,
    MEL_FMIN,
    MEL_MP3_SHELF_DROP_DB,
    MEL_MP3_SHELF_MIN_FRAMES_PCT,
    MEL_N_FILTERS,
    MEL_SOFT_CLIP_HARMONICS_SEVERE_PCT,
    MEL_SOFT_CLIP_HARMONICS_WARN_PCT,
    MEL_WEIGHT_AAC_HOLES,
    MEL_WEIGHT_FLATNESS,
    MEL_WEIGHT_MP3_SHELF,
    MEL_WEIGHT_SOFT_CLIP,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MelAnalysisResult:
    """Resultat complet de l'analyse Mel."""

    mel_soft_clipping_pct: float
    mel_mp3_shelf_detected: bool
    mel_mp3_shelf_drop_db: float
    mel_aac_holes_ratio: float
    mel_aac_synthetic_variance_ratio: float
    mel_spectral_flatness_mean: float
    mel_score: int
    mel_verdict: str
    # "clean" | "soft_clipped" | "mp3_encoded" | "aac_low_bitrate" | "insufficient_data"


# ---------------------------------------------------------------------------
# Conversions Hz <-> Mel (Slaney 1998)
# ---------------------------------------------------------------------------


def hz_to_mel(hz: float) -> float:
    """Hz -> Mel (Slaney 1998)."""
    return 2595.0 * float(np.log10(1.0 + float(hz) / 700.0))


def mel_to_hz(mel: float) -> float:
    """Mel -> Hz (inverse Slaney 1998)."""
    return 700.0 * (10.0 ** (float(mel) / 2595.0) - 1.0)


# ---------------------------------------------------------------------------
# Filter bank Mel
# ---------------------------------------------------------------------------


def build_mel_filter_bank(
    n_filters: int = MEL_N_FILTERS,
    sample_rate: int = 48000,
    n_fft: int = 4096,
    fmin: float = MEL_FMIN,
    fmax: float = MEL_FMAX,
) -> np.ndarray:
    """Construit un filter bank triangulaire Mel.

    Args:
        n_filters: nombre de filtres triangulaires.
        sample_rate: SR de l'audio source (Hz).
        n_fft: taille FFT source.
        fmin, fmax: bornes frequentielles (Hz).

    Returns:
        np.ndarray shape (n_filters, n_fft // 2 + 1). Chaque filtre est
        triangulaire (0 aux extremes, 1 au centre). Peut avoir des filtres
        a zero si leur centre tombe au-dela de Nyquist.
    """
    n_freqs = int(n_fft) // 2 + 1
    freqs_hz = np.linspace(0.0, float(sample_rate) / 2.0, n_freqs)

    # Espacement uniforme en Mel
    mel_min = hz_to_mel(float(fmin))
    mel_max = hz_to_mel(min(float(fmax), float(sample_rate) / 2.0))
    mel_points = np.linspace(mel_min, mel_max, int(n_filters) + 2)
    hz_points = np.array([mel_to_hz(m) for m in mel_points])

    filters = np.zeros((int(n_filters), n_freqs), dtype=np.float64)
    for i in range(int(n_filters)):
        left = hz_points[i]
        center = hz_points[i + 1]
        right = hz_points[i + 2]
        # Branche montante
        if center > left:
            rising = (freqs_hz - left) / (center - left)
            rising = np.clip(rising, 0.0, None)
        else:
            rising = np.zeros(n_freqs)
        # Branche descendante
        if right > center:
            falling = (right - freqs_hz) / (right - center)
            falling = np.clip(falling, 0.0, None)
        else:
            falling = np.zeros(n_freqs)
        triangle = np.minimum(rising, falling)
        filters[i] = np.clip(triangle, 0.0, 1.0)
    return filters


def apply_mel_filters(
    spectrogram: np.ndarray,
    mel_filters: np.ndarray,
) -> np.ndarray:
    """Applique le filter bank au spectrogramme STFT magnitude.

    Args:
        spectrogram: shape (n_frames, n_freqs).
        mel_filters: shape (n_filters, n_freqs).

    Returns:
        Mel spectrogram shape (n_frames, n_filters), non-negatif.
    """
    # spec @ filters.T : (n_frames, n_filters)
    mel = spectrogram @ mel_filters.T
    return np.maximum(mel, 0.0)


def mel_to_db(mel_spec: np.ndarray, top_db: float = 80.0, eps: float = 1e-10) -> np.ndarray:
    """Conversion lineaire -> dB, clippe a [-top_db, 0]."""
    max_val = float(mel_spec.max()) if mel_spec.size > 0 else 1.0
    ref = max(max_val, eps)
    db = 20.0 * np.log10(np.maximum(mel_spec, eps) / ref)
    return np.clip(db, -float(top_db), 0.0)


# ---------------------------------------------------------------------------
# Spectrogramme STFT (cohérent §9 spectral_analysis)
# ---------------------------------------------------------------------------


def _compute_stft_magnitude(
    samples: np.ndarray,
    n_fft: int = 4096,
    hop: int = 2048,
) -> np.ndarray:
    """STFT magnitude (Hann window), retourne shape (n_frames, n_freqs)."""
    if samples is None or samples.size < n_fft:
        return np.zeros((0, n_fft // 2 + 1), dtype=np.float64)
    hann = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n_fft) / (n_fft - 1))
    n_frames = (len(samples) - n_fft) // hop + 1
    if n_frames <= 0:
        return np.zeros((0, n_fft // 2 + 1), dtype=np.float64)
    result = np.zeros((n_frames, n_fft // 2 + 1), dtype=np.float64)
    for i in range(n_frames):
        start = i * hop
        block = samples[start : start + n_fft].astype(np.float64, copy=False) * hann
        result[i] = np.abs(np.fft.rfft(block))
    return result


# ---------------------------------------------------------------------------
# Detections
# ---------------------------------------------------------------------------


def _mel_filter_freqs(n_filters: int, sample_rate: int, fmin: float, fmax: float) -> np.ndarray:
    """Frequences centrales (Hz) des filtres Mel."""
    mel_min = hz_to_mel(float(fmin))
    mel_max = hz_to_mel(min(float(fmax), float(sample_rate) / 2.0))
    mel_points = np.linspace(mel_min, mel_max, int(n_filters) + 2)
    # Centres = points 1..n (exclut points 0 et n+1 qui sont les bords)
    centers = np.array([mel_to_hz(m) for m in mel_points[1:-1]])
    return centers


def detect_soft_clipping(
    mel_spec_db: np.ndarray,
    mel_freqs_hz: np.ndarray,
) -> Dict[str, Any]:
    """Detection soft clipping via harmoniques regulieres.

    Pour chaque frame :
      - Trouve les pics locaux sous 6000 Hz.
      - Pour chaque pic f, verifie si 2f, 3f, 4f sont aussi presents (> -40 dB).
      - Si >= 2 harmoniques detectees -> frame "clippee".

    Returns:
        {"pct_frames_with_harmonics": float, "verdict": str}
    """
    if mel_spec_db.size == 0 or mel_freqs_hz.size == 0:
        return {"pct_frames_with_harmonics": 0.0, "verdict": "insufficient"}

    n_frames = mel_spec_db.shape[0]
    frames_with_harmonics = 0
    fundamental_mask = mel_freqs_hz < 6000.0
    fundamental_idx = np.where(fundamental_mask)[0]
    if fundamental_idx.size == 0:
        return {"pct_frames_with_harmonics": 0.0, "verdict": "insufficient"}

    for i in range(n_frames):
        frame = mel_spec_db[i]
        # Pics locaux dans la bande fondamentale : bande avec valeur
        # > voisins et > -40 dB
        peak_count_with_harmonics = 0
        for fi in fundamental_idx[1:-1]:
            value = frame[fi]
            if value < -40.0:
                continue
            if value <= frame[fi - 1] or value <= frame[fi + 1]:
                continue
            # Chercher harmoniques 2f, 3f, 4f
            f0 = mel_freqs_hz[fi]
            harmonics_found = 0
            for mult in (2, 3, 4):
                target = f0 * mult
                if target > mel_freqs_hz[-1]:
                    break
                # Trouve le filtre le plus proche
                h_idx = int(np.argmin(np.abs(mel_freqs_hz - target)))
                if frame[h_idx] > -40.0:
                    harmonics_found += 1
            if harmonics_found >= 2:
                peak_count_with_harmonics += 1
                break  # un seul pic suffit a flagger la frame
        if peak_count_with_harmonics > 0:
            frames_with_harmonics += 1

    pct = 100.0 * frames_with_harmonics / max(1, n_frames)
    if pct < MEL_SOFT_CLIP_HARMONICS_WARN_PCT:
        verdict = "normal"
    elif pct < MEL_SOFT_CLIP_HARMONICS_SEVERE_PCT:
        verdict = "warn"
    else:
        verdict = "severe"
    return {"pct_frames_with_harmonics": pct, "verdict": verdict}


def detect_mp3_shelf(
    mel_spec_db: np.ndarray,
    mel_freqs_hz: np.ndarray,
) -> Dict[str, Any]:
    """Detecte la signature shelf MP3 a 16 kHz.

    - Puissance moy bandes [14000, 16000] Hz
    - Puissance moy bandes [16000, 18000] Hz
    - drop = puissance_avant - puissance_apres (dB)
    - shelf detecte si drop > seuil sur >= 70% frames

    Returns: {"shelf_detected": bool, "shelf_drop_db": float, "frames_pct": float}
    """
    if mel_spec_db.size == 0 or mel_freqs_hz.size == 0:
        return {"shelf_detected": False, "shelf_drop_db": 0.0, "frames_pct": 0.0}

    before_mask = (mel_freqs_hz >= 14000.0) & (mel_freqs_hz < 16000.0)
    after_mask = (mel_freqs_hz >= 16000.0) & (mel_freqs_hz < 18000.0)
    before_idx = np.where(before_mask)[0]
    after_idx = np.where(after_mask)[0]
    if before_idx.size == 0 or after_idx.size == 0:
        # Nyquist insuffisant, pas de shelf mesurable
        return {"shelf_detected": False, "shelf_drop_db": 0.0, "frames_pct": 0.0}

    drops = []
    for i in range(mel_spec_db.shape[0]):
        before_pow = float(np.mean(mel_spec_db[i, before_idx]))
        after_pow = float(np.mean(mel_spec_db[i, after_idx]))
        drops.append(before_pow - after_pow)

    drops_arr = np.asarray(drops, dtype=np.float64)
    mean_drop = float(drops_arr.mean()) if drops_arr.size > 0 else 0.0
    frames_with_shelf = int(np.sum(drops_arr > MEL_MP3_SHELF_DROP_DB))
    frames_pct = 100.0 * frames_with_shelf / max(1, drops_arr.size)
    shelf_detected = frames_pct >= MEL_MP3_SHELF_MIN_FRAMES_PCT
    return {
        "shelf_detected": shelf_detected,
        "shelf_drop_db": mean_drop,
        "frames_pct": frames_pct,
    }


def detect_aac_holes(
    mel_spec_db: np.ndarray,
    mel_freqs_hz: np.ndarray,
) -> Dict[str, Any]:
    """Detecte trous spectraux AAC bas bitrate.

    - hole_ratio : fraction de bandes avec puissance moy < -80 dB
    - synthetic_ratio : fraction de bandes avec variance temporelle < 0.05

    Returns: {"hole_ratio": float, "synthetic_ratio": float, "verdict": str}
    """
    if mel_spec_db.size == 0:
        return {"hole_ratio": 0.0, "synthetic_ratio": 0.0, "verdict": "insufficient"}

    # Ne considerer que les bandes dans la plage audible <= 20 kHz
    valid_mask = mel_freqs_hz <= 20000.0
    valid_idx = np.where(valid_mask)[0]
    if valid_idx.size == 0:
        return {"hole_ratio": 0.0, "synthetic_ratio": 0.0, "verdict": "insufficient"}

    band_means = mel_spec_db[:, valid_idx].mean(axis=0)
    band_vars = mel_spec_db[:, valid_idx].var(axis=0)

    n_bands = int(valid_idx.size)
    holes = int(np.sum(band_means < MEL_AAC_HOLE_THRESHOLD_DB))
    # "Synthetic" = variance quasi nulle (bande re-synthetisee ou constante)
    synth = int(np.sum(band_vars < MEL_AAC_SYNTHETIC_VARIANCE_THRESHOLD))
    hole_ratio = holes / max(1, n_bands)
    synth_ratio = synth / max(1, n_bands)

    if hole_ratio >= MEL_AAC_HOLE_RATIO_SEVERE:
        verdict = "severe"
    elif hole_ratio >= MEL_AAC_HOLE_RATIO_WARN:
        verdict = "warn"
    else:
        verdict = "normal"

    return {
        "hole_ratio": hole_ratio,
        "synthetic_ratio": synth_ratio,
        "verdict": verdict,
    }


def compute_spectral_flatness(mel_spec_linear: np.ndarray) -> float:
    """Spectral flatness moyenne (rapport geo mean / arithmetic mean).

    Returns: float 0.0-1.0 (1.0 = bruit blanc, 0.0 = ton pur).
    """
    if mel_spec_linear.size == 0:
        return 0.0
    eps = 1e-10
    arr = np.maximum(mel_spec_linear.astype(np.float64, copy=False), eps)
    # Par frame : exp(mean(log(x))) / mean(x)
    log_mean = np.mean(np.log(arr), axis=1)
    arith_mean = np.mean(arr, axis=1)
    geo_mean = np.exp(log_mean)
    # Evite division par zero
    flatness = np.where(arith_mean > eps, geo_mean / arith_mean, 0.0)
    return float(np.clip(np.mean(flatness), 0.0, 1.0))


# ---------------------------------------------------------------------------
# Score composite
# ---------------------------------------------------------------------------


def _score_from_soft_clip(soft_clip: Dict[str, Any]) -> int:
    """Score 0-100 pour le soft clipping (moins = mieux)."""
    pct = float(soft_clip.get("pct_frames_with_harmonics", 0.0))
    if pct < MEL_SOFT_CLIP_HARMONICS_WARN_PCT:
        return 100
    if pct < MEL_SOFT_CLIP_HARMONICS_SEVERE_PCT:
        # Interpolation lineaire 100 -> 40
        span = MEL_SOFT_CLIP_HARMONICS_SEVERE_PCT - MEL_SOFT_CLIP_HARMONICS_WARN_PCT
        pos = (pct - MEL_SOFT_CLIP_HARMONICS_WARN_PCT) / max(span, 1e-9)
        return int(100 - 60 * pos)
    # > severe : 40 -> 0
    return max(0, int(40 - (pct - MEL_SOFT_CLIP_HARMONICS_SEVERE_PCT) * 1.0))


def _score_from_mp3_shelf(mp3_shelf: Dict[str, Any]) -> int:
    """Score 0-100 : 100 si pas de shelf, 30 si shelf detecte."""
    if bool(mp3_shelf.get("shelf_detected", False)):
        return 30
    drop = float(mp3_shelf.get("shelf_drop_db", 0.0))
    # Interpolation : 0 dB -> 100, 20 dB -> 70
    return int(max(0, min(100, 100 - drop * 1.5)))


def _score_from_aac_holes(aac_holes: Dict[str, Any]) -> int:
    """Score 0-100 en fonction du ratio de trous."""
    ratio = float(aac_holes.get("hole_ratio", 0.0))
    if ratio < MEL_AAC_HOLE_RATIO_WARN:
        return 100
    if ratio < MEL_AAC_HOLE_RATIO_SEVERE:
        span = MEL_AAC_HOLE_RATIO_SEVERE - MEL_AAC_HOLE_RATIO_WARN
        pos = (ratio - MEL_AAC_HOLE_RATIO_WARN) / max(span, 1e-9)
        return int(100 - 60 * pos)
    return max(0, int(40 - (ratio - MEL_AAC_HOLE_RATIO_SEVERE) * 200))


def _score_from_flatness(flatness: float) -> int:
    """Score flatness : 100 si flatness intermediaire (musique/parole normales).

    Une flatness trop eleve = bruit blanc / insuffisance signal.
    Une flatness tres faible = ton pur / signal artificiel.
    Penalite symetrique autour d'un sweet spot ~0.3.
    """
    sweet_spot = 0.3
    deviation = abs(float(flatness) - sweet_spot)
    # 0.0 deviation -> 100, 0.5 deviation -> 50
    return max(0, min(100, int(100 - deviation * 100)))


def compute_mel_score(
    soft_clip: Dict[str, Any],
    mp3_shelf: Dict[str, Any],
    aac_holes: Dict[str, Any],
    flatness: float,
) -> Tuple[int, str]:
    """Score composite Mel 0-100 + verdict textuel.

    Verdicts priorises :
      1. "mp3_encoded" si shelf detecte
      2. "aac_low_bitrate" si hole_ratio severe
      3. "soft_clipped" si soft_clip severe
      4. sinon "clean" si score >= 70, "insufficient_data" sinon
    """
    s_soft = _score_from_soft_clip(soft_clip)
    s_mp3 = _score_from_mp3_shelf(mp3_shelf)
    s_aac = _score_from_aac_holes(aac_holes)
    s_flat = _score_from_flatness(flatness)

    total_weight = MEL_WEIGHT_SOFT_CLIP + MEL_WEIGHT_MP3_SHELF + MEL_WEIGHT_AAC_HOLES + MEL_WEIGHT_FLATNESS
    weighted = (
        s_soft * MEL_WEIGHT_SOFT_CLIP
        + s_mp3 * MEL_WEIGHT_MP3_SHELF
        + s_aac * MEL_WEIGHT_AAC_HOLES
        + s_flat * MEL_WEIGHT_FLATNESS
    )
    score = int(round(weighted / total_weight))
    score = max(0, min(100, score))

    # Verdict
    if bool(mp3_shelf.get("shelf_detected", False)):
        verdict = "mp3_encoded"
    elif aac_holes.get("verdict") == "severe":
        verdict = "aac_low_bitrate"
    elif soft_clip.get("verdict") == "severe":
        verdict = "soft_clipped"
    elif score >= 70:
        verdict = "clean"
    else:
        verdict = "insufficient_data"

    return (score, verdict)


# ---------------------------------------------------------------------------
# Orchestrateur
# ---------------------------------------------------------------------------


def analyze_mel(
    samples: np.ndarray,
    sample_rate: int = 48000,
    n_fft: int = 4096,
    hop: int = 2048,
    n_filters: int = MEL_N_FILTERS,
) -> MelAnalysisResult:
    """Analyse Mel complete sur un signal audio mono PCM float32.

    Args:
        samples: np.ndarray 1D float (sortie extract_audio_segment §9).
        sample_rate: SR du signal.
        n_fft, hop: parametres STFT.
        n_filters: nombre de filtres Mel.

    Returns:
        MelAnalysisResult avec les 4 metriques + score + verdict.
    """
    # Guard : trop peu de samples
    if samples is None or samples.size < n_fft:
        return MelAnalysisResult(
            mel_soft_clipping_pct=0.0,
            mel_mp3_shelf_detected=False,
            mel_mp3_shelf_drop_db=0.0,
            mel_aac_holes_ratio=0.0,
            mel_aac_synthetic_variance_ratio=0.0,
            mel_spectral_flatness_mean=0.0,
            mel_score=0,
            mel_verdict="insufficient_data",
        )

    # 1. STFT magnitude
    spec = _compute_stft_magnitude(samples, n_fft=n_fft, hop=hop)
    if spec.shape[0] == 0:
        return MelAnalysisResult(
            mel_soft_clipping_pct=0.0,
            mel_mp3_shelf_detected=False,
            mel_mp3_shelf_drop_db=0.0,
            mel_aac_holes_ratio=0.0,
            mel_aac_synthetic_variance_ratio=0.0,
            mel_spectral_flatness_mean=0.0,
            mel_score=0,
            mel_verdict="insufficient_data",
        )

    # 2. Filter bank + mel spectrogramme
    filters = build_mel_filter_bank(
        n_filters=n_filters,
        sample_rate=sample_rate,
        n_fft=n_fft,
        fmin=MEL_FMIN,
        fmax=min(MEL_FMAX, sample_rate / 2.0),
    )
    mel_spec_linear = apply_mel_filters(spec, filters)
    mel_spec_db = mel_to_db(mel_spec_linear)
    mel_freqs = _mel_filter_freqs(n_filters, sample_rate, MEL_FMIN, min(MEL_FMAX, sample_rate / 2.0))

    # 3. Detections
    soft_clip = detect_soft_clipping(mel_spec_db, mel_freqs)
    mp3_shelf = detect_mp3_shelf(mel_spec_db, mel_freqs)
    aac_holes = detect_aac_holes(mel_spec_db, mel_freqs)
    flatness = compute_spectral_flatness(mel_spec_linear)

    # 4. Score composite + verdict
    score, verdict = compute_mel_score(soft_clip, mp3_shelf, aac_holes, flatness)

    return MelAnalysisResult(
        mel_soft_clipping_pct=float(soft_clip.get("pct_frames_with_harmonics", 0.0)),
        mel_mp3_shelf_detected=bool(mp3_shelf.get("shelf_detected", False)),
        mel_mp3_shelf_drop_db=float(mp3_shelf.get("shelf_drop_db", 0.0)),
        mel_aac_holes_ratio=float(aac_holes.get("hole_ratio", 0.0)),
        mel_aac_synthetic_variance_ratio=float(aac_holes.get("synthetic_ratio", 0.0)),
        mel_spectral_flatness_mean=float(flatness),
        mel_score=score,
        mel_verdict=verdict,
    )
