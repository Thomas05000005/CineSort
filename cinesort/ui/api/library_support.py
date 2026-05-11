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

from cinesort.infra import state
from cinesort.ui.api.settings_support import normalize_user_path

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
        settings = api.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _ = api._get_or_create_infra(state_dir)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("library_support cannot get store: %s", exc)
        return []

    # Perceptual reports indexes par row_id
    try:
        perc_list = store.list_perceptual_reports(run_id=run_id)
    except (OSError, AttributeError, TypeError, ValueError):
        perc_list = []
    perc_by_row = {str(p.get("row_id", "")): p for p in perc_list}

    # Quality reports
    try:
        quality_list = store.list_quality_reports(run_id=run_id)
    except (AttributeError, OSError, TypeError, ValueError):
        quality_list = []
    quality_by_row = {str(q.get("row_id", "")): q for q in quality_list}

    # PlanRows
    plan_result = api.get_plan(run_id)
    if not plan_result or not plan_result.get("ok"):
        return []
    plan_rows = plan_result.get("rows") or []

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

        row = {
            "row_id": row_id,
            "title": r.get("proposed_title") or r.get("nfo_title") or "",
            "year": int(r.get("proposed_year") or 0),
            "duration_s": duration_s,
            "duration_min": int(duration_s / 60) if duration_s > 0 else 0,
            "codec": _normalize_codec(probe_video.get("codec")),
            "resolution": _classify_resolution(width, height),
            "width": width,
            "height": height,
            "hdr": _classify_hdr(probe_video),
            "tier_v2": str((perc or {}).get("global_tier_v2") or "unknown").lower(),
            "score_v2": (perc or {}).get("global_score_v2"),
            "warnings": _extract_row_warnings(perc),
            "grain_era_v2": None,  # extrait du metrics si dispo
            "grain_nature": None,
            "added_ts": float(r.get("mtime") or 0),
            "path": r.get("source_path") or "",
            "poster_url": r.get("poster_url"),
            # v7.6.0 Vague 7 : champs pour get_scoring_rollup
            "tmdb_collection_name": r.get("tmdb_collection_name"),
            "edition": r.get("edition"),
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
        settings = api.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _ = api._get_or_create_infra(state_dir)
        runs = store.list_runs(limit=1)
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
        settings = api.get_settings()
    except (OSError, AttributeError, KeyError, TypeError, ValueError):
        return []
    raw = settings.get("smart_playlists")
    if isinstance(raw, list):
        return raw
    return []


def _write_playlists_to_settings(api: Any, playlists: List[Dict[str, Any]]) -> bool:
    try:
        settings = api.get_settings()
        settings["smart_playlists"] = playlists
        api.save_settings(settings)
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
        return {"ok": False, "message": "Nom requis."}
    if not isinstance(filters, dict):
        return {"ok": False, "message": "Filtres invalides."}

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
            return {"ok": False, "message": "Playlist introuvable."}
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
        return {"ok": False, "message": "Erreur de persistance."}

    return {"ok": True, "playlist_id": playlist_id}


def delete_smart_playlist(api: Any, playlist_id: str) -> Dict[str, Any]:
    """Supprime une smart playlist custom (les presets ne peuvent etre supprimes)."""
    if not playlist_id or str(playlist_id).startswith("_preset_"):
        return {"ok": False, "message": "Playlist protegee."}

    playlists = _get_playlists_from_settings(api)
    before = len(playlists)
    playlists = [p for p in playlists if p.get("id") != playlist_id]
    if len(playlists) == before:
        return {"ok": False, "message": "Playlist introuvable."}

    if not _write_playlists_to_settings(api, playlists):
        return {"ok": False, "message": "Erreur de persistance."}

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
