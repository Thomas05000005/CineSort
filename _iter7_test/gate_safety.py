"""GATE Safety global ITER7 (post 2 fixes lowercase_extensions + separator).

Mission:
1. Pre-etape harness 6193e02b (kill all, reset DB, purge webview, reset settings)
2. Dry-run side-effect-free : manifeste FS AVANT + apply dry_run + manifeste APRES == identique
3. Smoke apply REEL + undo atomique sur test_library
4. Verify templates custom existants produisent meme sortie qu'avant (re-test)

Une casse = STOP REMONTER (verdict NON SAFE => bilan WIP).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

import requests

ROOT = Path(r"C:\Users\blanc\projects\CineSort")
STATE_DIR = Path(r"C:\Users\blanc\AppData\Local\CineSort")
DB_PATH = STATE_DIR / "db" / "cinesort.sqlite"
SETTINGS_PATH = STATE_DIR / "settings.json"
WEBVIEW2_DIR = STATE_DIR / "webview"
API_BASE = "http://127.0.0.1:8642"
TEST_LIB = ROOT / "test_library"
OUT_DIR = ROOT / "_iter7_test"


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
    backup = DB_PATH.parent / f"cinesort.sqlite.bak_ITER7_safety_{tag}"
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


def start_app():
    log = open(OUT_DIR / "safety_api.log", "wb")
    err = open(OUT_DIR / "safety_api.err", "wb")
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
    with open(SETTINGS_PATH, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    data["roots"] = [
        str(TEST_LIB / "RootA" / "Movies"),
        str(TEST_LIB / "RootB" / "Movies"),
        str(TEST_LIB / "RootB" / "Shows"),
    ]
    data["root"] = data["roots"][0]
    data["library_path"] = str(TEST_LIB)
    data["tmdb_enabled"] = False
    data["omdb_enabled"] = False
    data["perceptual_enabled"] = False
    data["perceptual_auto_on_scan"] = False
    data["perceptual_auto_on_quality"] = False
    data["auto_recompute_quality_on_scan"] = False
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


def manifest_fs(root: Path) -> dict:
    """Manifeste FS recursif : pour chaque fichier, (rel_path, size, sha1_first1k).
    Pour les dossiers, (rel_path, "DIR").
    Sortie deterministe triee par rel_path.
    """
    entries = []
    for p in sorted(root.rglob("*")):
        try:
            rel = str(p.relative_to(root))
        except ValueError:
            continue
        if p.is_dir():
            entries.append((rel, "DIR", 0, ""))
        elif p.is_file():
            try:
                size = p.stat().st_size
                h = hashlib.sha1()
                with open(p, "rb") as f:
                    h.update(f.read(1024))
                entries.append((rel, "FILE", size, h.hexdigest()[:12]))
            except Exception as e:
                entries.append((rel, f"ERR:{e}", 0, ""))
    return {
        "root": str(root),
        "count": len(entries),
        "entries": entries,
    }


def manifest_hash(m: dict) -> str:
    """Hash deterministe du manifeste pour comparaison rapide."""
    payload = json.dumps(m["entries"], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def start_plan(token: str) -> str:
    body = {
        "settings": {
            "library_path": str(TEST_LIB),
            "roots": [
                str(TEST_LIB / "RootA" / "Movies"),
                str(TEST_LIB / "RootB" / "Movies"),
                str(TEST_LIB / "RootB" / "Shows"),
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


def read_plan_jsonl(run_id: str) -> list:
    runs_dir = STATE_DIR / "runs"
    cand = list(runs_dir.glob(f"{run_id}/plan.jsonl"))
    if not cand:
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


def build_decisions(plan_rows: list) -> dict:
    decisions = {}
    for row in plan_rows:
        row_id = row.get("row_id")
        if not row_id:
            continue
        decisions[row_id] = {
            "ok": True,
            "title": row.get("proposed_title"),
            "year": row.get("proposed_year"),
            "decision": "accepted",
        }
    return decisions


def apply_call(token: str, run_id: str, decisions: dict, dry_run: bool, apply_atomic: bool = True) -> dict:
    body = {
        "run_id": run_id,
        "decisions": decisions,
        "dry_run": dry_run,
        "quarantine_unapproved": False,
        "apply_atomic": apply_atomic,
    }
    r = post(token, "/api/run/apply", body, timeout=300)
    print(f"[apply dry_run={dry_run} atomic={apply_atomic}] HTTP {r.status_code} body[:300]={r.text[:300]}")
    return r.json()


def undo_call(token: str, run_id: str, dry_run: bool, atomic: bool = True) -> dict:
    body = {"run_id": run_id, "dry_run": dry_run, "atomic": atomic}
    r = post(token, "/api/run/undo_last_apply", body, timeout=300)
    print(f"[undo dry_run={dry_run} atomic={atomic}] HTTP {r.status_code} body[:300]={r.text[:300]}")
    return r.json()


# =========================
# GATE 1 : dry_run side-effect-free
# =========================
def gate_dry_run_side_effect_free(token: str) -> dict:
    print("\n========== GATE 1 : dry_run side-effect-free ==========")
    # Manifeste FS AVANT
    print("[gate1] manifest BEFORE...")
    m_before = manifest_fs(TEST_LIB)
    h_before = manifest_hash(m_before)
    print(f"[gate1] manifest BEFORE : {m_before['count']} entries, hash={h_before[:16]}")

    # Lancer plan + dry_run apply
    run_id = start_plan(token)
    wait_scan(token, run_id, timeout=300)
    plan_rows = read_plan_jsonl(run_id)
    decisions = build_decisions(plan_rows)
    print(f"[gate1] plan_rows={len(plan_rows)} decisions={len(decisions)}")

    dry_result = apply_call(token, run_id, decisions, dry_run=True, apply_atomic=True)

    # Manifeste FS APRES
    print("[gate1] manifest AFTER dry_run...")
    m_after = manifest_fs(TEST_LIB)
    h_after = manifest_hash(m_after)
    print(f"[gate1] manifest AFTER  : {m_after['count']} entries, hash={h_after[:16]}")

    identical = (h_before == h_after)
    diffs = []
    if not identical:
        before_set = {e[0]: e for e in m_before["entries"]}
        after_set = {e[0]: e for e in m_after["entries"]}
        added = sorted(set(after_set) - set(before_set))
        removed = sorted(set(before_set) - set(after_set))
        changed = []
        for k in set(before_set) & set(after_set):
            if before_set[k] != after_set[k]:
                changed.append((k, before_set[k], after_set[k]))
        diffs = {"added": added[:20], "removed": removed[:20], "changed": changed[:20]}

    return {
        "gate": "dry_run_side_effect_free",
        "run_id": run_id,
        "plan_rows_count": len(plan_rows),
        "decisions_count": len(decisions),
        "manifest_before_count": m_before["count"],
        "manifest_after_count": m_after["count"],
        "hash_before": h_before,
        "hash_after": h_after,
        "identical": identical,
        "dry_result_ok": dry_result.get("ok", False),
        "diffs": diffs,
        "verdict": "PASS" if identical else "FAIL",
    }


# =========================
# GATE 2 : smoke apply reel + undo atomique
# =========================
def gate_smoke_apply_undo(token: str) -> dict:
    print("\n========== GATE 2 : smoke apply REEL + undo atomique ==========")
    # Manifeste avant apply reel
    print("[gate2] manifest BEFORE apply reel...")
    m_before = manifest_fs(TEST_LIB)
    h_before = manifest_hash(m_before)
    print(f"[gate2] manifest BEFORE : {m_before['count']} entries, hash={h_before[:16]}")

    # Run plan
    run_id = start_plan(token)
    wait_scan(token, run_id, timeout=300)
    plan_rows = read_plan_jsonl(run_id)
    decisions = build_decisions(plan_rows)
    print(f"[gate2] plan_rows={len(plan_rows)} decisions={len(decisions)}")

    # APPLY REEL (dry_run=False, apply_atomic=True)
    apply_result = apply_call(token, run_id, decisions, dry_run=False, apply_atomic=True)
    apply_ok = apply_result.get("ok", False)

    # Manifeste apres apply reel (different attendu)
    print("[gate2] manifest AFTER apply reel...")
    m_after_apply = manifest_fs(TEST_LIB)
    h_after_apply = manifest_hash(m_after_apply)
    print(f"[gate2] manifest AFTER apply : {m_after_apply['count']} entries, hash={h_after_apply[:16]}")
    changed_after_apply = (h_before != h_after_apply)

    # UNDO atomique reel
    undo_result = undo_call(token, run_id, dry_run=False, atomic=True)
    undo_ok = undo_result.get("ok", False)

    # Manifeste apres undo - doit revenir a l'etat AVANT
    print("[gate2] manifest AFTER undo...")
    m_after_undo = manifest_fs(TEST_LIB)
    h_after_undo = manifest_hash(m_after_undo)
    print(f"[gate2] manifest AFTER undo  : {m_after_undo['count']} entries, hash={h_after_undo[:16]}")
    undo_restores = (h_before == h_after_undo)

    # Diffs si pas restaure
    diffs = {}
    if not undo_restores:
        before_set = {e[0]: e for e in m_before["entries"]}
        after_set = {e[0]: e for e in m_after_undo["entries"]}
        added = sorted(set(after_set) - set(before_set))
        removed = sorted(set(before_set) - set(after_set))
        changed = []
        for k in set(before_set) & set(after_set):
            if before_set[k] != after_set[k]:
                changed.append((k, before_set[k], after_set[k]))
        diffs = {"added": added[:20], "removed": removed[:20], "changed": changed[:20]}

    verdict = "PASS" if (apply_ok and changed_after_apply and undo_ok and undo_restores) else "FAIL"
    return {
        "gate": "smoke_apply_reel_undo_atomic",
        "run_id": run_id,
        "plan_rows_count": len(plan_rows),
        "decisions_count": len(decisions),
        "hash_before": h_before,
        "hash_after_apply": h_after_apply,
        "hash_after_undo": h_after_undo,
        "apply_ok": apply_ok,
        "apply_changed_fs": changed_after_apply,
        "undo_ok": undo_ok,
        "undo_restores_fs": undo_restores,
        "diffs": diffs,
        "verdict": verdict,
    }


# =========================
# GATE 4 : Verify templates custom inchanges
# =========================
def gate_templates_custom_inchanges() -> dict:
    """Re-test des templates custom existants - mesure runtime directe.
    On verifie que format_movie_folder(tpl, ctx) avec sep variable
    produit la MEME sortie pour les templates qui n'embarquent pas {sep}.
    """
    print("\n========== GATE 4 : templates custom inchanges ==========")
    # Importer cinesort
    sys.path.insert(0, str(ROOT))
    try:
        from cinesort.domain.naming import build_naming_context, format_movie_folder
    except Exception as e:
        return {"gate": "templates_custom_inchanges", "verdict": "FAIL", "error": f"import error: {e}"}

    # Templates a verifier (custom existants typiques)
    templates = [
        "{title} ({year})",        # default
        "{title}_{year}",          # custom underscore embedded
        "{title}.{year}",          # custom dot embedded
        "{title}-{year}",          # custom dash embedded
        "{title} ({year}) {tmdb_tag}",  # plex preset
    ]
    sep_values = ["_", " ", ".", "-"]

    results = []
    all_invariant = True
    for tpl in templates:
        outs = []
        for sep in sep_values:
            ctx = build_naming_context(title="Inception", year=2010, separator=sep, tmdb_id=27205)
            out = format_movie_folder(tpl, ctx)
            outs.append({"sep": sep, "out": out})
        distinct = {o["out"] for o in outs}
        invariant = (len(distinct) == 1)
        if not invariant:
            all_invariant = False
        results.append({
            "template": tpl,
            "outputs": outs,
            "distinct_count": len(distinct),
            "invariant": invariant,
        })

    # Verifier que le mecanisme opt-in {sep} reagit (anti-regression du fix)
    opt_in_outs = []
    for sep in sep_values:
        ctx = build_naming_context(title="Inception", year=2010, separator=sep)
        out = format_movie_folder("{title}{sep}{year}", ctx)
        opt_in_outs.append({"sep": sep, "out": out})
    opt_in_distinct = len({o["out"] for o in opt_in_outs})
    opt_in_reacts = (opt_in_distinct == 4)

    verdict = "PASS" if (all_invariant and opt_in_reacts) else "FAIL"
    return {
        "gate": "templates_custom_inchanges",
        "templates_results": results,
        "all_invariant": all_invariant,
        "opt_in_template": "{title}{sep}{year}",
        "opt_in_outputs": opt_in_outs,
        "opt_in_distinct_count": opt_in_distinct,
        "opt_in_reacts": opt_in_reacts,
        "verdict": verdict,
    }


def run_pre_etape_harness(tag: str):
    """Pre-etape harness 6193e02b reapppliquee."""
    print(f"\n[harness 6193e02b] tag={tag}")
    kill_all()
    reset_db(tag)
    purge_webview()


def main():
    OUT_DIR.mkdir(exist_ok=True)
    results = {"started_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    # ETAPE 1 : Pre-etape harness initial + GATE 1 (dry_run side-effect-free)
    print("\n" + "=" * 60)
    print("STEP 1: pre-etape harness + GATE 1 dry_run side-effect-free")
    print("=" * 60)
    run_pre_etape_harness("gate1")
    write_settings_with_overrides({
        "lowercase_extensions": True,
        "separator": " ",
    })
    proc = start_app()
    try:
        if not wait_health(timeout=120):
            raise RuntimeError("health timeout gate1")
        token = _read_token()
        results["gate1_dry_run_side_effect_free"] = gate_dry_run_side_effect_free(token)
    except Exception as e:
        results["gate1_dry_run_side_effect_free"] = {
            "gate": "dry_run_side_effect_free", "verdict": "ERROR",
            "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc(),
        }
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

    # Sauvegarde intermediaire (anti-interruption)
    out_path = OUT_DIR / "result_gate_safety.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n[checkpoint] partial results -> {out_path}")

    # STOP REMONTER si GATE 1 a casse
    gate1 = results.get("gate1_dry_run_side_effect_free", {})
    if gate1.get("verdict") not in ("PASS",):
        print(f"[STOP REMONTER] GATE 1 verdict={gate1.get('verdict')}, arret immediat")
        return results

    # ETAPE 2 : GATE 2 (smoke apply reel + undo atomique)
    print("\n" + "=" * 60)
    print("STEP 2: pre-etape harness + GATE 2 smoke apply reel + undo")
    print("=" * 60)
    run_pre_etape_harness("gate2")
    write_settings_with_overrides({
        "lowercase_extensions": True,
        "separator": " ",
    })
    proc = start_app()
    try:
        if not wait_health(timeout=120):
            raise RuntimeError("health timeout gate2")
        token = _read_token()
        results["gate2_smoke_apply_undo"] = gate_smoke_apply_undo(token)
    except Exception as e:
        results["gate2_smoke_apply_undo"] = {
            "gate": "smoke_apply_reel_undo_atomic", "verdict": "ERROR",
            "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc(),
        }
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

    # Sauvegarde intermediaire
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n[checkpoint] partial results -> {out_path}")

    # STOP REMONTER si GATE 2 a casse
    gate2 = results.get("gate2_smoke_apply_undo", {})
    if gate2.get("verdict") not in ("PASS",):
        print(f"[STOP REMONTER] GATE 2 verdict={gate2.get('verdict')}, arret immediat")
        return results

    # ETAPE 3 : GATE 4 (templates custom inchanges - runtime direct, pas besoin EXE)
    print("\n" + "=" * 60)
    print("STEP 3: GATE 4 templates custom inchanges (runtime direct)")
    print("=" * 60)
    results["gate4_templates_custom_inchanges"] = gate_templates_custom_inchanges()

    # Final save
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n[final] results -> {out_path}")

    # Verdict global
    verdicts = {
        "gate1": results.get("gate1_dry_run_side_effect_free", {}).get("verdict", "?"),
        "gate2": results.get("gate2_smoke_apply_undo", {}).get("verdict", "?"),
        "gate4": results.get("gate4_templates_custom_inchanges", {}).get("verdict", "?"),
    }
    print(f"\n=========== VERDICTS ===========")
    for k, v in verdicts.items():
        print(f"  {k}: {v}")
    return results


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException as e:
        print(f"FATAL: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        sys.exit(2)
