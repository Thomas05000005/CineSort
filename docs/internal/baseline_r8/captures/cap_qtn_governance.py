"""R8-002 / F-QTN-GOV — capture baseline INSTRUMENTEE (resout le placeholder cap_qtn_governance).

CAUSE RACINE (verifiee dans le code, 2026-06-17) :
  - L'apply ecrit les buckets quarantaine conflict/duplicate/leftover sous
    <run_dir>/_review  (apply_support.py:1489 : run_review_root = run_paths.run_dir/"_review").
  - Le TTL de quarantaine (quarantine_ttl.review_root) ne gouverne QUE cfg.root/_review.
  - La retention-runs `clean_old_runs(state_dir, keep_last=20)` (infra/state.py:105)
    fait shutil.rmtree(run_dir) sur les vieux runs -> DETRUIT <run_dir>/_review ENTIER,
    donc les ORIGINAUX quarantines (vrais fichiers films deplaces sur collision/doublon),
    AVANT toute revue utilisateur et QUEL QUE SOIT le TTL configure (30 j ignore).
  => PERTE DE DONNEES NON RECUPERABLE.

Ce harnais appelle le VRAI `state.clean_old_runs` sur une FIXTURE jetable et mesure si
un original quarantine survit. Aucun effet de bord hors tempdir, jamais la vraie biblio.

AVANT (code casse)  : l'original quarantine est SUPPRIME (rmtree du run_dir) -> perdu.
APRES (R8-002 fixe) : l'original quarantine est PRESERVE (relocate hors retention).

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/baseline_r8/captures/cap_qtn_governance.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from cinesort.infra import state as state_mod


def run():
    tmp = Path(tempfile.mkdtemp(prefix="cs_qtn_gov_"))
    state_dir = tmp / "state"
    runs = state_dir / "runs"
    runs.mkdir(parents=True)

    # 3 runs, tries DESC par nom : keep_last=2 garde [0301,0201], supprime [0101].
    # Le plus vieux (0101) contient une quarantaine NON REVUE = un original deplace.
    for name in ("20260301_120000", "20260201_120000"):
        (runs / name).mkdir()
    old = runs / "20260101_120000"
    qfile = old / "_review" / "_conflicts" / "Film (2020)" / "__from__" / "Saga" / "original_movie.mkv"
    qfile.parent.mkdir(parents=True)
    qfile.write_bytes(b"PRECIEUX-ORIGINAL-QUARANTINE" * 10)

    keep_last = 2
    before_exists = qfile.exists()
    before_size = qfile.stat().st_size if before_exists else 0

    # VRAI appel de prod (retention-runs).
    state_mod.clean_old_runs(state_dir, keep_last=keep_last)

    old_dir_still = old.exists()
    qfile_still_at_origin = qfile.exists()
    # Recherche d'une copie PRESERVEE n'importe ou sous state_dir (hors le run supprime).
    preserved = [p for p in state_dir.rglob("original_movie.mkv") if old not in p.parents and p != qfile]
    data_lost = (not qfile_still_at_origin) and (len(preserved) == 0)

    print("=== R8-002 F-QTN-GOV — gouvernance TTL quarantaine vs retention-runs ===")
    print(f"  keep_last                                 : {keep_last}")
    print(f"  original quarantine AVANT (taille)        : {before_exists} ({before_size} o)")
    print(f"  run_dir vieux encore present apres clean  : {old_dir_still}")
    print(f"  original encore a son emplacement d'origine: {qfile_still_at_origin}")
    print(f"  copie PRESERVEE ailleurs sous state_dir   : {[str(p.relative_to(state_dir)) for p in preserved]}")
    print()
    if data_lost:
        print("VERDICT : CASSE (PERTE DE DONNEES) — l'original quarantine est DETRUIT par la retention-runs,")
        print("          sans preservation, quel que soit le TTL configure.")
    else:
        print("VERDICT : GOUVERNE — l'original quarantine est PRESERVE (pas de perte).")
    print(
        "RESUME:",
        json.dumps(
            {
                "data_lost": data_lost,
                "qfile_at_origin": qfile_still_at_origin,
                "preserved_copies": len(preserved),
                "old_run_dir_removed": not old_dir_still,
            },
            ensure_ascii=False,
        ),
    )


if __name__ == "__main__":
    run()
