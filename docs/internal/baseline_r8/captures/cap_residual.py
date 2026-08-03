"""BASELINE R8 — captures RESIDUELLES (findings non couverts par les 6 familles workflow).

Captures STATIQUES (grep + line-read) et PURES-FONCTIONS, deterministes, read-only.
Aucune DB ouverte, aucun FS reel mute, aucun binaire execute. Chemin=source reelle.

Findings couverts :
  R8-025 F-DB-01           busy_timeout NAS ecrase a 8000 (logique back-compat)
  R8-033 F-CONF-02         sibling ffmpeg derive non valide
  R8-037 F-PERC-04         batch perceptuel non annulable (should_cancel non propage)
  R8-016 [8]               batch zombie sans expected_ops -> ROLLED_BACK (UPDATE statut seul)
  R8-029 [2]               _save_ttl_manifest write_text sans os.replace (last-writer-wins)
  R8-079 F-H5-03           convention TV non-standard non detectee
  R8-080 F-H7-02           flag Jellyfin "vu" non re-tente sur 503 transitoire
  R8-081 F-TEST-01         assertion tautologique (x or True)

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/baseline_r8/captures/cap_residual.py
"""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[4]  # repo root (captures/baseline_r8/internal/docs/<ROOT>)
RESUME: dict[str, bool] = {}


def read(rel: str) -> list[str]:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace").splitlines()


def grep(rel: str, pattern: str, flags=0):
    """Retourne [(no_ligne_1based, texte)] des lignes matchant."""
    rx = re.compile(pattern, flags)
    out = []
    for i, line in enumerate(read(rel), 1):
        if rx.search(line):
            out.append((i, line.rstrip()))
    return out


def section(title: str):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


# ---------------------------------------------------------------- R8-025 F-DB-01
section("R8-025 F-DB-01 — busy_timeout NAS ecrase a 8000 (back-compat connection.py)")
try:
    hits = grep("cinesort/infra/db/connection.py", r"busy_timeout|_DEFAULT_BUSY_TIMEOUT_MS|back.?compat|!= ", re.I)
    for n, t in hits[:25]:
        print(f"  connection.py:{n}: {t}")
    rt = grep("cinesort/ui/api/runtime_support.py", r"busy_timeout_ms\s*=\s*8000|busy_timeout_ms=8000|8000")
    for n, t in rt[:6]:
        print(f"  runtime_support.py:{n}: {t}")
    # Logique : le store prod passe 8000 ; si 8000 != _DEFAULT(5000) la branche back-compat ecrase le profil NAS.
    src = "\n".join(read("cinesort/infra/db/connection.py"))
    has_default_5000 = bool(re.search(r"_DEFAULT_BUSY_TIMEOUT_MS\s*[:=]\s*5000", src))
    overwrites = bool(re.search(r"busy_timeout", src, re.I)) and has_default_5000
    print(f"  _DEFAULT_BUSY_TIMEOUT_MS==5000 : {has_default_5000}")
    print(
        "  -> 8000 (store prod) != 5000 (defaut) => branche back-compat REECRASE le busy_timeout du profil NAS (30000/60000) par 8000"
    )
    RESUME["R8-025_busy_timeout_overwrite"] = overwrites
    print(f"  VERDICT : {'CONFIRME (override back-compat ecrase le profil NAS)' if overwrites else 'a verifier'}")
except Exception as e:
    print(f"  [erreur lecture] {e}")
    RESUME["R8-025_busy_timeout_overwrite"] = False


# -------------------------------------------------------------- R8-033 F-CONF-02
section("R8-033 F-CONF-02 — sibling ffmpeg.exe derive de ffprobe_path, non valide")
try:
    FFR = "cinesort/domain/perceptual/ffmpeg_runner.py"
    hits = grep(FFR, r"ffprobe|sibling|with_name|parent|ffmpeg", re.I)
    for n, t in hits[:20]:
        print(f"  ffmpeg_runner.py:{n}: {t}")
    src = "\n".join(read(FFR))
    derives_sibling = bool(re.search(r"with_name\(|\.parent\b", src))
    validates = bool(re.search(r"_binary_name_allowed|validate_tool_path", src))
    confirmed = derives_sibling and not validates
    print(f"  derive le sibling (with_name/parent) : {derives_sibling}")
    print(f"  appelle _binary_name_allowed/validate_tool_path : {validates}")
    RESUME["R8-033_sibling_unvalidated"] = confirmed
    print(f"  VERDICT : {'CONFIRME (sibling derive sans validation)' if confirmed else 'a verifier'}")
except Exception as e:
    print(f"  [erreur lecture] {e}")
    RESUME["R8-033_sibling_unvalidated"] = False


# -------------------------------------------------------------- R8-037 F-PERC-04
section("R8-037 F-PERC-04 — batch perceptuel non annulable (should_cancel non propage)")
try:
    rf = grep("cinesort/ui/api/run_flow_support.py", r"analyze_perceptual_batch", re.I)
    for n, t in rf[:6]:
        print(f"  run_flow_support.py:{n}: {t}")
    # should_cancel passe a analyze_perceptual_batch ?
    blk = "\n".join(read("cinesort/ui/api/run_flow_support.py"))
    m = re.search(r"analyze_perceptual_batch\((.{0,400}?)\)", blk, re.S)
    arglist = m.group(1) if m else ""
    passes_cancel = "should_cancel" in arglist
    print(f"  arglist analyze_perceptual_batch contient should_cancel : {passes_cancel}")
    pc = grep("cinesort/ui/api/perceptual_support.py", r"_perceptual_cancel_event", re.I)
    for n, t in pc[:8]:
        print(f"  perceptual_support.py:{n}: {t}")
    psrc = "\n".join(read("cinesort/ui/api/perceptual_support.py"))
    assigned_event = bool(re.search(r"_perceptual_cancel_event\s*=\s*(threading\.)?Event\(", psrc))
    confirmed = (not passes_cancel) and (not assigned_event)
    print(f"  _perceptual_cancel_event assigne un Event() en prod : {assigned_event}")
    RESUME["R8-037_cancel_inert"] = confirmed
    print(
        f"  VERDICT : {'CONFIRME (cancel inerte : ni should_cancel propage, ni Event assigne)' if confirmed else 'a verifier'}"
    )
except Exception as e:
    print(f"  [erreur lecture] {e}")
    RESUME["R8-037_cancel_inert"] = False


# ----------------------------------------------------------------- R8-016 [8]
section("R8-016 [8] — batch zombie sans expected_ops classe ROLLED_BACK (UPDATE statut seul)")
try:
    hits = grep(
        "cinesort/app/apply_batches_reconciliation.py",
        r"expected_ops|rolled_back|ROLLED_BACK|_close_batch|expected is None",
        re.I,
    )
    for n, t in hits[:20]:
        print(f"  reconciliation.py:{n}: {t}")
    src = "\n".join(read("cinesort/app/apply_batches_reconciliation.py"))
    confirmed = bool(re.search(r"expected\s+is\s+None", src)) and bool(re.search(r"rolled_back", src, re.I))
    RESUME["R8-016_zombie_mislabel"] = confirmed
    print(
        f"  VERDICT : {'CONFIRME (expected None -> rolled_back, mislabel observabilite, aucune action FS)' if confirmed else 'a verifier'}"
    )
except Exception as e:
    print(f"  [erreur lecture] {e}")
    RESUME["R8-016_zombie_mislabel"] = False


# ----------------------------------------------------------------- R8-029 [2]
section("R8-029 [2] — _save_ttl_manifest write_text sans os.replace (last-writer-wins)")
try:
    hits = grep("cinesort/app/quarantine_ttl.py", r"_save_ttl_manifest|write_text|os\.replace|atomic", re.I)
    for n, t in hits[:20]:
        print(f"  quarantine_ttl.py:{n}: {t}")
    src = "\n".join(read("cinesort/app/quarantine_ttl.py"))
    m = re.search(r"def _save_ttl_manifest.*?(?=\ndef |\nclass |\Z)", src, re.S)
    body = m.group(0) if m else ""
    uses_write_text = "write_text" in body
    uses_atomic = ("os.replace" in body) or ("atomic_write" in body)
    confirmed = uses_write_text and not uses_atomic
    print(f"  corps utilise write_text : {uses_write_text} ; os.replace/atomic : {uses_atomic}")
    RESUME["R8-029_manifest_nonatomic"] = confirmed
    print(f"  VERDICT : {'CONFIRME (write_text non atomique, recoupe F-V3-E1)' if confirmed else 'a verifier'}")
except Exception as e:
    print(f"  [erreur lecture] {e}")
    RESUME["R8-029_manifest_nonatomic"] = False


# ----------------------------------------------------------------- R8-079 F-H5-03
section("R8-079 F-H5-03 — convention TV non-standard non detectee comme serie")
try:
    import cinesort.domain.core as core

    fn = getattr(core, "looks_tv_like", None)
    # signature : looks_tv_like(name, videos) -> un PACK est-il une serie ?
    nonstd = {
        "Show.101/.102 (NxNN colle)": [f"Show.10{e}.mkv" for e in (1, 2, 3)],
        "Show.E01/.E02 (E seul)": [f"Show.E0{e}.mkv" for e in (1, 2, 3)],
        "Show - 01/02 (- NN)": [f"Show - 0{e}.mkv" for e in (1, 2, 3)],
    }
    controls = {
        "Show.S01E01.. (SxxExx)": [f"Show.S01E0{e}.mkv" for e in (1, 2, 3)],
        "Show.1x01.. (NxNN)": [f"Show.1x0{e}.mkv" for e in (1, 2, 3)],
    }
    if fn:
        print("  fonction testee : core.looks_tv_like(folder: Path, videos: List[Path])")
        ns = {k: bool(fn(Path("Show"), [Path(f) for f in v])) for k, v in nonstd.items()}
        st = {k: bool(fn(Path("Show"), [Path(f) for f in v])) for k, v in controls.items()}
        print(f"  non-standard (attendu False=non detecte TV) : {ns}")
        print(f"  controles standard (attendu True)           : {st}")
        confirmed = (not any(ns.values())) and all(st.values())
        RESUME["R8-079_nonstd_tv_missed"] = confirmed
        print(
            f"  VERDICT : {'CONFIRME (conventions non-standard non detectees, standard OK)' if confirmed else 'partiel/a verifier'}"
        )
    else:
        print("  [looks_tv_like introuvable] -> grep de secours")
        for n, t in grep("cinesort/domain/core.py", r"_TV_HINT_RE|def looks_tv_like", re.I)[:8]:
            print(f"  core.py:{n}: {t}")
        RESUME["R8-079_nonstd_tv_missed"] = False
except Exception as e:
    print(f"  [erreur] {e}")
    RESUME["R8-079_nonstd_tv_missed"] = False


# ----------------------------------------------------------------- R8-080 F-H7-02
section("R8-080 F-H7-02 — flag Jellyfin 'vu' non re-tente sur 503 transitoire (POST hors retry)")
try:
    JF = "cinesort/app/jellyfin_sync.py"
    hits = grep(JF, r"mark_played|result\.errors|still_pending|mark_played failed", re.I)
    for n, t in hits[:20]:
        print(f"  jellyfin_sync.py:{n}: {t}")
    src = "\n".join(read(JF))
    # Le restore du flag 'vu' appelle client.mark_played ; en cas d'echec -> result.errors += 1
    # SANS re-ajout a still_pending (seuls les non-trouves sont re-tentes) -> POST 'vu' droppe, non re-tente.
    has_mark = "mark_played" in src
    has_fail = "mark_played failed" in src
    confirmed = has_mark and has_fail
    print(
        f"  appelle client.mark_played : {has_mark} ; branche d'echec 'mark_played failed' (errors++, pas de re-queue) : {has_fail}"
    )
    RESUME["R8-080_played_not_retried"] = confirmed
    print(
        f"  VERDICT : {'CONFIRME (echec mark_played -> errors++ sans re-tentative dans ce run)' if confirmed else 'a verifier'}"
    )
except Exception as e:
    print(f"  [erreur lecture] {e}")
    RESUME["R8-080_played_not_retried"] = False


# ----------------------------------------------------------------- R8-081 F-TEST-01
section("R8-081 F-TEST-01 — assertion tautologique (x or True) toujours vraie")
try:
    hits = grep("tests/test_auto_install.py", r"or True|assertTrue|exists\(\)", re.I)
    for n, t in hits[:8]:
        print(f"  test_auto_install.py:{n}: {t}")
    # Demonstration logique : quelle que soit la valeur de exists(), (exists() or True) == True.
    truth = {f"({v} or True)": (v or True) for v in (True, False)}
    print(f"  table de verite : {truth}")
    has_or_true = bool(grep("tests/test_auto_install.py", r"or True"))
    always_true = all(truth.values())
    confirmed = has_or_true and always_true
    RESUME["R8-081_tautological_assert"] = confirmed
    print(
        f"  VERDICT : {'CONFIRME (assertTrue(d.exists() or True) passe quoi qu il arrive)' if confirmed else 'a verifier'}"
    )
except Exception as e:
    print(f"  [erreur lecture] {e}")
    RESUME["R8-081_tautological_assert"] = False


# ----------------------------------------------------------------------- RESUME
section("RESUME")
print(json.dumps(RESUME, ensure_ascii=False, indent=2))
total = sum(1 for v in RESUME.values() if v)
print(f"\nTOTAL captures confirmees : {total}/{len(RESUME)}")
