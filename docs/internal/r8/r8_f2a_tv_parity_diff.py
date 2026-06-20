"""R8 F2-a — DIFFERENTIEL parité TV (apply_tv_episode portée du chemin film). Fixtures jetables.

Baseline (cassé, figé) : docs/internal/baseline_r8/captures/v5_tv_apply_repro.out.txt
  -> B1_sidecars_orphelins=true, B2_ops_sans_sha1=true ; + cap_tv_parity.out.txt (gates 3/4/5/6/8).

Prouve cassé->correct sur chaque garde portée (gates 1,2,4,5,6,8) :
  S1 : move réel -> sidecars RÉALIGNÉS sur stem SxxExx (gate1) ; ops vidéo portent src_sha1/size (gate2) ;
       MKDIR journalisé (gate6).
  S2 : 2e épisode DIFFÉRENT visant la même cible -> QUARANTAINE (conflict), source PAS laissée en place (gate4).
  S3 : move sidecar échoue (verrouillé) -> vidéo ROLLBACK, état cohérent, op ROLLBACK (gate8).
  S4 : dry_run -> ops journalisées (preview) + AUCUN move physique (gate5).

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f2a_tv_parity_diff.py
"""
from __future__ import annotations
import json
import tempfile
from pathlib import Path

import cinesort.domain.core as core
import cinesort.app.apply_core as apply_core
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


SRC_STEM = "Showname.S01E01.1080p.HDTV.x264-GRP"


def _fixture(tmp_prefix: str):
    tmp = Path(tempfile.mkdtemp(prefix=tmp_prefix))
    root = tmp / "lib"
    folder = root / "_inbox"
    folder.mkdir(parents=True)
    (folder / f"{SRC_STEM}.mkv").write_bytes(b"video-bytes" * 100)
    (folder / f"{SRC_STEM}.srt").write_text("1\n00:00 --> 00:01\nhi\n", encoding="utf-8")
    (folder / f"{SRC_STEM}.nfo").write_text("<episodedetails><title>Pilot</title></episodedetails>", encoding="utf-8")
    return tmp, root, folder


def _roots(root):
    return dict(
        conflicts_root=root / "_review" / "_conflicts",
        conflicts_sidecars_root=root / "_review" / "_conflicts_sidecars",
        duplicates_identical_root=root / "_review" / "_duplicates_identical",
    )


def _row():
    return Row(video=f"{SRC_STEM}.mkv", proposed_title="Showname", proposed_year=2020,
               tv_season=1, tv_episode=1, tv_episode_title="Pilot", tv_series_name="Showname")


def run():
    results = {}

    # ---- S1 : gate1 realignement + gate2 sha1 + gate6 mkdir ----
    tmp, root, folder = _fixture("cs_f2a_s1_")
    cfg, res, ops = Cfg(root), core.ApplyResult(), []
    log = lambda lv, m: None
    def rec(op): ops.append(dict(op) if isinstance(op, dict) else {"raw": str(op)})
    apply_tv_episode(cfg, folder, _row(), dry_run=False, log=log, res=res, record_op=rec, **_roots(root))
    season_dir = root / "Showname (2020)" / "Saison 01"
    vids = [p for p in season_dir.rglob("*") if p.suffix.lower() == ".mkv"]
    subs = [p for p in season_dir.rglob("*") if p.suffix.lower() in {".srt", ".nfo"}]
    video_stem = vids[0].stem if vids else None
    orphaned = [p.name for p in subs if p.stem != video_stem]
    move_ops = [o for o in ops if (o.get("op_type") or o.get("type")) == "MOVE_FILE"]
    video_op = next((o for o in move_ops if str(o.get("dst_path", "")).endswith(".mkv")), None)
    has_sha1 = bool(video_op and video_op.get("src_sha1"))
    mkdir_ops = [o for o in ops if (o.get("op_type") or o.get("type")) == "MKDIR"]
    s1_realigned = (video_stem == "S01E01 - Pilot") and (len(subs) == 2) and (len(orphaned) == 0)
    results["S1_gate1_sidecars_realignes"] = s1_realigned
    results["S1_gate2_video_op_src_sha1"] = has_sha1
    results["S1_gate6_mkdir_journalise"] = len(mkdir_ops) > 0 or res.mkdirs > 0
    print("=== S1 (gate1 realignement / gate2 sha1 / gate6 mkdir) ===")
    print(f"  stem video cible        : {video_stem!r} (attendu 'S01E01 - Pilot')")
    print(f"  sidecars                : {sorted(p.name for p in subs)}")
    print(f"  sidecars orphelins      : {orphaned} (attendu [])")
    print(f"  video op src_sha1       : {video_op.get('src_sha1','<absent>')[:12] if video_op else 'no-op'}...")
    print(f"  MKDIR journalisé        : {len(mkdir_ops)} ops / res.mkdirs={res.mkdirs}")

    # ---- S2 : gate4 collision (2e episode different) -> quarantaine, source pas laissee ----
    tmp2, root2, folder2 = _fixture("cs_f2a_s2_")
    cfg2, res2, ops2 = Cfg(root2), core.ApplyResult(), []
    # pre-placer un fichier DIFFERENT a la cible
    season_dir2 = root2 / "Showname (2020)" / "Saison 01"
    season_dir2.mkdir(parents=True)
    (season_dir2 / "S01E01 - Pilot.mkv").write_bytes(b"DIFFERENT-CONTENT-already-there")
    def rec2(op): ops2.append(dict(op) if isinstance(op, dict) else {"raw": str(op)})
    apply_tv_episode(cfg2, folder2, _row(), dry_run=False, log=(lambda lv, m: None), res=res2, record_op=rec2, **_roots(root2))
    src_video_still = (folder2 / f"{SRC_STEM}.mkv").exists()
    quarantined = res2.conflicts_quarantined_count > 0 or any((root2 / "_review" / "_conflicts").rglob("*.mkv"))
    s2_ok = (not src_video_still) and quarantined  # source DEPLACEE en quarantaine, pas laissee silencieusement
    results["S2_gate4_collision_quarantaine_pas_silencieux"] = s2_ok
    print("\n=== S2 (gate4 collision : 2e episode different) ===")
    print(f"  source encore en place (attendu False) : {src_video_still}")
    print(f"  quarantaine conflict (count={res2.conflicts_quarantined_count}) : {quarantined}")

    # ---- S3 : gate8 atomicite (sidecar verrouille) -> rollback video ----
    tmp3, root3, folder3 = _fixture("cs_f2a_s3_")
    cfg3, res3, ops3 = Cfg(root3), core.ApplyResult(), []
    def rec3(op): ops3.append(dict(op) if isinstance(op, dict) else {"raw": str(op)})
    orig = apply_core.move_file_with_collision_policy
    def patched(cfg_, src_file, dst_file, **kw):
        if Path(src_file).suffix.lower() == ".srt":
            raise PermissionError(f"[simule] verrouille: {Path(src_file).name}")
        return orig(cfg_, src_file, dst_file, **kw)
    apply_core.move_file_with_collision_policy = patched
    raised = None
    try:
        apply_tv_episode(cfg3, folder3, _row(), dry_run=False, log=(lambda lv, m: None), res=res3, record_op=rec3, **_roots(root3))
    except (PermissionError, OSError) as e:
        raised = str(e)
    finally:
        apply_core.move_file_with_collision_policy = orig
    season_dir3 = root3 / "Showname (2020)" / "Saison 01"
    video_back_in_src = (folder3 / f"{SRC_STEM}.mkv").exists()
    video_at_target = (season_dir3 / "S01E01 - Pilot.mkv").exists()
    rollback_ops = [o for o in ops3 if "ROLLBACK" in str(o.get("op_type") or o.get("type") or "")]
    s3_coherent = video_back_in_src and (not video_at_target) and len(rollback_ops) >= 1
    results["S3_gate8_atomicite_rollback"] = s3_coherent
    print("\n=== S3 (gate8 atomicite : sidecar .srt verrouille) ===")
    print(f"  exception re-levee       : {raised!r}")
    print(f"  video REVENUE en source  : {video_back_in_src} (attendu True)")
    print(f"  video restee a la cible  : {video_at_target} (attendu False)")
    print(f"  ops ROLLBACK             : {len(rollback_ops)} (attendu >=1)")

    # ---- S4 : gate5 dry_run -> ops journalisees, aucun move physique ----
    tmp4, root4, folder4 = _fixture("cs_f2a_s4_")
    cfg4, res4, ops4 = Cfg(root4), core.ApplyResult(), []
    def rec4(op): ops4.append(dict(op) if isinstance(op, dict) else {"raw": str(op)})
    apply_tv_episode(cfg4, folder4, _row(), dry_run=True, log=(lambda lv, m: None), res=res4, record_op=rec4, **_roots(root4))
    move_ops4 = [o for o in ops4 if (o.get("op_type") or o.get("type")) == "MOVE_FILE"]
    nothing_moved = (folder4 / f"{SRC_STEM}.mkv").exists() and not (root4 / "Showname (2020)").exists()
    s4_ok = len(move_ops4) >= 1 and nothing_moved
    results["S4_gate5_dryrun_ops_sans_move"] = s4_ok
    print("\n=== S4 (gate5 dry_run : ops preview sans move physique) ===")
    print(f"  MOVE_FILE ops journalisées : {len(move_ops4)} (attendu >=1)")
    print(f"  aucun fichier deplace       : {nothing_moved} (attendu True)")

    # ---- S5 : gate7 TV-UIEDIT -> edition titre/annee honoree (parite apply_single) ----
    tmp5, root5, folder5 = _fixture("cs_f2a_s5_")
    cfg5, res5 = Cfg(root5), core.ApplyResult()
    row5 = Row(video=f"{SRC_STEM}.mkv", proposed_title="Wrong", proposed_year=2019,
               tv_season=1, tv_episode=1, tv_episode_title="Pilot", tv_series_name="Wrong Series")
    apply_tv_episode(cfg5, folder5, row5, dry_run=False, log=(lambda lv, m: None), res=res5,
                     record_op=(lambda op: None), new_title="Corrected Series", new_year=2021, **_roots(root5))
    corrected_dir = (root5 / "Corrected Series (2021)" / "Saison 01" / "S01E01 - Pilot.mkv").exists()
    wrong_dir = (root5 / "Wrong Series (2019)").exists()
    results["S5_gate7_uiedit_honoree"] = corrected_dir and not wrong_dir
    print("\n=== S5 (gate7 TV-UIEDIT : edition titre/annee) ===")
    print(f"  dossier 'Corrected Series (2021)' utilise : {corrected_dir} (attendu True)")
    print(f"  ancien 'Wrong Series (2019)' present      : {wrong_dir} (attendu False)")

    allok = all(results.values())
    print(f"\nVERDICT : {'PARITE PORTEE (toutes les gardes C1+gate7 cassé->correct)' if allok else 'INCOMPLET'}")
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
