"""Dataclasses pour les resultats d'analyse perceptuelle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FrameMetrics:
    """Metriques extraites d'une frame unique."""

    timestamp: float = 0.0
    y_avg: float = 0.0
    saturation_avg: float = 0.0
    blockiness: float = 0.0
    blur: float = 0.0
    banding_score: int = 0
    effective_bits: float = 0.0
    variance_mean: float = 0.0
    flat_ratio: float = 0.0
    is_dark: bool = False
    skipped: bool = False


@dataclass
class VideoPerceptual:
    """Resultat de l'analyse video perceptuelle (Phase 1)."""

    frames_analyzed: int = 0
    frames_skipped: int = 0
    analysis_duration_s: float = 0.0
    is_bw: bool = False
    color_space: str = "bt709"
    bit_depth_nominal: int = 8
    resolution_width: int = 0
    resolution_height: int = 0

    blockiness_mean: float = 0.0
    blockiness_median: float = 0.0
    blockiness_stddev: float = 0.0
    blur_mean: float = 0.0
    blur_median: float = 0.0
    blur_stddev: float = 0.0
    banding_mean: float = 0.0
    effective_bits_mean: float = 0.0
    variance_mean: float = 0.0
    flat_ratio: float = 0.0
    temporal_stddev: float = 0.0

    y_avg_mean: float = 0.0
    saturation_avg: float = 0.0
    tout_mean: float = 0.0
    vrep_mean: float = 0.0

    dark_frame_count: int = 0
    dark_frame_pct: float = 0.0

    visual_score: int = 0
    visual_tier: str = "degrade"

    # §13 v7.5.0 — SSIM self-referential (detection fake 4K)
    ssim_self_ref: float = -1.0  # -1 = non applicable/non calcule
    upscale_verdict: str = "unknown"
    upscale_confidence: float = 0.0

    # §5 v7.5.0 — HDR10+ multi-frame detection (Pass 2, perceptual opt-in)
    has_hdr10_plus_detected: bool = False

    # §7 v7.5.0 — Fake 4K detection via FFT 2D + combinaison avec §13 SSIM
    fft_hf_ratio_median: Optional[float] = None
    fake_4k_verdict_fft: str = "unknown"
    fake_4k_verdict_combined: str = "unknown"
    fake_4k_combined_confidence: float = 0.0

    # §8 v7.5.0 — Interlacing / Crop / Judder / IMAX
    interlaced_detected: bool = False
    interlace_type: str = "progressive"
    crop_has_bars: bool = False
    crop_verdict: str = "full_frame"
    detected_aspect_ratio: float = 0.0
    detected_crop_w: int = 0
    detected_crop_h: int = 0
    judder_ratio: float = 0.0
    judder_verdict: str = "judder_none"
    is_imax: bool = False
    imax_type: str = "none"
    imax_confidence: float = 0.0

    frames_detail: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise pour stockage JSON."""
        return {
            "frames_analyzed": self.frames_analyzed,
            "frames_skipped": self.frames_skipped,
            "analysis_duration_s": round(self.analysis_duration_s, 2),
            "is_bw": self.is_bw,
            "color_space": self.color_space,
            "bit_depth_nominal": self.bit_depth_nominal,
            "resolution": {"width": self.resolution_width, "height": self.resolution_height},
            "blockiness": {
                "mean": round(self.blockiness_mean, 2),
                "median": round(self.blockiness_median, 2),
                "stddev": round(self.blockiness_stddev, 2),
            },
            "blur": {
                "mean": round(self.blur_mean, 4),
                "median": round(self.blur_median, 4),
                "stddev": round(self.blur_stddev, 4),
            },
            "banding": {"mean_score": round(self.banding_mean, 1)},
            "effective_bit_depth": {"mean_bits": round(self.effective_bits_mean, 2)},
            "local_variance": {
                "mean_variance": round(self.variance_mean, 1),
                "flat_ratio": round(self.flat_ratio, 3),
                "detail_ratio": round(1.0 - self.flat_ratio, 3),
            },
            "temporal_consistency": {"inter_frame_stddev": round(self.temporal_stddev, 2)},
            "dark_scene_stats": {
                "dark_frame_count": self.dark_frame_count,
                "dark_frame_pct": round(self.dark_frame_pct, 1),
            },
            "signalstats": {
                "y_avg_mean": round(self.y_avg_mean, 1),
                "saturation_avg": round(self.saturation_avg, 1),
                "tout_mean": round(self.tout_mean, 4),
                "vrep_mean": round(self.vrep_mean, 4),
            },
            "visual_score": self.visual_score,
            "visual_tier": self.visual_tier,
            "upscale_self_ref": {
                "ssim_y": round(self.ssim_self_ref, 4),
                "verdict": self.upscale_verdict,
                "confidence": round(self.upscale_confidence, 2),
            },
            "hdr10_plus": {
                "detected_multi_frame": self.has_hdr10_plus_detected,
            },
            "fake_4k": {
                "fft_hf_ratio_median": (
                    round(self.fft_hf_ratio_median, 4) if self.fft_hf_ratio_median is not None else None
                ),
                "verdict_fft": self.fake_4k_verdict_fft,
                "verdict_combined": self.fake_4k_verdict_combined,
                "confidence": round(self.fake_4k_combined_confidence, 2),
            },
            "interlacing": {
                "detected": self.interlaced_detected,
                "type": self.interlace_type,
            },
            "crop": {
                "has_bars": self.crop_has_bars,
                "verdict": self.crop_verdict,
                "aspect_ratio": round(self.detected_aspect_ratio, 3),
                "width": self.detected_crop_w,
                "height": self.detected_crop_h,
            },
            "judder": {
                "ratio": round(self.judder_ratio, 4),
                "verdict": self.judder_verdict,
            },
            "imax": {
                "is_imax": self.is_imax,
                "type": self.imax_type,
                "confidence": round(self.imax_confidence, 2),
            },
        }


@dataclass
class GrainAnalysis:
    """Resultat de la detection grain / DNR (Phase 2)."""

    grain_level: float = 0.0
    grain_uniformity: float = 0.0
    flat_zone_count: int = 0
    film_era: str = "unknown"
    tmdb_year: int = 0
    tmdb_genres: List[str] = field(default_factory=list)
    tmdb_budget: int = 0
    is_animation: bool = False
    is_major_studio: bool = False

    verdict: str = "unknown"
    verdict_label: str = ""
    verdict_detail: str = ""
    verdict_confidence: float = 0.0
    dnr_suspect: bool = False
    artificial_grain_suspect: bool = False
    score: int = 50

    # §15 v7.5.0 — Grain Intelligence v2 (section phare)
    film_era_v2: str = "unknown"
    film_format_detected: Optional[str] = None
    expected_grain_level: float = 0.0
    expected_grain_tolerance: float = 0.0
    expected_grain_uniformity_max: float = 0.0
    signature_label: str = "default_era_profile"
    grain_nature: str = "unknown"  # film_grain | encode_noise | post_added | ambiguous | unknown
    grain_nature_confidence: float = 0.0
    temporal_correlation: float = 0.0
    spatial_lag8_ratio: float = 0.0
    spatial_lag16_ratio: float = 0.0
    cross_color_correlation: Optional[float] = None
    is_partial_dnr: bool = False
    texture_loss_ratio: float = 0.0
    texture_variance_actual: float = 0.0
    texture_variance_baseline: float = 0.0
    av1_afgs1_present: bool = False
    historical_context_fr: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialise pour stockage JSON."""
        return {
            "grain_level": round(self.grain_level, 2),
            "grain_uniformity": round(self.grain_uniformity, 3),
            "flat_zone_count": self.flat_zone_count,
            "film_era": self.film_era,
            "tmdb_year": self.tmdb_year,
            "tmdb_genres": list(self.tmdb_genres),
            "tmdb_budget": self.tmdb_budget,
            "is_animation": self.is_animation,
            "is_major_studio": self.is_major_studio,
            "verdict": self.verdict,
            "verdict_label": self.verdict_label,
            "verdict_detail": self.verdict_detail,
            "verdict_confidence": round(self.verdict_confidence, 2),
            "dnr_suspect": self.dnr_suspect,
            "artificial_grain_suspect": self.artificial_grain_suspect,
            "score": self.score,
            "grain_intelligence": {
                "film_era_v2": self.film_era_v2,
                "film_format_detected": self.film_format_detected,
                "expected": {
                    "level_mean": round(self.expected_grain_level, 2),
                    "tolerance": round(self.expected_grain_tolerance, 2),
                    "uniformity_max": round(self.expected_grain_uniformity_max, 3),
                },
                "signature_label": self.signature_label,
                "nature": self.grain_nature,
                "nature_confidence": round(self.grain_nature_confidence, 2),
                "temporal_correlation": round(self.temporal_correlation, 3),
                "spatial_lag8_ratio": round(self.spatial_lag8_ratio, 3),
                "spatial_lag16_ratio": round(self.spatial_lag16_ratio, 3),
                "cross_color_correlation": (
                    round(self.cross_color_correlation, 3) if self.cross_color_correlation is not None else None
                ),
                "dnr_partial": {
                    "is_partial_dnr": self.is_partial_dnr,
                    "texture_loss_ratio": round(self.texture_loss_ratio, 3),
                    "texture_variance_actual": round(self.texture_variance_actual, 1),
                    "texture_variance_baseline": round(self.texture_variance_baseline, 1),
                },
                "av1_afgs1_present": self.av1_afgs1_present,
                "historical_context_fr": self.historical_context_fr,
            },
        }


@dataclass
class AudioPerceptual:
    """Resultat de l'analyse audio perceptuelle (Phase 3)."""

    track_index: int = -1
    track_codec: str = ""
    track_channels: int = 0
    track_language: str = ""
    analysis_duration_s: float = 0.0

    integrated_loudness: Optional[float] = None
    loudness_range: Optional[float] = None
    true_peak: Optional[float] = None

    rms_level: Optional[float] = None
    peak_level: Optional[float] = None
    noise_floor: Optional[float] = None
    crest_factor: Optional[float] = None
    dynamic_range: Optional[float] = None

    clipping_total_segments: int = 0
    clipping_segments: int = 0
    clipping_pct: float = 0.0

    audio_score: int = 0
    audio_tier: str = "degrade"

    # §3 v7.5.0 — Fingerprint Chromaprint
    audio_fingerprint: Optional[str] = None  # base64 des entiers 32-bit
    fingerprint_source: str = "none"  # "fpcalc" | "none" | "error" | "disabled"

    # §9 v7.5.0 — Spectral cutoff (detection lossy)
    spectral_cutoff_hz: float = 0.0
    lossy_verdict: str = "unknown"
    lossy_confidence: float = 0.0

    # §14 v7.5.0 — DRC classification (compression dynamique)
    drc_category: str = "unknown"  # cinema|standard|broadcast_compressed|unknown
    drc_confidence: float = 0.0

    # §12 v7.5.0 — Mel spectrogram (4 analyses derivees)
    mel_soft_clipping_pct: float = 0.0
    mel_mp3_shelf_detected: bool = False
    mel_aac_holes_ratio: float = 0.0
    mel_spectral_flatness: float = 0.0
    mel_score: int = 0
    mel_verdict: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        """Serialise pour stockage JSON."""
        return {
            "track_analyzed": {
                "index": self.track_index,
                "codec": self.track_codec,
                "channels": self.track_channels,
                "language": self.track_language,
            },
            "analysis_duration_s": round(self.analysis_duration_s, 2),
            "ebu_r128": {
                "integrated_loudness": self.integrated_loudness,
                "loudness_range": self.loudness_range,
                "true_peak": self.true_peak,
            },
            "astats": {
                "rms_level": self.rms_level,
                "peak_level": self.peak_level,
                "noise_floor": self.noise_floor,
                "crest_factor": self.crest_factor,
                "dynamic_range": self.dynamic_range,
            },
            "clipping": {
                "total_segments": self.clipping_total_segments,
                "clipping_segments": self.clipping_segments,
                "clipping_pct": round(self.clipping_pct, 2),
            },
            "audio_score": self.audio_score,
            "audio_tier": self.audio_tier,
            "fingerprint": {
                "hash": self.audio_fingerprint,
                "source": self.fingerprint_source,
            },
            "spectral": {
                "cutoff_hz": round(self.spectral_cutoff_hz, 1),
                "lossy_verdict": self.lossy_verdict,
                "confidence": round(self.lossy_confidence, 2),
            },
            "drc": {
                "category": self.drc_category,
                "confidence": round(self.drc_confidence, 2),
            },
            "mel": {
                "soft_clipping_pct": round(self.mel_soft_clipping_pct, 2),
                "mp3_shelf_detected": self.mel_mp3_shelf_detected,
                "aac_holes_ratio": round(self.mel_aac_holes_ratio, 3),
                "spectral_flatness": round(self.mel_spectral_flatness, 3),
                "score": self.mel_score,
                "verdict": self.mel_verdict,
            },
        }


@dataclass
class PerceptualResult:
    """Resultat complet de l'analyse perceptuelle (Phase 4)."""

    version: str = "1.0"
    ts: float = 0.0
    analysis_duration_total_s: float = 0.0

    video: Optional[VideoPerceptual] = None
    grain: Optional[GrainAnalysis] = None
    audio: Optional[AudioPerceptual] = None

    visual_score: int = 0
    audio_score: int = 0
    global_score: int = 0
    global_tier: str = "degrade"

    cross_verdicts: List[Dict[str, str]] = field(default_factory=list)
    settings_used: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise pour stockage JSON."""
        return {
            "version": self.version,
            "ts": self.ts,
            "analysis_duration_total_s": round(self.analysis_duration_total_s, 2),
            "video_perceptual": self.video.to_dict() if self.video else None,
            "grain_analysis": self.grain.to_dict() if self.grain else None,
            "audio_perceptual": self.audio.to_dict() if self.audio else None,
            "visual_score": self.visual_score,
            "audio_score": self.audio_score,
            "global_score": self.global_score,
            "global_tier": self.global_tier,
            "cross_verdicts": list(self.cross_verdicts),
            "settings_used": dict(self.settings_used),
        }


# ---------------------------------------------------------------------------
# §16 v7.5.0 — Score composite V2 (Platinum/Gold/Silver/Bronze/Reject)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubScore:
    """Un sous-score unitaire avec sa confidence."""

    name: str  # identifiant technique (blockiness, hdr_validation, etc.)
    value: float  # 0-100
    weight: float  # poids relatif dans la categorie parente
    confidence: float  # 0.0-1.0
    label_fr: str  # label court UI
    tier: Optional[str] = None  # tier de ce sous-score (platinum/gold/...)
    detail_fr: Optional[str] = None  # phrase explicative UI (accordeon)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": round(float(self.value), 1),
            "weight": float(self.weight),
            "confidence": round(float(self.confidence), 3),
            "label_fr": self.label_fr,
            "tier": self.tier,
            "detail_fr": self.detail_fr,
        }


@dataclass(frozen=True)
class CategoryScore:
    """Score d'une categorie (video / audio / coherence)."""

    name: str  # "video" | "audio" | "coherence"
    value: float  # 0-100 pondere des sub_scores
    weight: float  # poids dans le global (60/35/5)
    confidence: float  # moyenne ponderee des sub_confidences
    tier: str  # tier de la categorie
    sub_scores: List[SubScore] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": round(float(self.value), 1),
            "weight": float(self.weight),
            "confidence": round(float(self.confidence), 3),
            "tier": self.tier,
            "sub_scores": [s.to_dict() for s in self.sub_scores],
        }


@dataclass(frozen=True)
class GlobalScoreResult:
    """Resultat score composite V2 complet."""

    global_score: float  # 0-100
    global_tier: str  # platinum | gold | silver | bronze | reject
    global_confidence: float  # 0.0-1.0
    category_scores: List[CategoryScore] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    adjustments_applied: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "global_score": round(float(self.global_score), 1),
            "global_tier": self.global_tier,
            "global_confidence": round(float(self.global_confidence), 3),
            "category_scores": [c.to_dict() for c in self.category_scores],
            "warnings": list(self.warnings),
            "adjustments_applied": list(self.adjustments_applied),
        }
