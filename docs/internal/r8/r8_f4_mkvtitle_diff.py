"""R8 F4 — DIFFERENTIEL R8-044 : faux signal mkv_title_mismatch sur release-names.

Vecteur : égalité exacte case-insensitive container_title vs proposed_title -> 88 %
des release-names à points ("Inception.2010.1080p.x264-SPARKS" != "Inception")
flaguaient `mkv_title_mismatch` = faux signal qui noie les vrais conflits.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f4_mkvtitle_diff.py
"""

from __future__ import annotations

import json

from cinesort.domain.mkv_title_check import check_container_title


def _avant(container, proposed):
    """Réplique de l'ancienne logique : égalité exacte case-insensitive."""
    if not container or not container.strip():
        return []
    ct = container.strip()
    pt = (proposed or "").strip()
    if not pt:
        return []
    if ct.lower() == pt.lower():
        return []
    return ["mkv_title_mismatch"]


# (container_title, proposed_title, devrait_flaguer ?)
CORPUS = [
    # Release-names du MÊME film -> NE doivent PAS flaguer (faux positifs avant).
    ("Inception.2010.1080p.BluRay.x264-SPARKS", "Inception", False),
    ("The.Dark.Knight.2008.2160p.UHD.BluRay.x265-TERMINAL", "The Dark Knight", False),
    ("Interstellar.2014.1080p.BluRay.DTS.x264-GROUP", "Interstellar", False),
    ("Mad_Max_Fury_Road_2015_720p_BrRip", "Mad Max Fury Road", False),
    ("Blade.Runner.2049.2017.1080p.WEB-DL.DDP5.1.x264", "Blade Runner 2049", False),
    ("The Matrix", "The Matrix", False),  # identique
    # VRAIS conflits -> DOIVENT flaguer (avant ET après).
    ("Mon Film", "Inception", True),
    ("rip.by.XxX", "The Matrix", True),
    ("The.Matrix.1999.1080p.BluRay.x264-SPARKS", "Inception", True),  # autre film
    ("The Office", "The Matrix", True),
]


def run():
    av_flags = 0
    ap_flags = 0
    av_false_pos = 0
    ap_false_pos = 0
    ap_correct = 0
    print("=== R8-044 — corpus container_title vs proposed_title ===")
    print(f"{'container':52} {'proposed':22} {'attendu':8} {'AVANT':6} {'APRÈS':6}")
    for ct, pt, should_flag in CORPUS:
        av = bool(_avant(ct, pt))
        ap = bool(check_container_title(ct, pt))
        av_flags += av
        ap_flags += ap
        if av and not should_flag:
            av_false_pos += 1
        if ap and not should_flag:
            ap_false_pos += 1
        if ap == should_flag:
            ap_correct += 1
        print(f"{ct[:52]:52} {pt[:22]:22} {str(should_flag):8} {'FLAG' if av else '-':6} {'FLAG' if ap else '-':6}")

    total = len(CORPUS)
    print(f"\n  AVANT : {av_false_pos} faux positifs / {total}")
    print(f"  APRÈS : {ap_false_pos} faux positifs / {total} ; {ap_correct}/{total} verdicts corrects")
    results = {
        "R8044_avant_has_false_positives": av_false_pos > 0,
        "R8044_apres_zero_false_positives": ap_false_pos == 0,
        "R8044_apres_all_correct": ap_correct == total,
    }
    allok = all(results.values())
    print(f"\nVERDICT : {'CORRIGE (faux positifs scene éliminés, vrais conflits conservés)' if allok else 'INCOMPLET'}")
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
