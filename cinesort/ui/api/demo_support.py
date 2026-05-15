"""V3-05 — Mode démo wizard (premier-run pour nouveaux utilisateurs).

Crée un run fictif avec 15 films représentatifs (tiers Premium / Bon / Moyen /
Mauvais), un plan.jsonl sur disque et des quality_reports en BDD pour permettre
à un nouvel utilisateur d'explorer la bibliothèque, le dashboard et les filtres
sans avoir scanné ses propres dossiers.

Signature critique : adaptée aux vraies API du store
(`insert_run_pending` + `mark_run_done` + `upsert_quality_report`).
La suppression utilise `_managed_conn` car aucune méthode publique du store
n'expose un DELETE cascade run/quality_reports.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Tuple

from cinesort.infra import state
from cinesort.ui.api.settings_support import normalize_user_path

logger = logging.getLogger(__name__)

DEMO_PROFILE_ID = "demo_profile"
DEMO_PROFILE_VERSION = 1
DEMO_ROOT = "C:\\DemoMovies"

# 15 films fictifs représentatifs des 4 tiers (Premium / Bon / Moyen / Mauvais)
DEMO_FILMS: List[Dict[str, Any]] = [
    {
        "title": "Inception",
        "year": 2010,
        "tmdb_id": 27205,
        "tier": "Premium",
        "score": 92,
        "resolution": "2160p",
        "video_codec": "hevc",
        "audio_codec": "truehd",
        "channels": 8,
        "bitrate": 25000,
    },
    {
        "title": "Interstellar",
        "year": 2014,
        "tmdb_id": 157336,
        "tier": "Premium",
        "score": 95,
        "resolution": "2160p",
        "video_codec": "hevc",
        "audio_codec": "atmos",
        "channels": 8,
        "bitrate": 30000,
    },
    {
        "title": "The Dark Knight",
        "year": 2008,
        "tmdb_id": 155,
        "tier": "Premium",
        "score": 89,
        "resolution": "1080p",
        "video_codec": "hevc",
        "audio_codec": "truehd",
        "channels": 6,
        "bitrate": 18000,
    },
    {
        "title": "Avatar",
        "year": 2009,
        "tmdb_id": 19995,
        "tier": "Premium",
        "score": 88,
        "resolution": "2160p",
        "video_codec": "hevc",
        "audio_codec": "atmos",
        "channels": 8,
        "bitrate": 28000,
    },
    {
        "title": "Pulp Fiction",
        "year": 1994,
        "tmdb_id": 680,
        "tier": "Bon",
        "score": 78,
        "resolution": "1080p",
        "video_codec": "h264",
        "audio_codec": "ac3",
        "channels": 6,
        "bitrate": 12000,
    },
    {
        "title": "The Matrix",
        "year": 1999,
        "tmdb_id": 603,
        "tier": "Bon",
        "score": 75,
        "resolution": "1080p",
        "video_codec": "h264",
        "audio_codec": "dts",
        "channels": 6,
        "bitrate": 11000,
    },
    {
        "title": "Fight Club",
        "year": 1999,
        "tmdb_id": 550,
        "tier": "Bon",
        "score": 72,
        "resolution": "1080p",
        "video_codec": "h264",
        "audio_codec": "ac3",
        "channels": 6,
        "bitrate": 10000,
    },
    {
        "title": "Forrest Gump",
        "year": 1994,
        "tmdb_id": 13,
        "tier": "Bon",
        "score": 70,
        "resolution": "1080p",
        "video_codec": "h264",
        "audio_codec": "aac",
        "channels": 6,
        "bitrate": 9000,
    },
    {
        "title": "The Godfather",
        "year": 1972,
        "tmdb_id": 238,
        "tier": "Moyen",
        "score": 62,
        "resolution": "720p",
        "video_codec": "h264",
        "audio_codec": "ac3",
        "channels": 2,
        "bitrate": 5000,
    },
    {
        "title": "Goodfellas",
        "year": 1990,
        "tmdb_id": 769,
        "tier": "Moyen",
        "score": 60,
        "resolution": "720p",
        "video_codec": "h264",
        "audio_codec": "ac3",
        "channels": 2,
        "bitrate": 4500,
    },
    {
        "title": "Casablanca",
        "year": 1942,
        "tmdb_id": 289,
        "tier": "Moyen",
        "score": 56,
        "resolution": "720p",
        "video_codec": "h264",
        "audio_codec": "aac",
        "channels": 2,
        "bitrate": 3500,
    },
    {
        "title": "Old Movie SD",
        "year": 1985,
        "tmdb_id": None,
        "tier": "Mauvais",
        "score": 42,
        "resolution": "480p",
        "video_codec": "xvid",
        "audio_codec": "mp3",
        "channels": 2,
        "bitrate": 1500,
    },
    {
        "title": "Bad Encode",
        "year": 2018,
        "tmdb_id": None,
        "tier": "Mauvais",
        "score": 38,
        "resolution": "1080p",
        "video_codec": "h264",
        "audio_codec": "aac",
        "channels": 2,
        "bitrate": 800,
    },
    {
        "title": "Sample Trailer",
        "year": 2020,
        "tmdb_id": None,
        "tier": "Mauvais",
        "score": 25,
        "resolution": "720p",
        "video_codec": "h264",
        "audio_codec": "aac",
        "channels": 2,
        "bitrate": 2000,
    },
    {
        "title": "Cam Rip",
        "year": 2022,
        "tmdb_id": None,
        "tier": "Mauvais",
        "score": 15,
        "resolution": "480p",
        "video_codec": "h264",
        "audio_codec": "aac",
        "channels": 2,
        "bitrate": 1000,
    },
]

_RESOLUTION_WH: Dict[str, Tuple[int, int]] = {
    "2160p": (3840, 2160),
    "1080p": (1920, 1080),
    "720p": (1280, 720),
    "480p": (854, 480),
}


def _row_id_for(run_id: str, film: Dict[str, Any]) -> str:
    safe = "".join(c if c.isalnum() else "_" for c in str(film["title"]).lower()).strip("_")
    return f"{run_id}_{safe}"


def _resolve_store(api: Any):
    """Retourne (settings, state_dir, store) en respectant le pattern api standard."""
    settings = api.settings.get_settings()
    state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
    store, _runner = api._get_or_create_infra(state_dir)
    return settings, state_dir, store


def _is_demo_run(run_row: Dict[str, Any]) -> bool:
    raw = run_row.get("config_json")
    cfg: Any = raw
    if isinstance(raw, str):
        try:
            cfg = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            return False
    return isinstance(cfg, dict) and bool(cfg.get("is_demo"))


def _list_demo_run_ids(store: Any) -> List[str]:
    runs = store.list_runs(limit=500)
    return [str(r.get("run_id") or "") for r in runs if _is_demo_run(r) and r.get("run_id")]


def is_demo_active(api: Any) -> bool:
    """True si au moins un run avec config_json['is_demo'] == True existe."""
    try:
        _, _, store = _resolve_store(api)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("V3-05 is_demo_active resolve store: %s", exc)
        return False
    try:
        return bool(_list_demo_run_ids(store))
    except (OSError, AttributeError, TypeError, ValueError, sqlite3.Error) as exc:
        logger.warning("V3-05 is_demo_active list runs: %s", exc)
        return False


def _build_plan_row(film: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    """Construit un PlanRow JSONL compatible run_data_support.row_from_json."""
    title = str(film["title"])
    year = int(film["year"])
    tmdb_id = film.get("tmdb_id")
    folder = f"{DEMO_ROOT}\\{title} ({year})"
    return {
        "row_id": _row_id_for(run_id, film),
        "kind": "single",
        "folder": folder,
        "video": f"{title} ({year}).mkv",
        "proposed_title": title,
        "proposed_year": year,
        "proposed_source": "tmdb" if tmdb_id else "name",
        "confidence": 95 if tmdb_id else 35,
        "confidence_label": "high" if tmdb_id else "low",
        "candidates": [
            {
                "title": title,
                "year": year,
                "source": "tmdb" if tmdb_id else "name",
                "tmdb_id": tmdb_id,
                "score": 0.95 if tmdb_id else 0.4,
                "note": "demo",
            }
        ],
        "warning_flags": [],
        "notes": "demo",
        "detected_year": year,
        "detected_year_reason": "demo",
        "source_root": DEMO_ROOT,
    }


def _build_quality_metrics(film: Dict[str, Any]) -> Dict[str, Any]:
    width, height = _RESOLUTION_WH.get(str(film.get("resolution") or ""), (0, 0))
    return {
        "video": {
            "codec": str(film["video_codec"]),
            "width": int(width),
            "height": int(height),
        },
        "audio": {
            "codec": str(film["audio_codec"]),
            "channels": int(film["channels"]),
        },
        "duration_s": 6300,
        "bitrate_kbps": int(film["bitrate"]),
    }


def start_demo_mode(api: Any) -> Dict[str, Any]:
    """Active le mode démo : 1 run + 15 films + quality_reports + plan.jsonl."""
    if is_demo_active(api):
        return {"ok": False, "error": "Mode démo déjà actif"}

    try:
        _, state_dir, store = _resolve_store(api)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.exception("V3-05 start_demo_mode resolve store")
        return {"ok": False, "error": f"store indisponible: {exc}"}

    started = time.time()
    run_id = f"demo_{int(started)}_{uuid.uuid4().hex[:6]}"
    config = {"is_demo": True, "demo_label": "CineSort démo", "root": DEMO_ROOT}

    try:
        run_paths = state.new_run(state_dir, run_id)
        store.insert_run_pending(
            run_id=run_id,
            root=DEMO_ROOT,
            state_dir=str(state_dir),
            config=config,
            created_ts=started,
        )
        store.mark_run_running(run_id, started_ts=started)

        with run_paths.plan_jsonl.open("w", encoding="utf-8") as fp:
            for film in DEMO_FILMS:
                row = _build_plan_row(film, run_id)
                fp.write(json.dumps(row, ensure_ascii=False) + "\n")

        for film in DEMO_FILMS:
            store.upsert_quality_report(
                run_id=run_id,
                row_id=_row_id_for(run_id, film),
                score=int(film["score"]),
                tier=str(film["tier"]),
                reasons=["démo : score fictif"],
                metrics=_build_quality_metrics(film),
                profile_id=DEMO_PROFILE_ID,
                profile_version=DEMO_PROFILE_VERSION,
                ts=started,
            )

        store.mark_run_done(
            run_id,
            stats={
                "planned_rows": len(DEMO_FILMS),
                "applied_count": 0,
                "is_demo": True,
            },
            ended_ts=time.time(),
        )
        logger.info("V3-05 mode démo créé run_id=%s films=%d", run_id, len(DEMO_FILMS))
        return {"ok": True, "run_id": run_id, "count": len(DEMO_FILMS)}
    except (OSError, AttributeError, KeyError, TypeError, ValueError, sqlite3.Error) as exc:
        logger.exception("V3-05 start_demo_mode failed")
        return {"ok": False, "error": str(exc)}


def stop_demo_mode(api: Any) -> Dict[str, Any]:
    """Supprime tous les runs is_demo + quality_reports + dossiers run_dir associés.

    Aucune méthode publique du store n'expose un DELETE cascade, donc on passe
    par `store._managed_conn()` (acceptable car ce module est l'unique
    propriétaire du cycle de vie des données démo).
    """
    try:
        _, state_dir, store = _resolve_store(api)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.exception("V3-05 stop_demo_mode resolve store")
        return {"ok": False, "error": f"store indisponible: {exc}"}

    try:
        demo_run_ids = _list_demo_run_ids(store)
    except (OSError, AttributeError, TypeError, ValueError, sqlite3.Error) as exc:
        logger.exception("V3-05 stop_demo_mode list runs")
        return {"ok": False, "error": str(exc)}

    removed = 0
    for rid in demo_run_ids:
        try:
            with store._managed_conn() as conn:
                conn.execute("DELETE FROM quality_reports WHERE run_id=?", (rid,))
                conn.execute("DELETE FROM errors WHERE run_id=?", (rid,))
                conn.execute("DELETE FROM runs WHERE run_id=?", (rid,))
            run_dir = state_dir / "runs" / f"tri_films_{rid}"
            if run_dir.is_dir():
                shutil.rmtree(run_dir, ignore_errors=True)
            removed += 1
        except (OSError, AttributeError, sqlite3.Error) as exc:
            logger.warning("V3-05 stop_demo_mode delete run=%s err=%s", rid, exc)

    logger.info("V3-05 mode démo supprimé : %d runs nettoyés", removed)
    return {"ok": True, "removed": removed}
