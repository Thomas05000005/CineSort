"""Smoke test parallel : verifie qu'avec workers>1, le code-path VO-B s'active."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["CINESORT_E2E"] = "1"

# Capture logs cinesort.* dans un buffer.
buf = StringIO()
h = logging.StreamHandler(buf)
h.setLevel(logging.INFO)
h.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
logging.getLogger("cinesort").addHandler(h)
logging.getLogger("cinesort").setLevel(logging.INFO)

import cinesort.domain.core as _core  # noqa: E402
from cinesort.ui.api.cinesort_api import CineSortApi  # noqa: E402

_core.MIN_VIDEO_BYTES = 1024

LIB_ROOT = r"C:\Users\blanc\test_cinesort_lib"
STATE_DIR = Path(tempfile.gettempdir()) / "cinesort_smoketest_state_par"
STATE_DIR.mkdir(parents=True, exist_ok=True)

api = CineSortApi()

settings = {
    "root": LIB_ROOT,
    "roots": [LIB_ROOT],
    "state_dir": str(STATE_DIR),
    "tmdb_enabled": False,
    "omdb_enabled": False,
    "probe_backend": "auto",
    "perceptual_enabled": False,
    "perceptual_auto_on_scan": False,
    "auto_recompute_quality_on_scan": False,
    "incremental_scan_enabled": False,
    "scan_max_workers_mode": "manual",
    "scan_max_workers_value": 8,  # force parallel
    "probe_parallelism_enabled": True,
    "subtitle_detection_enabled": False,
    "dry_run_apply": True,
    "debug_enabled": False,
    "log_level": "INFO",
}

t0 = time.monotonic()
resp = api.run.start_plan(settings)
print(f"start_plan -> ok={resp.get('ok')} run_id={resp.get('run_id')}")
run_id = resp["run_id"]
last_idx = 0
while True:
    status = api.run.get_status(run_id, last_idx)
    last_idx = status.get("next_log_index", last_idx)
    if status.get("done"):
        break
    time.sleep(0.5)
elapsed = time.monotonic() - t0
print(f"DONE in {elapsed:.2f}s status={status.get('status')}")

# Vault dashboard
dash = api.run.get_dashboard(run_id)
print(f"KPIs total_movies={dash.get('kpis', {}).get('total_movies')}")

# Log search
log_text = buf.getvalue()
print("---")
print("VO-B markers:")
for line in log_text.splitlines():
    if "VO-B" in line or "parallele" in line or "parallel" in line:
        print(f"  {line}")
