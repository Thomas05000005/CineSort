"""R8 F4 — DIFFERENTIEL R8-040 : résidu audio DD5.1 -> "DD5 1" pollue la query TMDb.

Vecteur : `name.replace('.',' ')` transforme "DD5.1" -> "DD5 1" AVANT _AUDIO_RESIDUE_RE
qui exige `\b[257][\s.][01]\b` — le `\b` échoue car le "5" est collé à "DD" (pas de
frontière de mot) -> résidu "DD5 1"/"DDP5 1"/"DD7 1" reste dans la query.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f4_scene_residue_diff.py
"""
from __future__ import annotations
import json

from cinesort.domain.scene_parser import parse_scene_title

CASES = [
    "The.Matrix.1999.DD5.1.1080p.BluRay.x264-GROUP",
    "Inception.2010.DDP5.1.2160p.WEB-DL.x265-RARBG",
    "Interstellar.2014.DD7.1.1080p.BluRay.x264",
    "Some.Movie.DD2.0.720p.HDTV.x264",
]
# Mots-résidus à ne PLUS voir dans le titre nettoyé (post-replace : espace).
RESIDUE_TOKENS = ["dd5 1", "ddp5 1", "dd7 1", "dd2 0", "dd5", "ddp5"]


def run():
    results = {}
    print("=== R8-040 : nettoyage scene title (résidu DD<canaux>) ===")
    all_clean = True
    for raw in CASES:
        title = parse_scene_title(raw).lower()
        residue = [tok for tok in RESIDUE_TOKENS if tok in title]
        clean = not residue
        all_clean = all_clean and clean
        print(f"  {raw}")
        print(f"     -> '{title}'   résidus={residue}   {'OK' if clean else 'POLLUÉ'}")
    results["R8040_no_dd_residue"] = all_clean

    # Garde anti-faux-positif : un vrai titre avec chiffres collés N'est PAS amputé.
    keep = parse_scene_title("21 Jump Street 2012 1080p BluRay x264-GROUP").lower()
    keep_ok = "21 jump street" in keep
    results["R8040_keeps_legit_title"] = keep_ok
    print(f"\n  garde '21 Jump Street' : '{keep}'  -> conservé={keep_ok}")

    allok = all(results.values())
    print(f"\nVERDICT : {'CORRIGE (résidu DD<canaux> retiré, titres légitimes préservés)' if allok else 'INCOMPLET'}")
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
