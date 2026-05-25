"""§v7.6.0 Vague 3 — Library / Explorer backend.

Endpoints :
    get_library_filtered(run_id, filters, sort, page, page_size)
    get_smart_playlists()
    save_smart_playlist(name, filters)
    delete_smart_playlist(playlist_id)

Les Smart Playlists sont persistees dans settings.json sous la cle
`smart_playlists` (liste de dicts).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from cinesort.domain.i18n_messages import t
from cinesort.infra import state
from cinesort.ui.api.settings_support import normalize_user_path
from cinesort.ui.api._responses import err as _err_response

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------


_CODEC_NORMALIZE = {
    "h.264": "h264",
    "h264": "h264",
    "avc": "h264",
    "avc1": "h264",
    "h.265": "hevc",
    "h265": "hevc",
    "hevc": "hevc",
    "hvc1": "hevc",
    "hev1": "hevc",
    "av1": "av1",
    "vp9": "vp9",
    "mpeg2": "mpeg2",
    "mpeg2video": "mpeg2",
    "vc1": "vc1",
    "xvid": "xvid",
    "divx": "divx",
    "wmv": "wmv",
    "wmv3": "wmv",
}


def _normalize_codec(codec: Optional[str]) -> str:
    if not codec:
        return "unknown"
    return _CODEC_NORMALIZE.get(str(codec).strip().lower(), str(codec).strip().lower())


def _classify_resolution(width: int, height: int) -> str:
    w = int(width or 0)
    h = int(height or 0)
    if w >= 3800 or h >= 2100:
        return "4k"
    if w >= 1900 or h >= 1060:
        return "1080p"
    if w >= 1280 or h >= 680:
        return "720p"
    if w > 0:
        return "sd"
    return "unknown"


def _classify_hdr(probe_video: Dict[str, Any]) -> str:
    if not isinstance(probe_video, dict):
        return "sdr"
    if probe_video.get("has_hdr10_plus"):
        return "hdr10_plus"
    if probe_video.get("has_dv"):
        profile = str(probe_video.get("dv_profile") or "").strip()
        if profile == "5":
            return "dv_p5"
        return "dv"
    if probe_video.get("has_hdr10"):
        return "hdr10"
    return "sdr"


def _extract_row_warnings(perceptual_row: Optional[Dict[str, Any]]) -> List[str]:
    """Liste des flags de warnings a partir du global_score_v2_payload."""
    if not perceptual_row:
        return []
    payload = perceptual_row.get("global_score_v2_payload") or {}
    warnings_text: List[str] = payload.get("warnings") or []
    flags: List[str] = []
    for w in warnings_text:
        low = str(w).lower()
        if "dolby vision profile 5" in low or "dv5" in low:
            flags.append("dv_profile_5")
        if "maxcll" in low or "hdr10 sans" in low:
            flags.append("hdr_metadata_missing")
        if "runtime" in low or "extended cut" in low or "theatrical" in low:
            flags.append("runtime_mismatch")
        if "court" in low and "fichier" in low:
            flags.append("short_file")
        if "confidence" in low or "analyse partielle" in low:
            flags.append("low_confidence")
        if "desequilibre" in low:
            flags.append("category_imbalance")
        if "lossless" in low:
            flags.append("fake_lossless")
    # DNR partial / fake 4K : signaux domain directs
    if payload.get("adjustments_applied"):
        for adj in payload["adjustments_applied"]:
            if "dnr_partial" in adj:
                flags.append("dnr_partial")
            if "fake_4k" in adj:
                flags.append("fake_4k_confirmed")
    return sorted(set(flags))


# ---------------------------------------------------------------------------
# Construction des rows enrichies
# ---------------------------------------------------------------------------


def _build_library_rows(api: Any, run_id: str) -> List[Dict[str, Any]]:
    """Construit la liste des rows Library enrichies (probe + perceptual V2)."""
    # Charger le plan
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _ = api._get_or_create_infra(state_dir)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("library_support cannot get store: %s", exc)
        return []

    # Perceptual reports indexes par row_id
    try:
        perc_list = store.perceptual.list_perceptual_reports(run_id=run_id)
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        logger.warning("library_support cannot list perceptual reports: %s", exc)
        perc_list = []
    perc_by_row = {str(p.get("row_id", "")): p for p in perc_list}

    # Quality reports
    try:
        quality_list = store.quality.list_quality_reports(run_id=run_id)
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        logger.warning("library_support cannot list quality reports: %s", exc)
        quality_list = []
    quality_by_row = {str(q.get("row_id", "")): q for q in quality_list}

    # PlanRows
    plan_result = api.run.get_plan(run_id)
    if not plan_result or not plan_result.get("ok"):
        return []
    plan_rows = plan_result.get("rows") or []

    # Fix audit 2026-05-25 (v1.5.4) Vague I (Bug 2) : pre-resolve poster URLs en
    # batch via integrations.get_tmdb_posters(). Avant : `r.get("poster_url")`
    # retournait toujours None car PlanRow n'a PAS de champ poster_url plat (le
    # poster vit sur les Candidate enfants, pas sur le row) -> les 853 cartes
    # affichaient toutes le placeholder clapper. Maintenant : on collecte tous
    # les tmdb_id non nuls, on appelle 1 fois get_tmdb_posters([...], "w342")
    # et on mappe poster par tmdb_id. Cache TMDb local evite la re-frappe HTTP
    # entre 2 appels. Films non identifies (tmdb_id=None) gardent leur
    # placeholder coté UI avec lien "Identifier manuellement".
    tmdb_ids: List[int] = []
    for r in plan_rows:
        tid_raw = r.get("tmdb_id")
        if tid_raw is None or tid_raw == "":
            continue
        try:
            tid = int(tid_raw)
        except (TypeError, ValueError):
            continue
        if tid > 0 and tid not in tmdb_ids:
            tmdb_ids.append(tid)
    posters_by_tmdb: Dict[str, str] = {}
    if tmdb_ids:
        try:
            poster_res = api.integrations.get_tmdb_posters(tmdb_ids, "w342")
            if poster_res and poster_res.get("ok"):
                raw_map = poster_res.get("posters") or {}
                # Normaliser cles en str (l'API retourne str(int) deja, mais on
                # protege contre les eventuels int).
                posters_by_tmdb = {str(k): v for k, v in raw_map.items() if v}
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            logger.debug("library_support poster batch fetch error: %s", exc)

    out: List[Dict[str, Any]] = []
    for r in plan_rows:
        row_id = str(r.get("row_id") or "")
        perc = perc_by_row.get(row_id)
        qual = quality_by_row.get(row_id)

        # Extraire metadata probe (cote quality_reports ou plan row)
        metrics = (qual or {}).get("metrics") if qual else None
        if not isinstance(metrics, dict):
            metrics = {}
        probe_video = metrics.get("video") or {}

        width = int(probe_video.get("width") or 0)
        height = int(probe_video.get("height") or 0)
        duration_s = float(metrics.get("duration_s") or 0)

        # Phase 4 spec 07 : exposer audio_langs / subs_langs / subs_missing pour
        # compteurs chips + export. audio_languages est dans metrics.audio.
        audio_metrics = metrics.get("audio") if isinstance(metrics, dict) else None
        audio_langs: List[str] = []
        if isinstance(audio_metrics, list):
            for stream in audio_metrics:
                if isinstance(stream, dict):
                    lang = str(stream.get("language") or "").strip().lower()
                    if lang and lang not in audio_langs:
                        audio_langs.append(lang)

        # Fix audit 2026-05-25 (v1.5.4) Vague I : BUG 2 — la PlanRow ne capture pas
        # les pistes subtitle EMBARQUEES (scan sans probe). On enrichit ici depuis
        # `quality_reports.metrics.subtitles_embedded` (persiste par _probe_and_score
        # apres get_quality_report), pour aligner le compte "sans subs FR" entre la
        # vue Bibliotheque et le rapport Qualite. Si pas de quality_report disponible,
        # fallback transparent sur les langues externes detectees au scan.
        scan_subtitle_languages = [str(s).lower() for s in (r.get("subtitle_languages") or [])]
        embedded_subs_raw = metrics.get("subtitles_embedded") if isinstance(metrics, dict) else None
        embedded_langs: List[str] = []
        if isinstance(embedded_subs_raw, list):
            try:
                from cinesort.domain.subtitle_helpers import _normalize_iso639

                for track in embedded_subs_raw:
                    if not isinstance(track, dict):
                        continue
                    raw_lang = (track.get("language") or "").strip().lower()
                    if not raw_lang:
                        continue
                    normalized = _normalize_iso639(raw_lang)
                    if normalized and normalized not in embedded_langs:
                        embedded_langs.append(normalized)
            except (ImportError, AttributeError, KeyError, TypeError, ValueError):
                embedded_langs = []
        # Union langues externes (PlanRow) + langues embarquees (quality_report metrics)
        merged_langs = list(scan_subtitle_languages)
        for lang in embedded_langs:
            if lang not in merged_langs:
                merged_langs.append(lang)
        subtitle_languages = merged_langs
        # Recalcul missing_langs en filtrant les langues finalement presentes
        scan_missing = [str(s).lower() for s in (r.get("subtitle_missing_langs") or [])]
        subtitle_missing_langs = [lang for lang in scan_missing if lang not in subtitle_languages]
        proposed_source = str(r.get("proposed_source") or "").strip().lower()
        confidence = int(r.get("confidence") or 0)

        # Fix audit 2026-05-25 (v1.5.4) Vague I (Bug 2) : resolve poster_url via
        # le batch posters_by_tmdb pre-calcule en haut de fonction. Fallback sur
        # le 1er candidat TMDb avec poster_url si tmdb_id direct absent (cas des
        # rows non encore identifies mais avec candidats suggeres).
        poster_url: Optional[str] = None
        tid_for_poster = r.get("tmdb_id")
        if tid_for_poster:
            try:
                poster_url = posters_by_tmdb.get(str(int(tid_for_poster)))
            except (TypeError, ValueError):
                poster_url = None
        if not poster_url:
            for cand in (r.get("candidates") or []):
                cand_poster = cand.get("poster_url") if isinstance(cand, dict) else None
                if cand_poster:
                    poster_url = cand_poster
                    break

        row = {
            "row_id": row_id,
            "title": r.get("proposed_title") or r.get("nfo_title") or "",
            "year": int(r.get("proposed_year") or 0),
            # Issue audit Tier 2 : tmdb_id absent ici cassait le match Jellyfin
            # DateCreated dans library_timeline_support (fallback toujours fs mtime).
            "tmdb_id": r.get("tmdb_id"),
            "duration_s": duration_s,
            "duration_min": int(duration_s / 60) if duration_s > 0 else 0,
            "codec": _normalize_codec(probe_video.get("codec")),
            "resolution": _classify_resolution(width, height),
            "width": width,
            "height": height,
            "hdr": _classify_hdr(probe_video),
            # Fix audit 2026-05-25 (v1.5.4) Vague I : fallback tier V1 si perceptual V2
            # pas calcule (V2 coute ~1h pour 853 films en ffmpeg, lance manuellement).
            # quality_reports.tier (V1, peu couteux) est calcule en post-scan auto et donne
            # deja Platinum/Gold/Silver/Bronze/Reject base sur les metrics du probe.
            # Sans ce fallback, l'utilisateur voit 853 "Non identifie" jusqu'a ce qu'il
            # lance manuellement l'analyse perceptuelle. Avec fallback : tier visible
            # immediatement apres scan, V2 viendra raffiner si lance plus tard.
            "tier_v2": str(
                (perc or {}).get("global_tier_v2")
                or (qual or {}).get("tier")
                or "unknown"
            ).lower(),
            "score_v2": (perc or {}).get("global_score_v2") or (qual or {}).get("score"),
            "warnings": _extract_row_warnings(perc),
            "grain_era_v2": None,  # extrait du metrics si dispo
            "grain_nature": None,
            "added_ts": float(r.get("mtime") or 0),
            "path": r.get("source_path") or "",
            "poster_url": poster_url,
            # v7.6.0 Vague 7 : champs pour get_scoring_rollup
            "tmdb_collection_name": r.get("tmdb_collection_name"),
            "edition": r.get("edition"),
            # Phase 4 spec 07 : champs additionnels pour counters chips + export
            "audio_languages": audio_langs,
            "subtitle_languages": subtitle_languages,
            "subtitle_missing_langs": subtitle_missing_langs,
            "proposed_source": proposed_source,
            "confidence": confidence,
            "size_bytes": int(r.get("size_bytes") or metrics.get("size_bytes") or 0),
        }

        # Si grain dans metrics
        grain = metrics.get("grain") if isinstance(metrics, dict) else None
        if isinstance(grain, dict):
            gi = grain.get("grain_intelligence") or {}
            row["grain_era_v2"] = gi.get("film_era_v2")
            row["grain_nature"] = gi.get("nature")

        out.append(row)

    return out


# ---------------------------------------------------------------------------
# Filtrage
# ---------------------------------------------------------------------------


def _row_matches(row: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    """Applique tous les filtres actifs a une row. AND entre categories."""

    # Search texte (titre)
    q = str(filters.get("search") or "").strip().lower()
    if q and q not in (row.get("title") or "").lower():
        return False

    def _in_list(row_val: Any, filter_list: Any) -> bool:
        if not filter_list:
            return True
        return str(row_val or "").lower() in [str(v).lower() for v in filter_list]

    def _any_in_list(row_vals: Any, filter_list: Any) -> bool:
        """True si au moins un element de row_vals (liste) est dans filter_list."""
        if not filter_list:
            return True
        if not row_vals:
            return False
        wanted = {str(v).lower() for v in filter_list}
        return any(str(rv or "").lower() in wanted for rv in row_vals)

    if not _in_list(row.get("tier_v2"), filters.get("tier_v2")):
        return False
    if not _in_list(row.get("codec"), filters.get("codec")):
        return False
    if not _in_list(row.get("resolution"), filters.get("resolution")):
        return False
    if not _in_list(row.get("hdr"), filters.get("hdr")):
        return False
    if not _in_list(row.get("grain_era_v2"), filters.get("grain_era_v2")):
        return False
    if not _in_list(row.get("grain_nature"), filters.get("grain_nature")):
        return False
    # Phase 5 spec 07 : source / audio_langs / subtitle_langs (drawer avance)
    if not _in_list(row.get("proposed_source"), filters.get("source")):
        return False
    if not _any_in_list(row.get("audio_languages"), filters.get("audio_languages")):
        return False
    if not _any_in_list(row.get("subtitle_languages"), filters.get("subtitle_languages")):
        return False

    # Warnings : OR interne (au moins un warning du filtre present dans la row)
    wflags = filters.get("warnings")
    if wflags:
        row_warns = set(row.get("warnings") or [])
        if not any(str(w).lower() in row_warns for w in wflags):
            return False

    # Year range
    year = int(row.get("year") or 0)
    y_min = filters.get("year_min")
    y_max = filters.get("year_max")
    if y_min and year and year < int(y_min):
        return False
    if y_max and year and year > int(y_max):
        return False

    # Duration (en minutes)
    dur = int(row.get("duration_min") or 0)
    d_min = filters.get("duration_min")
    d_max = filters.get("duration_max")
    if d_min and dur and dur < int(d_min):
        return False
    if d_max and dur and dur > int(d_max):
        return False

    # Phase 5 spec 07 : size range (bytes) — convertit Go en bytes cote frontend
    size_b = int(row.get("size_bytes") or 0)
    s_min = filters.get("size_min")
    s_max = filters.get("size_max")
    if s_min and size_b and size_b < int(s_min):
        return False
    if s_max and size_b and size_b > int(s_max):
        return False

    # Phase 5 spec 07 : confidence range (0-100)
    conf = int(row.get("confidence") or 0)
    c_min = filters.get("confidence_min")
    c_max = filters.get("confidence_max")
    if c_min is not None and conf < int(c_min):
        return False
    if c_max is not None and conf > int(c_max):
        return False

    # Phase 5 spec 07 : added date range (added_ts epoch seconds)
    added = float(row.get("added_ts") or 0.0)
    a_min = filters.get("added_after")
    a_max = filters.get("added_before")
    if a_min is not None and added and added < float(a_min):
        return False
    if a_max is not None and added and added > float(a_max):
        return False

    # Phase 5 spec 07 : chips non-tier (subs_missing_fr / unidentified /
    # recently_modified / in_duplicates / sagas_incomplete). AND interne.
    chips = filters.get("chips") or []
    if chips:
        chip_set = {str(c).strip().lower() for c in chips if c}
        if "subs_missing_fr" in chip_set and not _row_subs_missing_fr(row):
            return False
        if "unidentified" in chip_set and not _row_unidentified(row):
            return False
        if "recently_modified" in chip_set and not _row_recently_modified(
            row,
            time.time(),
            _RECENTLY_MODIFIED_WINDOW_S,
        ):
            return False
        if "sagas_incomplete" in chip_set and not row.get("tmdb_collection_name"):
            return False
        # "in_duplicates" est evalue a l'echelle de la collection (cf
        # _filter_in_duplicates apres _row_matches) - on le laisse passer ici.

    return True


_SORT_KEY = {
    "title": lambda r: (str(r.get("title") or "").lower(), r.get("year") or 0),
    "title_desc": lambda r: tuple(-ord(c) for c in str(r.get("title") or "").lower()[:50]),
    "score_desc": lambda r: -(r.get("score_v2") or 0),
    "score_asc": lambda r: r.get("score_v2") or 0,
    "year_desc": lambda r: -(r.get("year") or 0),
    "year_asc": lambda r: r.get("year") or 0,
    "duration_desc": lambda r: -(r.get("duration_s") or 0),
    "duration_asc": lambda r: r.get("duration_s") or 0,
    "added_desc": lambda r: -(r.get("added_ts") or 0),
    "added_asc": lambda r: r.get("added_ts") or 0,
    # Phase 5 spec 07 : tri par taille fichier
    "size_desc": lambda r: -(r.get("size_bytes") or 0),
    "size_asc": lambda r: r.get("size_bytes") or 0,
}


def _apply_sort(rows: List[Dict[str, Any]], sort: str) -> List[Dict[str, Any]]:
    key = _SORT_KEY.get(sort or "title") or _SORT_KEY["title"]
    try:
        return sorted(rows, key=key)
    except (TypeError, ValueError):
        return rows


def _resolve_run_id(api: Any, run_id: Optional[str]) -> Optional[str]:
    if run_id:
        return str(run_id)
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _ = api._get_or_create_infra(state_dir)
        runs = store.run.list_runs(limit=1)
        if runs:
            return str(runs[0].get("run_id") or "")
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.debug("_resolve_run_id error: %s", exc)
    return None


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------


def get_library_filtered(
    api: Any,
    run_id: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    sort: str = "title",
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    """Renvoie une liste paginee de films filtres + triés.

    Returns:
      {
        ok: bool,
        run_id: str,
        rows: list[dict],
        total: int,           # total apres filtrage
        page: int,
        pages: int,
        page_size: int,
        stats: {
          by_tier: {platinum, gold, silver, bronze, reject, unknown},
          ...
        }
      }
    """
    # Fix audit 2026-05-25 (v1.5.3) Vague F : wrap global pour eviter HTTP 500
    # quand le run est obsolete / la base inaccessible / la facade leve.
    try:
        return _get_library_filtered_impl(api, run_id, filters, sort, page, page_size)
    except Exception as exc:  # noqa: BLE001 - boundary top-level pour endpoint UI
        logger.exception(
            "get_library_filtered failed for run_id=%s page=%s", run_id, page
        )
        return {
            "ok": False,
            "error": "library_load_failed",
            "message": str(exc),
            "user_message": (
                "Impossible de charger la bibliotheque (run obsolete ou base "
                "inaccessible). Relance un scan ou redemarre l'app."
            ),
            "rows": [],
            "total": 0,
            "page": int(page or 1),
            "pages": 0,
            "page_size": int(page_size or 50),
            "stats": {"by_tier": {}},
        }


def _get_library_filtered_impl(
    api: Any,
    run_id: Optional[str],
    filters: Optional[Dict[str, Any]],
    sort: str,
    page: int,
    page_size: int,
) -> Dict[str, Any]:
    """Implementation reelle de get_library_filtered, sans wrap global (Vague F)."""
    filters = filters or {}
    page = max(1, int(page or 1))
    page_size = max(1, min(500, int(page_size or 50)))

    resolved_rid = _resolve_run_id(api, run_id)
    if not resolved_rid:
        return {
            "ok": True,
            "run_id": None,
            "rows": [],
            "total": 0,
            "page": page,
            "pages": 0,
            "page_size": page_size,
            "stats": {"by_tier": {}},
        }

    all_rows = _build_library_rows(api, resolved_rid)
    filtered = [r for r in all_rows if _row_matches(r, filters)]

    # Phase 5 spec 07 : chip "in_duplicates" — necessite une evaluation cross-row.
    chips = filters.get("chips") or []
    if chips and "in_duplicates" in {str(c).strip().lower() for c in chips if c}:
        by_titleyear: Dict[tuple, int] = {}
        for r in filtered:
            key = (str(r.get("title") or "").strip().lower(), int(r.get("year") or 0))
            if key[0]:
                by_titleyear[key] = by_titleyear.get(key, 0) + 1
        filtered = [
            r
            for r in filtered
            if by_titleyear.get(
                (str(r.get("title") or "").strip().lower(), int(r.get("year") or 0)),
                0,
            )
            >= 2
        ]

    total = len(filtered)

    # Stats pour la sidebar (counts par tier)
    by_tier: Dict[str, int] = {}
    for r in filtered:
        t = str(r.get("tier_v2") or "unknown").lower()
        by_tier[t] = by_tier.get(t, 0) + 1

    sorted_rows = _apply_sort(filtered, sort)
    pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    rows_page = sorted_rows[start : start + page_size]

    return {
        "ok": True,
        "run_id": resolved_rid,
        "rows": rows_page,
        "total": total,
        "page": page,
        "pages": pages,
        "page_size": page_size,
        "stats": {"by_tier": by_tier},
    }


# ---------------------------------------------------------------------------
# Smart Playlists (persistance settings.json)
# ---------------------------------------------------------------------------


def _get_playlists_from_settings(api: Any) -> List[Dict[str, Any]]:
    try:
        settings = api.settings.get_settings()
    except (OSError, AttributeError, KeyError, TypeError, ValueError):
        return []
    raw = settings.get("smart_playlists")
    if isinstance(raw, list):
        return raw
    return []


def _write_playlists_to_settings(api: Any, playlists: List[Dict[str, Any]]) -> bool:
    try:
        settings = api.settings.get_settings()
        settings["smart_playlists"] = playlists
        api.settings.save_settings(settings)
        return True
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("save smart_playlists failed: %s", exc)
        return False


def get_smart_playlists(api: Any) -> Dict[str, Any]:
    """Liste les smart playlists persistees."""
    playlists = _get_playlists_from_settings(api)
    # Ajouter les playlists predefinies suggestion
    predefined = [
        {
            "id": "_preset_reject",
            "name": "Films Reject a re-acquerir",
            "filters": {"tier_v2": ["reject"]},
            "preset": True,
        },
        {
            "id": "_preset_dnr",
            "name": "DNR partiel detecte",
            "filters": {"warnings": ["dnr_partial"]},
            "preset": True,
        },
        {
            "id": "_preset_platinum",
            "name": "Platinum recents (2020+)",
            "filters": {"tier_v2": ["platinum"], "year_min": 2020},
            "preset": True,
        },
    ]
    return {"ok": True, "playlists": predefined + list(playlists)}


def save_smart_playlist(
    api: Any,
    name: str,
    filters: Dict[str, Any],
    playlist_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Cree ou met a jour une smart playlist."""
    name = str(name or "").strip()
    if not name:
        return _err_response("Nom requis.", category="validation", level="info", log_module=__name__)
    if not isinstance(filters, dict):
        return _err_response("Filtres invalides.", category="validation", level="info", log_module=__name__)

    playlists = _get_playlists_from_settings(api)

    now = time.time()
    if playlist_id and not playlist_id.startswith("_preset_"):
        # Update
        updated = False
        for p in playlists:
            if p.get("id") == playlist_id:
                p["name"] = name
                p["filters"] = filters
                p["updated_ts"] = now
                updated = True
                break
        if not updated:
            return _err_response("Playlist introuvable.", category="resource", level="info", log_module=__name__)
    else:
        # Create
        new = {
            "id": f"sp_{uuid.uuid4().hex[:8]}",
            "name": name,
            "filters": filters,
            "created_ts": now,
            "updated_ts": now,
        }
        playlists.append(new)
        playlist_id = new["id"]

    if not _write_playlists_to_settings(api, playlists):
        return _err_response(t("errors.persistence_failed"), category="runtime", level="error", log_module=__name__)

    return {"ok": True, "playlist_id": playlist_id}


def delete_smart_playlist(api: Any, playlist_id: str) -> Dict[str, Any]:
    """Supprime une smart playlist custom (les presets ne peuvent etre supprimes)."""
    if not playlist_id or str(playlist_id).startswith("_preset_"):
        return _err_response("Playlist protegee.", category="permission", level="warning", log_module=__name__)

    playlists = _get_playlists_from_settings(api)
    before = len(playlists)
    playlists = [p for p in playlists if p.get("id") != playlist_id]
    if len(playlists) == before:
        return _err_response("Playlist introuvable.", category="resource", level="info", log_module=__name__)

    if not _write_playlists_to_settings(api, playlists):
        return _err_response(t("errors.persistence_failed"), category="runtime", level="error", log_module=__name__)

    return {"ok": True, "deleted_id": playlist_id}


# ---------------------------------------------------------------------------
# §v7.6.0 Vague 7 — Scoring rollup par realisateur / franchise
# ---------------------------------------------------------------------------


def get_scoring_rollup(
    api: Any,
    by: str = "franchise",
    limit: int = 20,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Aggregation scoring par dimension (director, franchise, decade, codec).

    Args:
        by: "franchise" | "director" | "decade" | "codec" | "era_grain"
        limit: max groupes retournes (tries par count desc)
    Returns:
      {
        ok: bool,
        by: str,
        groups: [
          { group_name, count, avg_score, tier_distribution: {...}, top_film_ids: [...] }
        ]
      }
    """
    dim = str(by or "franchise").lower()
    resolved_rid = _resolve_run_id(api, run_id)
    if not resolved_rid:
        return {"ok": True, "by": dim, "groups": []}

    rows = _build_library_rows(api, resolved_rid)
    if not rows:
        return {"ok": True, "by": dim, "groups": []}

    buckets: Dict[str, Dict[str, Any]] = {}

    # Pour franchise/director, on doit les extraire des candidats TMDb (on simplifie avec titre)
    # Ici on utilise soit la collection TMDb, soit le director, soit la decade, etc.
    for r in rows:
        group_key = _extract_group_key(r, dim)
        if not group_key:
            continue
        bucket = buckets.setdefault(
            group_key,
            {
                "group_name": group_key,
                "count": 0,
                "score_sum": 0.0,
                "score_samples": 0,
                "tier_distribution": {
                    "platinum": 0,
                    "gold": 0,
                    "silver": 0,
                    "bronze": 0,
                    "reject": 0,
                    "unknown": 0,
                },
                "top_film_ids": [],
            },
        )
        bucket["count"] += 1
        score = r.get("score_v2")
        if score is not None:
            bucket["score_sum"] += float(score)
            bucket["score_samples"] += 1
        tier = str(r.get("tier_v2") or "unknown").lower()
        if tier in bucket["tier_distribution"]:
            bucket["tier_distribution"][tier] += 1
        if len(bucket["top_film_ids"]) < 5:
            bucket["top_film_ids"].append(r.get("row_id"))

    # Finalize : moyenne + sort
    groups: List[Dict[str, Any]] = []
    for bucket in buckets.values():
        avg = round(bucket["score_sum"] / bucket["score_samples"], 1) if bucket["score_samples"] else None
        groups.append(
            {
                "group_name": bucket["group_name"],
                "count": bucket["count"],
                "avg_score": avg,
                "tier_distribution": bucket["tier_distribution"],
                "top_film_ids": bucket["top_film_ids"],
            }
        )

    # Tri par count desc, puis avg_score desc
    groups.sort(key=lambda g: (-int(g["count"]), -(g["avg_score"] or 0)))
    groups = groups[: max(1, min(100, int(limit or 20)))]

    return {"ok": True, "by": dim, "groups": groups, "run_id": resolved_rid}


# ---------------------------------------------------------------------------
# Phase 4 spec 07 — Compteurs par chip pour la vue Bibliotheque
# ---------------------------------------------------------------------------


_RECENTLY_MODIFIED_WINDOW_S = 7 * 24 * 3600  # 7 jours


def _row_subs_missing_fr(row: Dict[str, Any]) -> bool:
    """True si la row n'a pas de sous-titres FR (langue manquante ou liste subs vide)."""
    subs = set(row.get("subtitle_languages") or [])
    missing = set(row.get("subtitle_missing_langs") or [])
    # Soit "fr" est explicitement marque comme manquant, soit absent de la liste presente
    if any(lang.startswith("fr") for lang in missing):
        return True
    if not any(lang.startswith("fr") for lang in subs):
        return True
    return False


def _row_unidentified(row: Dict[str, Any]) -> bool:
    """True si la row n'a pas ete identifiee par TMDb (cf domain/librarian.py)."""
    src = str(row.get("proposed_source") or "").strip().lower()
    conf = int(row.get("confidence") or 0)
    return src in ("unknown", "") or conf == 0


def _row_recently_modified(row: Dict[str, Any], now_ts: float, window_s: float) -> bool:
    ts = float(row.get("added_ts") or 0.0)
    if ts <= 0:
        return False
    return (now_ts - ts) <= window_s


def _count_duplicates_and_sagas(rows: List[Dict[str, Any]]) -> tuple[int, int]:
    """Compte les films "in_duplicates" (meme titre+annee >= 2) et "sagas_incomplete".

    Heuristique pour in_duplicates : groupes de >= 2 rows avec meme (title, year).
    Heuristique pour sagas_incomplete : films appartenant a une collection TMDb.
    """
    by_titleyear: Dict[tuple, int] = {}
    sagas_count = 0
    for r in rows:
        key = (str(r.get("title") or "").strip().lower(), int(r.get("year") or 0))
        if key[0]:
            by_titleyear[key] = by_titleyear.get(key, 0) + 1
        if r.get("tmdb_collection_name"):
            sagas_count += 1

    in_duplicates = sum(c for c in by_titleyear.values() if c >= 2)
    return in_duplicates, sagas_count


def get_library_counters_by_chip(
    api: Any,
    filters: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Phase 4 spec 07 — Retourne les counts par chip pour la vue Bibliotheque.

    Les chips couvrent :
    - Tier qualite (6) : platinum, gold, silver, bronze, reject, unknown
    - Filtres problematiques (3) : subs_missing_fr, unidentified, recently_modified
    - Filtres structurels (2) : in_duplicates, sagas_incomplete

    Le filter `filters` est applique avant comptage (utile pour scope counters
    sur une sous-selection, ex: search="dune" -> counts dans le sous-ensemble).

    Returns:
      {
        ok: bool,
        run_id: str,
        total: int,
        counts: {
          platinum: int, gold: int, silver: int, bronze: int, reject: int, unknown: int,
          subs_missing_fr: int, unidentified: int, recently_modified: int,
          in_duplicates: int, sagas_incomplete: int,
        }
      }
    """
    filters = filters or {}
    resolved_rid = _resolve_run_id(api, run_id)
    if not resolved_rid:
        return {
            "ok": True,
            "run_id": None,
            "total": 0,
            "counts": {
                "platinum": 0,
                "gold": 0,
                "silver": 0,
                "bronze": 0,
                "reject": 0,
                "unknown": 0,
                "subs_missing_fr": 0,
                "unidentified": 0,
                "recently_modified": 0,
                "in_duplicates": 0,
                "sagas_incomplete": 0,
            },
        }

    all_rows = _build_library_rows(api, resolved_rid)
    # Appliquer filters EN AMONT pour scoper les counters (utile si search actif).
    scoped_rows = [r for r in all_rows if _row_matches(r, filters)]

    counts: Dict[str, int] = {
        "platinum": 0,
        "gold": 0,
        "silver": 0,
        "bronze": 0,
        "reject": 0,
        "unknown": 0,
        "subs_missing_fr": 0,
        "unidentified": 0,
        "recently_modified": 0,
        "in_duplicates": 0,
        "sagas_incomplete": 0,
    }

    now_ts = time.time()
    for row in scoped_rows:
        tier = str(row.get("tier_v2") or "unknown").lower()
        if tier in counts:
            counts[tier] += 1
        else:
            counts["unknown"] += 1

        if _row_subs_missing_fr(row):
            counts["subs_missing_fr"] += 1
        if _row_unidentified(row):
            counts["unidentified"] += 1
        if _row_recently_modified(row, now_ts, _RECENTLY_MODIFIED_WINDOW_S):
            counts["recently_modified"] += 1

    in_dup, sagas = _count_duplicates_and_sagas(scoped_rows)
    counts["in_duplicates"] = in_dup
    counts["sagas_incomplete"] = sagas

    return {
        "ok": True,
        "run_id": resolved_rid,
        "total": len(scoped_rows),
        "counts": counts,
    }


# Spec 06 Modal Film — 3 endpoints d'actions sur un film
# ---------------------------------------------------------------------------


def _get_store(api: Any):
    """Helper : retourne le SQLiteStore via les facades, ou None si indispo."""
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _ = api._get_or_create_infra(state_dir)
        return store
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("library_support _get_store error: %s", exc)
        return None


def _find_plan_row(api: Any, run_id: str, row_id: str) -> Optional[Dict[str, Any]]:
    """Recherche une PlanRow dans le run, par row_id."""
    try:
        plan = api.run.get_plan(run_id)
    except (OSError, AttributeError, KeyError, TypeError, ValueError):
        return None
    if not plan or not plan.get("ok"):
        return None
    for r in plan.get("rows") or []:
        if str(r.get("row_id") or "") == str(row_id):
            return r
    return None


def _confidence_label_from_value(value: int) -> str:
    """Reproduit la grille de labels utilisee par compute_confidence."""
    v = int(value or 0)
    if v >= 85:
        return "high"
    if v >= 60:
        return "med"
    return "low"


def _format_proposed_path(api: Any, run_id: str, title: str, year: int) -> str:
    """Reconstruit le 'proposed_path' relatif (sous-dossier) selon le template
    de renommage configure dans le run. Fallback : `Title (Year)/`.

    On garde simple : on ne reconstruit pas le path complet (ROOT inconnu sans
    cfg du run), on retourne juste le folder name + slash trailing, comme
    `proposed_path` est consomme cote frontend (diff avec current_path).
    """
    # Import lazy : module domain optionnel selon contexte UI/CLI/tests.
    try:
        from cinesort.domain import naming as _naming
    except ImportError:
        # Fallback ultra-simple
        return f"{title} ({int(year or 0)})/" if year else f"{title}/"
    template = ""
    try:
        settings = api.settings.get_settings()
        template = str(settings.get("naming_movie_template") or "")
    except (OSError, AttributeError, KeyError, TypeError, ValueError):
        template = ""
    ctx = {
        "title": str(title or ""),
        "year": str(int(year or 0)) if year else "",
        "edition": "",
        "edition-tag": "",
        "source-tag": "",
        "quality": "",
        "score": "",
    }
    try:
        folder = _naming.format_movie_folder(template, ctx)
    except (TypeError, ValueError, AttributeError, KeyError):
        folder = f"{title} ({int(year or 0)})" if year else str(title or "Film")
    return f"{folder}/"


def set_film_tmdb_candidate(
    api: Any,
    run_id: Optional[str],
    row_id: str,
    tmdb_id: int,
) -> Dict[str, Any]:
    """Spec 06 §3.4 : choisir un autre candidat TMDb pour un film.

    - Recherche le candidat dans `row.candidates[]` par tmdb_id
    - Recalcule la confidence depuis candidate.score (0..1) * 100
    - Construit le nouveau proposed_path depuis title + year
    - Persiste l'override en DB (table film_tmdb_overrides)
    - Reversible tant que l'apply n'est pas faite (clear_tmdb_override)

    Retourne :
        { ok, new_confidence, new_confidence_label, new_proposed_path,
          proposed_title, proposed_year, tmdb_id }
    """
    rid = _resolve_run_id(api, run_id)
    if not rid:
        return _err_response("Aucun run disponible.", category="state", level="info", log_module=__name__)
    try:
        tmdb_int = int(tmdb_id)
    except (TypeError, ValueError):
        return _err_response("tmdb_id invalide.", category="validation", level="info", log_module=__name__)
    if tmdb_int <= 0:
        return _err_response("tmdb_id invalide.", category="validation", level="info", log_module=__name__)

    row = _find_plan_row(api, rid, row_id)
    if not row:
        return _err_response(
            f"Film introuvable (row_id={row_id}).", category="resource", level="info", log_module=__name__
        )

    # Recherche du candidat
    chosen = None
    for c in row.get("candidates") or []:
        if int(c.get("tmdb_id") or 0) == tmdb_int:
            chosen = c
            break
    if chosen is None:
        return _err_response(
            f"Candidat TMDb {tmdb_int} introuvable parmi les candidats du film.",
            category="resource",
            level="info",
            log_module=__name__,
        )

    # Recalcul confidence : candidate.score (0..1) -> 0..100, plancher 30
    raw_score = chosen.get("score")
    try:
        score_pct = int(round(float(raw_score or 0.0) * 100))
    except (TypeError, ValueError):
        score_pct = 0
    new_confidence = max(30, min(100, score_pct))
    new_label = _confidence_label_from_value(new_confidence)

    proposed_title = str(chosen.get("title") or row.get("proposed_title") or "").strip()
    try:
        proposed_year = int(chosen.get("year") or row.get("proposed_year") or 0)
    except (TypeError, ValueError):
        proposed_year = 0

    new_proposed_path = _format_proposed_path(api, rid, proposed_title, proposed_year)

    # Persistance override
    store = _get_store(api)
    if store is None:
        return _err_response("Store SQLite indisponible.", category="runtime", level="error", log_module=__name__)
    try:
        store.film_modal.upsert_tmdb_override(
            run_id=rid,
            row_id=str(row_id),
            tmdb_id=tmdb_int,
            new_confidence=new_confidence,
            proposed_title=proposed_title,
            proposed_year=proposed_year,
        )
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        return _err_response(
            f"Persistance override echouee : {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )

    return {
        "ok": True,
        "run_id": rid,
        "row_id": str(row_id),
        "tmdb_id": tmdb_int,
        "new_confidence": new_confidence,
        "new_confidence_label": new_label,
        "new_proposed_path": new_proposed_path,
        "proposed_title": proposed_title,
        "proposed_year": proposed_year,
    }


def mark_for_deletion(api: Any, run_id: Optional[str], row_id: str) -> Dict[str, Any]:
    """Spec 06 §3.7 : marque un film pour le bucket `_user_marked_for_deletion/`.

    - Persiste en DB (table film_marked_for_deletion)
    - Reversible via undo (clear / unmark_for_deletion)
    - Le deplacement effectif sera applique au prochain apply

    Retourne : { ok, marked, run_id, row_id, source_path, marked_at }
    """
    # Fix audit 2026-05-25 (v1.5.3) Vague F : wrap global pour eviter HTTP 500.
    try:
        return _mark_for_deletion_impl(api, run_id, row_id)
    except Exception as exc:  # noqa: BLE001 - boundary top-level
        logger.exception("mark_for_deletion failed for run_id=%s row_id=%s", run_id, row_id)
        return {
            "ok": False,
            "error": "mark_for_deletion_failed",
            "message": str(exc),
            "user_message": "Impossible de marquer ce film. Verifie l'etat du run et reessaie.",
        }


def _mark_for_deletion_impl(api: Any, run_id: Optional[str], row_id: str) -> Dict[str, Any]:
    """Implementation reelle de mark_for_deletion, sans wrap global (Vague F)."""
    rid = _resolve_run_id(api, run_id)
    if not rid:
        return _err_response("Aucun run disponible.", category="state", level="info", log_module=__name__)

    row = _find_plan_row(api, rid, str(row_id))
    if not row:
        return _err_response(
            f"Film introuvable (row_id={row_id}).", category="resource", level="info", log_module=__name__
        )

    source_path = str(row.get("source_path") or row.get("folder") or "")

    store = _get_store(api)
    if store is None:
        return _err_response("Store SQLite indisponible.", category="runtime", level="error", log_module=__name__)
    try:
        res = store.film_modal.mark_for_deletion(
            run_id=rid,
            row_id=str(row_id),
            source_path=source_path,
        )
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        return _err_response(
            f"Persistance marquage echouee : {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )

    return {
        "ok": True,
        "marked": True,
        "run_id": rid,
        "row_id": str(row_id),
        "source_path": source_path,
        "marked_at": float(res.get("marked_at") or 0.0),
    }


def mark_alert_ignored(api: Any, row_id: str, alert_code: str) -> Dict[str, Any]:
    """Spec 06 §3.3 : persiste "j'ai vu cette alerte, on continue".

    - Insert en DB (table ignored_alerts)
    - L'alerte disparait visuellement mais reste loggee pour stats globales
    - Idempotent : meme couple (row_id, alert_code) ne re-insere pas

    Retourne : { ok, ignored, row_id, alert_code, ignored_at }
    """
    # Fix audit 2026-05-25 (v1.5.3) Vague F : wrap global pour eviter HTTP 500.
    try:
        return _mark_alert_ignored_impl(api, row_id, alert_code)
    except Exception as exc:  # noqa: BLE001 - boundary top-level
        logger.exception("mark_alert_ignored failed for row_id=%s alert_code=%s", row_id, alert_code)
        return {
            "ok": False,
            "error": "mark_alert_ignored_failed",
            "message": str(exc),
            "user_message": "Impossible d'ignorer cette alerte. Reessaie dans quelques instants.",
        }


def _mark_alert_ignored_impl(api: Any, row_id: str, alert_code: str) -> Dict[str, Any]:
    """Implementation reelle de mark_alert_ignored, sans wrap global (Vague F)."""
    rid_s = str(row_id or "").strip()
    code_s = str(alert_code or "").strip()
    if not rid_s:
        return _err_response("row_id manquant.", category="validation", level="info", log_module=__name__)
    if not code_s:
        return _err_response("alert_code manquant.", category="validation", level="info", log_module=__name__)

    store = _get_store(api)
    if store is None:
        return _err_response("Store SQLite indisponible.", category="runtime", level="error", log_module=__name__)
    try:
        res = store.film_modal.insert_ignored_alert(rid_s, code_s)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        return _err_response(
            f"Persistance alerte ignoree echouee : {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )

    return {
        "ok": True,
        "ignored": True,
        "row_id": rid_s,
        "alert_code": code_s,
        "ignored_at": float(res.get("ignored_at") or 0.0),
        "already_ignored": not bool(res.get("inserted")),
    }


# ---------------------------------------------------------------------------
# Rollup interne (legacy)
# ---------------------------------------------------------------------------


def _extract_group_key(row: Dict[str, Any], dim: str) -> Optional[str]:
    """Extrait la cle de regroupement depuis une row enrichie."""
    if dim == "franchise":
        # Pour le moment on utilise le champ tmdb_collection_name si present
        coll = row.get("tmdb_collection_name")
        return str(coll).strip() if coll else None
    if dim == "director":
        # Non dispo directement dans build_library_rows, retourne None
        return None
    if dim == "decade":
        year = int(row.get("year") or 0)
        if year == 0:
            return None
        return f"{(year // 10) * 10}s"
    if dim == "codec":
        codec = str(row.get("codec") or "").strip()
        return codec.upper() if codec and codec != "unknown" else None
    if dim == "era_grain":
        era = row.get("grain_era_v2")
        return str(era) if era else None
    if dim == "resolution":
        res = str(row.get("resolution") or "").strip()
        return res.upper() if res and res != "unknown" else None
    return None
