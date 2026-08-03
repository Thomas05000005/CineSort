"""VAGUE 9 C — repro comportementale DEFIANTE de F-V8-COLL-ATOMIC.

apply_collection_item deplace les sidecars AVANT la video. Si le move video echoue
(mkv verrouille = PermissionError, cas que le code reconnait frequent), les sidecars
sont DEJA dans sub_dir/ mais la video reste en source -> item collection a moitie
applique, sans rollback compensatoire intra-row.

Harness : on patche move_file_with_collision_policy pour qu'il REUSSISSE les sidecars
(.srt/.nfo) et LEVE PermissionError sur la video (.mkv), simulant un fichier verrouille.
On appelle le VRAI apply_collection_item et on mesure l'etat FS + le ledger dedup.

Falsifiable : si apply_collection_item etait atomique (deplacait tout ou rien) ou
revertait les sidecars en cas d'echec video, le harness le verrait. Chemin=prod.
Aucun effet de bord hors tempdir.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/audit_horizons/proofs/v9_coll_atomic_repro.py
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


def run():
    tmp = Path(tempfile.mkdtemp(prefix="cs_coll_atomic_"))
    root = tmp / "lib"
    folder = root / "Saga Pack"
    folder.mkdir(parents=True)
    stem = "Film.2020.1080p"
    (folder / f"{stem}.mkv").write_bytes(b"v" * 400)
    (folder / f"{stem}.srt").write_text("sub", encoding="utf-8")
    (folder / f"{stem}.nfo").write_text("<nfo/>", encoding="utf-8")

    cfg = Cfg(root)
    res = core.ApplyResult()
    logs, ops = [], []
    dedup = set()

    def log(level, msg):
        logs.append((level, msg))

    def record_op(op):
        ops.append(dict(op) if isinstance(op, dict) else {"raw": str(op)})

    # Patch : sidecars OK (move reel), video .mkv -> PermissionError (mkv verrouille)
    orig = apply_core.move_file_with_collision_policy

    def patched(cfg_, src_file, dst_file, **kw):
        if Path(src_file).suffix.lower() in {".mkv", ".mp4"}:
            raise PermissionError(f"[simule] fichier verrouille: {src_file.name}")
        return orig(cfg_, src_file, dst_file, **kw)

    apply_core.move_file_with_collision_policy = patched

    sub_dir = folder / "Film (2020)"
    raised = None
    try:
        apply_collection_item(
            cfg,
            folder,
            f"{stem}.mkv",
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
    except (PermissionError, OSError) as e:
        raised = str(e)
    finally:
        apply_core.move_file_with_collision_policy = orig

    # Etat FS mesure
    src_video_still = (folder / f"{stem}.mkv").exists()
    sidecars_in_subdir = sorted(p.name for p in sub_dir.glob("*")) if sub_dir.exists() else []
    sidecars_moved = any(s.endswith(".srt") or s.endswith(".nfo") for s in sidecars_in_subdir)
    src_sidecars_left = sorted(p.name for p in folder.glob("*.srt")) + sorted(p.name for p in folder.glob("*.nfo"))
    video_dedup_marked = any("collection_video" in str(k) for k in dedup)
    rollback_ops = [o for o in ops if "ROLLBACK" in str(o.get("op_type") or o.get("type") or "")]

    print("=== F-V8-COLL-ATOMIC repro (apply_collection_item, move video echoue) ===")
    print(f"  exception remontee (non geree intra-row) : {raised!r}")
    print(f"  VIDEO toujours en source (non deplacee)  : {src_video_still}")
    print(f"  SIDECARS deja dans sub_dir/              : {sidecars_in_subdir}")
    print(f"  sidecars source restants                 : {src_sidecars_left}")
    print(f"  ledger dedup marque la video 'vue'       : {video_dedup_marked} (=> retry skipperait la video)")
    print(f"  op de ROLLBACK compensatoire emise       : {len(rollback_ops)} (attendu 0)")
    half_applied = src_video_still and sidecars_moved and len(rollback_ops) == 0
    print(
        f"\nVERDICT : {'CONFIRME (item collection a moitie applique: sidecars deplaces, video bloquee, aucun rollback)' if half_applied else 'non reproduit'}"
    )
    print(
        "RESUME:",
        json.dumps(
            {
                "half_applied": half_applied,
                "sidecars_moved": sidecars_moved,
                "video_stuck": src_video_still,
                "no_rollback": len(rollback_ops) == 0,
                "dedup_poisoned": video_dedup_marked,
            },
            ensure_ascii=False,
        ),
    )


if __name__ == "__main__":
    run()
