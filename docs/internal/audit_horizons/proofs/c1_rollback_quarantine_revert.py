"""C1 P0 — Repro LIVE du revert QUARANTINE_* au rollback (bug 314 HIGH REAL 2/2).

Bug 314 : un rollback excluait QUARANTINE_FILE/QUARANTINE_DIR du switch -> les
fichiers restaient en quarantaine APRES rollback tout en renvoyant ok=True (FS
non restaure). Correctif apply_rollback.py:118 (les ajoute au switch + revert
dst->src reel + defenses TOCTOU).

Ce harnais (fichiers JETABLES temp, AUCUNE DB, aucun effet sur la vraie biblio)
appelle directement _revert_one_op :
  T1  op QUARANTINE_FILE valide -> status DONE ET fichier revenu dst->src
       (pre-fix : SKIPPED 'non revert-able' -> fichier reste en quarantaine).
  T2 (controle) op_type DELETE -> SKIPPED 'non revert-able' (prouve que le switch
       discrimine vraiment -> harnais falsifiable, pas un oui-systematique).
  T3 (controle) QUARANTINE_FILE mais dst manquant -> SKIPPED 'dst_missing'.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/audit_horizons/proofs/c1_rollback_quarantine_revert.py
"""
from __future__ import annotations
import json
import tempfile
from pathlib import Path

from cinesort.app.apply_rollback import _revert_one_op


def _scene(present_at_dst=True):
    tmp = Path(tempfile.mkdtemp(prefix="cs_rbq_"))
    src = tmp / "library" / "Film.2019.1080p.mkv"        # origine (videe par l'apply)
    dst = tmp / "_review" / "_conflicts" / "Film.2019.1080p.mkv"  # quarantaine
    src.parent.mkdir(parents=True, exist_ok=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if present_at_dst:
        dst.write_bytes(b"film-bytes")
    return tmp, src, dst


def run():
    out = {}

    # T1 : QUARANTINE_FILE -> doit revert dst->src
    tmp, src, dst = _scene()
    op = {"id": 1, "op_index": 0, "op_type": "QUARANTINE_FILE",
          "src_path": str(src), "dst_path": str(dst), "reversible": 1,
          "undo_status": "PENDING"}
    r = _revert_one_op(op)
    out["T1_quarantine_file_revert"] = {
        "status": r.get("status"), "reason": r.get("reason"),
        "src_existe_apres": src.exists(), "dst_existe_apres": dst.exists(),
        "VERDICT": "FIX OK (revert reel dst->src)"
                   if r.get("status") == "DONE" and src.exists() and not dst.exists()
                   else "GAP (quarantaine non restauree)",
    }

    # T2 : op non-revert-able -> SKIPPED (falsifiabilite du switch)
    tmp2, src2, dst2 = _scene()
    op2 = {"id": 2, "op_index": 1, "op_type": "DELETE",
           "src_path": str(src2), "dst_path": str(dst2), "reversible": 1,
           "undo_status": "PENDING"}
    r2 = _revert_one_op(op2)
    out["T2_delete_non_revertable_CONTROLE"] = {
        "status": r2.get("status"), "reason": r2.get("reason"),
        "VERDICT": "switch DISCRIMINE (falsifiable)" if r2.get("status") == "SKIPPED"
                   else "switch laxiste",
    }

    # T3 : QUARANTINE_FILE mais dst absent -> SKIPPED dst_missing (pas de faux DONE)
    tmp3, src3, dst3 = _scene(present_at_dst=False)
    op3 = {"id": 3, "op_index": 2, "op_type": "QUARANTINE_FILE",
           "src_path": str(src3), "dst_path": str(dst3), "reversible": 1,
           "undo_status": "PENDING"}
    r3 = _revert_one_op(op3)
    out["T3_dst_missing_CONTROLE"] = {
        "status": r3.get("status"), "reason": r3.get("reason"),
        "VERDICT": "garde dst_missing OK" if r3.get("status") == "SKIPPED" else "faux DONE",
    }

    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    run()
