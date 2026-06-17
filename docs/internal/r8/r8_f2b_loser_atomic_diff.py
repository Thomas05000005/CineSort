"""R8-017 — DIFFERENTIEL atomicite/isolation des helpers loser. Fixtures jetables.

Baseline (casse, structural) : docs/internal/baseline_r8/captures/cap_integrity_structural.out.txt
  -> les helpers move_duplicate_losers_to_user_decided / move_marked_for_deletion_to_bucket sont appeles
     AVANT la boucle per-row, HORS du try/except -> un loser verrouille AVORTE TOUT LE BATCH (winners inclus),
     travail partiel laisse = etat incoherent.

Prouve casse->correct (le helper isole desormais l'echec per-loser, ne propage plus -> le batch n'est pas avorte) :
  S1 ISOLATION : 2 losers single, le 1er verrouille (atomic_move leve) -> AVANT le helper PROPAGE
     (batch avorte, 2e loser non traite) ; APRES le helper N'AVORTE PAS, traite le 2e loser, res.errors>=1.
  S2 ROLLBACK : 1 loser collection (video + 2 sidecars), le move video echoue APRES les sidecars ->
     APRES les sidecars sont ROLLBACK (revenus source), etat coherent, pas de partiel.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f2b_loser_atomic_diff.py
"""
from __future__ import annotations
import json
import tempfile
from pathlib import Path

import cinesort.domain.core as core
import cinesort.app.apply_core as apply_core
from cinesort.app.apply_core import move_duplicate_losers_to_user_decided


class Cfg:
    def __init__(self, root: Path):
        self.root = root
        self.side_exts = {".srt", ".nfo"}
        self.generic_side_files = set()
        self.lowercase_extensions = False
        self.video_exts = {".mkv", ".mp4"}
        self.collection_root_name = "_Collection"
        self.enable_collection_folder = False
        self.naming_movie_template = "{title} ({year})"
        self.separator = " "


class Row:
    def __init__(self, **kw):
        self.row_id = kw.get("row_id", "")
        self.folder = kw.get("folder", "")
        self.video = kw.get("video", "")
        self.kind = kw.get("kind", "single")


def run():
    results = {}

    # ---- S1 : isolation (2 losers single, 1er verrouille) ----
    tmp = Path(tempfile.mkdtemp(prefix="cs_f2b_s1_"))
    root = tmp / "lib"
    bucket = root / "_review" / "_duplicates_user_decided"
    f1 = root / "Loser One (2020)"; f1.mkdir(parents=True); (f1 / "a.mkv").write_bytes(b"a")
    f2 = root / "Loser Two (2020)"; f2.mkdir(parents=True); (f2 / "b.mkv").write_bytes(b"b")
    cfg, res = Cfg(root), core.ApplyResult()
    rows = [Row(row_id="L1", folder=str(f1), kind="single"), Row(row_id="L2", folder=str(f2), kind="single")]

    orig_am = apply_core.atomic_move
    def patched_am(record_op, *, src, dst, op_type, **kw):
        if Path(src).name == "Loser One (2020)":
            raise PermissionError("[simule] loser verrouille: Loser One (2020)")
        return orig_am(record_op, src=src, dst=dst, op_type=op_type, **kw)
    apply_core.atomic_move = patched_am
    raised = None
    try:
        move_duplicate_losers_to_user_decided(cfg, rows, {"L1", "L2"}, duplicates_user_decided_root=bucket,
                                              dry_run=False, log=lambda lv, m: None, res=res, record_op=lambda op: None)
    except (PermissionError, OSError) as e:
        raised = str(e)
    finally:
        apply_core.atomic_move = orig_am

    l1_still_src = f1.exists()  # echec -> reste en source
    l2_moved = not f2.exists() and any(bucket.rglob("b.mkv"))  # 2e loser TRAITE malgre l'echec du 1er
    s1_ok = (raised is None) and l2_moved and res.errors >= 1
    results["S1_isolation_batch_non_avorte"] = s1_ok
    print("=== S1 (R8-017 isolation : loser verrouille n'avorte pas le batch) ===")
    print(f"  exception PROPAGEE par le helper : {raised!r} (AVANT = PermissionError ; APRES attendu None)")
    print(f"  loser 1 (verrouille) reste source : {l1_still_src}")
    print(f"  loser 2 TRAITE (deplace bucket)   : {l2_moved} (AVANT non atteint car batch avorte)")
    print(f"  res.errors                        : {res.errors} (>=1 attendu)")

    # ---- S2 : rollback (collection loser, video echoue apres sidecars) ----
    tmp2 = Path(tempfile.mkdtemp(prefix="cs_f2b_s2_"))
    root2 = tmp2 / "lib"
    bucket2 = root2 / "_review" / "_duplicates_user_decided"
    saga = root2 / "Saga"; saga.mkdir(parents=True)
    stem = "Film.2020.1080p"
    (saga / f"{stem}.mkv").write_bytes(b"v" * 50)
    (saga / f"{stem}.srt").write_text("s", encoding="utf-8")
    (saga / f"{stem}.nfo").write_text("<n/>", encoding="utf-8")
    cfg2, res2 = Cfg(root2), core.ApplyResult()
    rows2 = [Row(row_id="C1", folder=str(saga), video=f"{stem}.mkv", kind="collection")]

    orig_mb = apply_core.move_to_review_bucket
    def patched_mb(src_file, **kw):
        if Path(src_file).suffix.lower() == ".mkv":
            raise PermissionError(f"[simule] video verrouillee: {Path(src_file).name}")
        return orig_mb(src_file, **kw)
    apply_core.move_to_review_bucket = patched_mb
    raised2 = None
    try:
        move_duplicate_losers_to_user_decided(cfg2, rows2, {"C1"}, duplicates_user_decided_root=bucket2,
                                              dry_run=False, log=lambda lv, m: None, res=res2, record_op=lambda op: None)
    except (PermissionError, OSError) as e:
        raised2 = str(e)
    finally:
        apply_core.move_to_review_bucket = orig_mb

    sidecars_in_bucket = sorted(p.name for p in bucket2.rglob("*") if p.suffix.lower() in {".srt", ".nfo"})
    sidecars_back_src = sorted(p.name for p in saga.glob("*.srt")) + sorted(p.name for p in saga.glob("*.nfo"))
    video_src = (saga / f"{stem}.mkv").exists()
    s2_coherent = (raised2 is None) and (len(sidecars_in_bucket) == 0) and (len(sidecars_back_src) == 2) and video_src
    results["S2_rollback_collection_coherent"] = s2_coherent
    print("\n=== S2 (R8-017 rollback : video collection echoue apres sidecars) ===")
    print(f"  exception propagee        : {raised2!r} (attendu None)")
    print(f"  sidecars laisses au bucket : {sidecars_in_bucket} (attendu [] = rollback)")
    print(f"  sidecars revenus en source : {sidecars_back_src} (attendu 2)")
    print(f"  video restee en source     : {video_src}")

    allok = all(results.values())
    print(f"\nVERDICT : {'CORRIGE (isolation + rollback, batch non avorte)' if allok else 'INCOMPLET'}")
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
