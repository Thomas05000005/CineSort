"""R8 F5 — DIFFÉRENTIEL R8-056 : forme canonique perceptuelle servie à la modale.

La modale (perceptual-modal.js) lit TOP-LEVEL d.grain_analysis.verdict_label,
d.width, d.height, d.display_tier, d.breakdown[]. Le rapport DB les imbrique
(metrics.grain_analysis, metrics.video_perceptual.resolution, global_score_v2_payload).
AVANT : ces champs n'étaient PAS top-level -> grain « — », dimensions 0, breakdown vide.
APRÈS : _flatten_perceptual_for_modal les lève + dérive breakdown des category_scores.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f5_perceptual_flatten_diff.py
"""
from cinesort.ui.api.perceptual_support import _flatten_perceptual_for_modal

# Rapport DB réaliste (forme _parse_perceptual_row : tout imbriqué).
report = {
    "run_id": "r1", "row_id": "x1", "global_tier_v2": "gold", "global_score_v2": 82.0,
    "metrics": {
        "grain_analysis": {"verdict_label": "Grain naturel préservé", "verdict": "natural"},
        "video_perceptual": {"resolution": {"width": 3840, "height": 2160}},
    },
    "global_score_v2_payload": {
        "category_scores": [
            {"name": "video", "value": 88.0, "weight": 0.60, "tier": "gold"},
            {"name": "audio", "value": 75.0, "weight": 0.35, "tier": "silver"},
            {"name": "coherence", "value": 95.0, "weight": 0.05, "tier": "platinum"},
        ],
    },
}

# Ce que la modale lit AVANT le flatten (sur le rapport brut)
def modal_reads(d):
    return {
        "grain": (d.get("grain_analysis") or {}).get("verdict_label", "—"),
        "width": d.get("width") or 0,
        "display_tier": d.get("display_tier") or d.get("global_tier_v2") or "unknown",
        "breakdown_len": len(d.get("breakdown") or []),
    }

avant = modal_reads(dict(report))  # copie : pas encore aplati
apres = modal_reads(_flatten_perceptual_for_modal(report))

print("=== Ce que la modale obtient ===")
print(f"  champ            AVANT                          APRÈS")
print(f"  grain_verdict    {avant['grain']!r:30} {apres['grain']!r}")
print(f"  width            {avant['width']!r:30} {apres['width']!r}")
print(f"  display_tier     {avant['display_tier']!r:30} {apres['display_tier']!r}")
print(f"  breakdown rows   {avant['breakdown_len']!r:30} {apres['breakdown_len']!r}")
ok = (avant["grain"] == "—" and apres["grain"] != "—"
      and avant["width"] == 0 and apres["width"] == 3840
      and avant["breakdown_len"] == 0 and apres["breakdown_len"] == 3)
# Vérifie la forme d'une ligne breakdown (contrat modale : component/weight/value_label/status/points)
row0 = (_flatten_perceptual_for_modal(report).get("breakdown") or [{}])[0]
contract_ok = all(k in row0 for k in ("component", "weight", "value_label", "status", "points"))
print(f"\n  1re ligne breakdown : {row0}")
print(f"  VERDICT : {'CORRIGE' if ok and contract_ok else 'INCOMPLET'} (codec reste « — » : non stocké dans le rapport perceptuel)")
