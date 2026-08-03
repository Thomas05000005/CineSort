"""ITER2 GATE 1a — Pre-scan test_library/ pour peupler la DB avant observe.

Strategie [OPERATIONNEL] :
- Force LOCALAPPDATA -> out_dir/_state pour que CineSortApi resolve son state_dir
  vers le dossier isole partage avec observe.py.
- Seed settings.json est deja en place (DPAPI tmdb_api_key conservee).
- Instancie CineSortApi in-process et appelle run.start_plan + poll get_status
  jusqu'a completion.
- Pas de publication, pas de fix produit. Juste un scan pour faire entrer des
  posters TMDb dans la DB que observe.py va ensuite afficher.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# ITER15 5.4 : forcer UTF-8 sur stdout/stderr pour eviter UnicodeEncodeError
# sur les caracteres non-ASCII (em-dash, accents) sous Windows cp1252. Le
# fallback errors="replace" garantit qu'un caractere non encodable ne fait
# pas planter le script (cas observe iter precedentes a la L151 / L153).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        # Stream non standard (capture pytest, redirige, etc.) : on ignore.
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUT_DIR = PROJECT_ROOT / "docs" / "internal" / "observe" / "2026-06-08_ITER2_GATE1a"
STATE_PARENT = OUT_DIR / "_state"
STATE_DIR = STATE_PARENT / "CineSort"

# Activer mode E2E + baisser MIN_VIDEO_BYTES via env (idem smoketest).
os.environ["CINESORT_E2E"] = "1"
os.environ["LOCALAPPDATA"] = str(STATE_PARENT)

import cinesort.domain.core as _core  # noqa: E402
from cinesort.ui.api.cinesort_api import CineSortApi  # noqa: E402
from cinesort.ui.api.settings_support import read_settings  # noqa: E402

# Stubs sont ~11MB mais on baisse quand meme pour etre safe.
_core.MIN_VIDEO_BYTES = 1024

# Lire settings via read_settings pour declencher le decrypt DPAPI -> tmdb_api_key
settings = read_settings(STATE_DIR)
if not settings:
    # Fallback : lecture brute (DPAPI absent).
    with open(STATE_DIR / "settings.json", "r", encoding="utf-8-sig") as f:
        settings = json.load(f)
print(f"[iter2-scan] tmdb_api_key resolved : {bool(settings.get('tmdb_api_key'))} "
      f"protection={settings.get('tmdb_key_protection')}")

# Override quelques cles pour scan deterministe + offline-safe.
settings["state_dir"] = str(STATE_DIR)
settings["min_video_bytes"] = 1024
settings["tmdb_enabled"] = True
settings["omdb_enabled"] = False
settings["perceptual_enabled"] = False
settings["perceptual_auto_on_scan"] = False
settings["auto_recompute_quality_on_scan"] = False
settings["incremental_scan_enabled"] = False
settings["dry_run_apply"] = True
settings["debug_enabled"] = False
settings["log_level"] = "WARNING"
settings["scan_max_workers_mode"] = "manual"
settings["scan_max_workers_value"] = 4
settings["probe_parallelism_enabled"] = True
settings["subtitle_detection_enabled"] = False
settings["probe_backend"] = "auto"

print(f"[iter2-scan] state_dir = {STATE_DIR}")
print(f"[iter2-scan] roots = {settings.get('roots')}")
print(f"[iter2-scan] tmdb_enabled = {settings.get('tmdb_enabled')}")
print(f"[iter2-scan] has dpapi tmdb_api_key_secret = {'tmdb_api_key_secret' in settings}")

api = CineSortApi()
print("[iter2-scan] CineSortApi instancie. start_plan...")

t0 = time.monotonic()
resp = api.run.start_plan(settings)
print(f"[iter2-scan] start_plan -> ok={resp.get('ok')} run_id={resp.get('run_id')} error={resp.get('error')}")

if not resp.get("ok"):
    print("[iter2-scan] start_plan FAILED")
    print(json.dumps({k: v for k, v in resp.items() if k != 'logs'}, ensure_ascii=False, indent=2))
    sys.exit(1)

run_id = resp["run_id"]
last_idx = 0
deadline = time.monotonic() + 600  # 10 min
last_print = 0.0

while True:
    if time.monotonic() > deadline:
        print("[iter2-scan] TIMEOUT 10min")
        sys.exit(2)
    status = api.run.get_status(run_id, last_idx)
    if not status.get("ok"):
        print(f"[iter2-scan] get_status err: {status}")
        time.sleep(2)
        continue
    last_idx = status.get("next_log_index", last_idx)
    idx = status.get("idx", 0)
    total = status.get("total", 0)
    cur = status.get("current", "")
    done = status.get("done", False)
    if time.monotonic() - last_print >= 3.0 or done:
        print(f"[iter2-scan] idx={idx}/{total} status={status.get('status')} cur={cur!r:.80} done={done}")
        last_print = time.monotonic()
    if done:
        elapsed = time.monotonic() - t0
        print(f"[iter2-scan] DONE in {elapsed:.1f}s — final status={status.get('status')} err={status.get('error')}")
        break
    time.sleep(2)

# Dashboard summary
print("\n[iter2-scan] ===== DASHBOARD =====")
dash = api.run.get_dashboard(run_id)
keep = ["ok", "mode", "kpis", "summary", "tier_counts", "quality_counts", "total", "scan_root", "run_id", "run_status"]
slim = {k: dash.get(k) for k in keep if k in dash}
print(json.dumps(slim, ensure_ascii=False, indent=2, default=str)[:3500])

# Plan.jsonl analyse
run_dir = resp.get("run_dir")
plan_jsonl = Path(run_dir) / "plan.jsonl" if run_dir else None
if plan_jsonl and plan_jsonl.exists():
    rows = []
    with open(plan_jsonl, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    print(f"\n[iter2-scan] plan.jsonl rows: {len(rows)}")
    have_tmdb = 0
    have_poster = 0
    samples = []
    for r in rows:
        if r.get("tmdb_id"):
            have_tmdb += 1
        if r.get("poster_url") or r.get("tmdb_poster_url") or r.get("poster_path"):
            have_poster += 1
        if len(samples) < 12:
            samples.append({
                "folder": r.get("folder") or r.get("source_path"),
                "title": r.get("proposed_title") or r.get("title"),
                "tmdb_id": r.get("tmdb_id"),
                "poster_url": r.get("poster_url") or r.get("tmdb_poster_url") or r.get("poster_path"),
                "confidence": r.get("confidence_label") or r.get("confidence"),
            })
    print(f"[iter2-scan] rows with tmdb_id : {have_tmdb}")
    print(f"[iter2-scan] rows with poster  : {have_poster}")
    print("[iter2-scan] sample rows:")
    for s in samples:
        print("  -", s)

print(f"\n[iter2-scan] ELAPSED {time.monotonic()-t0:.1f}s — state_dir ready: {STATE_DIR}")
