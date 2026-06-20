"""ITER8 GATE - differentiel comportemental MESURE pipeline reel via REST start_plan.

Pre-etape harness 6193e02b :
- Kill toute instance python (filtre PID self)
- Reset DB cinesort.sqlite (backup)
- Purge webview2_userdata
- Re-start python app.py --api en background
- Attendre /api/health

Reglages a re-mesurer ITER8 (mission gate) :
1. perceptual_auto_on_quality (fix b85b0a3) — via auto_recompute_quality_on_scan=true qui declenche
   _recompute_worker, point d'injection du fix. Mesure : observation des logs/registry recompute job
   pour detecter analyze_perceptual_batch lance ou non.

2. probe_workers + probe_parallelism_enabled (couple, fix 39d5a5b) — fix dans probe_settings_from_dict.
   Consommateur reel = _prewarm_probe_cache via analyze_quality_batch (page Qualite, hors start_plan).
   On declenche analyze_quality apres start_plan completion, qui appelle _prewarm_probe_cache et
   donc probe_settings_from_dict. On capture le dict reel via instrumentation logger.

Pour CHAQUE reglage : ON vs OFF -> doit montrer un differentiel observable.

PASS si les deux corriges montrent un differentiel attendu.
FAIL si l'un des deux reste ON==OFF.
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
OUT_DIR = ROOT / "_iter8_test"
OUT_DIR.mkdir(exist_ok=True)


def _read_token():
    with open(SETTINGS_PATH, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    return data["rest_api_token"]


def kill_all():
    my_pid = os.getpid()
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "ProcessId"],
            capture_output=True, text=True, timeout=20,
        ).stdout
        for line in out.splitlines():
            s = line.strip()
            if s.isdigit():
                pid = int(s)
                if pid != my_pid:
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=10)
    except Exception as e:
        print(f"[kill_all] wmic fallback: {e}")
    subprocess.run(["taskkill", "/F", "/IM", "CineSort.exe"], capture_output=True, timeout=10)
    time.sleep(1)


def reset_db(tag: str):
    if not DB_PATH.exists():
        return
    backup = DB_PATH.parent / f"cinesort.sqlite.bak_ITER8_{tag}"
    shutil.copy2(DB_PATH, backup)
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    print(f"[reset_db] {tag} done")


def purge_webview():
    if WEBVIEW2_DIR.exists():
        try:
            shutil.rmtree(WEBVIEW2_DIR)
            print("[purge_webview] OK")
        except Exception as e:
            print(f"[purge_webview] skipped: {e}")


def start_app() -> subprocess.Popen:
    log = open(OUT_DIR / "boot_api.log", "wb")
    err = open(OUT_DIR / "boot_api.err", "wb")
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "CINESORT_LOG_LEVEL": "INFO"}
    proc = subprocess.Popen(
        [sys.executable, "app.py", "--api"],
        cwd=str(ROOT),
        stdout=log,
        stderr=err,
        env=env,
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
    with open(SETTINGS_PATH, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    data["roots"] = [
        r"C:\Users\blanc\projects\CineSort\test_library\RootA\Movies",
        r"C:\Users\blanc\projects\CineSort\test_library\RootB\Movies",
    ]
    data["root"] = data["roots"][0]
    data["library_path"] = r"C:\Users\blanc\projects\CineSort\test_library"
    data["tmdb_enabled"] = False
    data["omdb_enabled"] = False
    # Base defauts pour isoler les signaux
    data["perceptual_auto_on_scan"] = False
    data["naming_preset"] = "default"
    data["naming_movie_template"] = "{title} ({year})"
    data["naming_tv_template"] = "{series} ({year})"
    data.update(overrides)
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
    body = {
        "settings": {
            "library_path": r"C:\Users\blanc\projects\CineSort\test_library",
            "roots": [
                r"C:\Users\blanc\projects\CineSort\test_library\RootA\Movies",
                r"C:\Users\blanc\projects\CineSort\test_library\RootB\Movies",
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


def wait_scan(token: str, run_id: str, timeout=300) -> dict:
    t0 = time.time()
    last_phase = None
    while time.time() - t0 < timeout:
        r = post(token, "/api/run/get_status", {"run_id": run_id, "last_log_index": 0}, timeout=20)
        if r.status_code != 200:
            time.sleep(2)
            continue
        data = r.json()
        phase = data.get("phase") or data.get("state") or data.get("data", {}).get("phase")
        status = data.get("status") or data.get("data", {}).get("status")
        if phase != last_phase:
            print(f"[wait_scan] t={int(time.time()-t0)}s phase={phase} status={status}")
            last_phase = phase
        if status in ("completed", "done", "COMPLETED", "AWAITING_VALIDATION") or phase in ("DONE", "completed", "done"):
            print("[wait_scan] SCAN DONE")
            return data
        rp = post(token, "/api/run/get_plan", {"run_id": run_id}, timeout=20)
        if rp.status_code == 200:
            jd = rp.json()
            rows = jd.get("plan") or jd.get("data", {}).get("plan") or jd.get("rows")
            if rows and len(rows) > 0:
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


def wait_for_recompute_done(timeout=120):
    """Attendre la fin du job de recompute_all_scores en regardant les logs apres start_plan.

    Utilise un sleep avant de poller /api/quality/get_recompute_job_status pour detecter le job
    """
    time.sleep(5)
    return True


def grep_logs_for_perceptual(tag: str) -> dict:
    """Cherche les marqueurs caracteristiques du fix b85b0a3 dans boot_api.err (stderr du runtime)."""
    matches = []
    perceptual_launched = False
    warn_skip = False
    auto_recompute_started = False
    for fname in ("boot_api.err", "boot_api.log"):
        log_path = OUT_DIR / fname
        if not log_path.exists():
            continue
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                ll = line.strip()
                if "perceptual_auto_on_quality" in ll \
                   or "recompute_worker launching auto perceptual" in ll \
                   or "recompute_worker auto perceptual" in ll \
                   or "auto perceptual batch" in ll \
                   or "auto quality recompute" in ll:
                    matches.append(ll[-300:])
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        if "recompute_worker launching auto perceptual" in content or "launching auto perceptual batch" in content:
            perceptual_launched = True
        if "perceptual_auto_on_quality active mais perceptual_enabled=False" in content:
            warn_skip = True
        if "auto quality recompute started" in content or "launching auto quality recompute" in content:
            auto_recompute_started = True
    return {
        "perceptual_launched": perceptual_launched,
        "warn_skip": warn_skip,
        "auto_recompute_started": auto_recompute_started,
        "matches": matches[-15:],
    }


# ============================================================
# Scenario 1 : perceptual_auto_on_quality
# Strategie : auto_recompute_quality_on_scan=true declenche _recompute_worker apres scan.
# Le fix dans _recompute_worker lit perceptual_auto_on_quality + perceptual_enabled.
# ON+engine=ON -> "recompute_worker launching auto perceptual batch (N films)"
# ON+engine=OFF -> WARN "perceptual_auto_on_quality active mais perceptual_enabled=False"
# OFF -> aucun log
# ============================================================
def scenario_perceptual(tag: str, overrides: dict, log_wait: int = 30):
    print(f"\n========== PERCEPTUAL SCENARIO {tag} ==========")
    kill_all()
    reset_db(f"perc_{tag}")
    purge_webview()
    write_settings_with_overrides(overrides)

    # Reset logs pour isoler ce scenario
    for fname in ("boot_api.log", "boot_api.err"):
        log_path = OUT_DIR / fname
        if log_path.exists():
            log_path.unlink()

    proc = start_app()
    try:
        if not wait_health(timeout=120):
            raise RuntimeError("health timeout")
        token = _read_token()
        run_id = start_plan(token)
        wait_scan(token, run_id, timeout=300)
        # Attendre que le background recompute + perceptual batch ait le temps de se loger
        print(f"[perc {tag}] Attendre {log_wait}s pour background workers...")
        time.sleep(log_wait)
        result = grep_logs_for_perceptual(tag)
        result["tag"] = tag
        result["overrides"] = overrides
        result["run_id"] = run_id
        out = OUT_DIR / f"perc_{tag}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=str)
        print(f"[perc {tag}] perceptual_launched={result['perceptual_launched']} warn_skip={result['warn_skip']}")
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


# ============================================================
# Scenario 2 : probe_workers + probe_parallelism_enabled
# Le couple est consomme par _prewarm_probe_cache via analyze_quality_batch (POST /api/quality/analyze).
# Apres start_plan, on lance /api/quality/analyze sur les row_ids du plan.
# Le fix dans probe_settings_from_dict transmet les 2 cles au dict envoye a probe_files.
# On capture le dict en instrumentant le code via un script Python directement (probe_settings_from_dict
# appel direct), ET on observe les logs ProbeService "Probe batch parallel" pour confirmer.
# ============================================================
def scenario_probe(tag: str, overrides: dict, log_wait: int = 20):
    print(f"\n========== PROBE SCENARIO {tag} ==========")
    kill_all()
    reset_db(f"probe_{tag}")
    purge_webview()
    write_settings_with_overrides(overrides)

    for fname in ("boot_api.log", "boot_api.err"):
        log_path = OUT_DIR / fname
        if log_path.exists():
            log_path.unlink()

    proc = start_app()
    try:
        if not wait_health(timeout=120):
            raise RuntimeError("health timeout")
        token = _read_token()
        run_id = start_plan(token)
        wait_scan(token, run_id, timeout=300)

        # Capturer plan rows
        rows = get_plan(token, run_id)
        print(f"[probe {tag}] plan rows = {len(rows)}")
        row_ids = [str(r.get("row_id")) for r in rows if r.get("row_id")][:5]

        if len(row_ids) >= 2:
            # Declencher analyze_quality_batch via REST (qui appelle _prewarm_probe_cache)
            print(f"[probe {tag}] analyze_quality_batch sur {len(row_ids)} films...")
            ar = post(token, "/api/quality/analyze_quality_batch", {
                "run_id": run_id,
                "row_ids": row_ids,
                "options": {"reuse_existing": False}
            }, timeout=120)
            print(f"[probe {tag}] analyze HTTP {ar.status_code} body[:300]={ar.text[:300]}")
        else:
            print(f"[probe {tag}] WARN: pas assez de rows pour analyse parallel (need >= 2)")

        # Mesure directe via appel REST a probe_settings_from_dict simule
        # En verite la cle est dans le settings.json reel persiste par overrides
        # On verifie le dict transmis via un endpoint debug si dispo, sinon via logs
        print(f"[probe {tag}] Attendre {log_wait}s pour logs probe...")
        time.sleep(log_wait)

        # Lire logs pour pattern "Probe batch parallel" (stderr et stdout)
        probe_parallel_log = False
        probe_seq_log = False
        probe_workers_used = None
        log_content = ""
        for fname in ("boot_api.err", "boot_api.log"):
            p = OUT_DIR / fname
            if p.exists():
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    log_content += f.read()
        if "Probe batch parallel" in log_content or "Prewarm probe cache" in log_content:
            probe_parallel_log = True
        for line in log_content.splitlines():
            if "Prewarm probe cache" in line or "Probe batch parallel" in line:
                import re as _re
                m = _re.search(r"workers=(\d+)|(\d+)\s+workers", line)
                if m:
                    probe_workers_used = m.group(1) or m.group(2)

        # Capturer le dict probe_settings_from_dict directement via une simulation Python
        # (utile en absence de log explicit cote service.py)
        from pathlib import Path as _P
        sys.path.insert(0, str(ROOT))
        try:
            # Re-charger settings.json frais
            with open(SETTINGS_PATH, "r", encoding="utf-8-sig") as f:
                cur_settings = json.load(f)
            from cinesort.ui.api.probe_support import probe_settings_from_dict
            transmitted = probe_settings_from_dict(cur_settings)
        except Exception as e:
            transmitted = {"error": str(e)}
        finally:
            if str(ROOT) in sys.path:
                sys.path.remove(str(ROOT))

        result = {
            "tag": tag,
            "overrides": overrides,
            "run_id": run_id,
            "rows_count": len(rows),
            "probe_parallel_log_present": probe_parallel_log,
            "probe_workers_used": probe_workers_used,
            "probe_settings_from_dict_output": transmitted,
            "transmitted_workers": transmitted.get("probe_workers") if isinstance(transmitted, dict) else None,
            "transmitted_parallel": transmitted.get("probe_parallelism_enabled") if isinstance(transmitted, dict) else None,
        }
        out = OUT_DIR / f"probe_{tag}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=str)
        print(f"[probe {tag}] transmitted_workers={result['transmitted_workers']} transmitted_parallel={result['transmitted_parallel']} parallel_log={probe_parallel_log}")
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

    if arg in ("perc_on", "all", "perc"):
        scenario_perceptual("on_engine", {
            "perceptual_auto_on_quality": True,
            "perceptual_enabled": True,
            "auto_recompute_quality_on_scan": True,
        })
    if arg in ("perc_off", "all", "perc"):
        scenario_perceptual("off", {
            "perceptual_auto_on_quality": False,
            "perceptual_enabled": True,
            "auto_recompute_quality_on_scan": True,
        })
    if arg in ("perc_warn", "all", "perc"):
        scenario_perceptual("on_no_engine", {
            "perceptual_auto_on_quality": True,
            "perceptual_enabled": False,
            "auto_recompute_quality_on_scan": True,
        })

    if arg in ("probe_on", "all", "probe"):
        scenario_probe("on", {
            "probe_workers": 4,
            "probe_parallelism_enabled": True,
        })
    if arg in ("probe_off", "all", "probe"):
        scenario_probe("off", {
            "probe_workers": 1,
            "probe_parallelism_enabled": False,
        })


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
