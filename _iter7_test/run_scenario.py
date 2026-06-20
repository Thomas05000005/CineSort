"""ITER7 section 2 - differentiel mesure lowercase_extensions + separator.

Pre-etape (harness 6193e02b) :
- Kill toute instance python
- Reset DB cinesort.sqlite (backup)
- Purge webview2_userdata
- Re-start python app.py --api en background
- Attendre /api/health

Pour chaque scenario:
- ON: settings.lowercase_extensions=true (resp. separator='_')
- OFF: settings.lowercase_extensions=false (resp. separator=' ')
- start_plan via REST {settings: {...minimal...}}
- attendre status COMPLETED
- build_apply_preview -> capturer dst extensions / dst noms
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(r"C:\Users\blanc\projects\CineSort")
STATE_DIR = Path(r"C:\Users\blanc\AppData\Local\CineSort")
DB_PATH = STATE_DIR / "db" / "cinesort.sqlite"
SETTINGS_PATH = STATE_DIR / "settings.json"
WEBVIEW2_DIR = STATE_DIR / "webview"
API_BASE = "http://127.0.0.1:8642"


def _read_token():
    # utf-8-sig pour tolerer BOM PowerShell (memoire CineSort settings UTF-8 BOM)
    with open(SETTINGS_PATH, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    return data["rest_api_token"]


def kill_all():
    # Kill SEULEMENT les python.exe qui ne sont pas le processus courant
    # (sinon on se suicide pendant la pre-etape harness)
    my_pid = os.getpid()
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "ProcessId"],
            capture_output=True, text=True, timeout=20,
        ).stdout
        pids = []
        for line in out.splitlines():
            s = line.strip()
            if s.isdigit():
                pid = int(s)
                if pid != my_pid:
                    pids.append(pid)
        for pid in pids:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=10)
    except Exception as e:
        print(f"[kill_all] wmic fallback: {e}")
    subprocess.run(["taskkill", "/F", "/IM", "CineSort.exe"], capture_output=True, timeout=10)
    time.sleep(1)


def reset_db(tag: str):
    if not DB_PATH.exists():
        return
    backup = DB_PATH.parent / f"cinesort.sqlite.bak_ITER7_{tag}"
    shutil.copy2(DB_PATH, backup)
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    print(f"[reset_db] {tag} done, backup -> {backup.name}")


def purge_webview():
    if WEBVIEW2_DIR.exists():
        try:
            shutil.rmtree(WEBVIEW2_DIR)
            print("[purge_webview] OK")
        except Exception as e:
            print(f"[purge_webview] skipped: {e}")


def start_app() -> subprocess.Popen:
    log = open(ROOT / "_iter7_test" / "boot_api.log", "wb")
    err = open(ROOT / "_iter7_test" / "boot_api.err", "wb")
    proc = subprocess.Popen(
        [sys.executable, "app.py", "--api"],
        cwd=str(ROOT),
        stdout=log,
        stderr=err,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    return proc


def wait_health(timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(f"{API_BASE}/api/health", timeout=2)
            if r.status_code == 200:
                print("[health] UP")
                return True
        except Exception:
            pass
        time.sleep(1)
    print("[health] TIMEOUT")
    return False


def write_settings_with_overrides(overrides: dict):
    """Modifie SETTINGS_PATH avec overrides. Restaure les roots minimal test_library only."""
    with open(SETTINGS_PATH, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    # Limiter aux 2 roots test_library (eviter SMB lent et offline)
    data["roots"] = [
        r"C:\Users\blanc\projects\CineSort\test_library\RootA\Movies",
        r"C:\Users\blanc\projects\CineSort\test_library\RootB\Movies",
        r"C:\Users\blanc\projects\CineSort\test_library\RootB\Shows",
    ]
    data["root"] = data["roots"][0]
    data["library_path"] = r"C:\Users\blanc\projects\CineSort\test_library"
    data["tmdb_enabled"] = False  # eviter lenteur reseau + flakiness
    data["omdb_enabled"] = False
    data["perceptual_enabled"] = False
    data["perceptual_auto_on_scan"] = False
    data["perceptual_auto_on_quality"] = False
    data["auto_recompute_quality_on_scan"] = False
    data["naming_preset"] = "default"
    data["naming_movie_template"] = "{title} ({year})"
    data["naming_tv_template"] = "{series} ({year})"
    data.update(overrides)
    # Reecrire sans BOM (json.dump)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[settings] overrides applied: {overrides}")


def post(token: str, path: str, body: dict, timeout=180):
    return requests.post(
        f"{API_BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )


def start_plan(token: str) -> str:
    # Settings wrapper minimal : library_path + roots, le reste hydrate depuis settings.json
    body = {
        "settings": {
            "library_path": r"C:\Users\blanc\projects\CineSort\test_library",
            "roots": [
                r"C:\Users\blanc\projects\CineSort\test_library\RootA\Movies",
                r"C:\Users\blanc\projects\CineSort\test_library\RootB\Movies",
                r"C:\Users\blanc\projects\CineSort\test_library\RootB\Shows",
            ],
        }
    }
    r = post(token, "/api/run/start_plan", body, timeout=60)
    print(f"[start_plan] HTTP {r.status_code} body[:200]={r.text[:200]}")
    r.raise_for_status()
    data = r.json()
    run_id = data.get("run_id") or data.get("data", {}).get("run_id")
    if not run_id:
        raise RuntimeError(f"no run_id: {data}")
    print(f"[start_plan] run_id={run_id}")
    return run_id


def wait_scan(token: str, run_id: str, timeout=240) -> dict:
    t0 = time.time()
    last_phase = None
    while time.time() - t0 < timeout:
        r = post(token, "/api/run/get_status", {"run_id": run_id, "last_log_index": 0}, timeout=20)
        if r.status_code != 200:
            time.sleep(2)
            continue
        data = r.json()
        # Tentatives multiples pour trouver le phase/status (shape variable)
        phase = data.get("phase") or data.get("state") or data.get("data", {}).get("phase")
        status = data.get("status") or data.get("data", {}).get("status")
        if phase != last_phase:
            print(f"[wait_scan] t={int(time.time()-t0)}s phase={phase} status={status}")
            last_phase = phase
        if status in ("completed", "done", "COMPLETED", "AWAITING_VALIDATION") or phase in ("DONE", "completed", "done"):
            print("[wait_scan] SCAN DONE")
            return data
        # Fallback: si get_plan retourne des rows, c'est fini
        rp = post(token, "/api/run/get_plan", {"run_id": run_id}, timeout=20)
        if rp.status_code == 200:
            jd = rp.json()
            rows = jd.get("plan") or jd.get("data", {}).get("plan") or jd.get("rows")
            if rows and len(rows) > 0:
                # double check no scan en cours
                time.sleep(3)
                rp2 = post(token, "/api/run/get_plan", {"run_id": run_id}, timeout=20)
                jd2 = rp2.json()
                rows2 = jd2.get("plan") or jd2.get("data", {}).get("plan") or jd2.get("rows")
                if rows2 and len(rows2) == len(rows):
                    print(f"[wait_scan] plan stable @{len(rows)} rows")
                    return data
        time.sleep(2)
    raise TimeoutError("scan did not complete")


def get_plan(token: str, run_id: str) -> list:
    r = post(token, "/api/run/get_plan", {"run_id": run_id}, timeout=30)
    data = r.json()
    rows = data.get("plan") or data.get("data", {}).get("plan") or data.get("rows") or []
    return rows


def build_preview(token: str, run_id: str, rows: list) -> dict:
    # Decisions : approuver toutes les single rows
    decisions = {}
    for row in rows:
        row_id = row.get("row_id")
        if not row_id:
            continue
        # Shape attendue par normalize_decisions_for_rows : {ok, title, year}
        decisions[row_id] = {
            "ok": True,
            "title": row.get("proposed_title"),
            "year": row.get("proposed_year"),
            "decision": "accepted",
        }
    body = {"run_id": run_id, "decisions": decisions}
    r = post(token, "/api/run/build_apply_preview", body, timeout=120)
    print(f"[build_preview] HTTP {r.status_code} sample={r.text[:300]}")
    return r.json()


def read_plan_jsonl(run_id: str) -> list:
    runs_dir = STATE_DIR / "runs"
    cand = list(runs_dir.glob(f"{run_id}/plan.jsonl"))
    if not cand:
        # essayer par creation time
        all_runs = sorted(runs_dir.glob("tri_films_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if all_runs:
            cand = [all_runs[0] / "plan.jsonl"]
    if not cand or not cand[0].exists():
        return []
    rows = []
    with open(cand[0], "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def scenario(tag: str, overrides: dict):
    print(f"\n========== SCENARIO {tag} ==========")
    kill_all()
    reset_db(tag)
    purge_webview()
    write_settings_with_overrides(overrides)
    proc = start_app()
    try:
        if not wait_health(timeout=120):
            raise RuntimeError("health timeout")
        token = _read_token()
        run_id = start_plan(token)
        wait_scan(token, run_id, timeout=300)
        plan_rows = read_plan_jsonl(run_id)
        preview = build_preview(token, run_id, plan_rows)
        result = {
            "tag": tag,
            "overrides": overrides,
            "run_id": run_id,
            "plan_rows_count": len(plan_rows),
            "plan_rows": plan_rows,
            "preview": preview,
        }
        out = ROOT / "_iter7_test" / f"result_{tag}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=str)
        print(f"[scenario {tag}] OK -> {out}")
        return result
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        kill_all()


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    if arg == "lower_on":
        scenario("lower_on", {"lowercase_extensions": True, "separator": " "})
    elif arg == "lower_off":
        scenario("lower_off", {"lowercase_extensions": False, "separator": " "})
    elif arg == "sep_under":
        scenario("sep_under", {"lowercase_extensions": True, "separator": "_"})
    elif arg == "sep_space":
        scenario("sep_space", {"lowercase_extensions": True, "separator": " "})
    else:
        scenario("lower_on", {"lowercase_extensions": True, "separator": " "})
        scenario("lower_off", {"lowercase_extensions": False, "separator": " "})
        scenario("sep_under", {"lowercase_extensions": True, "separator": "_"})
        scenario("sep_space", {"lowercase_extensions": True, "separator": " "})


if __name__ == "__main__":
    import traceback
    try:
        main()
    except SystemExit:
        raise
    except BaseException as e:
        print(f"FATAL: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        sys.exit(2)
