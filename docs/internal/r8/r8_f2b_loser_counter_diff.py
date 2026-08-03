"""R8-018 — DIFFERENTIEL invariant compteur loser + chemin de recuperation. Fixtures jetables.

Baseline (casse) : docs/internal/baseline_r8/captures/cap_integrity_structural.out.txt
  -> les helpers loser incrementent duplicates_identical_moved_count (compteur des byte-identiques,
     lockstep avec duplicates_identical_deleted_count) -> invariant moved==deleted CASSE +
     chemin de recuperation MENSONGER (UI pointe _duplicates_identical alors que les fichiers
     sont dans _duplicates_user_decided).

Prouve casse->correct :
  S1 INVARIANT : apres deplacement d'un loser, duplicates_identical_moved_count reste = deleted (0==0)
     et un compteur DEDIE duplicates_user_decided_moved_count compte le loser.
     AVANT : duplicates_identical_moved_count=1, deleted=0 -> 1 != 0 (invariant casse).
  S2 CHEMIN RECUP : apply_support pointe le compteur loser vers _duplicates_user_decided (reel),
     plus vers _duplicates_identical (mensonger).

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f2b_loser_counter_diff.py
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import cinesort.domain.core as core
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

    # ---- S1 : invariant moved==deleted + compteur dedie ----
    tmp = Path(tempfile.mkdtemp(prefix="cs_f2b_cnt_"))
    root = tmp / "lib"
    bucket = root / "_review" / "_duplicates_user_decided"
    f1 = root / "Loser (2020)"
    f1.mkdir(parents=True)
    (f1 / "a.mkv").write_bytes(b"a")
    cfg, res = Cfg(root), core.ApplyResult()
    move_duplicate_losers_to_user_decided(
        cfg,
        [Row(row_id="L1", folder=str(f1), kind="single")],
        {"L1"},
        duplicates_user_decided_root=bucket,
        dry_run=False,
        log=lambda lv, m: None,
        res=res,
        record_op=lambda op: None,
    )
    di_moved = res.duplicates_identical_moved_count
    di_deleted = res.duplicates_identical_deleted_count
    ud_moved = getattr(res, "duplicates_user_decided_moved_count", "<absent>")
    invariant_ok = di_moved == di_deleted  # 0 == 0 (le loser ne pollue plus le compteur byte-identique)
    dedicated_ok = ud_moved == 1
    loser_in_real_bucket = any(bucket.rglob("a.mkv"))
    results["S1_invariant_moved_eq_deleted"] = invariant_ok
    results["S1_compteur_dedie_loser"] = dedicated_ok
    print("=== S1 (R8-018 invariant + compteur dedie) ===")
    print(f"  duplicates_identical_moved_count  : {di_moved} (AVANT=1 a tort ; APRES attendu 0)")
    print(f"  duplicates_identical_deleted_count: {di_deleted}")
    print(f"  -> invariant moved==deleted        : {invariant_ok} (AVANT casse : 1 != 0)")
    print(f"  duplicates_user_decided_moved_count: {ud_moved} (compteur DEDIE, attendu 1)")
    print(f"  loser dans le bucket REEL          : {loser_in_real_bucket} (_duplicates_user_decided)")

    # ---- S2 : chemin de recuperation pointe le bucket REEL (verif code apply_support) ----
    src = Path("cinesort/ui/api/apply_support.py").read_text(encoding="utf-8", errors="replace")
    points_real = bool(re.search(r"duplicates_user_decided_moved_count > 0", src)) and bool(
        re.search(r"_duplicates_user_decided['\"]\}", src) or "_duplicates_user_decided'" in src
    )
    # AVANT : seul _duplicates_identical etait propose en chemin de recup pour les losers.
    results["S2_chemin_recup_reel"] = points_real
    print("\n=== S2 (R8-018 chemin de recuperation reel) ===")
    print(f"  apply_support propose _duplicates_user_decided pour le compteur loser : {points_real}")

    allok = all(results.values())
    print(f"\nVERDICT : {'CORRIGE (invariant preserve + compteur dedie + chemin reel)' if allok else 'INCOMPLET'}")
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
