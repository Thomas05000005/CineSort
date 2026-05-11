"""§16 v7.5.0 — Score composite V2 (Platinum/Gold/Silver/Bronze/Reject).

Remplace progressivement `composite_score.py` v1. Agrege toutes les metriques
des sections §3-§15 en :
    - 3 categories ponderees (Video 60% / Audio 35% / Coherence 5%)
    - 9 regles d'ajustement contextuel
    - confidence-weighted scoring
    - warnings auto-collectes

Coexiste avec la v1 (composite_score.py reste le comportement par defaut pour
les rows historiques). La v2 est stockee separement en BDD.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .constants import (
    ADJUSTMENT_AV1_AFGS1_BONUS,
    ADJUSTMENT_DV_PROFILE_5_MALUS,
    ADJUSTMENT_FAKE_LOSSLESS_MALUS,
    ADJUSTMENT_GRAIN_ENCODE_NOISE_MALUS,
    ADJUSTMENT_GRAIN_FILM_BONUS,
    ADJUSTMENT_GRAIN_PARTIAL_DNR_MALUS,
    ADJUSTMENT_HDR_METADATA_MISSING_MALUS,
    ADJUSTMENT_IMAX_EXPANSION_BONUS,
    ADJUSTMENT_IMAX_TYPED_BONUS,
    AUDIO_WEIGHT_CHROMAPRINT,
    AUDIO_WEIGHT_DRC,
    AUDIO_WEIGHT_PERCEPTUAL_V2,
    AUDIO_WEIGHT_RESERVE,
    AUDIO_WEIGHT_SPECTRAL,
    CATEGORY_IMBALANCE_WARN_DELTA,
    COHERENCE_WEIGHT_NFO,
    COHERENCE_WEIGHT_RUNTIME,
    CONFIDENCE_LOW_WARN_THRESHOLD,
    GLOBAL_WEIGHT_AUDIO_V2,
    GLOBAL_WEIGHT_COHERENCE_V2,
    GLOBAL_WEIGHT_VIDEO_V2,
    SHORT_FILE_WARN_DURATION_S,
    TIER_BRONZE_THRESHOLD,
    TIER_GOLD_THRESHOLD,
    TIER_PLATINUM_THRESHOLD,
    TIER_SILVER_THRESHOLD,
    VIDEO_WEIGHT_HDR,
    VIDEO_WEIGHT_LPIPS,
    VIDEO_WEIGHT_PERCEPTUAL,
    VIDEO_WEIGHT_RESOLUTION,
)
from .models import CategoryScore, GlobalScoreResult, SubScore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(v)))


def determine_tier_v2(score: float) -> str:
    """Score 0-100 -> tier string."""
    s = float(score)
    if s >= TIER_PLATINUM_THRESHOLD:
        return "platinum"
    if s >= TIER_GOLD_THRESHOLD:
        return "gold"
    if s >= TIER_SILVER_THRESHOLD:
        return "silver"
    if s >= TIER_BRONZE_THRESHOLD:
        return "bronze"
    return "reject"


def weighted_score_with_confidence(
    scores: List[Tuple[float, float, float]],  # [(value, weight, confidence)]
) -> Tuple[float, float]:
    """Calcule un score pondere + confidence moyenne ponderee.

    - Le poids effectif de chaque item = weight * confidence.
    - Si tous les items ont confidence = 0 -> renvoyer (50.0, 0.0) fallback neutre.
    - Si la liste est vide -> (50.0, 0.0).
    """
    if not scores:
        return 50.0, 0.0
    total_eff_weight = 0.0
    weighted_sum = 0.0
    total_raw_weight = 0.0
    weighted_conf_sum = 0.0
    for value, weight, confidence in scores:
        w = float(weight)
        c = max(0.0, min(1.0, float(confidence)))
        eff = w * c
        total_eff_weight += eff
        weighted_sum += float(value) * eff
        total_raw_weight += w
        weighted_conf_sum += c * w
    if total_eff_weight <= 0:
        return 50.0, 0.0
    score = weighted_sum / total_eff_weight
    mean_conf = weighted_conf_sum / total_raw_weight if total_raw_weight > 0 else 0.0
    return _clamp(score), max(0.0, min(1.0, mean_conf))


# ---------------------------------------------------------------------------
# §16 — Builders sub-scores
# ---------------------------------------------------------------------------


def _score_from_visual(video: Any) -> Tuple[float, float]:
    """Score 'perceptual visual' depuis VideoPerceptual.visual_score."""
    if video is None:
        return 50.0, 0.0
    val = float(getattr(video, "visual_score", 0) or 0)
    conf = 1.0 if getattr(video, "frames_analyzed", 0) >= 5 else 0.5
    return val, conf


def _score_resolution(video: Any) -> Tuple[float, float, str]:
    """Score resolution + detection fake 4K.

    Returns (value, confidence, tier).
    """
    if video is None:
        return 50.0, 0.0, "bronze"
    width = int(getattr(video, "resolution_width", 0) or 0)
    height = int(getattr(video, "resolution_height", 0) or 0)
    fake = str(getattr(video, "fake_4k_verdict_combined", "unknown") or "unknown")
    if fake.startswith("fake_4k"):
        return 30.0, 0.9, "reject"  # upscale deguise en 4K
    if width >= 3800 or height >= 2100:
        return 100.0, 1.0, "platinum"  # vrai 4K/UHD
    if width >= 1900 or height >= 1060:
        return 85.0, 1.0, "gold"  # 1080p
    if width >= 1280 or height >= 680:
        return 70.0, 1.0, "silver"  # 720p
    if width > 0:
        return 50.0, 1.0, "bronze"  # SD
    return 50.0, 0.0, "bronze"


def _score_hdr(video: Any, normalized_probe: Optional[Dict[str, Any]]) -> Tuple[float, float, List[str]]:
    """Score HDR + detection profile DV + metadata integrity.

    Returns (value, confidence, flags). Flags = ["dv_profile_5", "hdr_metadata_missing", ...]
    """
    flags: List[str] = []
    if video is None:
        return 50.0, 0.0, flags

    video_data = (normalized_probe or {}).get("video") or {}
    has_hdr10 = bool(video_data.get("has_hdr10"))
    has_hdr10_plus = bool(getattr(video, "has_hdr10_plus_detected", False)) or bool(video_data.get("has_hdr10_plus"))
    has_dv = bool(video_data.get("has_dv"))
    dv_profile = str(video_data.get("dv_profile") or "").strip()
    max_cll = video_data.get("max_cll")
    max_fall = video_data.get("max_fall")

    if has_dv and dv_profile == "5":
        flags.append("dv_profile_5")
    if has_hdr10 and (max_cll is None or max_fall is None):
        flags.append("hdr_metadata_missing")

    if has_dv and dv_profile in ("8.1", "8.2", "8.4"):
        return 100.0, 1.0, flags  # DV avec fallback HDR10, excellent
    if has_hdr10_plus:
        return 95.0, 1.0, flags
    if has_dv and dv_profile == "5":
        return 80.0, 1.0, flags  # DV5 fonctionne mais pas de fallback
    if has_hdr10:
        base = 85.0 if not flags else 75.0
        return base, 1.0, flags
    # SDR : score neutre, confidence faible (HDR pas pertinent pour certains films)
    return 60.0, 0.3, flags


def _score_lpips(lpips_result: Any) -> Optional[Tuple[float, float]]:
    """Convertit LpipsResult.distance_median en score 0-100 (distance faible = score eleve).

    Returns None si LPIPS indisponible (pas de deep-compare).
    """
    if lpips_result is None:
        return None
    dist = getattr(lpips_result, "distance_median", None)
    if dist is None:
        return None
    # 0.0 -> 100, 0.5 -> 0 (distance > 0.5 = fichiers tres differents)
    score = _clamp(100.0 * (1.0 - min(float(dist), 0.5) * 2.0))
    return score, 1.0


def build_video_subscores(
    video: Any,
    grain: Any,
    normalized_probe: Optional[Dict[str, Any]],
    lpips_result: Any = None,
) -> Tuple[List[SubScore], List[str]]:
    """Construit les sous-scores video (4 ou 5 avec LPIPS).

    Returns (sub_scores, hdr_flags).
    """
    subs: List[SubScore] = []

    # Perceptual visual (50%)
    val, conf = _score_from_visual(video)
    subs.append(
        SubScore(
            name="perceptual_visual",
            value=val,
            weight=VIDEO_WEIGHT_PERCEPTUAL,
            confidence=conf,
            label_fr="Analyse perceptuelle (block/blur/banding)",
            tier=determine_tier_v2(val),
            detail_fr=(
                f"Score perceptuel synthetique ({getattr(video, 'visual_tier', 'inconnu')}). "
                "Combine blockiness, blur, banding, profondeur effective et grain."
            ),
        )
    )

    # Resolution effective (20%)
    val, conf, tier = _score_resolution(video)
    subs.append(
        SubScore(
            name="resolution",
            value=val,
            weight=VIDEO_WEIGHT_RESOLUTION,
            confidence=conf,
            label_fr="Resolution effective",
            tier=tier,
            detail_fr=(
                f"{getattr(video, 'resolution_width', 0)}x{getattr(video, 'resolution_height', 0)}. "
                "Tient compte de la detection fake 4K (FFT + SSIM self-ref)."
            ),
        )
    )

    # HDR validation (15%)
    val, conf, hdr_flags = _score_hdr(video, normalized_probe)
    subs.append(
        SubScore(
            name="hdr_validation",
            value=val,
            weight=VIDEO_WEIGHT_HDR,
            confidence=conf,
            label_fr="Validation HDR/DV",
            tier=determine_tier_v2(val),
            detail_fr="Presence et qualite des metadonnees HDR10/HDR10+/DV.",
        )
    )

    # LPIPS (15%) — optionnel
    lpips_pair = _score_lpips(lpips_result)
    if lpips_pair is not None:
        val, conf = lpips_pair
        subs.append(
            SubScore(
                name="lpips_distance",
                value=val,
                weight=VIDEO_WEIGHT_LPIPS,
                confidence=conf,
                label_fr="Distance perceptuelle apprise (LPIPS)",
                tier=determine_tier_v2(val),
                detail_fr="Similarite perceptuelle CNN. Utilisee en mode comparaison.",
            )
        )

    return subs, hdr_flags


def _score_audio_perceptual(audio: Any) -> Tuple[float, float]:
    if audio is None:
        return 50.0, 0.0
    val = float(getattr(audio, "audio_score", 0) or 0)
    conf = 0.8 if val > 0 else 0.0
    return val, conf


def _score_audio_spectral(audio: Any) -> Tuple[float, float, str]:
    """Score derive du verdict lossy §9."""
    if audio is None:
        return 50.0, 0.0, "bronze"
    verdict = str(getattr(audio, "lossy_verdict", "unknown") or "unknown")
    conf = float(getattr(audio, "lossy_confidence", 0) or 0)
    if verdict == "lossless":
        return 100.0, max(conf, 0.8), "platinum"
    if verdict == "high_bitrate_lossy":
        return 75.0, max(conf, 0.7), "gold"
    if verdict == "medium_bitrate_lossy":
        return 55.0, max(conf, 0.7), "silver"
    if verdict == "low_bitrate_lossy":
        return 30.0, max(conf, 0.7), "bronze"
    return 60.0, 0.0, "bronze"


def _score_audio_drc(audio: Any) -> Tuple[float, float]:
    """Score derive de la classification DRC §14."""
    if audio is None:
        return 50.0, 0.0
    category = str(getattr(audio, "drc_category", "unknown") or "unknown")
    conf = float(getattr(audio, "drc_confidence", 0) or 0)
    if category == "cinema":
        return 100.0, max(conf, 0.7)
    if category == "standard":
        return 85.0, max(conf, 0.6)
    if category == "broadcast_compressed":
        return 60.0, max(conf, 0.7)
    return 70.0, 0.0


def _score_audio_chromaprint(audio: Any) -> Tuple[float, float]:
    """Presence d'un fingerprint = audio exploitable."""
    if audio is None:
        return 50.0, 0.0
    source = str(getattr(audio, "fingerprint_source", "none") or "none")
    if source == "fpcalc":
        return 100.0, 0.9
    if source == "error":
        return 50.0, 0.3
    return 70.0, 0.0  # disabled/none : pas pertinent


def build_audio_subscores(audio: Any) -> List[SubScore]:
    """~4 sous-scores audio (+1 reserve pour NR-VMAF futur)."""
    subs: List[SubScore] = []

    val, conf = _score_audio_perceptual(audio)
    subs.append(
        SubScore(
            name="perceptual_audio",
            value=val,
            weight=AUDIO_WEIGHT_PERCEPTUAL_V2,
            confidence=conf,
            label_fr="Analyse perceptuelle audio",
            tier=determine_tier_v2(val),
            detail_fr=(
                f"Tier audio {getattr(audio, 'audio_tier', 'inconnu')}. "
                "Combine EBU R128 (LRA, integrated), clipping, bruit de fond."
            ),
        )
    )

    val, conf, tier = _score_audio_spectral(audio)
    subs.append(
        SubScore(
            name="spectral_cutoff",
            value=val,
            weight=AUDIO_WEIGHT_SPECTRAL,
            confidence=conf,
            label_fr="Spectre audio (lossy/lossless)",
            tier=tier,
            detail_fr=(
                f"Verdict §9 : {getattr(audio, 'lossy_verdict', 'inconnu')}. "
                f"Cutoff {float(getattr(audio, 'spectral_cutoff_hz', 0) or 0):.0f} Hz."
            ),
        )
    )

    val, conf = _score_audio_drc(audio)
    subs.append(
        SubScore(
            name="drc_category",
            value=val,
            weight=AUDIO_WEIGHT_DRC,
            confidence=conf,
            label_fr="Compression dynamique (DRC)",
            tier=determine_tier_v2(val),
            detail_fr=f"Categorie §14 : {getattr(audio, 'drc_category', 'inconnu')}.",
        )
    )

    val, conf = _score_audio_chromaprint(audio)
    subs.append(
        SubScore(
            name="chromaprint",
            value=val,
            weight=AUDIO_WEIGHT_CHROMAPRINT,
            confidence=conf,
            label_fr="Empreinte audio",
            tier=determine_tier_v2(val),
            detail_fr="Fingerprint Chromaprint §3 (identification audio robuste).",
        )
    )

    # Reserve pour extensions futures (pas de sub-score visible, poids conserve pour renormalisation)
    subs.append(
        SubScore(
            name="reserve",
            value=70.0,
            weight=AUDIO_WEIGHT_RESERVE,
            confidence=0.0,  # confidence 0 → poids effectif 0
            label_fr="Reserve extensions",
            tier=None,
            detail_fr="Reserve pour futurs critères audio (NR-VMAF, timbre, etc.).",
        )
    )
    return subs


def _score_runtime(runtime_vs_tmdb_flag: Optional[str]) -> Tuple[float, float]:
    """Score coherence runtime vs TMDb."""
    if not runtime_vs_tmdb_flag:
        return 80.0, 0.0
    flag = str(runtime_vs_tmdb_flag).lower()
    if flag in ("match", "ok", "runtime_ok"):
        return 100.0, 1.0
    if flag in ("warn", "runtime_warn"):
        return 70.0, 1.0  # Theatrical vs Extended envisageable
    if flag in ("mismatch", "runtime_mismatch"):
        return 40.0, 1.0
    return 80.0, 0.0


def _score_nfo(nfo_consistency: Optional[Dict[str, Any]]) -> Tuple[float, float]:
    """Score coherence NFO vs fichier."""
    if not nfo_consistency:
        return 80.0, 0.0
    consistent = bool(nfo_consistency.get("consistent"))
    has_tmdb = bool(nfo_consistency.get("has_tmdb_id"))
    conf = 1.0 if "consistent" in nfo_consistency else 0.0
    if consistent and has_tmdb:
        return 100.0, conf
    if consistent:
        return 85.0, conf
    return 40.0, conf


def build_coherence_subscores(
    runtime_vs_tmdb_flag: Optional[str],
    nfo_consistency: Optional[Dict[str, Any]],
) -> List[SubScore]:
    subs: List[SubScore] = []

    val, conf = _score_runtime(runtime_vs_tmdb_flag)
    subs.append(
        SubScore(
            name="runtime_match",
            value=val,
            weight=COHERENCE_WEIGHT_RUNTIME,
            confidence=conf,
            label_fr="Duree reelle vs TMDb",
            tier=determine_tier_v2(val),
            detail_fr="Comparaison runtime du fichier avec TMDb. Ecart = possible cut alternatif.",
        )
    )
    val, conf = _score_nfo(nfo_consistency)
    subs.append(
        SubScore(
            name="nfo_consistency",
            value=val,
            weight=COHERENCE_WEIGHT_NFO,
            confidence=conf,
            label_fr="Coherence NFO",
            tier=determine_tier_v2(val),
            detail_fr="Alignement entre metadonnees NFO et titre/annee detecte.",
        )
    )
    return subs


# ---------------------------------------------------------------------------
# §16 — Ajustements contextuels (9 regles)
# ---------------------------------------------------------------------------


def apply_contextual_adjustments(
    video_subs: List[SubScore],
    audio_subs: List[SubScore],
    grain: Any,
    normalized_probe: Optional[Dict[str, Any]],
    av1_grain_info: Optional[Any],
    imax_info: Optional[Any],
    hdr_flags: List[str],
    is_animation: bool,
    film_era: str,
) -> Tuple[List[SubScore], List[SubScore], List[str]]:
    """Applique les 9 regles d'ajustement. Retourne (video, audio, trace).

    Regle 1 : grain v2 bonus/malus
    Regle 2 : AV1 AFGS1 bonus
    Regle 3 : DV Profile 5 malus
    Regle 4 : HDR metadata missing malus
    Regle 5 : IMAX bonus
    Regle 6 : Spectral cutoff cross-validation (fake lossless)
    Regle 7 : Version hint warning-only (pas de malus)
    Regle 8 : Animation skip grain penalties
    Regle 9 : Vintage master tolerance
    """
    trace: List[str] = []

    def _patch(subs: List[SubScore], name: str, delta: float, reason: str) -> List[SubScore]:
        out: List[SubScore] = []
        for s in subs:
            if s.name == name:
                new_val = _clamp(s.value + delta)
                out.append(
                    SubScore(
                        name=s.name,
                        value=new_val,
                        weight=s.weight,
                        confidence=s.confidence,
                        label_fr=s.label_fr,
                        tier=determine_tier_v2(new_val),
                        detail_fr=s.detail_fr,
                    )
                )
                trace.append(f"{'+' if delta >= 0 else ''}{delta:g} {name} ({reason})")
            else:
                out.append(s)
        return out

    # Regle 8 d'abord : si animation, on ignore les règles 1 sur le grain
    skip_grain_rules = bool(is_animation)
    if skip_grain_rules:
        trace.append("skip_grain_rules (animation)")

    # Regle 1 — grain v2
    if grain is not None and not skip_grain_rules:
        nature = str(getattr(grain, "grain_nature", "unknown"))
        partial_dnr = bool(getattr(grain, "is_partial_dnr", False))
        if partial_dnr:
            video_subs = _patch(
                video_subs,
                "perceptual_visual",
                ADJUSTMENT_GRAIN_PARTIAL_DNR_MALUS,
                "dnr_partial",
            )
        elif nature == "film_grain":
            # Regle 9 : tolerance elargie pour films vintage (pre-1970) — moins penalisant,
            # bonus legerement reduit pour eviter double comptage.
            bonus = ADJUSTMENT_GRAIN_FILM_BONUS
            if film_era in ("16mm_era", "35mm_golden", "early_color"):
                bonus = int(bonus * 0.7)
                trace.append("vintage_master_tolerance")
            video_subs = _patch(video_subs, "perceptual_visual", bonus, "grain_film_authentic")
        elif nature == "encode_noise":
            video_subs = _patch(
                video_subs,
                "perceptual_visual",
                ADJUSTMENT_GRAIN_ENCODE_NOISE_MALUS,
                "grain_encode_noise",
            )

    # Regle 2 — AV1 AFGS1
    has_afgs1 = (bool(getattr(grain, "av1_afgs1_present", False)) if grain is not None else False) or bool(
        getattr(av1_grain_info, "has_afgs1", False) if av1_grain_info else False
    )
    if has_afgs1:
        video_subs = _patch(video_subs, "perceptual_visual", ADJUSTMENT_AV1_AFGS1_BONUS, "av1_afgs1")

    # Regle 3 — DV Profile 5
    if "dv_profile_5" in hdr_flags:
        video_subs = _patch(video_subs, "hdr_validation", ADJUSTMENT_DV_PROFILE_5_MALUS, "dv_profile_5")

    # Regle 4 — HDR metadata missing
    if "hdr_metadata_missing" in hdr_flags:
        video_subs = _patch(
            video_subs,
            "hdr_validation",
            ADJUSTMENT_HDR_METADATA_MISSING_MALUS,
            "hdr_metadata_missing",
        )

    # Regle 5 — IMAX
    if imax_info is not None:
        is_imax = bool(getattr(imax_info, "is_imax", False))
        imax_type = str(getattr(imax_info, "imax_type", "none"))
        if is_imax and imax_type == "expansion":
            video_subs = _patch(
                video_subs,
                "resolution",
                ADJUSTMENT_IMAX_EXPANSION_BONUS,
                "imax_expansion",
            )
        elif is_imax and imax_type in ("full_frame_143", "digital_190", "typed"):
            video_subs = _patch(video_subs, "resolution", ADJUSTMENT_IMAX_TYPED_BONUS, "imax_typed")

    # Regle 6 — fake lossless (codec claim lossless mais cutoff spectral bas)
    video_data = (normalized_probe or {}).get("audio") or []
    has_lossless_codec = any(
        str((t or {}).get("codec", "")).lower() in ("flac", "truehd", "dts-hd ma", "mlp")
        for t in (video_data if isinstance(video_data, list) else [])
    )
    # Retrouver audio_subs.spectral_cutoff
    spectral_sub = next((s for s in audio_subs if s.name == "spectral_cutoff"), None)
    if has_lossless_codec and spectral_sub is not None and spectral_sub.value < 60.0:
        audio_subs = _patch(audio_subs, "spectral_cutoff", ADJUSTMENT_FAKE_LOSSLESS_MALUS, "fake_lossless")

    return video_subs, audio_subs, trace


# ---------------------------------------------------------------------------
# §16 — Warnings top-level
# ---------------------------------------------------------------------------


def collect_warnings(
    category_scores: List[CategoryScore],
    global_confidence: float,
    duration_s: float,
    hdr_flags: List[str],
    runtime_vs_tmdb_flag: Optional[str],
    normalized_probe: Optional[Dict[str, Any]],
    has_fake_lossless: bool,
) -> List[str]:
    """Collecte les warnings jaunes top-level UI (5 familles)."""
    warnings: List[str] = []

    # Runtime mismatch
    flag = str(runtime_vs_tmdb_flag or "").lower()
    if flag in ("mismatch", "runtime_mismatch"):
        video_data = (normalized_probe or {}).get("video") or {}
        dur_min = int(float(video_data.get("duration_s", 0) or 0) / 60)
        warnings.append(
            f"Duree fichier {dur_min} min different notablement de TMDb — possible Theatrical vs Extended Cut."
        )
    elif flag in ("warn", "runtime_warn"):
        warnings.append("Ecart duree vs TMDb moderé — possible version alternative.")

    # DV Profile 5
    if "dv_profile_5" in hdr_flags:
        warnings.append("Dolby Vision Profile 5 — couleurs correctes uniquement sur player DV licencie.")

    # HDR metadata incomplete
    if "hdr_metadata_missing" in hdr_flags:
        warnings.append("HDR10 sans MaxCLL/MaxFALL — certains ecrans appliqueront un tone-mapping approximatif.")

    # Low confidence
    if 0.0 < global_confidence < CONFIDENCE_LOW_WARN_THRESHOLD:
        warnings.append(
            f"Analyse partielle — confidence {int(global_confidence * 100)}%. "
            "Considerer un re-scan avec plus de frames."
        )

    # Short file
    if 0 < duration_s < SHORT_FILE_WARN_DURATION_S:
        warnings.append(f"Fichier court ({duration_s:.0f}s) — confidence reduite, certaines metriques peu fiables.")

    # Category imbalance
    video_cat = next((c for c in category_scores if c.name == "video"), None)
    audio_cat = next((c for c in category_scores if c.name == "audio"), None)
    if video_cat and audio_cat:
        delta = abs(video_cat.value - audio_cat.value)
        if delta > CATEGORY_IMBALANCE_WARN_DELTA:
            side = "audio" if video_cat.value > audio_cat.value else "video"
            warnings.append(
                f"Desequilibre {side} marque (delta {delta:.0f} pts) — "
                "l'audio ou la video tire fortement le score global vers le bas."
            )

    # Fake lossless
    if has_fake_lossless:
        warnings.append(
            "Codec audio annonce lossless mais le spectre revele une compression anterieure — "
            "re-encode lossless d'une source lossy."
        )

    return warnings


# ---------------------------------------------------------------------------
# §16 — Orchestrateur
# ---------------------------------------------------------------------------


def compute_category(
    name: str,
    sub_scores: List[SubScore],
    global_weight: float,
) -> CategoryScore:
    """Reduit les sub_scores en 1 CategoryScore."""
    tuples = [(s.value, s.weight, s.confidence) for s in sub_scores]
    value, conf = weighted_score_with_confidence(tuples)
    return CategoryScore(
        name=name,
        value=value,
        weight=global_weight,
        confidence=conf,
        tier=determine_tier_v2(value),
        sub_scores=sub_scores,
    )


def compute_global_score_v2(
    video_perceptual: Any,
    audio_perceptual: Any,
    grain_analysis: Any,
    normalized_probe: Optional[Dict[str, Any]] = None,
    tmdb_metadata: Optional[Dict[str, Any]] = None,
    nfo_consistency: Optional[Dict[str, Any]] = None,
    runtime_vs_tmdb_flag: Optional[str] = None,
    av1_grain_info: Optional[Any] = None,
    lpips_result: Optional[Any] = None,
    imax_info: Optional[Any] = None,
    duration_s: float = 0.0,
    is_animation: Optional[bool] = None,
) -> GlobalScoreResult:
    """Calcule le score global composite V2 avec tous les ajustements contextuels."""
    # Film era + animation (grain utilise ces infos)
    film_era = str(getattr(grain_analysis, "film_era_v2", "unknown") or "unknown")
    if is_animation is None:
        is_animation = bool(getattr(grain_analysis, "is_animation", False))

    # 1) Build sub-scores bruts
    video_subs, hdr_flags = build_video_subscores(
        video_perceptual,
        grain_analysis,
        normalized_probe,
        lpips_result,
    )
    audio_subs = build_audio_subscores(audio_perceptual)
    coherence_subs = build_coherence_subscores(runtime_vs_tmdb_flag, nfo_consistency)

    # 2) Ajustements contextuels (9 regles)
    video_subs, audio_subs, trace = apply_contextual_adjustments(
        video_subs,
        audio_subs,
        grain_analysis,
        normalized_probe,
        av1_grain_info,
        imax_info,
        hdr_flags,
        is_animation=is_animation,
        film_era=film_era,
    )
    has_fake_lossless = any("fake_lossless" in t for t in trace)

    # 3) Categories
    cat_video = compute_category("video", video_subs, GLOBAL_WEIGHT_VIDEO_V2)
    cat_audio = compute_category("audio", audio_subs, GLOBAL_WEIGHT_AUDIO_V2)
    cat_coherence = compute_category("coherence", coherence_subs, GLOBAL_WEIGHT_COHERENCE_V2)
    categories = [cat_video, cat_audio, cat_coherence]

    # 4) Global
    global_score, global_conf = weighted_score_with_confidence([(c.value, c.weight, c.confidence) for c in categories])
    global_tier = determine_tier_v2(global_score)

    # 5) Warnings
    warnings = collect_warnings(
        categories,
        global_conf,
        duration_s,
        hdr_flags,
        runtime_vs_tmdb_flag,
        normalized_probe,
        has_fake_lossless,
    )

    return GlobalScoreResult(
        global_score=global_score,
        global_tier=global_tier,
        global_confidence=global_conf,
        category_scores=categories,
        warnings=warnings,
        adjustments_applied=trace,
    )
