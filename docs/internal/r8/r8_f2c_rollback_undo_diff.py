"""R8 F2-c — DIFFERENTIELS rollback/undo/statuts. Fixtures jetables (SQLiteStore tempdir + FS).

S-012 (RB1) : rollback_forward marque desormais apply_operations.undo_status='DONE' apres revert.
S-013 (RB2) : reconcile_inprogress_rollbacks reprend un rollback_status='IN_PROGRESS' orphelin (kill simule).
S-015      : transition apply_batches FAILED -> ROLLED_BACK_BY_ATOMIC desormais autorisee (refletait l'etat reel).
S-011 (UNDO-CASE) : _execute_undo_ops fait un undo casse-seule au lieu de classer CONFLIT (Windows insensible casse).

Baselines (casses) : cap_integrity_structural.out.txt (RB1/RB2 structural) + V6-UNDO-CASE (code).

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f2c_rollback_undo_diff.py
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from cinesort.app.apply_batches_reconciliation import reconcile_inprogress_rollbacks
from cinesort.app.apply_rollback import rollback_forward
from cinesort.infra.db.sqlite_store import SQLiteStore
from cinesort.ui.api.apply_support import _execute_undo_ops


def _store():
    tmp = Path(tempfile.mkdtemp(prefix="cs_f2c_"))
    st = SQLiteStore(tmp / "t.sqlite", busy_timeout_ms=5000)
    st.initialize()
    return st, tmp


def _mk_moved(tmp: Path, name: str):
    """Cree un fichier 'deja deplace' : present a dst, absent a src."""
    src = tmp / "src" / name
    dst = tmp / "dst" / name
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(b"x" * 64)
    return src, dst


def run():
    results = {}

    # ---- S-012 : rollback_forward marque undo_status ----
    st, tmp = _store()
    bid = st.apply.insert_apply_batch(run_id="r1", dry_run=False, quarantine_unapproved=False)
    st.apply.upsert_atomic_mode(bid, True)
    src, dst = _mk_moved(tmp, "movie.mkv")
    st.apply.append_apply_operation(
        batch_id=bid, op_index=1, op_type="MOVE_FILE", src_path=str(src), dst_path=str(dst), reversible=True
    )
    res = rollback_forward(st, bid)
    ops_after = st.apply.list_apply_operations(batch_id=bid)
    undo_statuses = [str(o.get("undo_status") or "PENDING") for o in ops_after]
    s012 = res["ok"] and src.exists() and (not dst.exists()) and undo_statuses == ["DONE"]
    results["S012_undo_status_marque"] = s012
    print("=== S-012 (RB1 : undo_status op-level marque apres revert) ===")
    print(f"  rollback ok / FS reverti : {res['ok']} / {src.exists() and not dst.exists()}")
    print(f"  undo_status des ops      : {undo_statuses} (AVANT toujours ['PENDING'] ; APRES ['DONE'])")
    shutil.rmtree(tmp, ignore_errors=True)

    # ---- S-013 : reprise d'un IN_PROGRESS orphelin (kill simule pendant revert) ----
    st2, tmp2 = _store()
    bid2 = st2.apply.insert_apply_batch(run_id="r2", dry_run=False, quarantine_unapproved=False)
    st2.apply.upsert_atomic_mode(bid2, True)
    # Etat reel d'un apply atomique crashe : batch clos FAILED AVANT le revert.
    st2.apply.close_apply_batch(batch_id=bid2, status="FAILED", summary={"crash": True})
    src2, dst2 = _mk_moved(tmp2, "film.mkv")
    st2.apply.append_apply_operation(
        batch_id=bid2, op_index=1, op_type="MOVE_FILE", src_path=str(src2), dst_path=str(dst2), reversible=True
    )
    # Simuler le kill PENDANT le revert : on marque IN_PROGRESS et on N'execute PAS le revert.
    st2.apply.mark_rollback_status(bid2, "IN_PROGRESS")
    mode_before = st2.apply.get_atomic_mode(bid2)["rollback_status"]

    def _batch_status(st, bid):
        with st._managed_conn() as c:
            row = c.execute("SELECT status FROM apply_batches WHERE batch_id=?", (bid,)).fetchone()
            return row[0] if row else None

    status_before = _batch_status(st2, bid2)  # FAILED
    fs_before = dst2.exists() and not src2.exists()  # toujours a moitie : fichier en dst
    report = reconcile_inprogress_rollbacks(st2)
    mode_after = st2.apply.get_atomic_mode(bid2)["rollback_status"]
    status_after = _batch_status(st2, bid2)  # R8-088 : doit refleter ROLLED_BACK_BY_ATOMIC
    fs_after = src2.exists() and not dst2.exists()  # revert termine
    s013 = (
        mode_before == "IN_PROGRESS"
        and fs_before
        and report.get("resumed") == 1
        and mode_after == "ROLLED_BACK_BY_ATOMIC"
        and fs_after
    )
    s088 = status_before == "FAILED" and status_after == "ROLLED_BACK_BY_ATOMIC"
    results["S013_reprise_inprogress_orphelin"] = s013
    results["S088_boot_reflete_status_batch"] = s088
    print("\n=== S-013/088 (RB2 : reprise IN_PROGRESS orphelin + status batch reflete au boot) ===")
    print(
        f"  AVANT : rollback_status={mode_before}, apply_batches.status={status_before}, FS a moitie (dst)={fs_before}"
    )
    print(f"  reconcile_inprogress_rollbacks report : {report}")
    print(
        f"  APRES : rollback_status={mode_after}, apply_batches.status={status_after} (R8-088, AVANT figé FAILED), FS reverti={fs_after}"
    )
    shutil.rmtree(tmp2, ignore_errors=True)

    # ---- S-015 : transition FAILED -> ROLLED_BACK_BY_ATOMIC autorisee ----
    st3, tmp3 = _store()
    bid3 = st3.apply.insert_apply_batch(run_id="r3", dry_run=False, quarantine_unapproved=False)
    st3.apply.close_apply_batch(batch_id=bid3, status="FAILED", summary={"x": 1})
    raised = None
    try:
        st3.apply.close_apply_batch(
            batch_id=bid3, status="ROLLED_BACK_BY_ATOMIC", summary={"rollback_status": "ROLLED_BACK_BY_ATOMIC"}
        )
    except Exception as e:  # ApplyBatchStateError (RuntimeError) AVANT le fix
        raised = type(e).__name__
    # relire le statut
    st3.apply.list_apply_history(run_id="r3") if hasattr(st3.apply, "list_apply_history") else []
    final_status = None
    with st3._managed_conn() as conn:
        cur = conn.execute("SELECT status FROM apply_batches WHERE batch_id=?", (bid3,))
        row = cur.fetchone()
        final_status = row[0] if row else None
    s015 = raised is None and final_status == "ROLLED_BACK_BY_ATOMIC"
    results["S015_transition_FAILED_to_ROLLED_BACK"] = s015
    print("\n=== S-015 (apply-status : FAILED -> ROLLED_BACK_BY_ATOMIC reflete le revert) ===")
    print(f"  exception sur la transition : {raised!r} (AVANT = ApplyBatchStateError ; APRES None)")
    print(f"  statut final du batch       : {final_status} (attendu ROLLED_BACK_BY_ATOMIC)")
    shutil.rmtree(tmp3, ignore_errors=True)

    # ---- S-011 : undo casse-seule (Windows) au lieu de CONFLIT ----
    st4, tmp4 = _store()
    bid4 = st4.apply.insert_apply_batch(run_id="r4", dry_run=False, quarantine_unapproved=False)
    # Apply casse-seule : "Film.mkv" -> "film.mkv". Pour annuler : current=film -> target=Film.
    lib = tmp4 / "lib"
    lib.mkdir(parents=True)
    current = lib / "film.mkv"  # etat courant (dst de l'apply)
    target = lib / "Film.mkv"  # cible de l'undo (src de l'apply)
    current.write_bytes(b"v" * 32)
    op = {
        "id": 1,
        "op_index": 1,
        "op_type": "MOVE_FILE",
        "src_path": str(target),
        "dst_path": str(current),
        "reversible": 1,
        "undo_status": "PENDING",
    }
    st4.apply.append_apply_operation(
        batch_id=bid4, op_index=1, op_type="MOVE_FILE", src_path=str(target), dst_path=str(current), reversible=True
    )

    class _Api:
        def _unique_path(self, p):
            return p

    class _RunPaths:
        def __init__(self, d):
            self.run_dir = d

    run_paths = _RunPaths(tmp4 / "run")
    (tmp4 / "run").mkdir(parents=True, exist_ok=True)
    # samefile(film, Film) sur Windows = True (insensible casse) -> branche casse-seule.
    import os

    case_insensitive = os.path.exists(str(target))  # target=Film "existe" si FS insensible casse
    rep = _execute_undo_ops(
        _Api(), [op], st4, lambda lv, m: None, run_paths, empty_bucket=None, residual_bucket=None, atomic=False
    )
    # Apres : sur Windows, le fichier doit s'appeler "Film.mkv" (casse cible), pas en _undo_conflicts.
    names = sorted(p.name for p in lib.glob("*.mkv"))
    in_conflicts = (
        list((run_paths.run_dir / "_review" / "_undo_conflicts").rglob("*.mkv"))
        if (run_paths.run_dir / "_review" / "_undo_conflicts").exists()
        else []
    )
    if case_insensitive:
        s011 = rep.get("done") == 1 and names == ["Film.mkv"] and not in_conflicts
        verdict_ctx = "FS insensible casse (Windows) : undo casse-seule attendu"
    else:
        # FS sensible casse (Linux) : 'Film' n'existe pas -> restore normal, pas un conflit non plus.
        s011 = rep.get("done") == 1 and not in_conflicts
        verdict_ctx = "FS sensible casse (Linux) : restore normal (pas de faux conflit)"
    results["S011_undo_casse_seule"] = s011
    print("\n=== S-011 (UNDO-CASE : undo casse-seule au lieu de CONFLIT) ===")
    print(f"  contexte                 : {verdict_ctx}")
    print(f"  rapport undo (done/failed/conflict) : {rep.get('done')}/{rep.get('failed')}/{rep.get('conflict_moves')}")
    print(f"  fichiers lib             : {names}")
    print(f"  classes en _undo_conflicts (AVANT bug) : {[p.name for p in in_conflicts]} (attendu [])")
    shutil.rmtree(tmp4, ignore_errors=True)

    allok = all(results.values())
    print(f"\nVERDICT : {'CORRIGE (rollback/undo/statuts coherents)' if allok else 'INCOMPLET'}")
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
