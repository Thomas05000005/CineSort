"""Orchestration analyse perceptuelle — single film + batch."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import cinesort.domain.perceptual.comparison as _comparison_mod
from cinesort.domain.i18n_messages import t
from cinesort.domain.perceptual.audio_perceptual import analyze_audio_perceptual
from cinesort.domain.perceptual.av1_grain_metadata import extract_av1_film_grain_params
from cinesort.domain.perceptual.comparison import build_comparison_report, compare_per_frame
from cinesort.domain.perceptual.composite_score import build_perceptual_result
from cinesort.domain.perceptual.composite_score_v2 import compute_global_score_v2
from cinesort.domain.perceptual.ffmpeg_runner import resolve_ffmpeg_path
from cinesort.domain.perceptual.frame_extraction import extract_representative_frames
from cinesort.domain.perceptual.grain_analysis import (
    analyze_grain,
    analyze_grain_v2,
    classify_film_era,
)
from cinesort.domain.perceptual.hdr_analysis import detect_hdr10_plus_multi_frame
from cinesort.domain.perceptual.lpips_compare import compute_lpips_comparison
from cinesort.domain.perceptual.metadata_analysis import (
    classify_crop,
    classify_imax,
    detect_crop_multi_segments,
    detect_interlacing,
    detect_judder,
)
from cinesort.domain.perceptual.parallelism import (
    resolve_batch_workers,
    resolve_max_workers,
    run_batch_parallel,
    run_parallel_tasks,
)
from cinesort.domain.perceptual.ssim_self_ref import compute_ssim_self_ref
from cinesort.domain.perceptual.upscale_detection import (
    classify_fake_4k_fft,
    combine_fake_4k_verdicts,
    compute_fft_hf_ratio_median,
)
from cinesort.domain.perceptual.video_analysis import analyze_video_frames, run_filter_graph
from cinesort.domain.probe_models import probe_quality_is_failed
from cinesort.infra.probe import ProbeService
from cinesort.infra.probe.tooling import safe_tool_path
from cinesort.infra.subprocess_safety import tracked_run
from cinesort.ui.api._responses import err as _err_response
from cinesort.ui.api.settings_support import _normalize_composite_score_version, normalize_user_path

logger = logging.getLogger(__name__)


def _ffmpeg_platform_kwargs() -> Dict[str, Any]:
    """Kwargs subprocess Windows pour eviter le flash console ffmpeg.

    Identique a `cinesort.domain.perceptual.ffmpeg_runner._runner_platform_kwargs`
    mais local pour eviter une dependance ui -> domain interne.
    """
    if os.name != "nt":
        return {}
    kwargs: Dict[str, Any] = {"creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0))}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
    si.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
    kwargs["startupinfo"] = si
    return kwargs


# ---------------------------------------------------------------------------
# R8-056 (F5) — Forme canonique perceptuelle servie à la modale
# ---------------------------------------------------------------------------
# La modale (perceptual-modal.js) consomme TOP-LEVEL : d.grain_analysis.verdict_label,
# d.width, d.height, d.display_tier, d.breakdown[]. Or le rapport DB les imbrique
# (metrics.grain_analysis, metrics.video_perceptual.resolution, global_score_v2_payload)
# -> grain « — », dimensions 0, breakdown vide. Ce sérialiseur APLATIT le rapport vers
# le contrat de la modale (jamais servi auparavant). breakdown est DÉRIVÉ des
# category_scores du payload V2 (cohérent avec les vraies métriques réparées en F4).

_CATEGORY_LABEL_FR = {"video": "Vidéo", "audio": "Audio", "coherence": "Cohérence"}


def _tier_to_status(tier: str) -> str:
    """Mappe un tier V2 -> classe de statut CSS de la modale (good/warning/reject/info)."""
    t = str(tier or "").strip().lower()
    if t in ("platinum", "gold"):
        return "good"
    if t in ("silver", "bronze"):
        return "warning"
    if t == "reject":
        return "reject"
    return "info"


def _category_to_breakdown_row(cat: Dict[str, Any]) -> Dict[str, Any]:
    """Traduit un category_score (video/audio/coherence) en ligne de breakdown modale."""
    value = float(cat.get("value") or 0.0)
    weight = float(cat.get("weight") or 0.0)
    name = str(cat.get("name") or "")
    return {
        "component": _CATEGORY_LABEL_FR.get(name, name or "?"),
        "weight": round(weight, 2),
        "value_label": f"{value:.0f}/100",
        "status": _tier_to_status(str(cat.get("tier") or "")),
        "points": round(value * weight, 1),  # contribution pondérée au score global
    }


def _flatten_perceptual_for_modal(report: Dict[str, Any]) -> Dict[str, Any]:
    """Enrichit le rapport DB avec la forme canonique top-level attendue par la modale.

    Mutation idempotente : ne réécrit pas un champ déjà présent. codec N'EST PAS dérivable
    (le rapport perceptuel ne stocke pas le codec vidéo — résidu documenté, la modale
    retombe sur « — »).
    """
    if not isinstance(report, dict):
        return report
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    grain = metrics.get("grain_analysis")
    if isinstance(grain, dict) and not report.get("grain_analysis"):
        report["grain_analysis"] = grain
    vid = metrics.get("video_perceptual") if isinstance(metrics.get("video_perceptual"), dict) else {}
    res = vid.get("resolution") if isinstance(vid.get("resolution"), dict) else {}
    if res:
        if report.get("width") is None:
            report["width"] = res.get("width")
        if report.get("height") is None:
            report["height"] = res.get("height")
    # R8-056b (filet F5) : remonter hdr_analysis (sibling de resolution sous
    # video_perceptual). OUBLIÉ par le flatten initial -> d.hdr_analysis undefined ->
    # la modale retombait sur « sdr » pour TOUS les films (y compris vrais HDR10/DV/HLG),
    # valeur FAUSSE et non « unknown » : résultat faux silencieux (famille F4).
    hdr = vid.get("hdr_analysis")
    if isinstance(hdr, dict) and not report.get("hdr_analysis"):
        report["hdr_analysis"] = hdr
    # Ultra-audit 2026-08 (N32) : deux champs de MEME FAMILLE que hdr_analysis
    # etaient oublies par le flatten. `to_dict()` (domain/perceptual/models.py)
    # les place sous `metrics`, la modale les lit au top-level :
    #   - audio_perceptual -> perceptual-modal.js:327 (dynamic_range_db) : la
    #     dynamique audio etait toujours absente ;
    #   - cross_verdicts   -> perceptual-modal.js:227 et :422 : la section
    #     « Verdicts croises » etait TOUJOURS vide, pour tous les films.
    # Les deux lectures sont gardees cote JS (`&&` / Array.isArray) : pas de
    # crash, juste une information silencieusement perdue.
    audio = metrics.get("audio_perceptual")
    if isinstance(audio, dict) and not report.get("audio_perceptual"):
        flat_audio = dict(audio)
        # La modale lit `dynamic_range_db`, que le rapport ne porte nulle part :
        # la valeur existe sous `astats.dynamic_range` (ffmpeg astats, en dB,
        # cf domain/perceptual/audio_perceptual.py:249). On la derive ici sans
        # toucher au rapport stocke (copie).
        astats = audio.get("astats") if isinstance(audio.get("astats"), dict) else {}
        if flat_audio.get("dynamic_range_db") is None and astats.get("dynamic_range") is not None:
            flat_audio["dynamic_range_db"] = astats["dynamic_range"]
        report["audio_perceptual"] = flat_audio
    cross = metrics.get("cross_verdicts")
    if isinstance(cross, list) and cross and not report.get("cross_verdicts"):
        report["cross_verdicts"] = cross
    if report.get("global_tier_v2") and not report.get("display_tier"):
        report["display_tier"] = report["global_tier_v2"]
    payload = report.get("global_score_v2_payload")
    payload = payload if isinstance(payload, dict) else {}
    cats = payload.get("category_scores")
    if isinstance(cats, list) and cats and not report.get("breakdown"):
        report["breakdown"] = [_category_to_breakdown_row(c) for c in cats if isinstance(c, dict)]
    return report


def get_perceptual_report(
    api: Any,
    run_id: str,
    row_id: str,
    options: Optional[Dict[str, Any]] = None,
    *,
    rows_index: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Analyse perceptuelle d'un film unique.

    `rows_index` (usage interne, cf `analyze_perceptual_batch`) : index
    row_id -> PlanRow deja charge. Evite de relire plan.jsonl une fois par
    film quand le run n'est pas en memoire.
    """
    try:
        ctx = _validate_and_load_context(api, run_id, row_id, options, rows_index=rows_index)
        if isinstance(ctx, dict):
            return ctx  # erreur de validation
        return _execute_perceptual_analysis(api, run_id, row_id, ctx)
    except (ImportError, OSError) as exc:
        logger.warning("get_perceptual_report error run=%s row=%s: %s", run_id, row_id, exc)
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


def get_perceptual_details(
    api: Any,
    run_id: str,
    row_id: str,
) -> Dict[str, Any]:
    """Retourne TOUTES les metriques perceptuelles d'un film (lecture DB).

    Backend pour issue #32 : expose les donnees orphelines actuellement
    calculees et persistees mais non visibles cote UI :
    - audio_fingerprint (Chromaprint hash hex)
    - ssim_self_ref (auto-similarite spatiale 0-1)
    - upscale_verdict ('native_4k' / 'upscaled_1080p' / etc.)
    - spectral_cutoff_hz + lossy_verdict (audio)
    - global_score_v2 + tier_v2 + breakdown JSON

    Ne declenche AUCUNE analyse : lecture pure de la DB.
    Returns 404-like si pas d'analyse persistee.
    """
    if not run_id or not row_id:
        return _err_response("run_id et row_id requis", category="validation", level="info", log_module=__name__)
    try:
        # Pattern CineSortApi : le store est obtenu via _get_or_create_infra,
        # pas attache directement sur self.store (cf commentaire BUG dans
        # cinesort_api.py:955).
        store, _runner = api._get_or_create_infra(api._state_dir)
        report = store.perceptual.get_perceptual_report(run_id=str(run_id), row_id=str(row_id))
        if not report:
            return {
                "ok": False,
                "message": "Aucune analyse perceptuelle persistee pour ce film. Lancez l'analyse depuis l'inspecteur.",
                "missing": True,
            }
        # R8-056 (F5) : aplatit vers la forme canonique que la modale consomme
        # (grain_analysis / width / height / display_tier / breakdown top-level).
        # Avant, ces champs n'existaient qu'imbriqués -> modale à moitié vide.
        return {"ok": True, "details": _flatten_perceptual_for_modal(report)}
    except (KeyError, ValueError, OSError) as exc:
        logger.warning("get_perceptual_details error run=%s row=%s: %s", run_id, row_id, exc)
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


def _validate_and_load_context(
    api: Any,
    run_id: str,
    row_id: str,
    options: Optional[Dict[str, Any]],
    *,
    rows_index: Optional[Dict[str, Any]] = None,
) -> Any:
    """Valide les pre-requis et charge le contexte. Retourne un dict erreur ou un tuple contexte."""
    settings = api.settings.get_settings()
    if not settings.get("perceptual_enabled"):
        return _err_response(t("errors.perceptual_disabled"), category="state", level="info", log_module=__name__)

    # R8-032 (F3) : valider le binaire AVANT exec (meme garde que get_tools_status).
    ffprobe_path = safe_tool_path(settings.get("ffprobe_path"), "ffprobe")
    ffmpeg_path = resolve_ffmpeg_path(ffprobe_path)
    if not ffmpeg_path:
        # H-7 audit QA 20260429 : message explicite + suggestion d'action
        # plutot qu'erreur seche. L'utilisateur peut installer ffmpeg via
        # Reglages > Outils video.
        return {
            "ok": False,
            "message": (
                "ffmpeg est introuvable. L'analyse perceptuelle necessite ffmpeg. "
                "Installez-le depuis Reglages > Outils video (bouton 'Installer'), "
                "ou ajoutez ffmpeg.exe a coté de ffprobe.exe."
            ),
            "missing_tool": "ffmpeg",
        }

    found = api._find_run_row(run_id)
    if not found:
        return _err_response("Run introuvable.", category="resource", level="info", log_module=__name__)
    run_row, store = found

    opts = options if isinstance(options, dict) else {}
    if not bool(opts.get("force")):
        existing = store.perceptual.get_perceptual_report(run_id=run_id, row_id=row_id)
        if existing:
            metrics = dict(existing.get("metrics", {}) or {})
            for k in ("audio_fingerprint", "ssim_self_ref", "upscale_verdict", "spectral_cutoff_hz", "lossy_verdict"):
                if k in existing and existing[k] is not None:
                    metrics[k] = existing[k]
            # R6-PERC-CACHE-HIT-VOCAB : applique le meme dispatch V1/V2 que le
            # chemin non-cache (cf lignes 482-505) pour eviter que le cache_hit
            # expose le vocabulaire V1 (reference/excellent/bon/mediocre/degrade)
            # alors que VN-B.1 a promu V2 (Platinum/Gold/Silver/Bronze/Reject)
            # comme source de verite par defaut (composite_score_version=2).
            score_version = _normalize_composite_score_version(settings.get("composite_score_version"))
            metrics["composite_score_version"] = score_version
            if score_version == 2:
                v2_score = existing.get("global_score_v2")
                v2_tier = existing.get("global_tier_v2")
                if v2_score is not None and v2_tier:
                    metrics["global_score"] = int(round(float(v2_score)))
                    metrics["global_tier"] = str(v2_tier)
                else:
                    metrics["composite_score_version"] = 1
            return {"ok": True, "cache_hit": True, "perceptual": metrics}

    state_dir = normalize_user_path(run_row.get("state_dir"), api._state_dir)
    run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=False)
    rs = api._get_run(run_id)
    # Ultra-audit 2026-08 (N24) : sur un run ANTERIEUR au process courant,
    # `api._runs` est vide (seul start_plan le peuple) -> cette ligne relisait
    # INTEGRALEMENT plan.jsonl une fois PAR FILM. Mesure sur le plan reel de
    # l'utilisateur : 1027 relectures, 1.45 Go relus, +33 s, et ~19 Mo de
    # PlanRow x N workers en pointe. `rows_index` (fourni par
    # analyze_perceptual_batch) charge le plan UNE fois pour tout le batch.
    if rs and rs.rows:
        row = next((r for r in rs.rows if str(r.row_id) == str(row_id)), None)
    elif rows_index is not None:
        row = rows_index.get(str(row_id))
    else:
        rows = api._load_rows_from_plan_jsonl(run_paths)
        row = next((r for r in rows if str(r.row_id) == str(row_id)), None)
    if row is None:
        return _err_response(
            "Film introuvable dans ce plan (row_id).", category="resource", level="info", log_module=__name__
        )

    cfg = rs.cfg if rs else api._cfg_from_run_row(run_row)
    media_path = api._resolve_media_path_for_row(cfg, row)
    if media_path is None or not media_path.exists():
        return _err_response("Fichier media introuvable.", category="resource", level="warning", log_module=__name__)

    probe_result = _load_probe(api, store, run_row, media_path)
    normalized = probe_result.get("normalized") if isinstance(probe_result.get("normalized"), dict) else {}
    video_info = normalized.get("video") or {}
    width = int(video_info.get("width") or 0)
    height = int(video_info.get("height") or 0)
    probe_quality = str(normalized.get("probe_quality") or "")
    # BUG-018 (hotfix1) : helper centralise vs == "FAILED" strict case-sensitive.
    if probe_quality_is_failed(probe_quality) and width == 0 and height == 0:
        return _err_response(
            "Probe echouee (fichier corrompu ou format non supporte).",
            category="runtime",
            level="warning",
            log_module=__name__,
        )

    has_video = width > 0 and height > 0
    has_audio = len(normalized.get("audio_tracks") or []) > 0
    if not has_video and not has_audio:
        return _err_response(
            "Probe incomplete (ni video ni audio detectes).", category="runtime", level="warning", log_module=__name__
        )
    duration_s = float(normalized.get("duration_s") or 0)
    if duration_s <= 0:
        return _err_response(
            "Probe incomplete (duree manquante).", category="runtime", level="warning", log_module=__name__
        )

    return (settings, ffmpeg_path, store, run_row, row, media_path, normalized, video_info)


def _execute_perceptual_analysis(
    api: Any,
    run_id: str,
    row_id: str,
    ctx: tuple,
) -> Dict[str, Any]:
    """Execute l'analyse perceptuelle sur un contexte valide.

    §1 v7.5.0 : video et audio lances en parallele via ThreadPoolExecutor.
    Les 2 taches sont I/O-bound (ffmpeg subprocess), le GIL est libere.
    """
    settings, ffmpeg_path, store, _run_row, row, media_path, normalized, video_info = ctx
    p_settings = _build_settings_dict(settings)
    timeout_s = p_settings["timeout_per_film_s"]

    width = int(video_info.get("width") or 0)
    height = int(video_info.get("height") or 0)
    bit_depth = int(video_info.get("bit_depth") or 8)
    duration_s = float(normalized.get("duration_s") or 0)
    audio_tracks = normalized.get("audio_tracks") or []
    fps = float(video_info.get("fps") or 24.0)
    has_video = width > 0 and height > 0
    has_audio = len(audio_tracks) > 0

    frames_count = p_settings["frames_count"]
    if duration_s < 120.0:
        frames_count = min(3, frames_count)

    color_space = _detect_color_space(video_info)
    t_start = time.time()

    # §9 v7.5.0 : film_era calcule une fois en amont, utilise par _audio_task
    # (spectral cutoff contextualise) et disponible pour _video_task si besoin.
    film_era = classify_film_era(int(getattr(row, "proposed_year", 0) or 0))

    def _video_task() -> tuple:
        frames_local = extract_representative_frames(
            ffmpeg_path,
            str(media_path),
            duration_s,
            width,
            height,
            bit_depth,
            frames_count=frames_count,
            skip_percent=p_settings["skip_percent"],
            timeout_s=timeout_s,
            scene_detection_enabled=p_settings["scene_detection_enabled"],
        )
        filter_results = run_filter_graph(ffmpeg_path, str(media_path), duration_s, fps=fps, timeout_s=timeout_s)
        video_local = analyze_video_frames(
            frames_local,
            filter_results,
            bit_depth,
            color_space,
            dark_weight=p_settings["dark_weight"],
            width=width,
            height=height,
        )
        # R8-043 (F4) : reporter le type HDR détecté par le probe (métadonnée
        # couleur bt2020/smpte2084/hlg...) sur le modèle perceptuel -> exposé en
        # hdr_analysis dans to_dict -> la modale affiche le vrai format (plus « sdr »
        # systématique). hdr_type vide/absent -> reste "sdr".
        video_local.hdr_type = str(video_info.get("hdr_type") or "sdr")
        tmdb_meta = _load_tmdb_metadata(api, row)
        # §15 v7.5.0 : utilise analyze_grain_v2 si Grain Intelligence active
        if p_settings.get("grain_intelligence_enabled"):
            # Extraction AV1 film grain parameters (opt-in, uniquement si codec av1)
            codec = str(video_info.get("codec") or "").lower()
            av1_info = None
            if codec in ("av1", "av01"):
                ffprobe_path_local = safe_tool_path(settings.get("ffprobe_path"), "ffprobe")  # R8-032 (F3)
                av1_info = extract_av1_film_grain_params(ffprobe_path_local, str(media_path))
            grain_local = analyze_grain_v2(
                frames_local,
                video_blur_mean=video_local.blur_mean,
                tmdb_metadata=tmdb_meta,
                bit_depth=bit_depth,
                tmdb_year=int(getattr(row, "proposed_year", 0) or 0),
                av1_grain_info=av1_info,
                video_height=height,
            )
        else:
            grain_local = analyze_grain(
                frames_local,
                video_blur_mean=video_local.blur_mean,
                tmdb_metadata=tmdb_meta,
                bit_depth=bit_depth,
                tmdb_year=int(getattr(row, "proposed_year", 0) or 0),
            )
        # §13 v7.5.0 : SSIM self-referential (detection fake 4K)
        if p_settings["ssim_self_ref_enabled"]:
            ssim_result = compute_ssim_self_ref(
                ffmpeg_path,
                str(media_path),
                duration_s=duration_s,
                video_height=height,
                video_width=width,  # #525 : re-upscale a la resolution NATIVE
                is_animation=grain_local.is_animation,
            )
            video_local.ssim_self_ref = ssim_result.ssim_y
            video_local.upscale_verdict = ssim_result.upscale_verdict
            video_local.upscale_confidence = ssim_result.confidence
        else:
            video_local.upscale_verdict = "disabled"
        # §5 v7.5.0 : Pass 2 HDR10+ multi-frame (opt-in) si HDR10 deja detecte
        if p_settings["hdr10_plus_detection_enabled"]:
            hdr_type = str(video_info.get("hdr_type") or "")
            if hdr_type == "hdr10":
                ffprobe_path_local = safe_tool_path(settings.get("ffprobe_path"), "ffprobe")  # R8-032 (F3)
                video_local.has_hdr10_plus_detected = detect_hdr10_plus_multi_frame(
                    ffprobe_path_local,
                    str(media_path),
                )
        # §7 v7.5.0 : Fake 4K detection FFT 2D + combinaison avec §13 SSIM
        # #823 : bit_depth transmis, sinon les gardes « frame sombre / uniforme »
        # restent calibrees 8 bits et ne filtrent quasi rien sur du 10 bits.
        fft_ratio = compute_fft_hf_ratio_median(frames_local, width, height, bit_depth)
        video_local.fft_hf_ratio_median = fft_ratio
        verdict_fft, _conf_fft = classify_fake_4k_fft(
            fft_ratio, video_height=height, is_animation=grain_local.is_animation
        )
        video_local.fake_4k_verdict_fft = verdict_fft
        # Combinaison §7 + §13 (SSIM = -1 si non calcule)
        ssim_value = video_local.ssim_self_ref if video_local.ssim_self_ref >= 0 else None
        combined, conf_combined = combine_fake_4k_verdicts(fft_ratio, ssim_value)
        video_local.fake_4k_verdict_combined = combined
        video_local.fake_4k_combined_confidence = conf_combined
        # §8 v7.5.0 : Interlacing + Crop + Judder + IMAX (parallele via §1)
        meta_tasks: Dict[str, Any] = {}
        if p_settings["interlacing_detection_enabled"]:
            meta_tasks["interlace"] = lambda: detect_interlacing(ffmpeg_path, str(media_path), duration_s)
        if p_settings["crop_detection_enabled"]:
            meta_tasks["crop_segments"] = lambda: detect_crop_multi_segments(ffmpeg_path, str(media_path), duration_s)
        if p_settings["judder_detection_enabled"]:
            meta_tasks["judder"] = lambda: detect_judder(ffmpeg_path, str(media_path), duration_s)

        if meta_tasks:
            meta_results = run_parallel_tasks(
                meta_tasks,
                max_workers=min(3, len(meta_tasks)),
                timeout_per_task_s=60.0,
            )
            if "interlace" in meta_results:
                ok, val = meta_results["interlace"]
                if ok:
                    video_local.interlaced_detected = val.detected
                    video_local.interlace_type = val.interlace_type
            crop_segments = []
            if "crop_segments" in meta_results:
                ok, val = meta_results["crop_segments"]
                if ok:
                    crop_segments = val
                    crop_info = classify_crop(val, width, height)
                    video_local.crop_has_bars = crop_info.has_bars
                    video_local.crop_verdict = crop_info.verdict
                    video_local.detected_aspect_ratio = crop_info.aspect_ratio
                    video_local.detected_crop_w = crop_info.detected_w
                    video_local.detected_crop_h = crop_info.detected_h
            if "judder" in meta_results:
                ok, val = meta_results["judder"]
                if ok:
                    video_local.judder_ratio = val.drop_ratio
                    video_local.judder_verdict = val.verdict

            # IMAX derive de crop + resolution + TMDb keywords
            tmdb_keywords = (tmdb_meta.get("keywords") if tmdb_meta else None) or []
            imax_info = classify_imax(width, height, crop_segments, tmdb_keywords)
            video_local.is_imax = imax_info.is_imax
            video_local.imax_type = imax_info.imax_type
            video_local.imax_confidence = imax_info.confidence
        return (frames_local, video_local, grain_local)

    def _audio_task() -> Any:
        return analyze_audio_perceptual(
            ffmpeg_path,
            str(media_path),
            audio_tracks,
            audio_deep=p_settings["audio_deep"],
            audio_segment_s=p_settings["audio_segment_s"],
            timeout_s=timeout_s,
            enable_fingerprint=p_settings["audio_fingerprint_enabled"],
            enable_spectral=p_settings["audio_spectral_enabled"],
            enable_mel=p_settings["audio_mel_enabled"],
            duration_s=duration_s,
            film_era=film_era,
        )

    tasks: Dict[str, Any] = {}
    if has_video:
        tasks["video"] = _video_task
    if has_audio:
        tasks["audio"] = _audio_task

    max_workers = resolve_max_workers(p_settings.get("parallelism_mode", "auto"), "single_film")
    cancel_event = _resolve_cancel_event(api)
    results = run_parallel_tasks(
        tasks,
        max_workers=max_workers,
        timeout_per_task_s=float(timeout_s) if timeout_s else None,
        cancel_event=cancel_event,
    )

    video_result = None
    grain_result = None
    if "video" in results:
        ok, value = results["video"]
        if ok:
            _, video_result, grain_result = value
        else:
            logger.warning("Analyse video perceptuelle echouee run=%s row=%s: %s", run_id, row_id, value)

    audio_result = None
    if "audio" in results:
        ok, value = results["audio"]
        if ok:
            audio_result = value
        else:
            logger.warning("Analyse audio perceptuelle echouee run=%s row=%s: %s", run_id, row_id, value)

    result = build_perceptual_result(
        video_result,
        grain_result,
        audio_result,
        settings_used=p_settings,
        analysis_duration_s=time.time() - t_start,
    )
    result_dict = result.to_dict()
    fp_for_db = result.audio.audio_fingerprint if result.audio else None
    cutoff_for_db = result.audio.spectral_cutoff_hz if result.audio else None
    verdict_for_db = result.audio.lossy_verdict if result.audio else None
    ssim_for_db = result.video.ssim_self_ref if result.video else None
    upscale_for_db = result.video.upscale_verdict if result.video else None

    # §16 v7.5.0 — Score composite V2 (coexiste avec v1, stockage dedie)
    gv2_score: Optional[float] = None
    gv2_tier: Optional[str] = None
    gv2_payload: Optional[Dict[str, Any]] = None
    try:
        gv2_result = compute_global_score_v2(
            video_perceptual=video_result,
            audio_perceptual=audio_result,
            grain_analysis=grain_result,
            normalized_probe=normalized,
            nfo_consistency=None,
            runtime_vs_tmdb_flag=None,
            duration_s=duration_s,
        )
        gv2_score = gv2_result.global_score
        gv2_tier = gv2_result.global_tier
        gv2_payload = gv2_result.to_dict()
    except (ImportError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.debug("compute_global_score_v2 skipped: %s", exc)

    store.perceptual.upsert_perceptual_report(
        run_id=run_id,
        row_id=row_id,
        visual_score=result.visual_score,
        audio_score=result.audio_score,
        global_score=result.global_score,
        global_tier=result.global_tier,
        metrics=result_dict,
        settings_used=p_settings,
        audio_fingerprint=fp_for_db,
        spectral_cutoff_hz=cutoff_for_db,
        lossy_verdict=verdict_for_db,
        ssim_self_ref=ssim_for_db,
        upscale_verdict=upscale_for_db,
        global_score_v2=gv2_score,
        global_tier_v2=gv2_tier,
        global_score_v2_payload=gv2_payload,
    )
    if gv2_payload is not None:
        result_dict["global_score_v2"] = gv2_payload

    # V4-05 (Polish Total v7.7.0, R4-PERC-7 / H16) : dispatch V1/V2.
    # VN-B.1 (Vague N batch 2) : V2 est desormais la source de verite unique
    # pour `global_score`/`global_tier` (vocabulaire Platinum/Gold/Silver/...
    # Bronze/Reject). V1 reste un kill-switch de rollback explicite
    # (composite_score_version=1) qui expose le vocabulaire historique
    # reference/excellent/bon/mediocre/degrade. Avant VN-B.1 les 2 vocabulaires
    # cohabitaient cote UI selon l'endroit consomme (audit Vague N).
    # - Defaut (`composite_score_version=2`) : on promeut V2 comme score
    #   principal. Si le calcul V2 a echoue, fallback silencieux vers V1
    #   (jamais de KeyError pour l'UI).
    # - Kill-switch (`composite_score_version=1`) : conserve les valeurs V1
    #   historiques exposees par build_perceptual_result.
    score_version = int(p_settings.get("composite_score_version") or 2)
    result_dict["composite_score_version"] = score_version
    if score_version == 2:
        if gv2_payload is not None and gv2_score is not None:
            result_dict["global_score"] = int(round(float(gv2_score)))
            result_dict["global_tier"] = str(gv2_tier or result_dict.get("global_tier") or "")
        else:
            # Fallback silencieux : V2 indisponible, on conserve V1 mais on
            # annonce explicitement la version effectivement exposee pour que
            # l'UI ne mixe pas 2 vocabulaires inconsciemment.
            result_dict["composite_score_version"] = 1
    return {"ok": True, "cache_hit": False, "perceptual": result_dict}


def _build_plan_rows_index(api: Any, run_id: str) -> Optional[Dict[str, Any]]:
    """Index row_id -> PlanRow charge UNE fois depuis plan.jsonl (cf N24).

    Retourne None quand l'index n'apporte rien (run deja en memoire) ou quand
    le plan est illisible : les appelants retombent alors sur le chemin
    historique, film par film. Le dict est lu seulement (jamais mute) par les
    workers, comme l'est deja `rs.rows` sur le chemin en memoire.
    """
    try:
        rs = api._get_run(run_id)
        if rs is not None and getattr(rs, "rows", None):
            return None  # deja en memoire : rien a precharger
        found = api._find_run_row(run_id)
        if not found:
            return None
        run_row, _store = found
        state_dir = normalize_user_path(run_row.get("state_dir"), api._state_dir)
        run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=False)
        rows = api._load_rows_from_plan_jsonl(run_paths)
    except (AttributeError, KeyError, OSError, TypeError, ValueError) as exc:
        logger.debug("perceptual batch: prechargement du plan impossible (%s)", exc)
        return None
    if not rows:
        return None
    return {str(r.row_id): r for r in rows}


def analyze_perceptual_batch(
    api: Any,
    run_id: str,
    row_ids: Any,
    options: Optional[Dict[str, Any]] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
    """Analyse perceptuelle batch sur plusieurs films.

    V5-02 Polish Total v7.7.0 (R5-STRESS-5) : parallelisation inter-films via
    `run_batch_parallel` (ThreadPoolExecutor, ffmpeg subprocess libere le GIL).

    Comportement :
      - Si `perceptual_parallelism_enabled=False` OU < 2 films -> sequentiel.
      - Sinon -> pool de N workers (N = `perceptual_workers` ou auto cap 8).
      - Ordre des resultats preserve par row_id.
      - Crash worker isole : un film qui plante ne casse pas le batch.
      - Le pool intra-film (video//audio) reste actif dans chaque worker
        (tasks I/O-bound, GIL libere). Le cap interne `single_film=2` evite
        l'explosion (8 externes x 2 internes = 16 ffmpeg max, acceptable
        sur SSD moderne ; configurable par l'utilisateur si I/O sature).

    Cible : 10k films en ~2 jours sur 8 cores (vs 14 jours mono-thread).
    """
    ids = [str(r) for r in (row_ids or []) if str(r).strip()]

    # Lecture settings une fois (evite N appels concurrents get_settings).
    parallelism_enabled = True
    configured_workers = 0
    try:
        settings = api.settings.get_settings()
        parallelism_enabled = bool(settings.get("perceptual_parallelism_enabled", True))
        configured_workers = int(settings.get("perceptual_workers", 0) or 0)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.debug("analyze_perceptual_batch: settings lookup failed (%s), fallback defaults", exc)

    cancel_event = _resolve_cancel_event(api)

    # Ultra-audit 2026-08 (N24) : charger le plan UNE seule fois pour tout le
    # batch. Sans ca, chaque film relisait plan.jsonl en entier (le run n'est
    # en memoire que s'il a ete lance par CE process). None = le chemin
    # historique par film reste en place (aucune regression si l'index echoue).
    rows_index = _build_plan_rows_index(api, run_id) if len(ids) > 1 else None

    # Choix du nombre de workers + fast path sequentiel.
    if not parallelism_enabled or len(ids) < 2:
        max_workers = 1
    else:
        max_workers = resolve_batch_workers(configured_workers)

    # AUDIT 2026-06-13 (R5-C) : progress_cb(done, total) appele apres CHAQUE film
    # (thread-safe) pour alimenter une barre de progression cote UI sans perdre
    # le parallelisme. None (defaut) = comportement historique inchange.
    _total = len(ids)
    _done_lock = threading.Lock()
    _done = [0]

    def _worker(rid: str) -> Dict[str, Any]:
        try:
            return get_perceptual_report(api, run_id, rid, options, rows_index=rows_index)
        finally:
            if progress_cb is not None:
                with _done_lock:
                    _done[0] += 1
                    current = _done[0]
                try:
                    progress_cb(current, _total)
                except Exception:  # noqa: BLE001 - un cb defaillant ne casse pas le batch
                    logger.debug("analyze_perceptual_batch: progress_cb a leve, ignore", exc_info=True)

    raw_results = run_batch_parallel(
        ids,
        _worker,
        max_workers=max_workers,
        cancel_event=cancel_event,
    )

    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for rid, (ok, value) in zip(ids, raw_results, strict=True):
        if ok and isinstance(value, dict) and value.get("ok"):
            results.append(
                {
                    "row_id": rid,
                    "ok": True,
                    "global_score": value.get("perceptual", {}).get("global_score", 0),
                }
            )
        elif ok and isinstance(value, dict):
            # get_perceptual_report a renvoye un dict d'erreur structure.
            errors.append({"row_id": rid, "ok": False, "message": str(value.get("message", ""))})
        else:
            # Exception capturee par run_batch_parallel (worker a crashe).
            msg = str(value) if value is not None else "erreur inconnue"
            errors.append({"row_id": rid, "ok": False, "message": msg})

    return {
        "ok": True,
        "total": len(ids),
        "success_count": len(results),
        "error_count": len(errors),
        "results": results,
        "errors": errors,
        "workers_used": max_workers,
    }


def compare_perceptual(
    api: Any,
    run_id: str,
    row_id_a: str,
    row_id_b: str,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Comparaison perceptuelle profonde entre 2 fichiers du meme film."""
    try:
        settings = api.settings.get_settings()
        if not settings.get("perceptual_enabled"):
            return _err_response(
                t("errors.perceptual_disabled"),
                category="state",
                level="info",
                log_module=__name__,
            )

        ffprobe_path = safe_tool_path(settings.get("ffprobe_path"), "ffprobe")  # R8-032 (F3)
        ffmpeg_path = resolve_ffmpeg_path(ffprobe_path)
        if not ffmpeg_path:
            # H-7 audit QA 20260429 : message explicite avec marqueur
            return {
                "ok": False,
                "message": (
                    "ffmpeg est introuvable. La comparaison perceptuelle necessite ffmpeg. "
                    "Installez-le depuis Reglages > Outils video."
                ),
                "missing_tool": "ffmpeg",
            }

        p_settings = _build_settings_dict(settings)

        # §1 v7.5.0 : analyser A et B en parallele (chacun deja parallelise video//audio en interne).
        reports_max_workers = resolve_max_workers(p_settings.get("parallelism_mode", "auto"), "deep_compare")
        reports = run_parallel_tasks(
            {
                "a": lambda: get_perceptual_report(api, run_id, row_id_a, options),
                "b": lambda: get_perceptual_report(api, run_id, row_id_b, options),
            },
            max_workers=min(2, reports_max_workers),
            cancel_event=_resolve_cancel_event(api),
        )
        ok_a, report_a = reports.get("a", (False, {"ok": False, "message": "non execute"}))
        ok_b, report_b = reports.get("b", (False, {"ok": False, "message": "non execute"}))
        if not ok_a or not isinstance(report_a, dict) or not report_a.get("ok"):
            msg = report_a.get("message", "") if isinstance(report_a, dict) else str(report_a)
            return _err_response(
                t("errors.perceptual_file_a_failed", detail=msg),
                category="validation",
                level="info",
                log_module=__name__,
            )
        if not ok_b or not isinstance(report_b, dict) or not report_b.get("ok"):
            msg = report_b.get("message", "") if isinstance(report_b, dict) else str(report_b)
            return _err_response(
                t("errors.perceptual_file_b_failed", detail=msg),
                category="validation",
                level="info",
                log_module=__name__,
            )

        perc_a = report_a.get("perceptual", {})
        perc_b = report_b.get("perceptual", {})

        # Charger les probes pour les dimensions
        found = api._find_run_row(run_id)
        if not found:
            return _err_response("Run introuvable.", category="resource", level="info", log_module=__name__)
        run_row, store = found
        state_dir = normalize_user_path(run_row.get("state_dir"), api._state_dir)
        run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=False)
        rs = api._get_run(run_id)
        rows = rs.rows if rs and rs.rows else api._load_rows_from_plan_jsonl(run_paths)
        cfg = rs.cfg if rs else api._cfg_from_run_row(run_row)

        row_a = next((r for r in rows if str(r.row_id) == str(row_id_a)), None)
        row_b = next((r for r in rows if str(r.row_id) == str(row_id_b)), None)
        if not row_a or not row_b:
            return _err_response(
                "Film introuvable dans le plan.", category="resource", level="info", log_module=__name__
            )

        media_a = api._resolve_media_path_for_row(cfg, row_a)
        media_b = api._resolve_media_path_for_row(cfg, row_b)
        if not media_a or not media_b:
            return _err_response(
                "Fichier media introuvable.", category="resource", level="warning", log_module=__name__
            )

        probe_a = _load_probe(api, store, run_row, media_a)
        probe_b = _load_probe(api, store, run_row, media_b)
        na = probe_a.get("normalized") or {}
        nb = probe_b.get("normalized") or {}
        va = na.get("video") or {}
        vb = nb.get("video") or {}

        # NB : accede via module pour permettre patch("cinesort.domain.perceptual.comparison.extract_aligned_frames").
        aligned = _comparison_mod.extract_aligned_frames(
            ffmpeg_path,
            str(media_a),
            str(media_b),
            float(na.get("duration_s") or 0),
            float(nb.get("duration_s") or 0),
            int(va.get("width") or 0),
            int(va.get("height") or 0),
            int(vb.get("width") or 0),
            int(vb.get("height") or 0),
            frames_count=p_settings["comparison_frames"],
            skip_percent=p_settings["skip_percent"],
            timeout_s=p_settings["comparison_timeout_s"],
        )

        per_frame = compare_per_frame(aligned)

        # §11 v7.5.0 — LPIPS (perceptual distance apprise via ONNX)
        lpips_result = None
        if p_settings.get("lpips_enabled", True):
            try:
                lpips_result = compute_lpips_comparison(aligned)
            except ImportError:
                logger.debug("LPIPS module indisponible")

        report = build_comparison_report(
            perc_a,
            perc_b,
            per_frame,
            str(media_a),
            str(media_b),
            lpips_result=lpips_result,
        )

        # §16b v7.5.0 — Exposer les scores V2 cote-a-cote si dispo.
        gsv2_a = perc_a.get("global_score_v2") if isinstance(perc_a, dict) else None
        gsv2_b = perc_b.get("global_score_v2") if isinstance(perc_b, dict) else None
        if gsv2_a:
            report["global_score_v2_a"] = gsv2_a
        if gsv2_b:
            report["global_score_v2_b"] = gsv2_b

        return {"ok": True, "comparison": report}

    except (OSError, KeyError, TypeError, ValueError) as exc:
        logger.warning("compare_perceptual error: %s", exc)
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


def get_perceptual_compare_frames(
    api: Any,
    run_id: str,
    row_id_a: str,
    row_id_b: str,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Cf #94 (audit-2026-05-12:s3t5) : extrait N paires de frames cote-a-cote.

    Les frames perceptuelles sont calculees pendant `compare_perceptual` mais
    JAMAIS exposees au frontend, alors qu'elles sont la cle pour valider
    visuellement une decision destructrice (supprimer un doublon).

    Strategie :
    1. Reuse `extract_aligned_frames` (greyscale Y plane).
    2. Picker les N frames avec la plus grosse difference (`compute_pixel_diff`)
       pour montrer ce qui distingue les fichiers.
    3. Encoder en PNG base64 via Pillow (mode "L" pour luminance).

    Cap a 3 frames par defaut (response ~1.5 MB max pour 1080p luminance).

    Returns: `{ok, frames: [{timestamp, frame_a_b64, frame_b_b64, mean_diff,
              max_diff}], width, height}` ou err.
    """
    max_frames = 3
    if isinstance(options, dict):
        try:
            max_frames = int(options.get("max_frames", 3))
        except (TypeError, ValueError):
            max_frames = 3
        max_frames = max(1, min(5, max_frames))

    if not run_id or not row_id_a or not row_id_b:
        return _err_response(
            "run_id, row_id_a et row_id_b requis", category="validation", level="info", log_module=__name__
        )

    try:
        settings = api.settings.get_settings()
        if not settings.get("perceptual_enabled"):
            return _err_response(
                t("errors.perceptual_disabled"),
                category="state",
                level="info",
                log_module=__name__,
            )

        ffprobe_path = safe_tool_path(settings.get("ffprobe_path"), "ffprobe")  # R8-032 (F3)
        ffmpeg_path = resolve_ffmpeg_path(ffprobe_path)
        if not ffmpeg_path:
            return _err_response(
                "ffmpeg introuvable.", category="config", level="info", log_module=__name__, missing_tool="ffmpeg"
            )

        found = api._find_run_row(run_id)
        if not found:
            return _err_response("Run introuvable.", category="resource", level="info", log_module=__name__)
        run_row, store = found
        state_dir = normalize_user_path(run_row.get("state_dir"), api._state_dir)
        run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=False)
        rs = api._get_run(run_id)
        rows = rs.rows if rs and rs.rows else api._load_rows_from_plan_jsonl(run_paths)
        cfg = rs.cfg if rs else api._cfg_from_run_row(run_row)

        row_a = next((r for r in rows if str(r.row_id) == str(row_id_a)), None)
        row_b = next((r for r in rows if str(r.row_id) == str(row_id_b)), None)
        if not row_a or not row_b:
            return _err_response(
                "Film introuvable dans le plan.", category="resource", level="info", log_module=__name__
            )

        media_a = api._resolve_media_path_for_row(cfg, row_a)
        media_b = api._resolve_media_path_for_row(cfg, row_b)
        if not media_a or not media_b:
            return _err_response(
                "Fichier media introuvable.", category="resource", level="warning", log_module=__name__
            )

        probe_a = _load_probe(api, store, run_row, media_a)
        probe_b = _load_probe(api, store, run_row, media_b)
        na = probe_a.get("normalized") or {}
        nb = probe_b.get("normalized") or {}
        va = na.get("video") or {}
        vb = nb.get("video") or {}

        p_settings = _build_settings_dict(settings)
        # NB : accede via module pour permettre patch("cinesort.domain.perceptual.comparison.extract_aligned_frames").
        aligned = _comparison_mod.extract_aligned_frames(
            ffmpeg_path,
            str(media_a),
            str(media_b),
            float(na.get("duration_s") or 0),
            float(nb.get("duration_s") or 0),
            int(va.get("width") or 0),
            int(va.get("height") or 0),
            int(vb.get("width") or 0),
            int(vb.get("height") or 0),
            frames_count=p_settings["comparison_frames"],
            skip_percent=p_settings["skip_percent"],
            timeout_s=p_settings["comparison_timeout_s"],
        )
        if not aligned:
            return _err_response("Aucune frame alignee extraite.", category="state", level="info", log_module=__name__)

        # Rank par mean_diff descendant et prend les top N.
        ranked = []
        for frame in aligned:
            diff = _comparison_mod.compute_pixel_diff(frame["pixels_a"], frame["pixels_b"])
            if diff is None:
                continue
            ranked.append((diff["mean_diff"], diff, frame))
        ranked.sort(key=lambda x: x[0], reverse=True)
        top = ranked[:max_frames]

        # Encode en PNG base64 (greyscale, mode "L").
        import base64
        import io

        from PIL import Image

        frames_out: List[Dict[str, Any]] = []
        width = aligned[0]["width"]
        height = aligned[0]["height"]
        for mean_diff, diff, frame in top:
            # B3 : pixels est desormais np.ndarray (sortie parse_raw_frame).
            # bytes(ndarray) interprete ndarray comme un iterateur d'ints,
            # ce qui est ~10x plus lent que .tobytes() (qui fait un memcpy).
            # Fallback bytes() pour les List[int] legacy des fixtures.
            pa = frame["pixels_a"]
            pb = frame["pixels_b"]
            data_a = pa.tobytes() if hasattr(pa, "tobytes") else bytes(pa)
            data_b = pb.tobytes() if hasattr(pb, "tobytes") else bytes(pb)
            img_a = Image.frombytes("L", (width, height), data_a)
            img_b = Image.frombytes("L", (width, height), data_b)
            buf_a = io.BytesIO()
            buf_b = io.BytesIO()
            img_a.save(buf_a, format="PNG", optimize=True)
            img_b.save(buf_b, format="PNG", optimize=True)
            frames_out.append(
                {
                    "timestamp": frame["timestamp"],
                    "frame_a_b64": base64.b64encode(buf_a.getvalue()).decode("ascii"),
                    "frame_b_b64": base64.b64encode(buf_b.getvalue()).decode("ascii"),
                    "mean_diff": diff["mean_diff"],
                    "max_diff": diff["max_diff"],
                }
            )

        return {
            "ok": True,
            "width": width,
            "height": height,
            "frame_count": len(frames_out),
            "frames": frames_out,
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        logger.warning("get_perceptual_compare_frames error: %s", exc)
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


# =============================================================================
# Phase 4 doublons (cf docs/internal/design/refonte_2026_05_17/screens/01-doublons.md)
# =============================================================================

# Registry global des jobs perceptuels batch en cours / termines.
# Cle = job_id, valeur = dict {status, total, done, errors, ts_start, ts_end, results}.
# Threading : lock dedie pour eviter les courses entre worker thread et polling.
_PERCEPTUAL_JOBS_LOCK = threading.RLock()
_PERCEPTUAL_JOBS: Dict[str, Dict[str, Any]] = {}
_PERCEPTUAL_JOB_RETENTION = 16  # cap pour eviter la fuite memoire


def _record_job_snapshot(job_id: str, **changes: Any) -> None:
    with _PERCEPTUAL_JOBS_LOCK:
        snapshot = _PERCEPTUAL_JOBS.get(job_id)
        if not snapshot:
            return
        snapshot.update(changes)


def _trim_perceptual_jobs() -> None:
    """Cap memoire : on garde les N derniers jobs termines + tous les actifs."""
    with _PERCEPTUAL_JOBS_LOCK:
        if len(_PERCEPTUAL_JOBS) <= _PERCEPTUAL_JOB_RETENTION:
            return
        finished = sorted(
            ((k, v) for k, v in _PERCEPTUAL_JOBS.items() if v.get("status") in ("done", "error", "cancelled")),
            key=lambda kv: kv[1].get("ts_end") or 0.0,
        )
        excess = len(_PERCEPTUAL_JOBS) - _PERCEPTUAL_JOB_RETENTION
        for k, _v in finished[:excess]:
            _PERCEPTUAL_JOBS.pop(k, None)


def _normalize_pairs(pairs: Any) -> List[Dict[str, str]]:
    """Normalise la liste de paires en dicts {run_id, row_a, row_b}.

    Tolere les variantes {row_id_a, row_id_b} pour compat. Skip silencieux
    les entrees malformees.
    """
    out: List[Dict[str, str]] = []
    if not isinstance(pairs, (list, tuple)):
        return out
    for item in pairs:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("run_id") or "").strip()
        a = str(item.get("row_a") or item.get("row_id_a") or "").strip()
        b = str(item.get("row_b") or item.get("row_id_b") or "").strip()
        if not rid or not a or not b:
            continue
        out.append({"run_id": rid, "row_a": a, "row_b": b})
    return out


def _run_perceptual_job(
    api: Any,
    job_id: str,
    pairs: List[Dict[str, str]],
    options: Optional[Dict[str, Any]],
) -> None:
    """Worker thread daemon : execute compare_perceptual sur chaque paire.

    BUG-005: garde-fou large `except Exception` autour de toute la boucle worker
    pour eviter qu'une exception inattendue (RuntimeError, AttributeError, etc.)
    laisse le job en status="running" indefiniment. Le catch etroit interne
    (OSError/KeyError/TypeError/ValueError) reste pour qu'une paire defaillante
    n'interrompe pas le batch, tandis que le catch externe garantit une
    finalisation systematique status=error+ts_end en cas de plantage fatal.

    Hotfix2 (H12) : verifie `api._perceptual_cancel_event` (s'il existe) entre
    chaque paire pour permettre un shutdown propre du batch sans laisser de
    ffmpeg orphelins ni de jobs bloques en "running". Les ffmpeg lances par
    compare_perceptual sont deja proteges par `tracked_run` (registre global
    + cleanup atexit), donc le shutdown gracieux les tue. Le check ici evite
    de demarrer une NOUVELLE paire apres signal cancel + marque le job comme
    "cancelled" avec ts_end pour finalisation propre.
    """
    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    done_count = 0
    cancel_event = _resolve_cancel_event(api)
    cancelled = False
    try:
        for pair in pairs:
            # H12: check cancel AVANT de lancer une nouvelle paire — evite de
            # demarrer un compare_perceptual (qui spawn ffmpeg) sur shutdown.
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            try:
                res = compare_perceptual(api, pair["run_id"], pair["row_a"], pair["row_b"], options)
                if isinstance(res, dict) and res.get("ok"):
                    results.append({**pair, "ok": True})
                else:
                    msg = str(res.get("message", "")) if isinstance(res, dict) else "erreur inconnue"
                    errors.append({**pair, "ok": False, "message": msg})
            except (OSError, KeyError, TypeError, ValueError) as exc:
                errors.append({**pair, "ok": False, "message": str(exc)})
            done_count += 1
            _record_job_snapshot(job_id, done=done_count, errors=list(errors), results=list(results))

        # Status final : cancelled si event signale en cours de boucle, sinon done.
        final_status = "cancelled" if cancelled else "done"
        _record_job_snapshot(
            job_id,
            status=final_status,
            done=done_count,
            ts_end=time.time(),
            results=list(results),
            errors=list(errors),
        )
    except Exception as exc:  # noqa: BLE001 - garde-fou worker thread
        logger.exception("perceptual job %s a echoue: %s", job_id, exc)
        try:
            _record_job_snapshot(
                job_id,
                status="error",
                done=done_count,
                ts_end=time.time(),
                results=list(results),
                errors=list(errors) + [{"ok": False, "message": f"job worker failure: {exc}"}],
            )
        except Exception:  # noqa: BLE001 - dernier rempart, jamais propager hors du thread
            logger.exception("perceptual job %s : impossible d'enregistrer le snapshot d'erreur", job_id)
    finally:
        try:
            _trim_perceptual_jobs()
        except Exception:  # noqa: BLE001
            logger.exception("perceptual job %s : _trim_perceptual_jobs a echoue", job_id)


def queue_perceptual_analyses(
    api: Any,
    pairs: Any,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Queue un batch d'analyses perceptuelles en background.

    Cf spec section 1 "Analyser perceptuel sur N groupes" + section 4 §4.
    Lance un thread daemon qui execute compare_perceptual sur chaque paire,
    expose le job_id pour polling via get_perceptual_job_status.

    Args:
        pairs: liste de {run_id, row_a, row_b}.
        options: passe a compare_perceptual (force, etc.).

    Returns:
        {ok: True, job_id, total} ou err.
    """
    normalized = _normalize_pairs(pairs)
    if not normalized:
        return _err_response(
            "Aucune paire valide. Format attendu : [{run_id, row_a, row_b}, ...]",
            category="validation",
            level="info",
            log_module=__name__,
        )

    job_id = f"perceptual_batch_{int(time.time() * 1000)}_{id(normalized) & 0xFFFF:04x}"
    snapshot: Dict[str, Any] = {
        "job_id": job_id,
        "status": "running",
        "total": len(normalized),
        "done": 0,
        "results": [],
        "errors": [],
        "ts_start": time.time(),
        "ts_end": None,
    }
    with _PERCEPTUAL_JOBS_LOCK:
        _PERCEPTUAL_JOBS[job_id] = snapshot

    thread = threading.Thread(
        target=_run_perceptual_job,
        args=(api, job_id, normalized, options),
        name=f"perc-{job_id}",
        daemon=True,
    )
    thread.start()

    return {"ok": True, "job_id": job_id, "total": len(normalized)}


def _run_perceptual_batch_job(
    api: Any,
    job_id: str,
    run_id: str,
    row_ids: List[str],
    options: Optional[Dict[str, Any]],
) -> None:
    """Worker thread daemon : analyse perceptuelle batch SINGLE-film (pas paires).

    Reutilise analyze_perceptual_batch (parallelisme + tally) en lui passant un
    progress_cb qui met a jour le snapshot du job (done/total) apres chaque film.
    Garde-fou large pour finaliser le job meme en cas de plantage (cf
    _run_perceptual_job pour la meme logique sur les paires).
    """
    try:

        def _cb(done: int, _total: int) -> None:
            _record_job_snapshot(job_id, done=done)

        res = analyze_perceptual_batch(api, run_id, row_ids, options, progress_cb=_cb)
        ok = bool(res.get("ok"))
        results = list(res.get("results") or [])
        errors = list(res.get("errors") or [])
        _record_job_snapshot(
            job_id,
            status="done" if ok else "error",
            done=int(res.get("total") or len(row_ids)),
            ts_end=time.time(),
            results=results,
            errors=errors,
            success_count=int(res.get("success_count") or len(results)),
            error_count=int(res.get("error_count") or len(errors)),
        )
    except Exception as exc:  # noqa: BLE001 - garde-fou worker thread
        logger.exception("perceptual batch job %s a echoue: %s", job_id, exc)
        try:
            _record_job_snapshot(
                job_id,
                status="error",
                ts_end=time.time(),
                errors=[{"ok": False, "message": f"job worker failure: {exc}"}],
            )
        except Exception:  # noqa: BLE001 - dernier rempart
            logger.exception("perceptual batch job %s : snapshot d'erreur impossible", job_id)
    finally:
        try:
            _trim_perceptual_jobs()
        except Exception:  # noqa: BLE001
            logger.exception("perceptual batch job %s : _trim a echoue", job_id)


def queue_perceptual_batch(
    api: Any,
    run_id: str,
    row_ids: Any,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Queue une analyse perceptuelle batch SINGLE-film en background.

    AUDIT 2026-06-13 (R5-C/D) : variante async de analyze_perceptual_batch pour
    la bibliotheque. Avant, le bouton "Analyser perceptuel" appelait le endpoint
    bloquant -> requete suspendue plusieurs minutes sans progression ni refresh,
    toast "lancee" trompeur. On expose desormais un job_id pollable via
    get_perceptual_job_status (meme registre que les paires de doublons), avec
    progression done/total.

    Returns: {ok, job_id, total} ou err.
    """
    ids = [str(r) for r in (row_ids or []) if str(r).strip()]
    if not run_id or not str(run_id).strip():
        return _err_response("run_id requis.", category="validation", level="info", log_module=__name__)
    if not ids:
        return _err_response("Aucun row_id valide.", category="validation", level="info", log_module=__name__)

    job_id = f"perceptual_batch_{int(time.time() * 1000)}_{id(ids) & 0xFFFF:04x}"
    snapshot: Dict[str, Any] = {
        "job_id": job_id,
        "status": "running",
        "total": len(ids),
        "done": 0,
        "results": [],
        "errors": [],
        "ts_start": time.time(),
        "ts_end": None,
    }
    with _PERCEPTUAL_JOBS_LOCK:
        _PERCEPTUAL_JOBS[job_id] = snapshot

    thread = threading.Thread(
        target=_run_perceptual_batch_job,
        args=(api, job_id, str(run_id), ids, options),
        name=f"perc-batch-{job_id}",
        daemon=True,
    )
    thread.start()

    return {"ok": True, "job_id": job_id, "total": len(ids)}


def get_perceptual_job_status(api: Any, job_id: str) -> Dict[str, Any]:  # noqa: ARG001
    """Polling : retourne le statut d'un job perceptuel batch.

    Returns:
        {ok: True, job_id, status, total, done, results, errors, ts_start, ts_end}
        ou err si job_id inconnu.
    """
    if not job_id or not str(job_id).strip():
        return _err_response("job_id requis.", category="validation", level="info", log_module=__name__)
    with _PERCEPTUAL_JOBS_LOCK:
        snap = _PERCEPTUAL_JOBS.get(str(job_id))
        if not snap:
            return _err_response("Job inconnu.", category="resource", level="info", log_module=__name__)
        # Copie defensive pour eviter race condition cote caller.
        return {"ok": True, **{k: (list(v) if isinstance(v, list) else v) for k, v in snap.items()}}


def get_perceptual_compare_audio(
    api: Any,
    run_id: str,
    row_id_a: str,
    row_id_b: str,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Extrait waveform PNG + clip MP3 court pour les 2 films d'une paire.

    Cf spec section 3 "Comparaison audio" + section 4 §2.

    Pour chaque fichier :
      - Genere une waveform PNG via ffmpeg `showwavespic=s=400x80` sur un
        timestamp representatif (par defaut milieu du film).
      - Extrait un clip MP3 court (~10s par defaut) via ffmpeg
        `-c:a libmp3lame -b:a 96k`.

    Args:
        run_id, row_id_a, row_id_b: identifiants standards.
        options: dict optionnel :
            - duration_s (int, 5-30, def 10)
            - timestamp_s (float, def = duration/2)
            - width / height (int, def 400x80)

    Returns:
        {ok, waveform_a_b64, waveform_b_b64, audio_a_b64, audio_b_b64,
         audio_mime, duration_s, timestamp_s} ou err.
    """
    opts = options if isinstance(options, dict) else {}
    try:
        duration_s = int(opts.get("duration_s") or 10)
    except (TypeError, ValueError):
        duration_s = 10
    duration_s = max(5, min(30, duration_s))

    try:
        waveform_w = int(opts.get("width") or 400)
    except (TypeError, ValueError):
        waveform_w = 400
    try:
        waveform_h = int(opts.get("height") or 80)
    except (TypeError, ValueError):
        waveform_h = 80
    waveform_w = max(100, min(1200, waveform_w))
    waveform_h = max(40, min(400, waveform_h))

    if not run_id or not row_id_a or not row_id_b:
        return _err_response(
            "run_id, row_id_a et row_id_b requis",
            category="validation",
            level="info",
            log_module=__name__,
        )

    try:
        settings = api.settings.get_settings()
        if not settings.get("perceptual_enabled"):
            return _err_response(
                t("errors.perceptual_disabled"),
                category="state",
                level="info",
                log_module=__name__,
            )

        ffprobe_path = safe_tool_path(settings.get("ffprobe_path"), "ffprobe")  # R8-032 (F3)
        ffmpeg_path = resolve_ffmpeg_path(ffprobe_path)
        if not ffmpeg_path:
            return _err_response(
                "ffmpeg introuvable.",
                category="config",
                level="info",
                log_module=__name__,
                missing_tool="ffmpeg",
            )

        found = api._find_run_row(run_id)
        if not found:
            return _err_response("Run introuvable.", category="resource", level="info", log_module=__name__)
        run_row, store = found
        state_dir = normalize_user_path(run_row.get("state_dir"), api._state_dir)
        run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=False)
        rs = api._get_run(run_id)
        rows = rs.rows if rs and rs.rows else api._load_rows_from_plan_jsonl(run_paths)
        cfg = rs.cfg if rs else api._cfg_from_run_row(run_row)

        row_a = next((r for r in rows if str(r.row_id) == str(row_id_a)), None)
        row_b = next((r for r in rows if str(r.row_id) == str(row_id_b)), None)
        if not row_a or not row_b:
            return _err_response(
                "Film introuvable dans le plan.",
                category="resource",
                level="info",
                log_module=__name__,
            )

        media_a = api._resolve_media_path_for_row(cfg, row_a)
        media_b = api._resolve_media_path_for_row(cfg, row_b)
        if not media_a or not media_b:
            return _err_response(
                "Fichier media introuvable.",
                category="resource",
                level="warning",
                log_module=__name__,
            )

        probe_a = _load_probe(api, store, run_row, media_a)
        probe_b = _load_probe(api, store, run_row, media_b)
        na = (probe_a.get("normalized") if isinstance(probe_a, dict) else {}) or {}
        nb = (probe_b.get("normalized") if isinstance(probe_b, dict) else {}) or {}
        dur_a = float(na.get("duration_s") or 0)
        dur_b = float(nb.get("duration_s") or 0)

        # Timestamp par defaut = milieu de la duree min (les 2 films sont supposes
        # representer le meme contenu : on prend la borne la plus prudente).
        if opts.get("timestamp_s") is not None:
            try:
                ts = float(opts.get("timestamp_s") or 0)
            except (TypeError, ValueError):
                ts = max(dur_a, dur_b) / 2.0
        else:
            base = min(dur_a, dur_b) if dur_a > 0 and dur_b > 0 else max(dur_a, dur_b)
            ts = base / 2.0 if base > 0 else 0.0
        # On s'assure qu'on a au moins `duration_s` de marge avant la fin.
        ts = max(0.0, ts)

        # Extraction sequentielle (2 paires waveform+audio = 4 ffmpeg) — le batch
        # batch est court (~2s par fichier sur SSD moderne), pas la peine de
        # paralleliser pour 4 jobs.
        waveform_a_b64 = _extract_audio_waveform_b64(ffmpeg_path, str(media_a), ts, duration_s, waveform_w, waveform_h)
        waveform_b_b64 = _extract_audio_waveform_b64(ffmpeg_path, str(media_b), ts, duration_s, waveform_w, waveform_h)
        audio_a_b64 = _extract_audio_clip_b64(ffmpeg_path, str(media_a), ts, duration_s)
        audio_b_b64 = _extract_audio_clip_b64(ffmpeg_path, str(media_b), ts, duration_s)

        return {
            "ok": True,
            "waveform_a_b64": waveform_a_b64,
            "waveform_b_b64": waveform_b_b64,
            "audio_a_b64": audio_a_b64,
            "audio_b_b64": audio_b_b64,
            "audio_mime": "audio/mpeg",
            "duration_s": duration_s,
            "timestamp_s": float(ts),
            "width": waveform_w,
            "height": waveform_h,
        }

    except (OSError, KeyError, TypeError, ValueError) as exc:
        logger.warning("get_perceptual_compare_audio error: %s", exc)
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


def _extract_audio_waveform_b64(
    ffmpeg_path: str,
    media_path: str,
    ts: float,
    duration_s: int,
    width: int,
    height: int,
) -> str:
    """Genere une waveform PNG via `ffmpeg showwavespic`, retourne base64.

    Renvoie chaine vide si ffmpeg echoue (pas d'erreur, l'UI peut afficher
    un placeholder).

    Hotfix2 (C1) : utilise `tracked_run` pour garantir le cleanup du child
    ffmpeg en cas de shutdown / KeyboardInterrupt / exception (sinon zombie
    ffmpeg.exe sur Windows). Applique aussi `CREATE_NO_WINDOW` pour eviter
    le flash de console.
    """
    import base64

    cmd = [
        ffmpeg_path,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(max(0.0, float(ts))),
        "-t",
        str(int(duration_s)),
        "-i",
        media_path,
        "-filter_complex",
        f"showwavespic=s={int(width)}x{int(height)}:colors=#4FC3F7",
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-c:v",
        "png",
        "-",
    ]
    platform_kwargs = _ffmpeg_platform_kwargs()
    try:
        result = tracked_run(  # noqa: S603 - cmd built from sanitized args
            cmd,
            capture_output=True,
            timeout=30,
            check=False,
            **platform_kwargs,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("waveform ffmpeg failed (%s)", exc)
        return ""
    if result.returncode != 0 or not result.stdout:
        return ""
    return base64.b64encode(result.stdout).decode("ascii")


def _extract_audio_clip_b64(
    ffmpeg_path: str,
    media_path: str,
    ts: float,
    duration_s: int,
) -> str:
    """Extrait un clip MP3 court via ffmpeg + libmp3lame, retourne base64.

    Hotfix2 (C1) : utilise `tracked_run` pour garantir le cleanup du child
    ffmpeg en cas de shutdown / KeyboardInterrupt / exception (sinon zombie
    ffmpeg.exe sur Windows). Applique aussi `CREATE_NO_WINDOW` pour eviter
    le flash de console.
    """
    import base64

    cmd = [
        ffmpeg_path,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(max(0.0, float(ts))),
        "-t",
        str(int(duration_s)),
        "-i",
        media_path,
        "-vn",
        "-ac",
        "2",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "96k",
        "-f",
        "mp3",
        "-",
    ]
    platform_kwargs = _ffmpeg_platform_kwargs()
    try:
        result = tracked_run(  # noqa: S603 - cmd built from sanitized args
            cmd,
            capture_output=True,
            timeout=30,
            check=False,
            **platform_kwargs,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("audio clip ffmpeg failed (%s)", exc)
        return ""
    if result.returncode != 0 or not result.stdout:
        return ""
    return base64.b64encode(result.stdout).decode("ascii")


def enrich_quality_report_with_perceptual(
    store: Any,
    run_id: str,
    row_id: str,
    result: Dict[str, Any],
    *,
    composite_score_version: int = 2,
) -> None:
    """Enrichit un rapport qualite technique avec les donnees perceptuelles si disponibles.

    V4-05 (Polish Total v7.7.0, R4-PERC-7 / H16) : si `composite_score_version=2`,
    on substitue le score/tier global par la version V2 (stockee en BDD via
    migration 018). Fallback silencieux sur V1 si V2 indisponible (legacy row
    sans calcul V2, ou kill-switch V1 active).

    VN-B.1 (Vague N batch 2) : V2 est desormais le defaut explicite. Les
    appels legacy sans kwarg recoivent automatiquement le vocabulaire
    Platinum/Gold/Silver/Bronze/Reject, supprimant le mix v1/v2 cote UI.
    """
    try:
        perc = store.perceptual.get_perceptual_report(run_id=run_id, row_id=row_id)
        if not perc:
            return
        global_score = perc.get("global_score", 0)
        global_tier = perc.get("global_tier", "")
        used_version = 1
        if int(composite_score_version) == 2:
            v2_score = perc.get("global_score_v2")
            v2_tier = perc.get("global_tier_v2")
            if v2_score is not None and v2_tier:
                global_score = int(round(float(v2_score)))
                global_tier = str(v2_tier)
                used_version = 2
        result["perceptual"] = {
            "global_score": global_score,
            "global_tier": global_tier,
            "visual_score": perc.get("visual_score", 0),
            "audio_score": perc.get("audio_score", 0),
            "composite_score_version": used_version,
        }
    except (KeyError, OSError, TypeError, ValueError):
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_settings_dict(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Extrait les parametres perceptuels depuis les settings."""
    return {
        "enabled": bool(settings.get("perceptual_enabled")),
        "auto_on_scan": bool(settings.get("perceptual_auto_on_scan")),
        "auto_on_quality": bool(settings.get("perceptual_auto_on_quality")),
        "timeout_per_film_s": int(settings.get("perceptual_timeout_per_film_s") or 120),
        "frames_count": int(settings.get("perceptual_frames_count") or 10),
        "skip_percent": int(settings.get("perceptual_skip_percent") or 5),
        "dark_weight": float(settings.get("perceptual_dark_weight") or 1.5),
        "audio_deep": bool(settings.get("perceptual_audio_deep", True)),
        "audio_segment_s": int(settings.get("perceptual_audio_segment_s") or 30),
        "comparison_frames": int(settings.get("perceptual_comparison_frames") or 20),
        "comparison_timeout_s": int(settings.get("perceptual_comparison_timeout_s") or 600),
        "parallelism_mode": str(settings.get("perceptual_parallelism_mode") or "auto").strip().lower(),
        "audio_fingerprint_enabled": bool(settings.get("perceptual_audio_fingerprint_enabled", True)),
        "scene_detection_enabled": bool(settings.get("perceptual_scene_detection_enabled", True)),
        "audio_spectral_enabled": bool(settings.get("perceptual_audio_spectral_enabled", True)),
        "ssim_self_ref_enabled": bool(settings.get("perceptual_ssim_self_ref_enabled", True)),
        "hdr10_plus_detection_enabled": bool(settings.get("perceptual_hdr10_plus_detection_enabled", True)),
        "interlacing_detection_enabled": bool(settings.get("perceptual_interlacing_detection_enabled", True)),
        "crop_detection_enabled": bool(settings.get("perceptual_crop_detection_enabled", True)),
        "judder_detection_enabled": bool(settings.get("perceptual_judder_detection_enabled", False)),
        "grain_intelligence_enabled": bool(settings.get("perceptual_grain_intelligence_enabled", True)),
        "audio_mel_enabled": bool(settings.get("perceptual_audio_mel_enabled", True)),
        "lpips_enabled": bool(settings.get("perceptual_lpips_enabled", True)),
        # V4-05 (Polish Total v7.7.0, R4-PERC-7 / H16) : toggle V1 (defaut) | V2.
        # Determine quel score est expose comme "global_score" principal et
        # propage dans les enrichissements quality_report. V2 reste calcule
        # cote BDD (cache `composite_score_v2` en migration 018) pour preserver
        # la possibilite de switch sans re-scan complet.
        "composite_score_version": _normalize_composite_score_version(settings.get("composite_score_version")),
    }


def _load_probe(api: Any, store: Any, run_row: Any, media_path: Any) -> Dict[str, Any]:
    """Charge la probe existante pour un fichier media."""
    probe_settings = api._effective_probe_settings_for_runtime(run_row)
    probe = ProbeService(store)
    return probe.probe_file(media_path=media_path, settings=probe_settings)


def _build_tmdb_client(api: Any):
    """Construit un TmdbClient depuis les settings (secrets en clair), ou None.

    AUDIT 2026-06-10 (REAL 2/2) : `api._tmdb_client()` n'existe pas sur
    CineSortApi -> AttributeError (hors du except de _load_tmdb_metadata) qui
    remontait dans _video_task et faisait echouer TOUTE l'analyse video
    perceptuelle (grain, fake-4K, HDR10+, etc.) pour tout film avec un tmdb_id.
    On construit le client correctement, avec la cle dé-masquee.
    """
    try:
        settings = api._internal_settings()
        api_key = str(settings.get("tmdb_api_key") or "").strip()
        if not api_key:
            return None
        import cinesort.infra.state as _state  # noqa: PLC0415
        from cinesort.infra.tmdb_client import TmdbClient  # noqa: PLC0415
        from cinesort.ui.api.settings_support import normalize_user_path  # noqa: PLC0415

        state_dir = normalize_user_path(settings.get("state_dir"), _state.default_state_dir())
        try:
            cache_ttl_days = int(settings.get("tmdb_cache_ttl_days") or 30)
        except (TypeError, ValueError):
            cache_ttl_days = 30
        return TmdbClient(
            api_key=api_key,
            cache_path=state_dir / "tmdb_cache.json",
            timeout_s=float(settings.get("tmdb_timeout_s") or 10.0),
            cache_ttl_days=cache_ttl_days,
        )
    except (ImportError, AttributeError, OSError, TypeError, ValueError) as exc:
        logger.debug("perceptual: build TmdbClient failed (best-effort): %s", exc)
        return None


def _load_tmdb_metadata(api: Any, row: Any) -> Optional[Dict[str, Any]]:
    """Charge les metadata TMDb pour l'analyse grain (genres, budget, companies)."""
    tmdb_id = 0
    candidates = getattr(row, "candidates", []) or []
    if candidates:
        tmdb_id = int(getattr(candidates[0], "tmdb_id", 0) or 0)
    if tmdb_id <= 0:
        return None
    try:
        tmdb = _build_tmdb_client(api)
        if tmdb:
            return tmdb.get_movie_metadata_for_perceptual(tmdb_id)
    except (ImportError, AttributeError, KeyError, OSError, TypeError, ValueError):
        pass
    return None


def _resolve_cancel_event(api: Any) -> Optional[threading.Event]:
    """Retourne le cancel event uniquement s'il s'agit d'un vrai threading.Event.

    Protege contre les MagicMock dans les tests : getattr retournerait un mock
    truthy qui ferait tout annuler.
    """
    event = getattr(api, "_perceptual_cancel_event", None)
    if isinstance(event, threading.Event):
        return event
    return None


def _detect_color_space(video_info: Dict[str, Any]) -> str:
    """Detecte le color space depuis les infos video probe."""
    cs = str(video_info.get("color_space") or "").lower()
    cp = str(video_info.get("color_primaries") or "").lower()
    if "2020" in cs or "2020" in cp:
        return "bt2020"
    return "bt709"
