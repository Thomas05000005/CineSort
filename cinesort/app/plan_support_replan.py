"""Single-row planning pipeline (VP-E refactor, sous-lot VP-6).

Construit une `PlanRow` pour un fichier video (`_plan_item`) et ses variantes
publiques `_plan_single`, `_plan_collection_item`, `replan_single_row` ainsi
que le pipeline TV `_plan_tv_episode`. Le pipeline NFO/TMDb/runtime de scoring
des candidats vit dans `plan_support_dedup.py` ; les helpers de cache et de
serialisation viennent de `plan_support_core.py`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

import cinesort.domain.core as core_mod
from cinesort.app.plan_support_core import (
    _nfo_signature,
    _resolve_path_cached,
    plan_row_from_jsonable,
    plan_row_to_jsonable,
    resolve_incremental_quick_hash,
)
from cinesort.domain.edition_helpers import extract_edition
from cinesort.domain.integrity_check import check_header
from cinesort.domain.runtime_matching import score_runtime_delta
from cinesort.domain.scan_helpers import _NOT_A_MOVIE_THRESHOLD, not_a_movie_score
from cinesort.domain.subtitle_helpers import build_subtitle_report
from cinesort.domain.tv_helpers import parse_tv_info
from cinesort.infra.tmdb_client import TmdbClient

if TYPE_CHECKING:
    from cinesort.domain.core import Config, PlanRow

_log = logging.getLogger(__name__)


def _try_lookup_row_cache(
    cfg: "Config",
    folder: Path,
    video: Path,
    *,
    cfg_sig: str,
    scan_index: Optional[Any],
    run_hash_cache: Optional[Dict[Tuple[str, int, int], str]],
    row_cache_stats: Optional[Dict[str, int]],
) -> Optional["PlanRow"]:
    """Tente un hit dans le cache row v2. Retourne la PlanRow cachee ou None.

    Met a jour row_cache_stats (row_hits / row_misses) en place.
    """
    if not (cfg_sig and scan_index is not None and hasattr(scan_index, "get_incremental_row_cache")):
        return None

    try:
        video_stat = video.stat()
        v_size = int(video_stat.st_size)
        v_mtime = int(video_stat.st_mtime_ns)
        v_hash = resolve_incremental_quick_hash(
            video,
            scan_index=scan_index,
            run_hash_cache=run_hash_cache or {},
        )
        nfo_path_for_sig = core_mod.find_best_nfo_for_video(folder, video)
        nfo_sig = _nfo_signature(nfo_path_for_sig)

        cached = scan_index.get_incremental_row_cache(
            root_path=str(cfg.root),
            video_path=str(video),
            cfg_sig=cfg_sig,
        )
        if cached is not None:
            if (
                int(cached.get("video_size") or 0) == v_size
                and int(cached.get("video_mtime_ns") or 0) == v_mtime
                and str(cached.get("video_hash") or "") == v_hash
                and cached.get("nfo_sig") == nfo_sig
            ):
                row_obj = plan_row_from_jsonable(cached.get("row_json") or {})
                if row_obj is not None:
                    if row_cache_stats is not None:
                        row_cache_stats["row_hits"] = row_cache_stats.get("row_hits", 0) + 1
                    return row_obj
        if row_cache_stats is not None:
            row_cache_stats["row_misses"] = row_cache_stats.get("row_misses", 0) + 1
    except (FileNotFoundError, PermissionError, OSError):
        pass
    return None


def _resolve_folder_context(
    cfg: "Config",
    folder: Path,
    video: Path,
    *,
    is_collection: bool,
    cfg_root_resolved: Optional[Path] = None,
) -> Tuple[str, str, Optional[str]]:
    """Calcule folder_name, log_ctx et l'edition detectee pour cet item.

    PERF-2 (v7.8.0) : `cfg_root_resolved` est pre-calcule par l'appelant pour
    eviter `cfg.root.resolve()` par film (5-15ms SMB). Fallback transparent
    si non fourni.
    """
    # Pour un film pose directement a la racine, le "folder_name" serait la racine
    # elle-meme (ex: "Films" ou "D:\"), qui ne porte aucune info de titre. On se
    # rabat sur le stem du fichier video pour que l'extraction titre/annee et la
    # construction des candidats marchent comme pour un dossier film classique.
    if cfg_root_resolved is None:
        cfg_root_resolved_str = _resolve_path_cached(str(cfg.root))
    else:
        cfg_root_resolved_str = str(cfg_root_resolved)
    folder_resolved_str = _resolve_path_cached(str(folder))
    _folder_is_root = folder_resolved_str == cfg_root_resolved_str
    folder_name = Path(video.name).stem if _folder_is_root else folder.name
    log_ctx = f"(collection): {folder_name}/{video.name}" if is_collection else f"({folder_name})"

    detected_edition = extract_edition(folder_name) or extract_edition(video.name)
    return folder_name, log_ctx, detected_edition


def _disambiguate_candidates(
    cands: List[Any],
    *,
    nfo: Optional[Any],
    name_year: Optional[int],
    log: Callable[[str, str], None],
    log_ctx: str,
) -> Tuple[List[Any], bool]:
    """Desambiguise par contexte (P2.2) si plusieurs films partagent le titre.

    Retourne (cands_ajustes, title_ambiguous). Modifie les scores uniquement si
    ambiguite detectee (ex : Dune 1984 vs 2021).
    """
    from cinesort.domain.title_ambiguity import disambiguate_by_context

    ambig_context = {
        "name_year": name_year,
        "nfo_tmdb_id": (
            int(nfo.tmdbid) if nfo and getattr(nfo, "tmdbid", None) and str(nfo.tmdbid).strip().isdigit() else None
        ),
        "nfo_runtime": getattr(nfo, "runtime", None) if nfo else None,
    }
    cands, title_ambiguous, ambig_title = disambiguate_by_context(cands, ambig_context)
    if title_ambiguous:
        log(
            "WARN",
            f"Titres TMDb ambigus {log_ctx}: {ambig_title!r} existe dans plusieurs années. "
            "Désambiguïsation sur contexte.",
        )
    return cands, title_ambiguous


def _build_unresolved_row(
    folder: Path,
    video: Path,
    *,
    row_id: str,
    kind: str,
    is_collection: bool,
    folder_name: str,
    cands: List[Any],
    nfo: Optional[Any],
    nfo_path: Optional[Path],
    nfo_state: Dict[str, Any],
    name_year: Optional[int],
    name_year_reason: str,
    remaster_hint: bool,
    tmdb_used: bool,
    title_ambiguous: bool,
    detected_edition: Optional[str],
    log: Callable[[str, str], None],
) -> "PlanRow":
    """Construit une PlanRow pour le cas ou aucun candidat fiable n'a ete trouve."""

    if not is_collection:
        log("WARN", f"Cannot resolve single: {folder_name}")
    note = core_mod.build_plan_note(
        confidence=0,
        label="low",
        chosen=None,
        name_year=name_year,
        name_year_reason=name_year_reason,
        remaster_hint=remaster_hint,
        nfo_present=bool(nfo),
        nfo_ok=nfo_state["nfo_ok"],
        nfo_cov=nfo_state["nfo_cov"],
        nfo_seq=nfo_state["nfo_seq"],
        nfo_reject_reason=nfo_state["nfo_reject_reason"],
        tmdb_used=tmdb_used,
    )
    warning_flags = core_mod._warning_flags_from_analysis(
        chosen=None,
        name_year_reason=name_year_reason,
        nfo_present=bool(nfo),
        nfo_ok=nfo_state["nfo_ok"],
        year_delta_reject=nfo_state["year_delta_reject"],
        nfo_partial_match=nfo_state["nfo_partial_match"],
        title_ambiguity=title_ambiguous,
    )
    note = f"{note} Impossible de determiner un titre+annee fiables."
    fallback_title = (core_mod.clean_title_guess(video.name) or video.stem) if is_collection else folder_name
    return core_mod.PlanRow(
        row_id=row_id,
        kind=kind,
        folder=str(folder),
        video=video.name,
        proposed_title=fallback_title,
        proposed_year=name_year or 0,
        proposed_source="unknown",
        confidence=0,
        confidence_label="low",
        candidates=cands,
        nfo_path=str(nfo_path) if nfo_path else None,
        notes=note,
        detected_year=int(name_year or 0),
        detected_year_reason=str(name_year_reason or ""),
        warning_flags=warning_flags,
        collection_name=folder.name if is_collection else None,
        edition=detected_edition,
        nfo_runtime=nfo.runtime if nfo else None,
    )


def _resolve_tmdb_collection(
    cfg: "Config",
    chosen: Any,
    folder_name: str,
    *,
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
) -> Tuple[Optional[int], Optional[str]]:
    """Retourne (collection_id, collection_name) si fiable, sinon (None, None).

    FIX 6 : la collection doit partager au moins un mot significatif avec le
    nom du dossier source OU avec le titre du candidat. Sinon le collection
    boost est toxique (ex: 'Ca' -> Pirates des Caraibes).
    """
    import contextlib

    if not (tmdb is not None and chosen.tmdb_id):
        return None, None
    coll_id: Optional[int] = None
    coll_name: Optional[str] = None
    with contextlib.suppress(KeyError, TypeError, ValueError):
        coll_id, coll_name = tmdb.get_movie_collection(chosen.tmdb_id)
    if not coll_name:
        return coll_id, coll_name
    coll_tokens = {t for t in core_mod.tokens(coll_name) if len(t) >= 3}
    folder_tokens = set(core_mod.tokens(folder_name))
    title_tokens = set(core_mod.tokens(chosen.title or ""))
    if coll_tokens and not (coll_tokens & folder_tokens) and not (coll_tokens & title_tokens):
        _log.warning(
            "scan: collection TMDb '%s' rejetee (pas de mot commun avec dossier='%s' ni titre='%s')",
            coll_name,
            folder_name,
            chosen.title,
        )
        log(
            "WARN",
            f"Collection '{coll_name}' ignoree pour '{folder_name}' (aucun mot commun avec le nom source).",
        )
        return None, None
    return coll_id, coll_name


def _build_resolved_row(
    cfg: "Config",
    folder: Path,
    video: Path,
    chosen: Any,
    *,
    row_id: str,
    kind: str,
    is_collection: bool,
    folder_name: str,
    cands: List[Any],
    nfo: Optional[Any],
    nfo_path: Optional[Path],
    nfo_state: Dict[str, Any],
    name_year: Optional[int],
    name_year_reason: str,
    remaster_hint: bool,
    tmdb_used: bool,
    title_ambiguous: bool,
    detected_edition: Optional[str],
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
) -> "PlanRow":
    """Construit une PlanRow pour le cas ou un candidat fiable a ete choisi."""

    confidence, label = core_mod.compute_confidence(
        cfg,
        chosen,
        nfo_ok=nfo_state["nfo_ok"],
        year_delta_reject=nfo_state["year_delta_reject"],
        tmdb_used=tmdb_used,
        nfo_partial_match=nfo_state["nfo_partial_match"],
    )
    proposed_title = core_mod.windows_safe(chosen.title)
    # BUG 3 : si le dossier courant est deja conforme (meme titre + annee que
    # le candidat), la confiance doit etre HIGH — aucune action ne sera prise
    # meme si la similarite textuelle TMDb < 0.60.
    is_already_conform = False
    if not is_collection and chosen.year:
        try:
            is_already_conform = core_mod._single_folder_is_conform(
                folder_name,
                chosen.title,
                int(chosen.year),
                naming_template=str(getattr(cfg, "naming_movie_template", "") or ""),
            )
        except (TypeError, ValueError, AttributeError):
            is_already_conform = False
    if is_already_conform and confidence < 85:
        confidence = 90
        label = "high"
    # Phase 6.1 : runtime cross-check NFO vs TMDb, edition-aware.
    runtime_warning: Optional[str] = None
    if nfo is not None and getattr(nfo, "runtime", None) and tmdb is not None and chosen.tmdb_id:
        try:
            tmdb_runtime = tmdb.get_movie_runtime(int(chosen.tmdb_id))
        except (AttributeError, TypeError, ValueError):
            tmdb_runtime = None
        if tmdb_runtime:
            bonus, runtime_warning = score_runtime_delta(
                file_runtime_min=float(nfo.runtime),
                tmdb_runtime_min=tmdb_runtime,
                edition_label=detected_edition,
            )
            confidence = max(0, min(100, confidence + bonus))
            if bonus >= 10:
                label = "high" if confidence >= 85 else label
            elif bonus < 0:
                label = "low" if confidence < 60 else label
    note = core_mod.build_plan_note(
        confidence=confidence,
        label=label,
        chosen=chosen,
        name_year=name_year,
        name_year_reason=name_year_reason,
        remaster_hint=remaster_hint,
        nfo_present=bool(nfo),
        nfo_ok=nfo_state["nfo_ok"],
        nfo_cov=nfo_state["nfo_cov"],
        nfo_seq=nfo_state["nfo_seq"],
        nfo_reject_reason=nfo_state["nfo_reject_reason"],
        tmdb_used=tmdb_used,
    )
    warning_flags = core_mod._warning_flags_from_analysis(
        chosen=chosen,
        name_year_reason=name_year_reason,
        nfo_present=bool(nfo),
        nfo_ok=nfo_state["nfo_ok"],
        year_delta_reject=nfo_state["year_delta_reject"],
        nfo_partial_match=nfo_state["nfo_partial_match"],
        title_ambiguity=title_ambiguous,
    )
    if runtime_warning and runtime_warning not in warning_flags:
        warning_flags.append(runtime_warning)
    coll_id, coll_name = _resolve_tmdb_collection(cfg, chosen, folder_name, tmdb=tmdb, log=log)
    return core_mod.PlanRow(
        row_id=row_id,
        kind=kind,
        folder=str(folder),
        video=video.name,
        proposed_title=proposed_title,
        proposed_year=int(chosen.year),
        proposed_source=chosen.source,
        confidence=confidence,
        confidence_label=label,
        candidates=cands,
        nfo_path=str(nfo_path) if nfo_path else None,
        notes=note,
        detected_year=int(name_year or 0),
        detected_year_reason=str(name_year_reason or ""),
        warning_flags=warning_flags,
        collection_name=folder.name if is_collection else None,
        tmdb_collection_id=coll_id,
        tmdb_collection_name=coll_name,
        edition=detected_edition,
        nfo_runtime=nfo.runtime if nfo else None,
    )


def _apply_subtitle_detection(
    folder: Path,
    video: Path,
    result_row: "PlanRow",
    *,
    subtitle_expected_languages: Optional[List[str]],
    normalized_probe: Optional[Dict[str, Any]] = None,
) -> None:
    """Enrichit la PlanRow avec les infos sous-titres + warning flags associes.

    Fix Vague F 2026-05-25 (v1.5.3) : si un `normalized_probe` est fourni
    (NormalizedProbe.to_dict() ou dict equivalent), ses pistes `subtitles`
    embarquees sont prises en compte -> plus de faux "subtitle_missing_fr"
    pour les MKV avec FR embarque.
    """
    if subtitle_expected_languages is None:
        return

    embedded_subs: Optional[List[Dict[str, Any]]] = None
    if isinstance(normalized_probe, dict):
        raw_subs = normalized_probe.get("subtitles")
        if isinstance(raw_subs, list):
            embedded_subs = raw_subs

    sub_report = build_subtitle_report(
        folder,
        video,
        subtitle_expected_languages,
        embedded_subtitles=embedded_subs,
    )
    result_row.subtitle_count = sub_report.count
    result_row.subtitle_languages = list(sub_report.languages)
    result_row.subtitle_formats = list(sub_report.formats)
    result_row.subtitle_missing_langs = list(sub_report.missing_languages)
    result_row.subtitle_orphans = sub_report.orphans
    for missing_lang in sub_report.missing_languages:
        flag = f"subtitle_missing_{missing_lang}"
        if flag not in result_row.warning_flags:
            result_row.warning_flags.append(flag)
    if sub_report.orphans > 0 and "subtitle_orphan" not in result_row.warning_flags:
        result_row.warning_flags.append("subtitle_orphan")
    if sub_report.duplicate_languages and "subtitle_duplicate_lang" not in result_row.warning_flags:
        result_row.warning_flags.append("subtitle_duplicate_lang")


def _apply_not_a_movie_detection(video: Path, result_row: "PlanRow") -> None:
    """Pose le flag 'not_a_movie' si l'heuristique depasse le seuil."""

    try:
        video_size = video.stat().st_size if video.exists() else 0
    except (OSError, PermissionError):
        video_size = 0
    nam_score = not_a_movie_score(
        video_name=video.name,
        file_size=video_size,
        proposed_source=result_row.proposed_source,
        confidence=result_row.confidence,
        title=result_row.proposed_title,
    )
    if nam_score >= _NOT_A_MOVIE_THRESHOLD and "not_a_movie" not in result_row.warning_flags:
        result_row.warning_flags.append("not_a_movie")


def _apply_integrity_check(video: Path, result_row: "PlanRow") -> None:
    """Pose le flag 'integrity_header_invalid' si magic bytes invalides.

    Ne jamais bloquer le scan pour un check d'integrite (try/except large).
    """

    try:
        hdr_valid, _hdr_detail = check_header(video)
        if not hdr_valid and "integrity_header_invalid" not in result_row.warning_flags:
            result_row.warning_flags.append("integrity_header_invalid")
    except (OSError, PermissionError, FileNotFoundError, ValueError):
        pass  # ne jamais bloquer le scan pour un check d'integrite


def _store_row_cache(
    cfg: "Config",
    folder: Path,
    video: Path,
    nfo_path: Optional[Path],
    result_row: "PlanRow",
    *,
    kind: str,
    cfg_sig: str,
    run_id: str,
    scan_index: Optional[Any],
    run_hash_cache: Optional[Dict[Tuple[str, int, int], str]],
) -> None:
    """Persiste la PlanRow dans le cache row v2 (best-effort, jamais bloquant)."""
    if not (cfg_sig and scan_index is not None and hasattr(scan_index, "upsert_incremental_row_cache")):
        return
    try:
        v_stat = video.stat()
        v_hash = resolve_incremental_quick_hash(
            video,
            scan_index=scan_index,
            run_hash_cache=run_hash_cache or {},
        )
        scan_index.upsert_incremental_row_cache(
            root_path=str(cfg.root),
            video_path=str(video),
            video_size=int(v_stat.st_size),
            video_mtime_ns=int(v_stat.st_mtime_ns),
            video_hash=v_hash,
            folder_path=str(folder),
            nfo_sig=_nfo_signature(nfo_path),
            cfg_sig=cfg_sig,
            kind=kind,
            row_json=plan_row_to_jsonable(result_row),
            run_id=str(run_id),
        )
    except (FileNotFoundError, PermissionError, OSError):
        pass


def _plan_item(
    cfg: "Config",
    folder: Path,
    video: Path,
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    *,
    kind: str,
    should_cancel: Optional[Callable[[], bool]] = None,
    scan_index: Optional[Any] = None,
    cfg_sig: str = "",
    run_id: str = "",
    run_hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    row_cache_stats: Optional[Dict[str, int]] = None,
    subtitle_expected_languages: Optional[List[str]] = None,
) -> List["PlanRow"]:
    """Orchestre la construction d'une PlanRow pour un fichier video.

    kind : "single" (film standalone) ou "collection" (film dans une saga).
    Pour les episodes TV, voir _plan_tv_episode (pipeline distinct).

    Pipeline : cache lookup -> contexte folder/edition -> NFO + cross-checks
    IMDb/TMDb -> TMDb fallback -> disambiguation -> PlanRow -> enrichissements
    (sous-titres, non-film, integrite) -> cache store.
    """
    # Import paresseux : plan_support_dedup importe ce module (replan_single_row
    # n'a aucune dependance dedup, mais _plan_item utilise le pipeline scoring).
    from cinesort.app.plan_support_dedup import (
        _apply_runtime_hard_filter_to_tmdb_cands,
        _augment_candidates_from_nfo_imdb,
        _augment_candidates_from_nfo_tmdb_id,
        _build_nfo_candidates,
        _build_tmdb_fallback_candidates,
        _resolve_file_runtime_min,
    )
    from cinesort.domain.runtime_hard_filter import WARN_RUNTIME_HARD_EXCLUDED

    is_collection = kind == "collection"
    row_id_prefix = "C" if is_collection else "S"
    row_id = f"{row_id_prefix}|{hash((str(folder), video.name)) & 0xFFFFFFFF:x}"

    # --- Scan v2: per-video row cache lookup ---
    cached_row = _try_lookup_row_cache(
        cfg,
        folder,
        video,
        cfg_sig=cfg_sig,
        scan_index=scan_index,
        run_hash_cache=run_hash_cache,
        row_cache_stats=row_cache_stats,
    )
    if cached_row is not None:
        return [cached_row]

    folder_name, log_ctx, detected_edition = _resolve_folder_context(cfg, folder, video, is_collection=is_collection)

    name_year, name_year_reason, remaster_hint = core_mod.infer_name_year(folder_name, video.name)
    name_cands = core_mod.build_candidates_from_name(folder_name, video.name, preferred_year=name_year)

    if core_mod._is_cancel_requested(should_cancel):
        return []

    nfo_path = core_mod.find_best_nfo_for_video(folder, video)
    if core_mod._is_cancel_requested(should_cancel):
        return []
    nfo = core_mod.parse_movie_nfo(nfo_path) if nfo_path else None

    nfo_cands, nfo_state = _build_nfo_candidates(
        cfg,
        folder_name,
        video.name,
        nfo=nfo,
        name_year=name_year,
        remaster_hint=remaster_hint,
        log=log,
        log_ctx=log_ctx,
    )

    _augment_candidates_from_nfo_imdb(
        cfg,
        nfo,
        nfo_cands,
        folder_name,
        video.name,
        name_year=name_year,
        tmdb=tmdb,
        log=log,
        log_ctx=log_ctx,
    )

    _augment_candidates_from_nfo_tmdb_id(
        cfg,
        nfo,
        nfo_cands,
        folder_name,
        video.name,
        name_year=name_year,
        nfo_ok=nfo_state["nfo_ok"],
        tmdb=tmdb,
        log=log,
        log_ctx=log_ctx,
    )

    tmdb_cands, tmdb_used = _build_tmdb_fallback_candidates(
        cfg,
        folder_name,
        video.name,
        is_collection=is_collection,
        name_year=name_year,
        nfo_cands=nfo_cands,
        year_delta_reject=nfo_state["year_delta_reject"],
        tmdb=tmdb,
        should_cancel=should_cancel,
    )

    # VN-D.3 : runtime HARD filter sur les candidats TMDb.
    runtime_hard_excluded_flag: Optional[str] = None
    if tmdb_cands:
        file_runtime_min = _resolve_file_runtime_min(nfo, folder, video)
        if file_runtime_min is not None:
            tmdb_cands, _excluded_any = _apply_runtime_hard_filter_to_tmdb_cands(
                tmdb_cands,
                file_runtime_min=file_runtime_min,
                detected_edition=detected_edition,
                tmdb=tmdb,
                settings=getattr(cfg, "_runtime_filter_settings", None),
                log=log,
                log_ctx=log_ctx,
            )
            if _excluded_any:
                runtime_hard_excluded_flag = WARN_RUNTIME_HARD_EXCLUDED

    cands = []
    cands.extend(nfo_cands)
    cands.extend(tmdb_cands)
    cands.extend(name_cands)

    # Dedup final par tmdb_id (sinon nfo_imdb 0.95 / nfo_tmdb 0.93 / tmdb 0.85
    # peuvent toutes survivre avec le meme tmdb_id et doubler dans le modal).
    # On garde le score max pour preserver le ranking de pick_best_candidate.
    _seen_cands: dict = {}
    for _c in cands:
        _k = _c.tmdb_id if _c.tmdb_id else ((_c.title or "").strip().lower(), _c.year)
        _prev = _seen_cands.get(_k)
        if _prev is None or (_c.score or 0.0) > (_prev.score or 0.0):
            _seen_cands[_k] = _c
    cands = list(_seen_cands.values())

    cands, title_ambiguous = _disambiguate_candidates(
        cands,
        nfo=nfo,
        name_year=name_year,
        log=log,
        log_ctx=log_ctx,
    )

    chosen = core_mod.pick_best_candidate(cands)
    if not chosen or not chosen.year:
        result_row = _build_unresolved_row(
            folder,
            video,
            row_id=row_id,
            kind=kind,
            is_collection=is_collection,
            folder_name=folder_name,
            cands=cands,
            nfo=nfo,
            nfo_path=nfo_path,
            nfo_state=nfo_state,
            name_year=name_year,
            name_year_reason=name_year_reason,
            remaster_hint=remaster_hint,
            tmdb_used=tmdb_used,
            title_ambiguous=title_ambiguous,
            detected_edition=detected_edition,
            log=log,
        )
    else:
        result_row = _build_resolved_row(
            cfg,
            folder,
            video,
            chosen,
            row_id=row_id,
            kind=kind,
            is_collection=is_collection,
            folder_name=folder_name,
            cands=cands,
            nfo=nfo,
            nfo_path=nfo_path,
            nfo_state=nfo_state,
            name_year=name_year,
            name_year_reason=name_year_reason,
            remaster_hint=remaster_hint,
            tmdb_used=tmdb_used,
            title_ambiguous=title_ambiguous,
            detected_edition=detected_edition,
            tmdb=tmdb,
            log=log,
        )

    # VN-D.3 : pose le warning sur la PlanRow si au moins un candidat TMDb a
    # ete exclu par le runtime HARD filter (utile pour debug user en UI).
    if runtime_hard_excluded_flag and result_row is not None:
        flags = getattr(result_row, "warning_flags", None)
        if flags is None:
            result_row.warning_flags = [runtime_hard_excluded_flag]
        elif runtime_hard_excluded_flag not in flags:
            flags.append(runtime_hard_excluded_flag)

    _apply_subtitle_detection(folder, video, result_row, subtitle_expected_languages=subtitle_expected_languages)
    _apply_not_a_movie_detection(video, result_row)
    _apply_integrity_check(video, result_row)
    _store_row_cache(
        cfg,
        folder,
        video,
        nfo_path,
        result_row,
        kind=kind,
        cfg_sig=cfg_sig,
        run_id=run_id,
        scan_index=scan_index,
        run_hash_cache=run_hash_cache,
    )

    return [result_row]


def _plan_single(
    cfg: "Config",
    folder: Path,
    video: Path,
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    *,
    should_cancel: Optional[Callable[[], bool]] = None,
    scan_index: Optional[Any] = None,
    cfg_sig: str = "",
    run_id: str = "",
    run_hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    row_cache_stats: Optional[Dict[str, int]] = None,
    subtitle_expected_languages: Optional[List[str]] = None,
) -> List["PlanRow"]:
    return _plan_item(
        cfg,
        folder,
        video,
        tmdb,
        log,
        kind="single",
        should_cancel=should_cancel,
        scan_index=scan_index,
        cfg_sig=cfg_sig,
        run_id=run_id,
        run_hash_cache=run_hash_cache,
        row_cache_stats=row_cache_stats,
        subtitle_expected_languages=subtitle_expected_languages,
    )


def _plan_collection_item(
    cfg: "Config",
    folder: Path,
    video: Path,
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    *,
    should_cancel: Optional[Callable[[], bool]] = None,
    scan_index: Optional[Any] = None,
    cfg_sig: str = "",
    run_id: str = "",
    run_hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    row_cache_stats: Optional[Dict[str, int]] = None,
    subtitle_expected_languages: Optional[List[str]] = None,
) -> List["PlanRow"]:
    return _plan_item(
        cfg,
        folder,
        video,
        tmdb,
        log,
        kind="collection",
        should_cancel=should_cancel,
        scan_index=scan_index,
        cfg_sig=cfg_sig,
        run_id=run_id,
        run_hash_cache=run_hash_cache,
        row_cache_stats=row_cache_stats,
        subtitle_expected_languages=subtitle_expected_languages,
    )


def replan_single_row(
    cfg: "Config",
    folder: Path,
    video: Path,
    *,
    tmdb: Optional[TmdbClient] = None,
    kind: str = "single",
    log: Optional[Callable[[str, str], None]] = None,
    subtitle_expected_languages: Optional[List[str]] = None,
) -> Optional["PlanRow"]:
    """Spec 06 §3.6 : reconstruit une PlanRow pour 1 seul fichier video.

    Helper public reutilisant le pipeline `_plan_item` (NFO + cross-checks
    IMDb/TMDb -> TMDb fallback -> disambiguation -> resolved/unresolved row
    -> enrichissements sous-titres/integrite/not-a-movie). Aucune mise en
    cache (cfg_sig/scan_index volontairement vides) : on force un rescan
    a froid pour ce row.

    Returns:
        La nouvelle PlanRow (jamais cachee), ou None si le pipeline n'a
        rien produit (cas degenere : video inexistante, etc.).
    """
    if log is None:

        def log(level: str, msg: str) -> None:  # noqa: ARG001
            _log.debug("replan_single_row[%s] %s", level, msg)

    if kind not in ("single", "collection"):
        kind = "single"

    rows = _plan_item(
        cfg,
        folder,
        video,
        tmdb,
        log,
        kind=kind,
        should_cancel=None,
        scan_index=None,
        cfg_sig="",
        run_id="",
        run_hash_cache=None,
        row_cache_stats=None,
        subtitle_expected_languages=subtitle_expected_languages,
    )
    if not rows:
        return None
    return rows[0]


def _plan_tv_episode(
    cfg: "Config",
    folder: Path,
    video: Path,
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    *,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> List["PlanRow"]:
    """Build a PlanRow for a TV episode (kind='tv_episode')."""

    tv = parse_tv_info(folder, video)
    if tv is None:
        return []

    row_id = f"T|{hash((str(folder), video.name)) & 0xFFFFFFFF:x}"
    series_name = tv.series_name
    season = tv.season
    episode = tv.episode
    year = tv.year
    tmdb_series_id: Optional[int] = None
    episode_title: Optional[str] = None
    source = "name"
    confidence = 45

    # TMDb TV lookup.
    if tmdb and cfg.enable_tmdb and series_name:
        if core_mod._is_cancel_requested(should_cancel):
            return []
        try:
            tv_results = tmdb.search_tv(series_name, year=year, language=cfg.tmdb_language)
            if tv_results:
                best = tv_results[0]
                tmdb_series_id = best.id
                series_name = best.name or series_name
                if best.first_air_date_year:
                    year = best.first_air_date_year
                source = "tmdb_tv"
                confidence = 65

                if season is not None and episode is not None and tmdb_series_id:
                    ep_title = tmdb.get_tv_episode_title(
                        tmdb_series_id,
                        season,
                        episode,
                        language=cfg.tmdb_language,
                    )
                    if ep_title:
                        episode_title = ep_title
                        confidence = 85
        except (FileNotFoundError, PermissionError, OSError):
            pass

    if season is not None and episode is not None:
        confidence = min(100, confidence + 10)
    confidence = max(0, min(100, confidence))
    label = "high" if confidence >= 80 else "med" if confidence >= 60 else "low"

    proposed_title = core_mod.windows_safe(series_name)
    note_parts = [f"Serie: {series_name}"]
    if season is not None:
        note_parts.append(f"S{season:02d}")
    if episode is not None:
        note_parts.append(f"E{episode:02d}")
    if episode_title:
        note_parts.append(f'"{episode_title}"')
    note_parts.append(f"source={source}")

    return [
        core_mod.PlanRow(
            row_id=row_id,
            kind="tv_episode",
            folder=str(folder),
            video=video.name,
            proposed_title=proposed_title,
            proposed_year=int(year or 0),
            proposed_source=source,
            confidence=confidence,
            confidence_label=label,
            candidates=[],
            notes=" | ".join(note_parts),
            detected_year=int(year or 0),
            detected_year_reason="tv_first_air_date" if source == "tmdb_tv" else "folder",
            warning_flags=[],
            tv_series_name=series_name,
            tv_season=season,
            tv_episode=episode,
            tv_episode_title=episode_title,
            tv_tmdb_series_id=tmdb_series_id,
        )
    ]
