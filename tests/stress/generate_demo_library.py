"""V4-01 — Genere N films fictifs en BDD pour stress test.

Usage:
    python tests/stress/generate_demo_library.py 10000 /tmp/stress.db

Produit dans la DB SQLite cible :
    - 1 run (statut DONE) avec stats_json mock
    - N quality_reports (score / tier v1 + metrics JSON realistes)
    - N perceptual_reports (visual/audio + global_score_v2 / global_tier_v2)

Ne touche pas au filesystem CineSort utilisateur : la DB cible doit etre
un fichier temporaire fourni par l'appelant. Le module supprime le fichier
DB cible s'il existe deja avant de regenerer (mode CLI uniquement).
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

RESOLUTIONS = ("480p", "720p", "1080p", "1440p", "2160p")
VIDEO_CODECS = ("h264", "hevc", "av1", "vp9", "mpeg4")
AUDIO_CODECS = ("aac", "ac3", "eac3", "dts", "dts-hd ma", "truehd", "atmos")
TIERS_V1 = ("Premium", "Bon", "Moyen", "Mauvais")
TIERS_V1_WEIGHTS = (0.20, 0.40, 0.30, 0.10)
TIERS_V2 = ("platinum", "gold", "silver", "bronze", "reject")
TIERS_V2_WEIGHTS = (0.10, 0.30, 0.35, 0.20, 0.05)

_TIER_V1_SCORE_RANGE = {
    "Premium": (85, 100),
    "Bon": (68, 84),
    "Moyen": (54, 67),
    "Mauvais": (20, 53),
}
_TIER_V2_SCORE_RANGE = {
    "platinum": (90, 100),
    "gold": (75, 89),
    "silver": (60, 74),
    "bronze": (40, 59),
    "reject": (10, 39),
}


def _sample_metrics(rng: random.Random) -> Dict:
    """Construit un payload metrics realiste pour quality_reports."""
    res = rng.choice(RESOLUTIONS)
    width_height = {
        "480p": (854, 480),
        "720p": (1280, 720),
        "1080p": (1920, 1080),
        "1440p": (2560, 1440),
        "2160p": (3840, 2160),
    }[res]
    has_hdr = res == "2160p" and rng.random() < 0.4
    return {
        "detected": {
            "resolution": res,
            "resolution_label": res,
            "video_codec": rng.choice(VIDEO_CODECS),
            "audio_best_codec": rng.choice(AUDIO_CODECS),
            "audio_best_channels": rng.choice([2, 6, 8]),
            "bitrate_kbps": rng.randint(800, 30000),
            "duration_s": rng.randint(60 * 80, 60 * 180),
            "file_size_bytes": rng.randint(500 * 1024 * 1024, 50 * 1024 * 1024 * 1024),
            "hdr10": has_hdr and rng.random() < 0.6,
            "hdr10_plus": has_hdr and rng.random() < 0.2,
            "hdr_dolby_vision": has_hdr and rng.random() < 0.2,
            "languages": rng.choice([["fr"], ["fr", "en"], ["en"]]),
            "title": "",
        },
        "video": {
            "codec": rng.choice(VIDEO_CODECS),
            "width": width_height[0],
            "height": width_height[1],
            "has_hdr10": has_hdr and rng.random() < 0.6,
            "has_hdr10_plus": has_hdr and rng.random() < 0.2,
            "has_dv": has_hdr and rng.random() < 0.2,
        },
        "subscores": {
            "video": rng.randint(40, 100),
            "audio": rng.randint(40, 100),
            "extras": rng.randint(40, 100),
        },
        "thresholds_used": {"bitrate_min_kbps_2160p": 25000},
        "probe_quality": rng.choice(["FULL", "FULL", "FULL", "PARTIAL"]),
        "duration_s": rng.randint(60 * 80, 60 * 180),
    }


def generate_films(n: int, db_path: Path) -> Dict:
    """Genere N films fictifs dans la DB SQLite cible.

    Retourne un dict {duration_s, total_films, run_id}.

    Le store est initialise avant insertion. Un seul run est cree (statut DONE),
    contenant les N quality_reports et les N perceptual_reports.
    """
    sys.path.insert(0, ".")
    from cinesort.infra.db.sqlite_store import SQLiteStore

    rng = random.Random(20260501)
    store = SQLiteStore(Path(db_path))
    store.initialize()

    t0 = time.perf_counter()
    run_id = f"stress_{int(time.time())}"
    state_dir = str(Path(db_path).parent)

    store.insert_run_pending(
        run_id=run_id,
        root="C:/StressMovies",
        state_dir=state_dir,
        config={"is_stress": True, "stress_count": n},
        created_ts=time.time(),
    )
    store.mark_run_running(run_id, started_ts=time.time())

    profile_id = "stress_profile"
    profile_version = 1

    for i in range(n):
        row_id = f"{run_id}_{i:06d}"
        tier_v1 = rng.choices(TIERS_V1, weights=TIERS_V1_WEIGHTS, k=1)[0]
        score_v1 = rng.randint(*_TIER_V1_SCORE_RANGE[tier_v1])
        metrics = _sample_metrics(rng)

        store.upsert_quality_report(
            run_id=run_id,
            row_id=row_id,
            score=score_v1,
            tier=tier_v1,
            reasons=[f"stress_reason_{i % 5}"],
            metrics=metrics,
            profile_id=profile_id,
            profile_version=profile_version,
        )

        tier_v2 = rng.choices(TIERS_V2, weights=TIERS_V2_WEIGHTS, k=1)[0]
        score_v2 = rng.randint(*_TIER_V2_SCORE_RANGE[tier_v2])
        warnings = []
        if rng.random() < 0.05:
            warnings.append("dnr_partial")
        if rng.random() < 0.05:
            warnings.append("HDR10 sans MaxCLL")
        store.upsert_perceptual_report(
            run_id=run_id,
            row_id=row_id,
            visual_score=rng.randint(30, 100),
            audio_score=rng.randint(30, 100),
            global_score=score_v2,
            global_tier=tier_v1.lower(),
            metrics=metrics,
            settings_used={"profile": "default"},
            global_score_v2=float(score_v2),
            global_tier_v2=tier_v2,
            global_score_v2_payload={
                "warnings": warnings,
                "adjustments_applied": [],
            },
        )

        if i and (i % 1000 == 0):
            logger.info("Insere %d/%d films... (%.1fs)", i, n, time.perf_counter() - t0)

    store.mark_run_done(
        run_id,
        stats={
            "planned_rows": n,
            "applied_count": 0,
            "is_stress": True,
        },
        ended_ts=time.time(),
    )

    duration = time.perf_counter() - t0
    return {"duration_s": duration, "total_films": n, "run_id": run_id}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="V4-01 stress test data generator")
    parser.add_argument("count", type=int, help="Nombre de films a generer")
    parser.add_argument("db_path", type=str, help="Chemin de la DB SQLite cible")
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    stats = generate_films(int(args.count), db_path)
    size_mb = db_path.stat().st_size / 1024 / 1024
    print(f"\nGenere {stats['total_films']} films en {stats['duration_s']:.1f}s")
    print(f"DB : {db_path} ({size_mb:.1f} MB)")
    print(f"run_id : {stats['run_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
