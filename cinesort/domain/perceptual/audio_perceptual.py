"""Analyse audio perceptuelle — EBU R128, astats, clipping."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from cinesort.domain.codec_ranks import AUDIO_CODEC_RANK_PATTERNS as _CODEC_RANK_FULL

from .constants import (
    AUDIO_WEIGHT_CLIPPING,
    AUDIO_WEIGHT_CREST,
    AUDIO_WEIGHT_DYNAMIC_RANGE,
    AUDIO_WEIGHT_LRA,
    AUDIO_WEIGHT_MEL,
    AUDIO_WEIGHT_NOISE_FLOOR,
    CLIPPING_ACCEPTABLE_PCT,
    CLIPPING_MODERATE_PCT,
    CLIPPING_SEVERE_PCT,
    CLIPPING_THRESHOLD_DBFS,
    CREST_FACTOR_COMPRESSED,
    CREST_FACTOR_EXCELLENT,
    CREST_FACTOR_GOOD,
    DRC_CREST_CINEMA,
    DRC_CREST_STANDARD,
    DRC_LRA_CINEMA,
    DRC_LRA_STANDARD,
    DYNAMIC_RANGE_EXCELLENT,
    DYNAMIC_RANGE_GOOD,
    DYNAMIC_RANGE_MEDIOCRE,
    LRA_COMPRESSED,
    LRA_EXCELLENT,
    LRA_GOOD,
    NOISE_FLOOR_EXCELLENT,
    NOISE_FLOOR_GOOD,
    NOISE_FLOOR_MEDIOCRE,
    TIER_EXCELLENT,
    TIER_GOOD,
    TIER_MEDIOCRE,
    TIER_REFERENCE,
    TP_CLIPPING,
    TP_MAX,
)
from .ffmpeg_runner import run_ffmpeg_text
from .models import AudioPerceptual

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hierarchie codec audio (centralisee dans cinesort.domain.codec_ranks)
# On strippe le label pour conserver la signature historique List[(pat, rang)].
# ---------------------------------------------------------------------------

_CODEC_RANK: List[tuple[str, int]] = [(pat, rank) for pat, rank, _label in _CODEC_RANK_FULL]

# Regex pour astats
_RE_RMS = re.compile(r"RMS level.*?:\s*([-\d.]+)", re.IGNORECASE)
_RE_PEAK = re.compile(r"Peak level.*?:\s*([-\d.]+)", re.IGNORECASE)
_RE_NOISE = re.compile(r"Noise floor.*?:\s*([-\d.]+)", re.IGNORECASE)
_RE_CREST = re.compile(r"Crest factor.*?:\s*([\d.]+)", re.IGNORECASE)
_RE_DYNRANGE = re.compile(r"Dynamic range.*?:\s*([\d.]+)", re.IGNORECASE)
# MEGA-HOTFIX bug (1) : ffmpeg astats imprime des blocs par canal AVANT le bloc
# "Overall". La regex precedente sur .search() prenait la PREMIERE occurrence
# (donc Channel 1, valeurs faussees sur multi-canal). On extrait d'abord le
# bloc Overall : soit en-tete "Overall" sur une ligne propre, soit prefixe
# "Overall <metric>" en-tete par metrique (format des tests + certains builds).
# Cf. https://ffmpeg.org/ffmpeg-filters.html#astats : "Overall" peut apparaitre
# comme label de bloc OU prefixe ligne par ligne.
_RE_OVERALL_BLOCK = re.compile(
    r"(?:^|\n)[^\n]*?\bOverall\b[^\n]*\n(.*)\Z",
    re.DOTALL | re.IGNORECASE,
)
# MEGA-HOTFIX bug (2) : marqueur de fin de segment dans la sortie astats avec
# reset>0. Chaque segment se termine par un bloc "Overall" qui est la seule
# valeur Peak agregee canal-confondus. Sans filtrage on multiplie le compte par
# le nombre de canaux (ex: 5.1 -> total_segments*6).
_RE_OVERALL_LINE = re.compile(r"^[^\n]*\bOverall\b[^\n]*$", re.IGNORECASE | re.MULTILINE)
# Cf issue #53 : on cible specifiquement le bloc loudnorm via la cle
# 'input_i' (toujours presente dans le JSON loudnorm ffmpeg). Le pattern
# precedent r'\{[^}]+\}' (1) ne supportait pas le JSON nested et (2)
# prenait le PREMIER match alors que loudnorm imprime son resultat en
# dernier (un avertissement contenant des accolades passait avant).
# DOTALL autorise les newlines dans le bloc, findall+[-1] prend le dernier.
_RE_JSON_BLOCK = re.compile(r"\{[^{}]*input_i[^{}]*\}", re.DOTALL)

_DEFAULT_SAMPLE_RATE = 48000


# ---------------------------------------------------------------------------
# Selection meilleure piste
# ---------------------------------------------------------------------------


def select_best_audio_track(audio_tracks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Selectionne la piste audio avec le codec le plus haut dans la hierarchie."""
    if not audio_tracks:
        return None

    best_track: Optional[Dict[str, Any]] = None
    best_rank = -1

    for track in audio_tracks:
        codec = str(track.get("codec") or "").lower()
        title = str(track.get("title") or "").lower()
        rank = 0
        for pattern, r in _CODEC_RANK:
            if pattern in codec or pattern in title:
                rank = r
                break
        if rank > best_rank:
            best_rank = rank
            best_track = track

    return best_track


# ---------------------------------------------------------------------------
# Loudnorm (EBU R128)
# ---------------------------------------------------------------------------


def analyze_loudnorm(
    ffmpeg_path: str,
    media_path: str,
    track_index: int,
    timeout_s: float = 60.0,
) -> Optional[Dict[str, Any]]:
    """Analyse EBU R128 via loudnorm (IL, LRA, TP)."""
    cmd = [
        ffmpeg_path,
        "-i",
        str(media_path),
        "-map",
        f"0:a:{track_index}",
        "-af",
        "loudnorm=print_format=json",
        "-f",
        "null",
        # R8-034 (F4) : loudnorm imprime son JSON via av_log au niveau INFO sur
        # stderr. "-v quiet" supprimait TOUT -> stderr vide -> analyze_loudnorm
        # renvoyait None -> loudness EBU R128 JAMAIS mesurée. "-v info" (comme
        # analyze_astats) laisse le bloc JSON atteindre stderr (vérifié ffmpeg 8.1.1).
        "-v",
        "info",
        "-",
    ]
    rc, _stdout, stderr = run_ffmpeg_text(cmd, timeout_s)
    if not stderr:
        logger.debug("loudnorm: pas de sortie stderr rc=%d", rc)
        return None

    # Cf issue #53 : prendre le DERNIER bloc loudnorm (filtre sur 'input_i'
    # via la regex). ffmpeg peut imprimer plusieurs blocs JSON-like dans
    # stderr (Parsed_loudnorm warnings) avant le vrai bloc loudnorm final.
    matches = _RE_JSON_BLOCK.findall(stderr)
    if not matches:
        logger.debug("loudnorm: bloc JSON contenant 'input_i' introuvable dans stderr")
        return None
    raw_json = matches[-1]

    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, ValueError) as exc:
        # Loggue le raw JSON tronque pour diagnostic ulterieur
        logger.warning("loudnorm: JSON invalide: %s (raw=%s)", exc, raw_json[:200])
        return None

    il = _safe_float(data.get("input_i"))
    lra = _safe_float(data.get("input_lra"))
    tp = _safe_float(data.get("input_tp"))

    # Verdicts
    lra_verdict = "unknown"
    if lra is not None:
        if lra > LRA_EXCELLENT:
            lra_verdict = "excellent"
        elif lra >= LRA_GOOD:
            lra_verdict = "good"
        elif lra >= LRA_COMPRESSED:
            lra_verdict = "compressed"
        else:
            lra_verdict = "flat"

    tp_verdict = "unknown"
    if tp is not None:
        if tp >= TP_CLIPPING:
            tp_verdict = "clipping"
        elif tp > TP_MAX:
            tp_verdict = "hot"
        else:
            tp_verdict = "safe"

    return {
        "integrated_loudness": il,
        "loudness_range": lra,
        "true_peak": tp,
        "lra_verdict": lra_verdict,
        "tp_verdict": tp_verdict,
    }


# ---------------------------------------------------------------------------
# Astats (analyse complete)
# ---------------------------------------------------------------------------


def analyze_astats(
    ffmpeg_path: str,
    media_path: str,
    track_index: int,
    timeout_s: float = 120.0,
) -> Optional[Dict[str, Any]]:
    """Analyse audio complete via astats (RMS, peak, noise floor, crest, DR)."""
    cmd = [
        ffmpeg_path,
        "-i",
        str(media_path),
        "-map",
        f"0:a:{track_index}",
        "-af",
        "astats=metadata=1:reset=0",
        "-f",
        "null",
        "-v",
        "info",
        "-",
    ]
    _rc, _stdout, stderr = run_ffmpeg_text(cmd, timeout_s)
    if not stderr:
        return None

    # MEGA-HOTFIX bug (1) : restreindre la recherche au bloc Overall pour
    # ne plus retourner les stats du canal 1 (premiere occurrence dans la
    # sortie ffmpeg). On garde un fallback sur le texte complet si aucun
    # marqueur "Overall" n'est present (compat builds anciens / mono).
    overall_text = _extract_overall_block(stderr)

    rms = _search_float(_RE_RMS, overall_text)
    peak = _search_float(_RE_PEAK, overall_text)
    noise = _search_float(_RE_NOISE, overall_text)
    # R8-035 (F4) : Crest factor / Dynamic range ne figurent PAS dans le bloc
    # Overall d'astats (vérifié ffmpeg 8.1.1 mono ET stéréo) — uniquement sous
    # "Channel: N". Les lire sur le texte COMPLET (tous les canaux) et garder le
    # pire (min). AVANT : _search_float sur overall_text -> toujours None ->
    # crest/dynrange figés -> 2 des 6 poids audio bloqués à 50 (valeur "parfaite").
    crest = _min_float(_RE_CREST, stderr)
    dynrange = _min_float(_RE_DYNRANGE, stderr)

    # Verdicts
    noise_verdict = _verdict_noise(noise)
    dynamics_verdict = _verdict_dynamics(dynrange)
    crest_verdict = _verdict_crest(crest)

    return {
        "rms_level": rms,
        "peak_level": peak,
        "noise_floor": noise,
        "crest_factor": crest,
        "dynamic_range": dynrange,
        "noise_verdict": noise_verdict,
        "dynamics_verdict": dynamics_verdict,
        "crest_verdict": crest_verdict,
    }


# ---------------------------------------------------------------------------
# Clipping par segments
# ---------------------------------------------------------------------------


def analyze_clipping_segments(
    ffmpeg_path: str,
    media_path: str,
    track_index: int,
    segment_s: int = 30,
    timeout_s: float = 180.0,
    sample_rate: int = _DEFAULT_SAMPLE_RATE,
) -> Dict[str, Any]:
    """Detecte le clipping segment par segment."""
    segment_frames = int(segment_s) * int(sample_rate)
    cmd = [
        ffmpeg_path,
        "-i",
        str(media_path),
        "-map",
        f"0:a:{track_index}",
        "-af",
        f"astats=metadata=1:reset={segment_frames}",
        "-f",
        "null",
        "-v",
        "info",
        "-",
    ]
    _rc, _stdout, stderr = run_ffmpeg_text(cmd, timeout_s)
    if not stderr:
        return {"total_segments": 0, "clipping_segments": 0, "clipping_pct": 0.0, "verdict": "unknown"}

    # MEGA-HOTFIX bug (2) : avec reset>0 ffmpeg imprime un bloc par canal +
    # un bloc "Overall" par segment. Compter toutes les lignes "Peak level"
    # gonfle total_segments par n_channels (5.1 -> x6) et fausse le %.
    # On filtre les lignes "Peak level" appartenant au bloc Overall, identifiees
    # soit par le prefixe "Overall ..." sur la ligne meme, soit par la ligne
    # "Overall" qui precede le bloc agrege.
    overall_peak_lines = _extract_overall_peak_lines(stderr)
    total = 0
    clipping = 0
    for line in overall_peak_lines:
        m = _RE_PEAK.search(line)
        if not m:
            continue
        val = _safe_float(m.group(1))
        if val is None:
            continue
        total += 1
        if val >= CLIPPING_THRESHOLD_DBFS:
            clipping += 1

    # Fallback : aucun marqueur "Overall" detecte (compat builds anciens, mono,
    # tests historiques). On normalise par le nombre de canaux detecte via les
    # blocs "Channel: N", sinon on compte brut.
    if total == 0:
        channel_count = _detect_channel_count(stderr) or 1
        raw_total = 0
        raw_clipping = 0
        for m in _RE_PEAK.finditer(stderr):
            val = _safe_float(m.group(1))
            if val is None:
                continue
            raw_total += 1
            if val >= CLIPPING_THRESHOLD_DBFS:
                raw_clipping += 1
        if channel_count > 1:
            # Normalisation : raw_total = n_segments * n_channels
            total = raw_total // channel_count
            # Pour clipping on garde le ratio (au moins 1 canal touche = segment clip)
            # Approximation conservative : on divise par n_channels aussi.
            clipping = raw_clipping // channel_count
        else:
            total = raw_total
            clipping = raw_clipping

    if total == 0:
        # Aucun segment "Peak level" detecte malgre un stderr non-vide :
        # parsing impossible (format ffmpeg inattendu, piste trop courte,
        # stream sans peak metering). Distinguer de "0 clipping" pour eviter
        # qu'un fichier non-analysable soit score "acceptable" par defaut.
        logger.debug("analyze_clipping_segments: no Peak level lines in stderr (len=%d)", len(stderr))
        return {"total_segments": 0, "clipping_segments": 0, "clipping_pct": 0.0, "verdict": "unknown"}

    pct = clipping / total * 100

    if pct < CLIPPING_ACCEPTABLE_PCT:
        verdict = "acceptable"
    elif pct < CLIPPING_MODERATE_PCT:
        verdict = "moderate"
    elif pct < CLIPPING_SEVERE_PCT:
        verdict = "severe"
    else:
        verdict = "critical"

    return {
        "total_segments": total,
        "clipping_segments": clipping,
        "clipping_pct": round(pct, 2),
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Orchestrateur audio perceptuel
# ---------------------------------------------------------------------------


def analyze_audio_perceptual(
    ffmpeg_path: str,
    media_path: str,
    audio_tracks: List[Dict[str, Any]],
    *,
    audio_deep: bool = True,
    audio_segment_s: int = 30,
    timeout_s: float = 120.0,
    enable_fingerprint: bool = True,
    enable_spectral: bool = True,
    enable_mel: bool = True,
    duration_s: float = 0.0,
    film_era: str = "unknown",
) -> AudioPerceptual:
    """Orchestre l'analyse audio perceptuelle complete.

    §3 v7.5.0 : `enable_fingerprint` + `duration_s` pour l'empreinte Chromaprint.
    §9 v7.5.0 : `enable_spectral` + `film_era` pour la detection lossy par FFT.
    §12 v7.5.0 : `enable_mel` pour l'analyse mel spectrogram (4 detections).
    Robuste aux echecs : ffmpeg/fpcalc manquants -> verdict "error"/"none".
    """
    result = AudioPerceptual()

    best = select_best_audio_track(audio_tracks)
    if not best:
        result.audio_score = 0
        result.audio_tier = "degrade"
        return result

    # AUDIT 2026-06-10 (REAL 2/2) : best["index"] est l'index ABSOLU du conteneur
    # (video=0, audio=1...), mais il est utilise comme index audio-RELATIF dans
    # `-map 0:a:{idx}`. Pour un film standard a 1 piste audio (index absolu 1),
    # `-map 0:a:1` ne matche aucun flux -> loudnorm/astats/clipping/fingerprint
    # echouent TOUS silencieusement. On calcule l'index audio-relatif = rang de
    # la piste parmi les pistes audio (par index absolu croissant).
    abs_idx = int(best.get("index", 0))
    result.track_index = abs_idx
    idx = sum(1 for t in audio_tracks if int((t or {}).get("index", abs_idx)) < abs_idx)
    result.track_codec = str(best.get("codec") or "")
    result.track_channels = int(best.get("channels") or 0)
    result.track_language = str(best.get("language") or "")

    # --- Loudnorm (toujours) ---
    loud = analyze_loudnorm(ffmpeg_path, media_path, idx, timeout_s=min(60.0, timeout_s))
    if loud:
        result.integrated_loudness = loud["integrated_loudness"]
        result.loudness_range = loud["loudness_range"]
        result.true_peak = loud["true_peak"]

    # --- Astats + clipping (si deep) ---
    astats_data: Optional[Dict[str, Any]] = None
    clip_data: Optional[Dict[str, Any]] = None
    if audio_deep:
        astats_data = analyze_astats(ffmpeg_path, media_path, idx, timeout_s=timeout_s)
        if astats_data:
            result.rms_level = astats_data["rms_level"]
            result.peak_level = astats_data["peak_level"]
            result.noise_floor = astats_data["noise_floor"]
            result.crest_factor = astats_data["crest_factor"]
            result.dynamic_range = astats_data["dynamic_range"]

        clip_data = analyze_clipping_segments(
            ffmpeg_path,
            media_path,
            idx,
            segment_s=audio_segment_s,
            timeout_s=timeout_s,
        )
        result.clipping_total_segments = clip_data["total_segments"]
        result.clipping_segments = clip_data["clipping_segments"]
        result.clipping_pct = clip_data["clipping_pct"]

    # --- DRC classification (§14 v7.5.0) — aucun calcul supplementaire ---
    drc_cat, drc_conf = classify_drc(
        crest_factor=result.crest_factor,
        lra=result.loudness_range,
    )
    result.drc_category = drc_cat
    result.drc_confidence = drc_conf

    # --- Fingerprint Chromaprint (§3 v7.5.0) ---
    if enable_fingerprint:
        # Lazy intentionnel : tests patchent les symboles au niveau du module source
        # (audio_fingerprint.resolve_fpcalc_path). Top-level casserait
        # test_audio_fingerprint.py::test_fingerprint_populated_when_fpcalc_available.
        from .audio_fingerprint import compute_audio_fingerprint, resolve_fpcalc_path

        fpcalc = resolve_fpcalc_path()
        if fpcalc:
            # MEGA-HOTFIX audio_fingerprint_offset : transmettre ffmpeg_path
            # pour permettre le seek strict (-ss OFFSET) via pipe stdin et
            # eviter les faux positifs causes par les logos studios partages
            # dans les 60 premieres secondes de tous les films.
            fp = compute_audio_fingerprint(
                media_path,
                duration_s=float(duration_s or 0.0),
                fpcalc_path=fpcalc,
                ffmpeg_path=ffmpeg_path or None,
                track_index=idx,
            )
            if fp:
                result.audio_fingerprint = fp
                result.fingerprint_source = "fpcalc"
            else:
                result.fingerprint_source = "error"
        else:
            result.fingerprint_source = "none"
    else:
        result.fingerprint_source = "disabled"

    # --- Spectral cutoff lossy detection (§9 v7.5.0) ---
    if enable_spectral:
        # Lazy intentionnel : tests patchent les symboles au niveau du module source
        # (spectral_analysis.analyze_spectral). Top-level casserait les tests
        # audio perceptuels qui mockent ce module.
        from .spectral_analysis import analyze_spectral

        sample_rate = int(best.get("sample_rate") or 48000)
        codec = str(best.get("codec") or "")
        spectral = analyze_spectral(
            ffmpeg_path,
            media_path,
            idx,
            duration_total_s=float(duration_s or 0.0),
            codec=codec,
            sample_rate=sample_rate,
            film_era=film_era,
        )
        result.spectral_cutoff_hz = spectral.cutoff_hz
        result.lossy_verdict = spectral.lossy_verdict
        result.lossy_confidence = spectral.confidence
    else:
        result.lossy_verdict = "disabled"

    # --- Mel spectrogram (§12 v7.5.0) ---
    mel_result = None
    if enable_mel:
        # Lazy intentionnel : tests patchent les symboles au niveau du module source
        # (mel_analysis.analyze_mel). Top-level casserait les tests audio
        # perceptuels qui mockent ce module.
        from .mel_analysis import analyze_mel
        from .spectral_analysis import SPECTRAL_SAMPLE_RATE, extract_audio_segment

        mel_offset = 60.0
        mel_duration = 30.0
        if duration_s > 0 and duration_s < mel_offset + mel_duration:
            mel_offset = 0.0
            mel_duration = max(1.0, float(duration_s))

        samples = extract_audio_segment(
            ffmpeg_path,
            media_path,
            idx,
            offset_s=mel_offset,
            duration_s=mel_duration,
            sample_rate=SPECTRAL_SAMPLE_RATE,
        )
        if samples is not None and samples.size >= 4096:
            mel_result = analyze_mel(samples, sample_rate=SPECTRAL_SAMPLE_RATE)
            result.mel_soft_clipping_pct = mel_result.mel_soft_clipping_pct
            result.mel_mp3_shelf_detected = mel_result.mel_mp3_shelf_detected
            result.mel_aac_holes_ratio = mel_result.mel_aac_holes_ratio
            result.mel_spectral_flatness = mel_result.mel_spectral_flatness_mean
            result.mel_score = mel_result.mel_score
            result.mel_verdict = mel_result.mel_verdict
        else:
            result.mel_verdict = "insufficient_data"
    else:
        result.mel_verdict = "disabled"

    # --- Re-score audio avec Mel (§12) ---
    # On recalcule le score apres avoir mel_result, car _compute_audio_score
    # initial ignorait Mel (execution avant le bloc spectral)
    result.audio_score = _compute_audio_score(loud, astats_data, clip_data, mel=mel_result)
    result.audio_tier = _determine_tier(result.audio_score)

    logger.debug(
        "audio_p: LRA=%.1f peak=%.1f clipping=%d score=%d fp=%s cutoff=%.0fHz verdict=%s",
        result.loudness_range or 0,
        result.true_peak or 0,
        result.clipping_segments or 0,
        result.audio_score,
        result.fingerprint_source,
        result.spectral_cutoff_hz,
        result.lossy_verdict,
    )
    return result


# ---------------------------------------------------------------------------
# DRC classification (§14 v7.5.0)
# ---------------------------------------------------------------------------


def classify_drc(
    crest_factor: Optional[float],
    lra: Optional[float],
) -> tuple[str, float]:
    """Classifie la compression dynamique en verdict textuel.

    Args:
        crest_factor: en dB, None si astats echoue.
        lra: Loudness Range en LU, None si loudnorm echoue.

    Returns:
        (drc_category, confidence) parmi :
          "cinema"               : pleine dynamique (Blu-ray, UHD, Atmos)
          "standard"             : DVD, streaming 4K, TV
          "broadcast_compressed" : broadcast compresse / loudness war
          "unknown"              : crest et lra non disponibles

    Strategie : somme des scores crest (0/1/2) et LRA (0/1/2), seuillee.
    """
    if crest_factor is None and lra is None:
        return ("unknown", 0.0)

    score_crest = 0
    if crest_factor is not None:
        if crest_factor >= DRC_CREST_CINEMA:
            score_crest = 2
        elif crest_factor >= DRC_CREST_STANDARD:
            score_crest = 1

    score_lra = 0
    if lra is not None:
        if lra >= DRC_LRA_CINEMA:
            score_lra = 2
        elif lra >= DRC_LRA_STANDARD:
            score_lra = 1

    combined = score_crest + score_lra
    if combined >= 3:
        return ("cinema", 0.95)
    if combined == 2:
        return ("cinema", 0.75)
    if combined == 1:
        return ("standard", 0.80)
    return ("broadcast_compressed", 0.85)


# ---------------------------------------------------------------------------
# Scoring audio
# ---------------------------------------------------------------------------


def _compute_audio_score(
    loud: Optional[Dict[str, Any]],
    astats: Optional[Dict[str, Any]],
    clip: Optional[Dict[str, Any]],
    mel: Optional[Any] = None,
) -> int:
    """Score audio composite pondere (0-100).

    §12 v7.5.0 : ajout du poids Mel (15%). Si `mel` est None (analyse
    desactivee ou echec), on utilise 70 comme valeur neutre (pas 50 pour
    ne pas penaliser indument les configurations sans Mel).
    """
    s_lra = 50  # defaut neutre
    s_noise = 50
    s_clip = 80  # presume bon si pas analyse
    s_dyn = 50
    s_crest = 50
    s_mel = 70  # defaut quasi-bon (pas de Mel = pas de penalite forte)

    if loud:
        lra = loud.get("loudness_range")
        if lra is not None:
            if lra > LRA_EXCELLENT:
                s_lra = 95
            elif lra >= LRA_GOOD:
                s_lra = 75
            elif lra >= LRA_COMPRESSED:
                s_lra = 45
            else:
                s_lra = 20

        tp = loud.get("true_peak")
        if tp is not None and tp >= TP_CLIPPING:
            s_clip = max(10, s_clip - 40)

    if astats:
        nf = astats.get("noise_floor")
        if nf is not None:
            if nf < NOISE_FLOOR_EXCELLENT:
                s_noise = 95
            elif nf < NOISE_FLOOR_GOOD:
                s_noise = 75
            elif nf < NOISE_FLOOR_MEDIOCRE:
                s_noise = 45
            else:
                s_noise = 20

        dr = astats.get("dynamic_range")
        if dr is not None:
            if dr > DYNAMIC_RANGE_EXCELLENT:
                s_dyn = 95
            elif dr > DYNAMIC_RANGE_GOOD:
                s_dyn = 75
            elif dr > DYNAMIC_RANGE_MEDIOCRE:
                s_dyn = 45
            else:
                s_dyn = 20

        cr = astats.get("crest_factor")
        if cr is not None:
            if cr > CREST_FACTOR_EXCELLENT:
                s_crest = 95
            elif cr > CREST_FACTOR_GOOD:
                s_crest = 75
            elif cr > CREST_FACTOR_COMPRESSED:
                s_crest = 45
            else:
                s_crest = 20

    # R8-098 (filet F4) : ne scorer le clipping QUE si la mesure a réellement eu
    # lieu (total_segments > 0). Sinon (stderr vide / ffmpeg muet -> verdict
    # 'unknown', total_segments=0) `clip` reste un dict truthy avec pct=0.0 ->
    # s_clip=90 fabriqué (« parfait ») au lieu du neutre 80. Même classe que
    # R8-034/035 : une mesure ratée mappait vers la valeur la plus flatteuse.
    if clip and int(clip.get("total_segments", 0) or 0) > 0:
        pct = clip.get("clipping_pct", 0.0)
        if pct < CLIPPING_ACCEPTABLE_PCT:
            s_clip = 90
        elif pct < CLIPPING_MODERATE_PCT:
            s_clip = 60
        elif pct < CLIPPING_SEVERE_PCT:
            s_clip = 30
        else:
            s_clip = 10

    if mel is not None:
        s_mel = int(getattr(mel, "mel_score", s_mel))

    total = (
        s_lra * AUDIO_WEIGHT_LRA
        + s_noise * AUDIO_WEIGHT_NOISE_FLOOR
        + s_clip * AUDIO_WEIGHT_CLIPPING
        + s_dyn * AUDIO_WEIGHT_DYNAMIC_RANGE
        + s_crest * AUDIO_WEIGHT_CREST
        + s_mel * AUDIO_WEIGHT_MEL
    ) / 100

    return max(0, min(100, int(round(total))))


def _determine_tier(score: int) -> str:
    """Determine le tier perceptuel audio."""
    if score >= TIER_REFERENCE:
        return "reference"
    if score >= TIER_EXCELLENT:
        return "excellent"
    if score >= TIER_GOOD:
        return "bon"
    if score >= TIER_MEDIOCRE:
        return "mediocre"
    return "degrade"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(val: Any) -> Optional[float]:
    """Convertit en float ou None."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _search_float(pattern: re.Pattern, text: str) -> Optional[float]:
    """Cherche un float dans le texte via regex."""
    m = pattern.search(text)
    if not m:
        return None
    return _safe_float(m.group(1))


def _min_float(pattern: re.Pattern, text: str) -> Optional[float]:
    """R8-035 (F4) : agrège TOUTES les occurrences (une par canal) et renvoie le
    minimum (= canal le plus compressé / plus faible dynamique = pire cas).
    Utilisé pour Crest factor / Dynamic range qui n'existent QUE par canal dans
    astats (absents du bloc Overall)."""
    vals = []
    for raw in pattern.findall(text):
        v = _safe_float(raw)
        if v is not None:
            vals.append(v)
    return min(vals) if vals else None


# MEGA-HOTFIX bug (1) : helper d'extraction du bloc "Overall" d'astats.
_RE_CHANNEL_LABEL = re.compile(r"Channel\s*:\s*(\d+)", re.IGNORECASE)


def _extract_overall_block(text: str) -> str:
    """Retourne la portion du texte astats correspondant au bloc 'Overall'.

    Deux formats possibles selon les builds ffmpeg :
    1) Lignes prefixees ``Overall <metric>: <value>`` (format des tests
       unitaires et de certains builds recents).
    2) Une ligne ``Overall`` seule en en-tete, suivie des metriques sans
       prefixe (format ffmpeg historique : bloc agrege apres les blocs
       ``Channel: N``).

    Strategie : on cherche la PREMIERE occurrence du marqueur ``Overall``
    APRES le dernier bloc ``Channel: N`` (ou la premiere occurrence si pas
    de bloc Channel), et on retourne le texte a partir de la. Cela couvre
    les deux formats : si "Overall" prefixe la metrique on prend la ligne,
    si "Overall" est un en-tete on inclut les lignes suivantes. Si aucun
    marqueur n'est trouve, on retourne le texte complet en fallback
    (compat tests historiques / mono / sortie sans label Overall).
    """
    if not text:
        return text
    # Cherche le debut du bloc Overall : apres le dernier "Channel: N" si
    # present, sinon des le debut.
    search_start = 0
    last_channel = -1
    for m in _RE_CHANNEL_LABEL.finditer(text):
        last_channel = m.end()
    if last_channel >= 0:
        search_start = last_channel
    overall_match = re.search(r"\bOverall\b", text[search_start:], re.IGNORECASE)
    if overall_match is None:
        # Pas de "Overall" apres le dernier Channel : essayer dans tout le texte
        overall_match = re.search(r"\bOverall\b", text, re.IGNORECASE)
        if overall_match is None:
            return text  # fallback : pas de marqueur, on garde tout
        abs_pos = overall_match.start()
    else:
        abs_pos = search_start + overall_match.start()
    # On rembobine au debut de la ligne contenant ce marqueur pour ne pas
    # couper la metrique courante (ex: "Overall RMS level: -28.4").
    line_start = text.rfind("\n", 0, abs_pos) + 1
    return text[line_start:]


def _extract_overall_peak_lines(text: str) -> List[str]:
    """Extrait les lignes 'Peak level' appartenant aux blocs 'Overall' par segment.

    Cf. MEGA-HOTFIX bug (2). Deux formats :
    1) Ligne prefixee ``Overall Peak level: <value>`` : match direct.
    2) En-tete ``Overall`` puis lignes de metriques sur les lignes suivantes :
       on collecte la premiere ligne ``Peak level`` apres chaque en-tete
       ``Overall`` (avant la prochaine sentinelle ``Channel:`` ou ``Overall``).
    """
    if not text:
        return []
    results: List[str] = []
    lines = text.splitlines()
    in_overall = False
    seen_peak_in_block = False
    for line in lines:
        # Format 1 : ligne explicitement prefixee "Overall ... Peak level"
        if re.search(r"\bOverall\b.*?\bPeak level\b", line, re.IGNORECASE):
            results.append(line)
            in_overall = False
            seen_peak_in_block = False
            continue
        # En-tete de bloc Overall (format 2)
        if re.search(r"\bOverall\b", line, re.IGNORECASE) and not re.search(
            r"\bPeak level\b|\bRMS\b|\bNoise\b|\bCrest\b|\bDynamic\b", line, re.IGNORECASE
        ):
            in_overall = True
            seen_peak_in_block = False
            continue
        # Nouveau bloc Channel : on sort du bloc Overall
        if _RE_CHANNEL_LABEL.search(line):
            in_overall = False
            seen_peak_in_block = False
            continue
        # Dans un bloc Overall, capturer la premiere occurrence Peak level
        if in_overall and not seen_peak_in_block and re.search(r"\bPeak level\b", line, re.IGNORECASE):
            results.append(line)
            seen_peak_in_block = True
    return results


def _detect_channel_count(text: str) -> int:
    """Detecte le nombre de canaux distincts via les marqueurs 'Channel: N'.

    Retourne 0 si aucun marqueur, sinon le numero max de canal vu (ce qui
    correspond au nombre total de canaux puisque ffmpeg les numerote
    consecutivement a partir de 1).
    """
    if not text:
        return 0
    max_ch = 0
    for m in _RE_CHANNEL_LABEL.finditer(text):
        try:
            n = int(m.group(1))
            if n > max_ch:
                max_ch = n
        except (ValueError, TypeError):
            continue
    return max_ch


def _verdict_noise(noise: Optional[float]) -> str:
    """Verdict noise floor."""
    if noise is None:
        return "unknown"
    if noise < NOISE_FLOOR_EXCELLENT:
        return "excellent"
    if noise < NOISE_FLOOR_GOOD:
        return "good"
    if noise < NOISE_FLOOR_MEDIOCRE:
        return "mediocre"
    return "poor"


def _verdict_dynamics(dr: Optional[float]) -> str:
    """Verdict dynamic range."""
    if dr is None:
        return "unknown"
    if dr > DYNAMIC_RANGE_EXCELLENT:
        return "excellent"
    if dr > DYNAMIC_RANGE_GOOD:
        return "good"
    if dr > DYNAMIC_RANGE_MEDIOCRE:
        return "mediocre"
    return "poor"


def _verdict_crest(crest: Optional[float]) -> str:
    """Verdict crest factor."""
    if crest is None:
        return "unknown"
    if crest > CREST_FACTOR_EXCELLENT:
        return "excellent"
    if crest > CREST_FACTOR_GOOD:
        return "good"
    if crest > CREST_FACTOR_COMPRESSED:
        return "compressed"
    return "crushed"
