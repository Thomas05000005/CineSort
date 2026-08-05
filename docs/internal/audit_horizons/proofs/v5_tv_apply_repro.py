"""VAGUE 5 B1+B2 — repro comportementale DEFIANTE de F-V4B-TV1 / F-V4B-TV2.

Appelle le VRAI apply_tv_episode (cinesort.app.apply_core) sur une fixture TV
JETABLE (tempfile), en mode reel (dry_run=False), et mesure :
  B1 (TV1) : les sidecars .srt/.nfo suivent-ils le nouveau stem video
             (SxxExx - Titre) ou gardent-ils leur nom source -> ORPHELINS ?
  B2 (TV2) : les ops journalisees (record_apply_op) portent-elles src_sha1/
             src_size (filet anti-undo-dangereux) ou non ?

Falsifiabilite : si le code realignait les sidecars, le harness le verrait
(stems compares). Chemin = prod : on appelle la fonction de prod, pas une copie.
Aucun effet de bord hors du tempdir.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/audit_horizons/proofs/v5_tv_apply_repro.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import cinesort.domain.core as core
from cinesort.app.apply_core import apply_tv_episode


class Cfg:
    def __init__(self, root: Path):
        self.root = root
        self.naming_tv_template = "{series} ({year})"
        self.naming_movie_template = "{title} ({year})"
        self.separator = " "
        self.enable_collection_folder = False
        self.collection_root_name = "_Collection"
        self.side_exts = {".srt", ".nfo", ".jpg", ".ass"}
        self.generic_side_files = set()
        self.lowercase_extensions = False
        self.video_exts = {".mkv", ".mp4", ".avi"}


class Row:
    def __init__(self, **kw):
        self.video = kw.get("video", "")
        self.proposed_title = kw.get("proposed_title", "")
        self.proposed_year = kw.get("proposed_year", 0)
        self.tv_season = kw.get("tv_season", 0)
        self.tv_episode = kw.get("tv_episode", 0)
        self.tv_episode_title = kw.get("tv_episode_title", "")
        self.tv_series_name = kw.get("tv_series_name", "")
        self.row_id = kw.get("row_id", "r1")


def run():
    tmp = Path(tempfile.mkdtemp(prefix="cs_tv_repro_"))
    root = tmp / "lib"
    folder = root / "_inbox"
    folder.mkdir(parents=True)

    # Fixture : video + sidecars nommes au stem SOURCE (release name)
    src_stem = "Showname.S01E01.1080p.HDTV.x264-GRP"
    (folder / f"{src_stem}.mkv").write_bytes(b"video-bytes" * 100)
    (folder / f"{src_stem}.srt").write_text("1\n00:00 --> 00:01\nhello\n", encoding="utf-8")
    (folder / f"{src_stem}.nfo").write_text("<episodedetails><title>Pilot</title></episodedetails>", encoding="utf-8")

    cfg = Cfg(root)
    row = Row(
        video=f"{src_stem}.mkv",
        proposed_title="Showname",
        proposed_year=2020,
        tv_season=1,
        tv_episode=1,
        tv_episode_title="Pilot",
        tv_series_name="Showname",
    )
    res = core.ApplyResult()
    logs = []
    ops = []

    def log(level, msg):
        logs.append((level, msg))

    def record_op(op):
        ops.append(dict(op) if isinstance(op, dict) else {"raw": str(op)})

    before = sorted(str(p.relative_to(tmp)) for p in root.rglob("*") if p.is_file())
    apply_tv_episode(cfg, folder, row, dry_run=False, log=log, res=res, record_op=record_op)
    after = sorted(str(p.relative_to(tmp)) for p in root.rglob("*") if p.is_file())

    # --- B1 : stems alignes ? ---
    vids = [p for p in root.rglob("*") if p.suffix.lower() in cfg.video_exts]
    subs = [p for p in root.rglob("*") if p.suffix.lower() in {".srt", ".nfo"}]
    video_stem = vids[0].stem if vids else None
    sub_stems = {p.suffix: p.stem for p in subs}
    orphaned = [s for s in subs if s.stem != video_stem]

    print("=== FIXTURE TV — apply_tv_episode (mode reel, prod) ===")
    print("AVANT:", before)
    print("APRES:", after)
    print()
    print("--- B1 (F-V4B-TV1) : alignement sidecars ---")
    print(f"  stem video cible   : {video_stem!r}")
    print(f"  stems sidecars     : {sub_stems}")
    print(f"  sidecars ORPHELINS (stem != video) : {[p.name for p in orphaned]}")
    b1 = len(orphaned) > 0 and video_stem is not None
    print(f"  VERDICT B1 : {'CONFIRME (sidecars orphelins)' if b1 else 'sain (alignes)'}")
    print()

    # --- B2 : ops journalisees portent src_sha1/src_size ? ---
    [o for o in ops if o.get("op_type") == "MOVE_FILE" or o.get("type") == "MOVE_FILE" or "src_path" in o or "src" in o]
    has_hash = [("src_sha1" in o and o.get("src_sha1")) for o in ops]
    any_hash = any(has_hash)
    print("--- B2 (F-V4B-TV2) : empreinte src_sha1/src_size dans les ops ---")
    print(f"  nb ops capturees : {len(ops)}")
    for o in ops:
        keys = sorted(o.keys())
        print(
            f"    op: type={o.get('op_type') or o.get('type')} keys={keys} src_sha1={o.get('src_sha1', '<absent>')} src_size={o.get('src_size', '<absent>')}"
        )
    b2 = not any_hash and len(ops) > 0
    print(
        f"  VERDICT B2 : {'CONFIRME (aucune empreinte -> garde-fou undo inerte sur TV)' if b2 else 'empreinte presente'}"
    )
    print()
    print(
        "RESUME:",
        json.dumps({"B1_sidecars_orphelins": b1, "B2_ops_sans_sha1": b2, "res_moves": res.moves}, ensure_ascii=False),
    )


if __name__ == "__main__":
    run()
