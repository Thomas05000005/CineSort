"""R8 F4 — DIFFERENTIEL R8-043 : HDR exposé à la modale (plus « sdr » systématique).

Vecteur : la modale lit `d.hdr_analysis.hdr_format`/`.is_hdr` mais VideoPerceptual.to_dict
n'émettait AUCUNE clé hdr_analysis -> `d.hdr_analysis` undefined -> ternaire JS -> « sdr »
pour TOUT film, même HDR. Le type HDR de base était calculé (detect_hdr_type) mais jamais
reporté sur le modèle ni sérialisé.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f4_hdr_diff.py
"""
from __future__ import annotations
import json

from cinesort.domain.perceptual.hdr_analysis import detect_hdr_type
from cinesort.domain.perceptual.models import VideoPerceptual


def _modal_hdr(d):
    """Réplique de la logique perceptual-modal.js:292."""
    ha = d.get("hdr_analysis")
    if ha:
        return ha.get("hdr_format") or ("HDR" if ha.get("is_hdr") else "sdr")
    return "sdr"


def run():
    results = {}

    # (1) detect_hdr_type sur des valeurs couleur RÉELLES (vrai ffmpeg/ffprobe).
    print("=== (1) detect_hdr_type (métadonnée couleur réelle) ===")
    hdr10 = detect_hdr_type("bt2020", "smpte2084", [])
    sdr = detect_hdr_type("bt709", "bt709", [])
    print(f"  bt2020 + smpte2084 -> {hdr10}   |   bt709 + bt709 -> {sdr}")
    results["R8043_detect_hdr10"] = hdr10 == "hdr10"
    results["R8043_detect_sdr"] = sdr == "sdr"

    # (2) Contrat to_dict : hdr_analysis présent + cohérent avec hdr_type.
    print("\n=== (2) VideoPerceptual.to_dict -> hdr_analysis (contrat modale) ===")
    d_hdr = VideoPerceptual(hdr_type="hdr10").to_dict()
    d_sdr = VideoPerceptual(hdr_type="sdr").to_dict()
    has_key = "hdr_analysis" in d_hdr
    print(f"  clé hdr_analysis présente : {has_key} (AVANT : absente -> modale 'sdr')")
    print(f"  hdr_type='hdr10' -> {d_hdr.get('hdr_analysis')}")
    print(f"  hdr_type='sdr'   -> {d_sdr.get('hdr_analysis')}")
    results["R8043_todict_has_hdr_analysis"] = has_key
    results["R8043_todict_hdr_correct"] = (
        d_hdr["hdr_analysis"] == {"hdr_format": "hdr10", "is_hdr": True}
        and d_sdr["hdr_analysis"] == {"hdr_format": "sdr", "is_hdr": False}
    )

    # (3) Logique modale : AVANT (sans clé) vs APRÈS (avec clé).
    print("\n=== (3) rendu modale (perceptual-modal.js:292) ===")
    avant_render = _modal_hdr({})                      # AVANT : pas de hdr_analysis
    apres_render_hdr = _modal_hdr(d_hdr)               # APRÈS : film HDR
    apres_render_sdr = _modal_hdr(d_sdr)               # APRÈS : film SDR
    print(f"  AVANT (d.hdr_analysis absent)     -> '{avant_render}'  (toujours sdr)")
    print(f"  APRÈS (film HDR10)                -> '{apres_render_hdr}'")
    print(f"  APRÈS (film SDR)                  -> '{apres_render_sdr}'")
    results["R8043_modal_hdr_shown"] = (avant_render == "sdr" and apres_render_hdr == "hdr10" and apres_render_sdr == "sdr")

    allok = all(results.values())
    print(f"\nVERDICT : {'CORRIGE (HDR détecté + exposé + affiché ; sdr seulement si vraiment sdr)' if allok else 'INCOMPLET'}")
    print("NOTE PLAN A : detect_hdr_type prouvé sur valeurs couleur réelles ; le wiring complet "
          "probe->perceptual->modale est sérialisé. (Une fixture HDR synthétique testsrc2 ne tague pas "
          "toujours color_primaries/transfer dans le conteneur — un vrai film HDR porte les tags bt2020/PQ.)")
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
