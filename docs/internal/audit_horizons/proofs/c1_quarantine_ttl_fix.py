"""C1 P0 — Repro LIVE du correctif TTL quarantaine (bug 314 st_mtime).

Bug 314 (CRITICAL REAL 2/2) : le TTL se basait sur st_mtime ; apply preserve le
mtime d'origine -> un film vieux de 100j etait purge des le 1er cycle (perte).
Correctif : manifest `.cinesort_ttl_manifest.json` (premiere observation = now).

Ce harnais (dry_run, AUCUNE suppression reelle, state_dir JETABLE) tranche :
  T1  fichier mtime=100j, 1re observation  -> NE DOIT PAS etre purge (deleted=0)
       (comportement OLD st_mtime aurait purge : age 100j > 30 -> ROUGE).
  T2 (controle positif / falsifiabilite) : manifest force first_seen=100j ago
       -> DOIT etre purge (deleted>=1) -> prouve que le harnais peut virer ROUGE.
  T3  ttl_days=0 -> no-op (deleted=0) meme si first_seen ancien.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/audit_horizons/proofs/c1_quarantine_ttl_fix.py
"""
from __future__ import annotations
import json
import tempfile
import time
from pathlib import Path

from cinesort.app.quarantine_ttl import (
    purge_review_bucket, REVIEW_FOLDER_NAME, _TTL_MANIFEST_NAME, _ttl_manifest_path,
)


class _Cfg:
    def __init__(self, root): self.root = str(root)


def _make_bucket():
    tmp = Path(tempfile.mkdtemp(prefix="cs_qttl_"))
    review = tmp / REVIEW_FOLDER_NAME
    sub = review / "_leftovers"
    sub.mkdir(parents=True)
    f = sub / "OldFilm.2019.1080p.mkv"
    f.write_bytes(b"x" * 1024)
    # mtime = il y a 100 jours (vieil encode preserve par le move)
    old = time.time() - 100 * 86400.0
    import os
    os.utime(f, (old, old))
    return tmp, review, f


def run():
    results = {}

    # T1 : 1re observation, mtime 100j -> ne doit PAS purger (fix manifest)
    tmp, review, f = _make_bucket()
    cfg = _Cfg(tmp)
    r1 = purge_review_bucket(cfg, ttl_days=30, dry_run=True)
    results["T1_first_seen_mtime100j"] = {
        "deleted": r1.get("deleted"), "considered": r1.get("considered"),
        "VERDICT": "FIX OK (non purge)" if r1.get("deleted") == 0 else "REGRESSION (purge premature)",
    }

    # T2 : controle positif -> manifest first_seen = 100j ago => doit purger
    tmp2, review2, f2 = _make_bucket()
    cfg2 = _Cfg(tmp2)
    rel = f2.relative_to(review2).as_posix()
    _ttl_manifest_path(review2).write_text(
        json.dumps({rel: time.time() - 100 * 86400.0}), encoding="utf-8"
    )
    r2 = purge_review_bucket(cfg2, ttl_days=30, dry_run=True)
    results["T2_manifest_first_seen_100j_POSITIF"] = {
        "deleted": r2.get("deleted"), "considered": r2.get("considered"),
        "VERDICT": "harnais FALSIFIABLE OK (purge quand TTL vrai)" if r2.get("deleted", 0) >= 1
                   else "INERTE (n'a pas purge un fichier vraiment expire)",
    }

    # T3 : ttl_days=0 -> no-op meme avec first_seen ancien
    tmp3, review3, f3 = _make_bucket()
    cfg3 = _Cfg(tmp3)
    rel3 = f3.relative_to(review3).as_posix()
    _ttl_manifest_path(review3).write_text(
        json.dumps({rel3: time.time() - 100 * 86400.0}), encoding="utf-8"
    )
    r3 = purge_review_bucket(cfg3, ttl_days=0, dry_run=True)
    results["T3_ttl0_noop"] = {
        "deleted": r3.get("deleted"), "ok": r3.get("ok"),
        "VERDICT": "no-op OK" if r3.get("deleted") == 0 else "BUG (purge malgre ttl=0)",
    }

    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    run()
