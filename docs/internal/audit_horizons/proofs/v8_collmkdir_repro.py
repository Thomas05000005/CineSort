"""VAGUE 8 D — repro comportementale DEFIANTE de F-V7-COLLMKDIR (chemin FILM).

Appelle le VRAI apply_single (cinesort.app.apply_core) sur une fixture collection
JETABLE, en mode reel, avec une cible qui depasse MAX_PATH (259) APRES le mkdir
du dossier saga (L1888 < killswitch L1893). Mesure :
  - le dossier saga <root>/_Collection/<saga>/ est-il cree VIDE et orphelin ?
  - une op MKDIR est-elle journalisee pour lui (record_op) ? (attendu: NON, mkdir brut)
  - le film est-il bien SKIPPE (MAX_PATH) ?

Falsifiable : si apply_single creait le dossier via mkdir_counted (op journalisee)
ou apres le killswitch, le harness le verrait. Chemin=prod (fonction de prod).
Aucun effet de bord hors tempdir.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/audit_horizons/proofs/v8_collmkdir_repro.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import cinesort.domain.core as core
from cinesort.app.apply_core import apply_single


class Cfg:
    def __init__(self, root: Path):
        self.root = root
        self.collection_root_name = "_Collection"
        self.enable_collection_folder = True
        self.naming_movie_template = "{title} ({year})"
        self.separator = " "
        self.side_exts = {".srt", ".nfo"}
        self.generic_side_files = set()
        self.lowercase_extensions = False
        self.video_exts = {".mkv", ".mp4"}


def run():
    tmp = Path(tempfile.mkdtemp(prefix="cs_collmkdir_"))
    root = tmp / "lib"
    folder = root / "MovieSrc"
    folder.mkdir(parents=True)
    (folder / "movie.mkv").write_bytes(b"x" * 500)

    # Saga ~150 chars : coll_dir < 260 (mkdir OK) mais coll_dir/new_name > 259 (killswitch skip)
    saga = "S" * 150
    cfg = Cfg(root)
    res = core.ApplyResult()
    logs, ops = [], []

    def log(level, msg):
        logs.append((level, msg))

    def record_op(op):
        ops.append(dict(op) if isinstance(op, dict) else {"raw": str(op)})

    coll_dir = root / cfg.collection_root_name / saga
    target_len = len(str(coll_dir / "A Very Long Movie Title (2020)"))
    before = sorted(str(p.relative_to(tmp)) for p in root.rglob("*"))

    apply_single(
        cfg,
        folder,
        title="A Very Long Movie Title",
        year=2020,
        dry_run=False,
        log=log,
        res=res,
        conflicts_root=root / "_review" / "_conflicts",
        conflicts_sidecars_root=root / "_review" / "_conflicts_sidecars",
        duplicates_identical_root=root / "_review" / "_dups",
        leftovers_root=root / "_review" / "_leftovers",
        record_op=record_op,
        tmdb_collection_name=saga,
    )

    after = sorted(str(p.relative_to(tmp)) for p in root.rglob("*"))
    saga_dir_created = coll_dir.exists() and coll_dir.is_dir()
    saga_dir_empty = saga_dir_created and not any(coll_dir.iterdir())
    movie_still_in_src = (folder / "movie.mkv").exists()
    mkdir_ops = [o for o in ops if (o.get("op_type") or o.get("type")) == "MKDIR"]
    skipped = res.skipped > 0 or any("PATH_TOO_LONG" in str(m) for m in res.error_messages)

    print("=== F-V7-COLLMKDIR repro (apply_single, mode reel) ===")
    print(f"coll_dir len={len(str(coll_dir))}  target len={target_len} (killswitch a 259)")
    print(f"AVANT: {before}")
    print(f"APRES: {after}")
    print(f"  dossier saga cree VIDE orphelin : {saga_dir_empty}  (path={coll_dir.name[:20]}...)")
    print(f"  film toujours en source (skip)  : {movie_still_in_src}")
    print(f"  op MKDIR journalisee pour saga  : {len(mkdir_ops)} (attendu 0 = mkdir brut)")
    print(f"  film skippe (MAX_PATH)          : {skipped}")
    verdict = saga_dir_empty and movie_still_in_src and len(mkdir_ops) == 0
    print(
        f"\nVERDICT : {'CONFIRME (dossier saga vide orphelin + non journalise + film non deplace)' if verdict else 'non reproduit'}"
    )
    print(
        "RESUME:",
        json.dumps(
            {
                "saga_dir_empty_orphan": saga_dir_empty,
                "no_mkdir_op": len(mkdir_ops) == 0,
                "movie_skipped": movie_still_in_src,
            },
            ensure_ascii=False,
        ),
    )


if __name__ == "__main__":
    run()
