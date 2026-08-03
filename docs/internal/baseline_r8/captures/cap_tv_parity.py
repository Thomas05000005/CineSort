"""BASELINE R8 — cap_tv_parity : ecarts de parite du chemin APPLY TV vs FILM.

Capture l'etat CASSE (au sens "fonctionnalites du chemin film absentes ou
divergentes sur le chemin TV") de `apply_tv_episode` (cinesort.app.apply_core)
compare a `apply_single` / `merge_dir_safe` / `_apply_loop`. Chaque finding est
soit COMPORTEMENTAL (fixture tempfile JETABLE, on appelle la vraie fonction de
prod en mode reel dry_run=False), soit STRUCTUREL (grep / lecture de ligne reelle
verifiee contre la source courante au moment de l'ecriture du script).

Template repris : docs/internal/audit_horizons/proofs/v5_tv_apply_repro.py
(pattern Cfg stub + Row stub + record_op/log captureurs). LECTURE SEULE sur le
code de prod ; aucun effet de bord hors du tempdir ; la vraie bibliotheque n'est
JAMAIS touchee.

Findings couverts (RESUME json final, une cle par finding -> True == CASSE) :
  F-V4B-TV1        sidecars gardent le nom source (apply_core.py:2253) -> orphelins
  F-V4B-TV2        ops journalisees sans src_sha1/src_size (2241)
  F-V5-TV3         NOOP skip sur target_file.exists() sans compare contenu (2232)
  F-V6-TV-SIDECOLL sidecar DROPPE si dst existe deja (2253-2254)
  F-V6-TV-MAXPATH  killswitch uniquement target_file, pas le chemin interne (2222)
  F-V6-TV-DRYRUN   atomic_move + record_op tous deux dans `if not dry_run` (2238)
  F-V6-TV-MKDIR    target_dir.mkdir brut, pas mkdir_counted/op journalisee (2239)
  F-V6-TV-UIEDIT   noms depuis row.proposed_* pas new_title/new_year UI (1567)
  F-V7-TV-LEFTOVERS pas de leftovers_root / pas de cleanup source (bloc TV)
  F-V6-TV-ANIME    season=None -> Saison 00 / S00 (tv_helpers.py:95, cite :92)
  F-V6-UNDO-CASE   undo case-only classe CONFLIT (apply_support.py:442)
  F-H3-02          sidecar except pass avale tout sans WARN (2263)

Usage (depuis la racine repo) :
  PYTHONPATH=. .venv313/Scripts/python.exe \
    docs/internal/baseline_r8/captures/cap_tv_parity.py \
    > docs/internal/baseline_r8/captures/cap_tv_parity.out.txt 2>&1
"""

from __future__ import annotations

import inspect
import json
import re
import tempfile
from pathlib import Path

import cinesort.domain.core as core
from cinesort.app import apply_core
from cinesort.app.apply_core import apply_tv_episode

# Racine repo deduite de l'emplacement du script (.../docs/internal/baseline_r8/captures).
REPO_ROOT = Path(__file__).resolve().parents[4]
APPLY_CORE = REPO_ROOT / "cinesort" / "app" / "apply_core.py"
TV_HELPERS = REPO_ROOT / "cinesort" / "domain" / "tv_helpers.py"
APPLY_SUPPORT = REPO_ROOT / "cinesort" / "ui" / "api" / "apply_support.py"


# --------------------------------------------------------------------------
# Stubs (template v5_tv_apply_repro.py)
# --------------------------------------------------------------------------
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
        self.kind = kw.get("kind", "tv_episode")


def _mk_apply_env(cfg, folder, row, dry_run):
    res = core.ApplyResult()
    logs, ops = [], []

    def log(level, msg):
        logs.append((level, msg))

    def record_op(op):
        ops.append(dict(op) if isinstance(op, dict) else {"raw": str(op)})

    apply_tv_episode(cfg, folder, row, dry_run=dry_run, log=log, res=res, record_op=record_op)
    return res, logs, ops


def _read_line(path: Path, lineno: int) -> str:
    try:
        return path.read_text(encoding="utf-8").splitlines()[lineno - 1]
    except (OSError, IndexError):
        return "<introuvable>"


def _find_line(path: Path, needle: str, start: int = 1) -> int:
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(lines[start - 1 :], start=start):
        if needle in ln:
            return i
    return -1


def _verify_anchor(path: Path, cited: int, needle: str) -> tuple[int, bool, str]:
    """Verifie le needle a la ligne citee ; sinon localise la vraie ligne."""
    cited_txt = _read_line(path, cited)
    if needle in cited_txt:
        return cited, True, cited_txt
    real = _find_line(path, needle)
    return real, False, (_read_line(path, real) if real > 0 else "<introuvable>")


# ==========================================================================
def run():
    resume = {}
    drift = {}

    print("=" * 74)
    print("BASELINE R8 — cap_tv_parity : parite APPLY TV vs FILM (etat CASSE)")
    print("=" * 74)
    print(f"repo_root = {REPO_ROOT}")
    print()

    # ----------------------------------------------------------------------
    # BLOC COMPORTEMENTAL #1 — fixture TV reelle (TV1, TV2, TV3, MKDIR, DRYRUN)
    # ----------------------------------------------------------------------
    tmp = Path(tempfile.mkdtemp(prefix="cs_tvparity_"))
    root = tmp / "lib"
    folder = root / "_inbox"
    folder.mkdir(parents=True)

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

    before = sorted(str(p.relative_to(tmp)) for p in root.rglob("*") if p.is_file())
    res, logs, ops = _mk_apply_env(cfg, folder, row, dry_run=False)
    after = sorted(str(p.relative_to(tmp)) for p in root.rglob("*") if p.is_file())

    vids = [p for p in root.rglob("*") if p.suffix.lower() in cfg.video_exts]
    subs = [p for p in root.rglob("*") if p.suffix.lower() in {".srt", ".nfo"}]
    video_stem = vids[0].stem if vids else None
    orphaned = [p for p in subs if p.stem != video_stem]

    print("--- BLOC COMPORTEMENTAL #1 : apply_tv_episode(dry_run=False) ---")
    print("AVANT:", before)
    print("APRES:", after)
    print()

    # F-V4B-TV1 : sidecars suivent-ils le stem video cible ?
    ln, ok, txt = _verify_anchor(APPLY_CORE, 2253, "dst_side = target_dir / sidecar.name")
    drift["F-V4B-TV1"] = (2253, ln, ok)
    tv1 = video_stem is not None and len(orphaned) > 0
    resume["F-V4B-TV1"] = tv1
    print("[F-V4B-TV1] sidecars orphelins (gardent le nom source)")
    print(f"  ancre apply_core.py L{ln} (cite 2253, verifie={ok}): {txt.strip()}")
    print(f"  stem video cible : {video_stem!r}")
    print(f"  sidecars ORPHELINS (stem != video) : {[p.name for p in orphaned]}")
    print(f"  => CASSE={tv1}\n")

    # F-V4B-TV2 : ops journalisees portent-elles src_sha1/src_size ?
    ln, ok, txt = _verify_anchor(APPLY_CORE, 2241, "record_apply_op(")
    drift["F-V4B-TV2"] = (2241, ln, ok)
    move_ops = [o for o in ops if (o.get("op_type") or o.get("type")) == "MOVE_FILE"]
    any_hash = any(o.get("src_sha1") for o in ops)
    tv2 = len(move_ops) > 0 and not any_hash
    resume["F-V4B-TV2"] = tv2
    print("[F-V4B-TV2] ops MOVE_FILE sans src_sha1/src_size")
    print(f"  ancre apply_core.py L{ln} (cite 2241, verifie={ok}): {txt.strip()}")
    for o in ops:
        keys = sorted(o.keys())
        print(
            f"    op type={o.get('op_type') or o.get('type')} keys={keys} "
            f"src_sha1={o.get('src_sha1', '<absent>')} src_size={o.get('src_size', '<absent>')}"
        )
    print(f"  => CASSE={tv2}\n")

    # F-V6-TV-MKDIR : la creation target_dir est-elle journalisee (op MKDIR) ?
    ln, ok, txt = _verify_anchor(APPLY_CORE, 2239, "target_dir.mkdir(parents=True, exist_ok=True)")
    drift["F-V6-TV-MKDIR"] = (2239, ln, ok)
    mkdir_ops = [o for o in ops if (o.get("op_type") or o.get("type")) == "MKDIR"]
    target_dir_created = any(p.is_dir() for p in root.rglob("Saison*"))
    mkdir_broken = target_dir_created and len(mkdir_ops) == 0
    resume["F-V6-TV-MKDIR"] = mkdir_broken
    print("[F-V6-TV-MKDIR] target_dir.mkdir brut, aucune op MKDIR journalisee")
    print(f"  ancre apply_core.py L{ln} (cite 2239, verifie={ok}): {txt.strip()}")
    print(f"  dossier Saison cree : {target_dir_created} | ops MKDIR journalisees : {len(mkdir_ops)}")
    print(f"  => CASSE={mkdir_broken}\n")

    # ----------------------------------------------------------------------
    # BLOC COMPORTEMENTAL #2 — F-V5-TV3 : NOOP sur target.exists() sans compare contenu
    # ----------------------------------------------------------------------
    tmp2 = Path(tempfile.mkdtemp(prefix="cs_tvparity_noop_"))
    root2 = tmp2 / "lib"
    folder2 = root2 / "_inbox"
    folder2.mkdir(parents=True)
    src2 = "Showname.S01E02.1080p.WEB.x264-GRP"
    # Source = contenu NEUF (plus complet / different bitrate)
    src_video = folder2 / f"{src2}.mkv"
    src_video.write_bytes(b"NEW-HIGH-QUALITY-BYTES" * 500)

    # Cible deja en place avec un contenu DIFFERENT (ancien fichier corrompu/tronque)
    cfg2 = Cfg(root2)
    target_dir2 = root2 / "Showname (2020)" / "Saison 01"
    target_dir2.mkdir(parents=True)
    target_file2 = target_dir2 / "S01E02 - Deuxieme.mkv"
    target_file2.write_bytes(b"OLD-TRUNCATED")  # contenu different + taille differente

    row2 = Row(
        video=f"{src2}.mkv",
        proposed_title="Showname",
        proposed_year=2020,
        tv_season=1,
        tv_episode=2,
        tv_episode_title="Deuxieme",
        tv_series_name="Showname",
    )
    res2, logs2, ops2 = _mk_apply_env(cfg2, folder2, row2, dry_run=False)

    ln, ok, txt = _verify_anchor(APPLY_CORE, 2232, "if target_file.exists():")
    drift["F-V5-TV3"] = (2232, ln, ok)
    src_still_there = src_video.exists()
    target_unchanged = target_file2.read_bytes() == b"OLD-TRUNCATED"
    sizes_differ = src_video.stat().st_size != len(b"OLD-TRUNCATED")
    skipped_noop = res2.skipped > 0
    tv3 = skipped_noop and src_still_there and target_unchanged and sizes_differ
    resume["F-V5-TV3"] = tv3
    print("--- BLOC COMPORTEMENTAL #2 : NOOP sur target.exists() ---")
    print("[F-V5-TV3] skip NOOP sans comparaison de contenu (source meilleure ignoree)")
    print(f"  ancre apply_core.py L{ln} (cite 2232, verifie={ok}): {txt.strip()}")
    print(f"  res.skipped={res2.skipped} skip_reasons={dict(res2.skip_reasons)}")
    print(f"  source NEUVE encore en place : {src_still_there} (taille {src_video.stat().st_size})")
    print(f"  cible ANCIENNE inchangee     : {target_unchanged} (taille {len(b'OLD-TRUNCATED')})")
    print(f"  tailles differentes (preuve contenu different) : {sizes_differ}")
    print(f"  => CASSE={tv3}\n")

    # ----------------------------------------------------------------------
    # BLOC COMPORTEMENTAL #3 — F-V6-TV-SIDECOLL : sidecar droppe si dst existe deja
    # ----------------------------------------------------------------------
    tmp3 = Path(tempfile.mkdtemp(prefix="cs_tvparity_sidecoll_"))
    root3 = tmp3 / "lib"
    folder3 = root3 / "_inbox"
    folder3.mkdir(parents=True)
    src3 = "Showname.S01E03.1080p.WEB.x264-GRP"
    (folder3 / f"{src3}.mkv").write_bytes(b"vid" * 200)
    (folder3 / f"{src3}.srt").write_text("nouveau-sous-titre-correct\n", encoding="utf-8")

    cfg3 = Cfg(root3)
    # Pre-positionne un .srt cible avec un contenu DIFFERENT au NOM DE DESTINATION
    # REEL du sidecar. Comme le chemin TV garde le nom SOURCE du sidecar (TV1,
    # L2253 dst_side = target_dir / sidecar.name), la collision doit porter sur
    # le stem source, pas sur le stem realigne de la video. On ne pre-place PAS
    # la video cible (sinon NOOP-skip global avant d'atteindre les sidecars).
    target_dir3 = root3 / "Showname (2020)" / "Saison 01"
    target_dir3.mkdir(parents=True)
    dst_srt = target_dir3 / f"{src3}.srt"  # = dst_side.name attendu par L2253
    dst_srt.write_text("ANCIEN-SOUS-TITRE-DESYNC\n", encoding="utf-8")

    row3 = Row(
        video=f"{src3}.mkv",
        proposed_title="Showname",
        proposed_year=2020,
        tv_season=1,
        tv_episode=3,
        tv_episode_title="Troisieme",
        tv_series_name="Showname",
    )
    res3, logs3, ops3 = _mk_apply_env(cfg3, folder3, row3, dry_run=False)

    ln, ok, txt = _verify_anchor(APPLY_CORE, 2254, "if not dst_side.exists():")
    drift["F-V6-TV-SIDECOLL"] = (2254, ln, ok)
    src_srt_orphan = (folder3 / f"{src3}.srt").exists()  # reste en source = droppe
    dst_srt_unchanged = dst_srt.read_text(encoding="utf-8") == "ANCIEN-SOUS-TITRE-DESYNC\n"
    # Aucun bucket conflits-sidecar TV : la nouvelle piste correcte est perdue.
    no_keepboth = sum(1 for o in ops3 if (o.get("op_type") or o.get("type")) == "MOVE_FILE") <= 1
    sidecoll = src_srt_orphan and dst_srt_unchanged
    resume["F-V6-TV-SIDECOLL"] = sidecoll
    print("--- BLOC COMPORTEMENTAL #3 : sidecar droppe si dst existe ---")
    print("[F-V6-TV-SIDECOLL] le .srt source est abandonne, aucun keep-both")
    print(f"  ancre apply_core.py L{ln} (cite 2253/2254, verifie={ok}): {txt.strip()}")
    print(f"  dst_side attendu (nom SOURCE)          : {src3}.srt")
    print(f"  .srt source orphelin (reste en _inbox) : {src_srt_orphan}")
    print(f"  .srt cible DESYNC conserve tel quel    : {dst_srt_unchanged}")
    print(f"  un seul MOVE journalise (video, pas le sidecar) : {no_keepboth}")
    print("  (chemin film: keep-both via conflicts_sidecars_root -> ici aucun bucket)")
    print(f"  => CASSE={sidecoll}\n")

    # ----------------------------------------------------------------------
    # BLOC COMPORTEMENTAL #4 — F-V6-TV-DRYRUN : dry_run ne journalise aucune op
    # ----------------------------------------------------------------------
    tmp4 = Path(tempfile.mkdtemp(prefix="cs_tvparity_dry_"))
    root4 = tmp4 / "lib"
    folder4 = root4 / "_inbox"
    folder4.mkdir(parents=True)
    src4 = "Showname.S01E04.1080p.WEB.x264-GRP"
    (folder4 / f"{src4}.mkv").write_bytes(b"vid" * 100)
    (folder4 / f"{src4}.srt").write_text("x\n", encoding="utf-8")
    cfg4 = Cfg(root4)
    row4 = Row(
        video=f"{src4}.mkv",
        proposed_title="Showname",
        proposed_year=2020,
        tv_season=1,
        tv_episode=4,
        tv_episode_title="Quatre",
        tv_series_name="Showname",
    )
    files_before_dry = sorted(str(p.relative_to(tmp4)) for p in root4.rglob("*") if p.is_file())
    res4, logs4, ops4 = _mk_apply_env(cfg4, folder4, row4, dry_run=True)
    files_after_dry = sorted(str(p.relative_to(tmp4)) for p in root4.rglob("*") if p.is_file())

    ln, ok, txt = _verify_anchor(APPLY_CORE, 2238, "if not dry_run:")
    drift["F-V6-TV-DRYRUN"] = (2238, ln, ok)
    no_ops_in_dry = len(ops4) == 0
    fs_untouched = files_before_dry == files_after_dry
    counter_bumped = res4.moves > 0  # res.moves += 1 est HORS du if not dry_run
    dryrun_broken = no_ops_in_dry and counter_bumped
    resume["F-V6-TV-DRYRUN"] = dryrun_broken
    print("--- BLOC COMPORTEMENTAL #4 : dry_run ---")
    print("[F-V6-TV-DRYRUN] atomic_move + record_op tous deux sous `if not dry_run`")
    print(f"  ancre apply_core.py L{ln} (cite 2238, verifie={ok}): {txt.strip()}")
    print(f"  ops journalisees en dry_run : {len(ops4)} (FS inchange : {fs_untouched})")
    print(f"  res.moves bumpe meme en dry_run : {counter_bumped} (res.moves={res4.moves})")
    print(f"  => CASSE (aucune op planifiee mais compteur bumpe)={dryrun_broken}\n")

    # ----------------------------------------------------------------------
    # BLOC STRUCTUREL — F-V6-TV-MAXPATH : killswitch only target_file vs film (inner)
    # ----------------------------------------------------------------------
    print("--- BLOC STRUCTUREL ---")
    ln_tv, ok_tv, txt_tv = _verify_anchor(APPLY_CORE, 2222, "check_path_length_killswitch(str(target_file))")
    # Chemin film: double check dst + chemin interne le plus long.
    film_ln = _find_line(APPLY_CORE, "_candidate_inner_path = str(dst")
    film_check_ln = _find_line(APPLY_CORE, "check_path_length_killswitch(_candidate_inner_path)")
    drift["F-V6-TV-MAXPATH"] = (2222, ln_tv, ok_tv)
    tv_single_check = "_candidate_inner" not in txt_tv  # TV ne checke que target_file
    film_double_check = film_check_ln > 0
    maxpath_broken = tv_single_check and film_double_check
    resume["F-V6-TV-MAXPATH"] = maxpath_broken
    print("[F-V6-TV-MAXPATH] killswitch TV ne couvre pas le chemin interne le plus long")
    print(f"  TV   apply_core.py L{ln_tv} (cite 2222, verifie={ok_tv}): {txt_tv.strip()}")
    print(f"  FILM apply_core.py L{film_ln}: {_read_line(APPLY_CORE, film_ln).strip()}")
    print(f"  FILM apply_core.py L{film_check_ln}: {_read_line(APPLY_CORE, film_check_ln).strip()}")
    print(f"  TV check unique (pas d'inner-path) : {tv_single_check}")
    print(f"  => CASSE={maxpath_broken}\n")

    # F-V6-TV-UIEDIT : dispatch TV ignore new_title/new_year (override UI)
    ln_disp, ok_disp, txt_disp = _verify_anchor(APPLY_CORE, 1567, 'if row.kind == "tv_episode":')
    drift["F-V6-TV-UIEDIT"] = (1567, ln_disp, ok_disp)
    # Source de verite : la fonction apply_tv_episode lit row.proposed_*, jamais new_title.
    tv_src = inspect.getsource(apply_tv_episode)
    reads_proposed = "row.proposed_title" in tv_src and "row.proposed_year" in tv_src
    ignores_new = "new_title" not in tv_src and "new_year" not in tv_src
    # Le dispatch passe new_title/new_year a apply_single mais RIEN a apply_tv_episode.
    loop_src = inspect.getsource(apply_core._apply_loop) if hasattr(apply_core, "_apply_loop") else ""
    if not loop_src:
        # fallback : lire le bloc dispatch autour de la ligne TV.
        block = "\n".join(APPLY_CORE.read_text(encoding="utf-8").splitlines()[ln_disp - 1 : ln_disp + 40])
        loop_src = block
    tv_call = re.search(r"apply_tv_episode\((.*?)\)", loop_src, re.S)
    single_call = re.search(r"apply_single\((.*?)\)", loop_src, re.S)
    tv_passes_no_override = bool(tv_call) and "new_title" not in (tv_call.group(1) if tv_call else "")
    single_passes_override = bool(single_call) and "new_title" in (single_call.group(1) if single_call else "")
    uiedit_broken = reads_proposed and ignores_new and tv_passes_no_override and single_passes_override
    resume["F-V6-TV-UIEDIT"] = uiedit_broken
    print("[F-V6-TV-UIEDIT] apply TV lit row.proposed_* et ignore l'override UI new_title/new_year")
    print(f"  dispatch apply_core.py L{ln_disp} (cite 1567, verifie={ok_disp}): {txt_disp.strip()}")
    print(f"  apply_tv_episode lit row.proposed_* : {reads_proposed} | ignore new_*: {ignores_new}")
    print(f"  dispatch -> apply_tv_episode sans new_title : {tv_passes_no_override}")
    print(f"  dispatch -> apply_single AVEC new_title     : {single_passes_override}")
    print(f"  => CASSE={uiedit_broken}\n")

    # F-V7-TV-LEFTOVERS : aucun leftovers_root / aucun cleanup source dans le bloc TV
    tv_lines = tv_src.splitlines()
    has_leftovers = any("leftovers" in ln.lower() for ln in tv_lines)
    has_source_cleanup = any(
        kw in tv_src for kw in ("rmdir", "shutil.rmtree", "move_leftovers", "delete_empty", "source_dirs_deleted")
    )
    # apply_tv_episode n'accepte meme pas le param leftovers_root.
    sig = inspect.signature(apply_tv_episode)
    has_leftovers_param = "leftovers_root" in sig.parameters
    single_sig = inspect.signature(apply_core.apply_single)
    single_has_leftovers = "leftovers_root" in single_sig.parameters
    leftovers_broken = (
        (not has_leftovers) and (not has_source_cleanup) and (not has_leftovers_param) and single_has_leftovers
    )
    resume["F-V7-TV-LEFTOVERS"] = leftovers_broken
    print("[F-V7-TV-LEFTOVERS] le chemin TV n'a ni leftovers_root ni nettoyage source")
    print(f"  apply_tv_episode signature params : {list(sig.parameters)}")
    print(f"  param leftovers_root present (TV)   : {has_leftovers_param}")
    print(f"  param leftovers_root present (FILM) : {single_has_leftovers}")
    print(f"  mot-cle 'leftovers' dans le corps TV : {has_leftovers}")
    print(f"  cleanup source (rmdir/rmtree/...) dans TV : {has_source_cleanup}")
    print(f"  => CASSE={leftovers_broken}\n")

    # F-V6-TV-ANIME : season=None pour "Episode N" -> Saison 00 / S00
    # cite tv_helpers.py:92 (commentaire) ; vrai assignement = ligne suivante.
    cited_anime = 92
    real_anime = _find_line(TV_HELPERS, "season = None")
    anime_ok = real_anime == cited_anime
    drift["F-V6-TV-ANIME"] = (cited_anime, real_anime, anime_ok)
    # Verifie aussi le rendu S00 dans apply_tv_episode (season tombe a 0 -> S00 / Saison 00).
    renders_s00 = 'f"Saison {season:02d}" if season else "Saison 00"' in tv_src
    anime_broken = real_anime > 0 and renders_s00
    resume["F-V6-TV-ANIME"] = anime_broken
    print("[F-V6-TV-ANIME] 'Episode N' sans saison -> season=None -> Saison 00 / S00")
    print(f"  tv_helpers.py cite L{cited_anime} (commentaire): {_read_line(TV_HELPERS, cited_anime).strip()}")
    print(f"  tv_helpers.py REEL L{real_anime} (assignement) : {_read_line(TV_HELPERS, real_anime).strip()}")
    print(f"  apply_tv_episode rend 'Saison 00' si season falsy : {renders_s00}")
    print(f"  => CASSE={anime_broken}  (DRIFT ligne citee {cited_anime} -> reelle {real_anime})\n")

    # F-V6-UNDO-CASE : undo case-only classe CONFLIT (target_path.exists() True sur Windows)
    ln_undo, ok_undo, txt_undo = _verify_anchor(APPLY_SUPPORT, 442, "if target_path.exists():")
    drift["F-V6-UNDO-CASE"] = (442, ln_undo, ok_undo)
    # Le bloc CONFLIT marque FAILED + deplace vers undo_conflicts_root, pas de garde case-only.
    block = "\n".join(APPLY_SUPPORT.read_text(encoding="utf-8").splitlines()[ln_undo - 1 : ln_undo + 40])
    marks_conflict = "Conflit cible existante" in block and 'undo_status="FAILED"' in block
    no_caseonly_guard = "casefold" not in block and ".lower()" not in block and "name_eq_fs" not in block
    undo_case_broken = (ln_undo > 0) and marks_conflict and no_caseonly_guard
    resume["F-V6-UNDO-CASE"] = undo_case_broken
    print("[F-V6-UNDO-CASE] undo case-only classe CONFLIT (pas de garde insensible a la casse)")
    print(f"  apply_support.py L{ln_undo} (cite 442, verifie={ok_undo}): {txt_undo.strip()}")
    print(f"  bloc marque FAILED + 'Conflit cible existante' : {marks_conflict}")
    print(f"  aucune garde case-only dans le bloc : {no_caseonly_guard}")
    print(f"  => CASSE={undo_case_broken}\n")

    # F-H3-02 : except (PermissionError, OSError): pass avale tout, aucun WARN
    ln_h3, ok_h3, txt_h3 = _verify_anchor(APPLY_CORE, 2263, "except (PermissionError, OSError):")
    drift["F-H3-02"] = (2263, ln_h3, ok_h3)
    body_lines = APPLY_CORE.read_text(encoding="utf-8").splitlines()
    next_line = body_lines[ln_h3].strip() if ln_h3 < len(body_lines) else ""
    is_bare_pass = next_line == "pass"
    # Aucun log("WARN"...) dans le try-sidecar (lignes 2250..2264 approx).
    sidecar_block = "\n".join(body_lines[ln_h3 - 15 : ln_h3 + 1])
    no_warn_logged = 'log("WARN"' not in sidecar_block and "log('WARN'" not in sidecar_block
    h3_broken = is_bare_pass and no_warn_logged
    resume["F-H3-02"] = h3_broken
    print("[F-H3-02] except sidecar avale PermissionError/OSError sans WARN (pass nu)")
    print(f"  apply_core.py L{ln_h3} (cite 2263, verifie={ok_h3}): {txt_h3.strip()}")
    print(f"  ligne suivante == 'pass' nu : {is_bare_pass} ({next_line!r})")
    print(f"  aucun log WARN dans le bloc sidecar : {no_warn_logged}")
    print(f"  => CASSE={h3_broken}\n")

    # ----------------------------------------------------------------------
    # RESUME
    # ----------------------------------------------------------------------
    drift_report = {k: {"cited": c, "real": r, "verified": ok} for k, (c, r, ok) in drift.items() if not ok}
    print("=" * 74)
    print("RESUME:", json.dumps(resume, ensure_ascii=False, sort_keys=True))
    print("DRIFT (lignes citees != reelles):", json.dumps(drift_report, ensure_ascii=False))
    n_broken = sum(1 for v in resume.values() if v)
    print(f"TOTAL: {n_broken}/{len(resume)} findings reproduisent l'etat CASSE.")
    print("=" * 74)


if __name__ == "__main__":
    run()
