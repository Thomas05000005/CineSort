"""Generateur de donnees mock pour les tests E2E du dashboard.

Cree un state_dir realiste avec 15 films, 2 runs, quality reports et perceptual reports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# 15 films deterministes
# ---------------------------------------------------------------------------

_RUN_ID = "20260401_120000_001"
_OLD_RUN_ID = "20260328_100000_001"
_TOKEN = "test-token-e2e"

_BASE_TS = 1711929600.0  # 2024-04-01 12:00 UTC


def _row(
    idx: int,
    title: str,
    year: int,
    res: str,
    score: int,
    codec: str,
    audio: str,
    edition: str = "",
    warnings: str = "",
    collection_id: int = 0,
    collection_name: str = "",
    sub_count: int = 2,
    sub_langs: str = "fr,en",
) -> Dict[str, Any]:
    """Fabrique un PlanRow dict."""
    row_id = f"row-{idx:03d}"
    w, h = {"2160p": (3840, 2160), "1080p": (1920, 1080), "720p": (1280, 720), "SD": (720, 480)}.get(res, (1920, 1080))
    return {
        "row_id": row_id,
        "kind": "single",
        "folder": f"/media/films/{title.replace(' ', '.')}",
        "video": f"{title.replace(' ', '.')}.{year}.{res}.mkv",
        "proposed_title": title,
        "proposed_year": year,
        "proposed_source": "name",
        "confidence": max(50, score),
        "confidence_label": "high" if score >= 80 else ("med" if score >= 60 else "low"),
        "candidates": [{"title": title, "year": year, "source": "name", "tmdb_id": 10000 + idx, "score": 0.9}],
        "nfo_path": None,
        "notes": "",
        "detected_year": year,
        "detected_year_reason": "extracted",
        "warning_flags": [w.strip() for w in warnings.split(",") if w.strip()],
        "collection_name": collection_name or None,
        "tmdb_collection_id": collection_id or None,
        "tmdb_collection_name": collection_name or None,
        "edition": edition or None,
        "source_root": None,
        "subtitle_count": sub_count,
        "subtitle_languages": [s.strip() for s in sub_langs.split(",") if s.strip()],
        "subtitle_formats": ["srt"],
        "subtitle_missing_langs": [],
        "subtitle_orphans": 0,
        "tv_series_name": None,
        "tv_season": None,
        "tv_episode": None,
        "tv_episode_title": None,
        "tv_tmdb_series_id": None,
        # Champs enrichis pour les quality reports
        "_score": score,
        "_resolution": res,
        "_codec": codec,
        "_audio": audio,
        "_width": w,
        "_height": h,
    }


def build_plan_rows() -> List[Dict[str, Any]]:
    """Retourne 15 PlanRow dicts deterministes."""
    return [
        _row(
            1, "Avengers Endgame", 2019, "2160p", 92, "hevc", "atmos", collection_id=86311, collection_name="Avengers"
        ),
        _row(
            2,
            "Avengers Infinity War",
            2018,
            "2160p",
            88,
            "hevc",
            "truehd",
            collection_id=86311,
            collection_name="Avengers",
        ),
        _row(
            3,
            "Captain America Civil War",
            2016,
            "1080p",
            78,
            "h264",
            "ac3",
            collection_id=86311,
            collection_name="Avengers",
        ),
        _row(4, "Blade Runner 2049", 2017, "2160p", 95, "hevc", "atmos", edition="IMAX"),
        _row(5, "The Matrix", 1999, "1080p", 82, "h264", "dts-hd", sub_langs="fr,en,es"),
        _row(6, "Interstellar", 2014, "2160p", 90, "hevc", "truehd"),
        _row(7, "Parasite", 2019, "1080p", 75, "h264", "aac", warnings="mkv_title_mismatch"),
        _row(8, "The Room", 2003, "720p", 30, "h264", "aac", warnings="not_a_movie", sub_count=0, sub_langs=""),
        _row(9, "Cats", 2019, "1080p", 35, "h264", "ac3", warnings="not_a_movie"),
        _row(
            10,
            "Corrupted Film",
            2020,
            "SD",
            42,
            "mpeg2",
            "ac3",
            warnings="integrity_header_invalid",
            sub_count=0,
            sub_langs="",
        ),
        _row(11, "Upscale Suspect", 2021, "2160p", 55, "hevc", "aac", warnings="upscale_suspect"),
        _row(12, "Dune Part Two", 2024, "2160p", 91, "hevc", "atmos"),
        _row(13, "Dune Part Two", 2024, "1080p", 68, "h264", "ac3"),
        _row(14, "Oppenheimer", 2023, "2160p", 93, "hevc", "truehd", edition="IMAX", warnings="mkv_title_mismatch"),
        _row(15, "Old Boy", 2003, "720p", 58, "h264", "aac"),
    ]


def _tier_from_score(score: int) -> str:
    """Tier technique depuis le score."""
    if score >= 85:
        return "Premium"
    if score >= 68:
        return "Bon"
    if score >= 54:
        return "Moyen"
    return "Faible"


def populate_database(
    store: Any,
    root: Path,
    state_dir: Path,
    run_id: str = _RUN_ID,
    old_run_id: str = _OLD_RUN_ID,
) -> Dict[str, Any]:
    """Insere 2 runs + 15 quality reports + 3 perceptual reports."""
    rows = build_plan_rows()

    # Run ancien (plus vieux)
    store.insert_run_pending(
        run_id=old_run_id,
        root=str(root),
        state_dir=str(state_dir),
        config={"root": str(root), "enable_collection_folder": True},
        created_ts=_BASE_TS - 86400 * 4,
    )
    store.mark_run_done(
        old_run_id, stats={"planned_rows": 10, "folders_scanned": 10}, ended_ts=_BASE_TS - 86400 * 4 + 300
    )

    # Run principal
    store.insert_run_pending(
        run_id=run_id,
        root=str(root),
        state_dir=str(state_dir),
        config={"root": str(root), "enable_collection_folder": True},
        created_ts=_BASE_TS,
    )
    store.mark_run_done(run_id, stats={"planned_rows": 15, "folders_scanned": 15}, ended_ts=_BASE_TS + 600)

    # Quality reports pour chaque film
    for r in rows:
        score = r["_score"]
        store.upsert_quality_report(
            run_id=run_id,
            row_id=r["row_id"],
            score=score,
            tier=_tier_from_score(score),
            reasons=[f"score_{score}"],
            metrics={
                "engine_version": "CinemaLux_v1",
                "probe_quality": "FULL",
                "detected": {
                    "codec": r["_codec"],
                    "width": r["_width"],
                    "height": r["_height"],
                    "resolution_label": r["_resolution"],
                    "audio_codec": r["_audio"],
                    "bitrate_kbps": 15000 if "2160p" in r["_resolution"] else 8000,
                },
            },
            profile_id="CinemaLux_v1",
            profile_version=1,
            ts=_BASE_TS + 10,
        )

    # Perceptual reports (3 films)
    _perceptual = [
        ("row-012", 88, 92, 90, "reference"),
        ("row-014", 85, 90, 87, "reference"),
        ("row-015", 52, 48, 50, "mediocre"),
    ]
    for row_id, vs, aus, gs, tier in _perceptual:
        store.upsert_perceptual_report(
            run_id=run_id,
            row_id=row_id,
            visual_score=vs,
            audio_score=aus,
            global_score=gs,
            global_tier=tier,
            metrics={"global_score": gs, "visual_score": vs, "audio_score": aus, "global_tier": tier},
            settings_used={"frames_count": 10},
            ts=_BASE_TS + 20,
        )

    return {"run_id": run_id, "old_run_id": old_run_id, "rows": rows}


def write_plan_file(state_dir: Path, run_id: str, rows: List[Dict[str, Any]]) -> Path:
    """Ecrit plan.jsonl pour un run. Retourne le chemin du fichier."""
    run_dir = state_dir / "runs" / f"tri_films_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    plan_path = run_dir / "plan.jsonl"
    # Ecrire les rows sans les champs internes (_score, _resolution, etc.)
    with open(plan_path, "w", encoding="utf-8") as f:
        for r in rows:
            clean = {k: v for k, v in r.items() if not k.startswith("_")}
            f.write(json.dumps(clean, ensure_ascii=False) + "\n")
    return plan_path


def get_settings_dict(root: Path, state_dir: Path) -> Dict[str, Any]:
    """Retourne le dict settings pour les tests E2E."""
    return {
        "root": str(root),
        "state_dir": str(state_dir),
        "tmdb_enabled": False,
        "jellyfin_enabled": True,
        "jellyfin_url": "http://fake-jellyfin:8096",
        "jellyfin_api_key": "fake-key",
        "plex_enabled": False,
        "watch_enabled": True,
        "watch_interval_minutes": 5,
        "plugins_enabled": True,
        "perceptual_enabled": True,
        "rest_api_enabled": True,
        "rest_api_token": _TOKEN,
        "auto_approve_threshold": 85,
        "collection_folder_enabled": True,
        "probe_backend": "none",
    }
