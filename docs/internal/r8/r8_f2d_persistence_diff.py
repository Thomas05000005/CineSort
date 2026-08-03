"""R8 F2-d — DIFFERENTIEL persistance (R8-025 busy_timeout NAS, R8-026 atomic_write retry).

S-025 : un store profil NAS (busy_timeout 30000) avec busy_timeout_ms=5000 (nouveau defaut prod)
        PRESERVE le 30000 du profil ; avec 8000 (ancien prod) il etait ECRASE a 8000.
S-026 : atomic_write_json RE-TENTE os.replace sur PermissionError (Windows lecteur concurrent)
        au lieu de PERDRE le write ; borne (re-leve apres epuisement).

(R8-024 prouve par c3e_cron ; R8-019..022 par r8_f2d_selfheal_diff.)

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f2d_persistence_diff.py
"""

from __future__ import annotations

import json
import shutil
import tempfile
from contextlib import closing
from pathlib import Path

import cinesort.infra.state as state_mod
from cinesort.infra.db.sqlite_store import SQLiteStore


def _busy_timeout(db_path: Path, busy_ms: int) -> int:
    st = SQLiteStore(db_path, busy_timeout_ms=busy_ms, pragma_profile_name="nas_smb")
    st.initialize()
    with closing(st._connect()) as conn:
        return int(conn.execute("PRAGMA busy_timeout").fetchone()[0])


def run():
    results = {}

    # ---- S-025 : profil NAS preserve avec 5000, ecrase avec 8000 ----
    tmp = Path(tempfile.mkdtemp(prefix="cs_f2d_bt_"))
    bt_new_prod = _busy_timeout(tmp / "new.sqlite", 5000)  # nouveau defaut prod
    bt_old_prod = _busy_timeout(tmp / "old.sqlite", 8000)  # ancien prod (le bug)
    s025 = bt_new_prod == 30000 and bt_old_prod == 8000
    results["S025_profil_nas_preserve_avec_5000"] = s025
    print("=== S-025 (busy_timeout profil NAS) ===")
    print(f"  busy_timeout avec 5000 (NOUVEAU prod) : {bt_new_prod} (attendu 30000 = profil NAS preserve)")
    print(f"  busy_timeout avec 8000 (ANCIEN prod)  : {bt_old_prod} (le bug : profil ecrase a 8000)")
    shutil.rmtree(tmp, ignore_errors=True)

    # ---- S-026 : atomic_write_json retry sur PermissionError ----
    tmp2 = Path(tempfile.mkdtemp(prefix="cs_f2d_aw_"))
    target = tmp2 / "state.json"
    orig_replace = state_mod.os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst, _fail=2):
        calls["n"] += 1
        if calls["n"] <= _fail:
            raise PermissionError(f"[simule] WinError 32 lecteur concurrent (call {calls['n']})")
        return orig_replace(src, dst)

    state_mod.os.replace = flaky_replace
    raised = None
    try:
        state_mod.atomic_write_json(target, {"k": "v", "n": 42})
    except PermissionError as e:
        raised = str(e)
    finally:
        state_mod.os.replace = orig_replace

    wrote_ok = target.exists() and json.loads(target.read_text(encoding="utf-8")).get("n") == 42
    s026_retry = raised is None and wrote_ok and calls["n"] == 3  # 2 echecs + 1 succes
    results["S026_atomic_write_retry"] = s026_retry
    print("\n=== S-026 (atomic_write_json retry os.replace) ===")
    print(f"  os.replace appele {calls['n']}x (2 PermissionError + 1 OK) ; exception finale : {raised!r}")
    print(f"  write reussi (n=42)  : {wrote_ok} (AVANT le fix : 1er PermissionError -> write PERDU)")

    # Controle borne : 6 echecs -> re-leve (pas de boucle infinie)
    target2 = tmp2 / "state2.json"
    calls2 = {"n": 0}

    def always_fail(src, dst):
        calls2["n"] += 1
        raise PermissionError("[simule] toujours verrouille")

    state_mod.os.replace = always_fail
    raised2 = None
    try:
        state_mod.atomic_write_json(target2, {"k": "v"})
    except PermissionError as e:
        raised2 = str(e)
    finally:
        state_mod.os.replace = orig_replace
    s026_bounded = raised2 is not None and calls2["n"] == 5  # 5 tentatives puis re-leve
    results["S026_borne_5_tentatives"] = s026_bounded
    print(f"  controle borne : {calls2['n']} tentatives puis re-leve={raised2 is not None} (attendu 5 + re-leve)")
    shutil.rmtree(tmp2, ignore_errors=True)

    allok = all(results.values())
    print(f"\nVERDICT : {'CORRIGE (busy_timeout NAS preserve + atomic_write resilient)' if allok else 'INCOMPLET'}")
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
