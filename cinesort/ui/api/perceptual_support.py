"""Orchestration analyse perceptuelle — single film + batch."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from cinesort.domain.perceptual.ffmpeg_runner import resolve_ffmpeg_path
from cinesort.domain.perceptual.frame_extraction import extract_representative_frames
from cinesort.domain.perceptual.video_analysis import analyze_video_frames, run_filter_graph
from cinesort.domain.perceptual.grain_analysis import analyze_grain
from cinesort.domain.perceptual.audio_perceptual import analyze_audio_perceptual
from cinesort.domain.perceptual.composite_score import build_perceptual_result
from cinesort.domain.perceptual.parallelism import (
    resolve_batch_workers,
    resolve_max_workers,
    run_batch_parallel,
    run_parallel_tasks,
)
from cinesort.ui.api.settings_support import normalize_user_path

logger = logging.getLogger(__name__)


def get_perceptual_report(
    api: Any,
    run_id: str,
    row_id: str,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Analyse perceptuelle d'un film unique."""
    try:
        ctx = _validate_and_load_context(api, run_id, row_id, options)
        if isinstance(ctx, dict):
            return ctx  # erreur de validation
        return _execute_perceptual_analysis(api, run_id, row_id, ctx)
    except (ImportError, OSError) as exc:
        logger.warning("get_perceptual_report error run=%s row=%s: %s", run_id, row_id, exc)
        return {"ok": False, "message": str(exc)}


def _validate_and_load_context(
    api: Any,
    run_id: str,
    row_id: str,
    options: Optional[Dict[str, Any]],
) -> Any:
    """Valide les pre-requis et charge le contexte. Retourne un dict erreur ou un tuple contexte."""
    settings = api.get_settings()
    if not settings.get("perceptual_enabled"):
        return {"ok": False, "message": "Analyse perceptuelle desactivee dans les reglages."}

    ffprobe_path = str(settings.get("ffprobe_path") or "")
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
        return {"ok": False, "message": "Run introuvable."}
    run_row, store = found

    opts = options if isinstance(options, dict) else {}
    if not bool(opts.get("force")):
        existing = store.get_perceptual_report(run_id=run_id, row_id=row_id)
        if existing:
            return {"ok": True, "cache_hit": True, "perceptual": existing.get("metrics", {})}

    state_dir = normalize_user_path(run_row.get("state_dir"), api._state_dir)
    run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=False)
    rs = api._get_run(run_id)
    rows = rs.rows if rs and rs.rows else api._load_rows_from_plan_jsonl(run_paths)
    row = next((r for r in rows if str(r.row_id) == str(row_id)), None)
    if row is None:
        return {"ok": False, "message": "Film introuvable dans ce plan (row_id)."}

    cfg = rs.cfg if rs else api._cfg_from_run_row(run_row)
    media_path = api._resolve_media_path_for_row(cfg, row)
    if media_path is None or not media_path.exists():
        return {"ok": False, "message": "Fichier media introuvable."}

    probe_result = _load_probe(api, store, run_row, media_path)
    normalized = probe_result.get("normalized") if isinstance(probe_result.get("normalized"), dict) else {}
    video_info = normalized.get("video") or {}
    width = int(video_info.get("width") or 0)
    height = int(video_info.get("height") or 0)
    probe_quality = str(normalized.get("probe_quality") or "")
    if probe_quality == "FAILED" and width == 0 and height == 0:
        return {"ok": False, "message": "Probe echouee (fichier corrompu ou format non supporte)."}

    has_video = width > 0 and height > 0
    has_audio = len(normalized.get("audio_tracks") or []) > 0
    if not has_video and not has_audio:
        return {"ok": False, "message": "Probe incomplete (ni video ni audio detectes)."}
    duration_s = float(normalized.get("duration_s") or 0)
    if duration_s <= 0:
        return {"ok": False, "message": "Probe incomplete (duree manquante)."}

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
    settings, ffmpeg_path, store, run_row, row, media_path, normalized, video_info = ctx
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
    from cinesort.domain.perceptual.grain_analysis import classify_film_era

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
        tmdb_meta = _load_tmdb_metadata(api, row)
        # §15 v7.5.0 : utilise analyze_grain_v2 si Grain Intelligence active
        if p_settings.get("grain_intelligence_enabled"):
            from cinesort.domain.perceptual.av1_grain_metadata import (
                extract_av1_film_grain_params,
            )
            from cinesort.domain.perceptual.grain_analysis import analyze_grain_v2

            # Extraction AV1 film grain parameters (opt-in, uniquement si codec av1)
            codec = str(video_info.get("codec") or "").lower()
            av1_info = None
            if codec in ("av1", "av01"):
                ffprobe_path_local = str(settings.get("ffprobe_path") or "") or "ffprobe"
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
            from cinesort.domain.perceptual.ssim_self_ref import compute_ssim_self_ref

            ssim_result = compute_ssim_self_ref(
                ffmpeg_path,
                str(media_path),
                duration_s=duration_s,
                video_height=height,
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
                from cinesort.domain.perceptual.hdr_analysis import (
                    detect_hdr10_plus_multi_frame,
                )

                ffprobe_path_local = str(settings.get("ffprobe_path") or "") or "ffprobe"
                video_local.has_hdr10_plus_detected = detect_hdr10_plus_multi_frame(
                    ffprobe_path_local,
                    str(media_path),
                )
        # §7 v7.5.0 : Fake 4K detection FFT 2D + combinaison avec §13 SSIM
        from cinesort.domain.perceptual.upscale_detection import (
            classify_fake_4k_fft,
            combine_fake_4k_verdicts,
            compute_fft_hf_ratio_median,
        )

        fft_ratio = compute_fft_hf_ratio_median(frames_local, width, height)
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
        from cinesort.domain.perceptual.metadata_analysis import (
            classify_crop,
            classify_imax,
            detect_crop_multi_segments,
            detect_interlacing,
            detect_judder,
        )

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
        from cinesort.domain.perceptual.composite_score_v2 import compute_global_score_v2

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

    store.upsert_perceptual_report(
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
    # - Defaut (`composite_score_version=1`) : on conserve le score V1 historique
    #   comme `global_score`/`global_tier`, V2 reste accessible via la cle
    #   `global_score_v2` (et en BDD).
    # - Toggle V2 (`composite_score_version=2`) : on promeut V2 en score
    #   principal pour ce payload (`global_score`, `global_tier`, marqueur
    #   `composite_score_version=2`). Si le calcul V2 a echoue, fallback
    #   silencieux vers V1 (jamais de KeyError pour l'UI).
    result_dict["composite_score_version"] = 1
    if p_settings.get("composite_score_version") == 2 and gv2_payload is not None and gv2_score is not None:
        result_dict["global_score"] = int(round(float(gv2_score)))
        result_dict["global_tier"] = str(gv2_tier or result_dict.get("global_tier") or "")
        result_dict["composite_score_version"] = 2
    return {"ok": True, "cache_hit": False, "perceptual": result_dict}


def analyze_perceptual_batch(
    api: Any,
    run_id: str,
    row_ids: Any,
    options: Optional[Dict[str, Any]] = None,
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
        settings = api.get_settings()
        parallelism_enabled = bool(settings.get("perceptual_parallelism_enabled", True))
        configured_workers = int(settings.get("perceptual_workers", 0) or 0)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.debug("analyze_perceptual_batch: settings lookup failed (%s), fallback defaults", exc)

    cancel_event = _resolve_cancel_event(api)

    # Choix du nombre de workers + fast path sequentiel.
    if not parallelism_enabled or len(ids) < 2:
        max_workers = 1
    else:
        max_workers = resolve_batch_workers(configured_workers)

    def _worker(rid: str) -> Dict[str, Any]:
        return get_perceptual_report(api, run_id, rid, options)

    raw_results = run_batch_parallel(
        ids,
        _worker,
        max_workers=max_workers,
        cancel_event=cancel_event,
    )

    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for rid, (ok, value) in zip(ids, raw_results):
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
        settings = api.get_settings()
        if not settings.get("perceptual_enabled"):
            return {"ok": False, "message": "Analyse perceptuelle desactivee dans les reglages."}

        ffprobe_path = str(settings.get("ffprobe_path") or "")
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
            return {"ok": False, "message": f"Erreur fichier A: {msg}"}
        if not ok_b or not isinstance(report_b, dict) or not report_b.get("ok"):
            msg = report_b.get("message", "") if isinstance(report_b, dict) else str(report_b)
            return {"ok": False, "message": f"Erreur fichier B: {msg}"}

        perc_a = report_a.get("perceptual", {})
        perc_b = report_b.get("perceptual", {})

        # Charger les probes pour les dimensions
        found = api._find_run_row(run_id)
        if not found:
            return {"ok": False, "message": "Run introuvable."}
        run_row, store = found
        state_dir = normalize_user_path(run_row.get("state_dir"), api._state_dir)
        run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=False)
        rs = api._get_run(run_id)
        rows = rs.rows if rs and rs.rows else api._load_rows_from_plan_jsonl(run_paths)
        cfg = rs.cfg if rs else api._cfg_from_run_row(run_row)

        row_a = next((r for r in rows if str(r.row_id) == str(row_id_a)), None)
        row_b = next((r for r in rows if str(r.row_id) == str(row_id_b)), None)
        if not row_a or not row_b:
            return {"ok": False, "message": "Film introuvable dans le plan."}

        media_a = api._resolve_media_path_for_row(cfg, row_a)
        media_b = api._resolve_media_path_for_row(cfg, row_b)
        if not media_a or not media_b:
            return {"ok": False, "message": "Fichier media introuvable."}

        probe_a = _load_probe(api, store, run_row, media_a)
        probe_b = _load_probe(api, store, run_row, media_b)
        na = probe_a.get("normalized") or {}
        nb = probe_b.get("normalized") or {}
        va = na.get("video") or {}
        vb = nb.get("video") or {}

        from cinesort.domain.perceptual.comparison import (
            build_comparison_report,
            compare_per_frame,
            extract_aligned_frames,
        )

        aligned = extract_aligned_frames(
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
                from cinesort.domain.perceptual.lpips_compare import (
                    compute_lpips_comparison,
                )

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
        return {"ok": False, "message": str(exc)}


def enrich_quality_report_with_perceptual(
    store: Any,
    run_id: str,
    row_id: str,
    result: Dict[str, Any],
    *,
    composite_score_version: int = 1,
) -> None:
    """Enrichit un rapport qualite technique avec les donnees perceptuelles si disponibles.

    V4-05 (Polish Total v7.7.0, R4-PERC-7 / H16) : si `composite_score_version=2`,
    on substitue le score/tier global par la version V2 (stockee en BDD via
    migration 018). Fallback silencieux sur V1 si V2 indisponible (legacy row
    sans calcul V2, ou setting V2 active mais cache V1 historique).
    """
    try:
        perc = store.get_perceptual_report(run_id=run_id, row_id=row_id)
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
    # V4-05 (Polish Total v7.7.0) : import tardif pour eviter cycle.
    from cinesort.ui.api.settings_support import _normalize_composite_score_version

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
    from cinesort.infra.probe import ProbeService

    probe_settings = api._effective_probe_settings_for_runtime(run_row)
    probe = ProbeService(store)
    return probe.probe_file(media_path=media_path, settings=probe_settings)


def _load_tmdb_metadata(api: Any, row: Any) -> Optional[Dict[str, Any]]:
    """Charge les metadata TMDb pour l'analyse grain (genres, budget, companies)."""
    tmdb_id = 0
    candidates = getattr(row, "candidates", []) or []
    if candidates:
        tmdb_id = int(getattr(candidates[0], "tmdb_id", 0) or 0)
    if tmdb_id <= 0:
        return None
    try:
        tmdb = api._tmdb_client()
        if tmdb:
            return tmdb.get_movie_metadata_for_perceptual(tmdb_id)
    except (ImportError, KeyError, OSError, TypeError, ValueError):
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
