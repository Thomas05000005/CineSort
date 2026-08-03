"""Smoke test : drive un scan complet via l'API in-process.

Cible : C:\\Users\\blanc\\test_cinesort_lib (~50 dossiers, accents, emojis,
brackets {tmdb-...} / [imdbid-...], long path).

Pour eviter de cogner avec l'instance CineSort deja lancee qui tient le
state_dir par defaut, on utilise un state_dir isole sous %TEMP%.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# ITER15 5.4 : forcer UTF-8 sur stdout/stderr pour eviter UnicodeEncodeError
# sur les caracteres non-ASCII (em-dash, accents) sous Windows cp1252. Le
# fallback errors="replace" garantit qu'un caractere non encodable ne fait
# pas planter le script (cas observe L96 avec "—").
for _stream in (sys.stdout, sys.stderr):
    try:  # noqa: SIM105 - contextlib.suppress ferait perdre la justification du catch
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

# Repo root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Avant import : activer mode E2E pour pouvoir baisser MIN_VIDEO_BYTES.
os.environ["CINESORT_E2E"] = "1"

import contextlib

import cinesort.domain.core as _core  # noqa: E402
from cinesort.ui.api.cinesort_api import CineSortApi  # noqa: E402

# Test lib utilise des stubs ~20KB.
_core.MIN_VIDEO_BYTES = 1024

LIB_ROOT = r"C:\Users\blanc\test_cinesort_lib"
STATE_DIR = Path(tempfile.gettempdir()) / "cinesort_smoketest_state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

print(f"[smoketest] lib_root = {LIB_ROOT}")
print(f"[smoketest] state_dir = {STATE_DIR}")
print(f"[smoketest] lib exists? {Path(LIB_ROOT).exists()}")

api = CineSortApi()

settings = {
    "root": LIB_ROOT,
    "roots": [LIB_ROOT],
    "state_dir": str(STATE_DIR),
    "tmdb_enabled": False,  # offline pour deterministe
    "omdb_enabled": False,
    "probe_backend": "auto",  # mediainfo/ffprobe pour detection videos
    "perceptual_enabled": False,
    "perceptual_auto_on_scan": False,
    "auto_recompute_quality_on_scan": False,
    "incremental_scan_enabled": False,
    "scan_max_workers_mode": "manual",
    "scan_max_workers_value": 4,
    "probe_parallelism_enabled": True,
    "subtitle_detection_enabled": False,
    # Test lib utilise des stubs ~20KB, on baisse le seuil.
    "min_video_bytes": 1024,
    "dry_run_apply": True,
    "debug_enabled": False,
    "log_level": "WARNING",
}

t0 = time.monotonic()
print("[smoketest] calling start_plan...")
resp = api.run.start_plan(settings)
print(f"[smoketest] start_plan -> {json.dumps({k: v for k, v in resp.items() if k != 'logs'}, ensure_ascii=False)}")

if not resp.get("ok"):
    print("[smoketest] start_plan FAILED, abort")
    sys.exit(1)

run_id = resp["run_id"]
last_idx = 0
deadline = time.monotonic() + 300  # 5 min
last_print = 0.0

while True:
    if time.monotonic() > deadline:
        print("[smoketest] TIMEOUT 5min")
        sys.exit(2)
    status = api.run.get_status(run_id, last_idx)
    if not status.get("ok"):
        print(f"[smoketest] get_status err: {status}")
        time.sleep(2)
        continue
    last_idx = status.get("next_log_index", last_idx)
    idx = status.get("idx", 0)
    total = status.get("total", 0)
    cur = status.get("current", "")
    done = status.get("done", False)
    if time.monotonic() - last_print >= 2.0 or done:
        print(f"[smoketest] idx={idx}/{total} status={status.get('status')} cur={cur!r:.80} done={done}")
        last_print = time.monotonic()
    if done:
        elapsed = time.monotonic() - t0
        print(f"[smoketest] DONE in {elapsed:.1f}s — final status={status.get('status')} err={status.get('error')}")
        break
    time.sleep(2)

elapsed = time.monotonic() - t0
print("[smoketest] ====== DASHBOARD ======")
dash = api.run.get_dashboard(run_id)
# Print only KPI-ish fields
keep_keys = [
    "ok",
    "mode",
    "kpis",
    "summary",
    "tier_counts",
    "anomaly_counts",
    "quality_counts",
    "validated_count",
    "rejected_count",
    "total",
    "scan_root",
    "run_id",
    "run_status",
]
slim = {k: dash.get(k) for k in keep_keys if k in dash}
print(json.dumps(slim, ensure_ascii=False, indent=2, default=str)[:4000])

# Read plan.jsonl directly for accurate count
run_dir = resp.get("run_dir")
plan_jsonl = Path(run_dir) / "plan.jsonl" if run_dir else None
if plan_jsonl and plan_jsonl.exists():
    plan_rows = []
    with open(plan_jsonl, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                with contextlib.suppress(Exception):
                    plan_rows.append(json.loads(line))
    print(f"[smoketest] plan.jsonl rows: {len(plan_rows)}")
    # Sample 5 paths to detect unicode handling
    print("[smoketest] sample film paths from plan:")
    for r in plan_rows[:6]:
        sp = r.get("source_path") or r.get("path") or r.get("src") or ""
        title = r.get("title") or r.get("clean_title") or ""
        print(f"  - title={title!r} src={sp!r}")
    # Look at problematic ones
    print("[smoketest] paths matching unicode/emoji/brackets:")
    for r in plan_rows:
        sp = r.get("source_path") or r.get("path") or r.get("src") or ""
        if any(c in sp for c in ("é", "ê", "ô", "î", "{", "[", "🎬", "ðŸŽ¬")) or "Long Path" in sp:
            print(f"  - {sp!r}")

print(f"[smoketest] ELAPSED total: {elapsed:.1f}s")
