"""R8-001 — DIFFERENTIEL baseline COLL-ATOMIC (apply_collection_item) : casse -> correct.

Prouve les DEUX observations baseline distinctes, sur fixture jetable (jamais la vraie biblio) :
  (A) ATOMICITE INTRA-ROW : move video echoue -> aucun etat PARTIEL ne subsiste
      (les sidecars deja deplaces sont ROLLBACK -> retour source ; coherent).
  (B) LEDGER NON EMPOISONNE + RETRY RE-TRAITE : l'item echoue n'est PAS marque "vu"
      dans dedup_seen_ops -> un RETRY (video deverrouillee) RE-TRAITE l'item et le
      complete (video + sidecars dans le sous-dossier).

Baseline (etat CASSE, fige) : docs/internal/baseline_r8/captures/v9_coll_atomic_repro.out.txt
  -> half_applied=true, dedup_poisoned=true, no_rollback=true.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_001_coll_atomic_diff.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import cinesort.app.apply_core as apply_core
import cinesort.domain.core as core
from cinesort.app.apply_core import apply_collection_item


class Cfg:
    def __init__(self, root: Path):
        self.root = root
        self.naming_movie_template = "{title} ({year})"
        self.separator = " "
        self.side_exts = {".srt", ".nfo"}
        self.generic_side_files = set()
        self.lowercase_extensions = False
        self.video_exts = {".mkv", ".mp4"}
        self.collection_root_name = "_Collection"
        self.enable_collection_folder = False


def _fixture():
    tmp = Path(tempfile.mkdtemp(prefix="cs_r8_001_"))
    root = tmp / "lib"
    folder = root / "Saga Pack"
    folder.mkdir(parents=True)
    stem = "Film.2020.1080p"
    (folder / f"{stem}.mkv").write_bytes(b"v" * 400)
    (folder / f"{stem}.srt").write_text("sub", encoding="utf-8")
    (folder / f"{stem}.nfo").write_text("<nfo/>", encoding="utf-8")
    return tmp, root, folder, stem


def run():
    tmp, root, folder, stem = _fixture()
    cfg = Cfg(root)
    res = core.ApplyResult()
    ops = []
    dedup = set()
    sub_dir = folder / "Film (2020)"

    def log(level, msg):
        pass

    def record_op(op):
        ops.append(dict(op) if isinstance(op, dict) else {"raw": str(op)})

    common = dict(
        title="Film",
        year=2020,
        dry_run=False,
        log=log,
        res=res,
        conflicts_root=root / "_review" / "_conflicts",
        conflicts_sidecars_root=root / "_review" / "_conflicts_sidecars",
        duplicates_identical_root=root / "_review" / "_dups",
        dedup_seen_ops=dedup,
        record_op=record_op,
    )

    # --- RUN 1 : video .mkv verrouillee (PermissionError) -> doit rollback, NON poisoner ---
    orig = apply_core.move_file_with_collision_policy

    def patched(cfg_, src_file, dst_file, **kw):
        if Path(src_file).suffix.lower() in {".mkv", ".mp4"}:
            raise PermissionError(f"[simule] verrouille: {Path(src_file).name}")
        return orig(cfg_, src_file, dst_file, **kw)

    apply_core.move_file_with_collision_policy = patched
    raised1 = None
    try:
        apply_collection_item(cfg, folder, f"{stem}.mkv", **common)
    except (PermissionError, OSError) as e:
        raised1 = str(e)
    finally:
        apply_core.move_file_with_collision_policy = orig

    video_in_src = (folder / f"{stem}.mkv").exists()
    sidecars_in_sub_after1 = sorted(p.name for p in sub_dir.glob("*")) if sub_dir.exists() else []
    sidecars_back_in_src = sorted(p.name for p in folder.glob("*.srt")) + sorted(p.name for p in folder.glob("*.nfo"))
    video_dedup_marked = any("collection_video" in str(k) for k in dedup)
    rollback_ops = [o for o in ops if "ROLLBACK" in str(o.get("op_type") or o.get("type") or "")]
    coherent_after_fail = video_in_src and not sidecars_in_sub_after1 and len(sidecars_back_in_src) == 2

    # --- RUN 2 : RETRY, video deverrouillee, MEME dedup -> doit RE-TRAITER l'item ---
    apply_collection_item(cfg, folder, f"{stem}.mkv", **common)
    video_moved_now = (sub_dir / f"{stem}.mkv").exists()
    sidecars_in_sub_after2 = sorted(p.name for p in sub_dir.glob("*")) if sub_dir.exists() else []
    item_complete = (
        video_moved_now
        and any(s.endswith(".srt") for s in sidecars_in_sub_after2)
        and any(s.endswith(".nfo") for s in sidecars_in_sub_after2)
    )
    src_empty_now = not any(folder.glob(f"{stem}.*"))

    print("=== R8-001 DIFFERENTIEL (apply_collection_item) ===")
    print(
        "--- BASELINE (casse, fige v9_coll_atomic_repro.out.txt) : half_applied=true, dedup_poisoned=true, no_rollback=true ---"
    )
    print()
    print("--- (A) ATOMICITE intra-row : RUN 1 (video verrouillee) ---")
    print(f"  exception re-levee (per-row handler)     : {raised1!r}")
    print(f"  video toujours en source (non perdue)    : {video_in_src}")
    print(f"  sidecars dans sub_dir (=PARTIEL si non[]) : {sidecars_in_sub_after1}")
    print(f"  sidecars RESTAURES en source (rollback)   : {sidecars_back_in_src}")
    print(f"  ops ROLLBACK emises                       : {len(rollback_ops)} (baseline=0)")
    print(f"  => etat COHERENT apres echec (tout-ou-rien): {coherent_after_fail}")
    print()
    print("--- (B) LEDGER non empoisonne + RETRY re-traite : RUN 2 (video deverrouillee, meme dedup) ---")
    print(f"  ledger avait marque la video 'vue'        : {video_dedup_marked} (baseline=true => retry skippait)")
    print(f"  RETRY a deplace la video                  : {video_moved_now}")
    print(f"  sidecars dans sub_dir apres retry         : {sidecars_in_sub_after2}")
    print(f"  source videe                              : {src_empty_now}")
    print(f"  => RETRY a COMPLETE l'item                : {item_complete}")
    print()
    fixed = coherent_after_fail and (not video_dedup_marked) and item_complete and len(rollback_ops) >= 2
    print(
        f"VERDICT : {'CORRIGE (A atomicite + B retry re-traite, differentiel casse->correct prouve)' if fixed else 'NON corrige'}"
    )
    print(
        "RESUME:",
        json.dumps(
            {
                "A_coherent_apres_echec": coherent_after_fail,
                "A_rollback_ops": len(rollback_ops),
                "B_dedup_non_poisonne": not video_dedup_marked,
                "B_retry_complete_item": item_complete,
                "fixed": fixed,
            },
            ensure_ascii=False,
        ),
    )


if __name__ == "__main__":
    run()
