"""R8 F2-d — DIFFERENTIEL round-trip PlanRow (R8-027 nfo_runtime + R8-090 source_root jumeau).

Baseline (casse) : meta_roundtrip_planrow.out.txt (row_from_json perd nfo_runtime).
Les DEUX deserialiseurs perdaient un champ DIFFERENT (asdict serialise les deux) :
  - run_data_support.row_from_json : perdait nfo_runtime (R8-027).
  - plan_support_core.plan_row_from_jsonable : perdait source_root (R8-090, jumeau).

Apres fix : chaque deserialiseur preserve les DEUX champs.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f2d_roundtrip_diff.py
"""
from __future__ import annotations
import dataclasses
import json

from cinesort.domain import core
from cinesort.app.plan_support_core import plan_row_to_jsonable, plan_row_from_jsonable
from cinesort.ui.api.run_data_support import row_from_json


def _build_row():
    fields = {f.name: f for f in dataclasses.fields(core.PlanRow)}

    def marker(f):
        n, t = f.name, str(f.type)
        if n == "candidates":
            return [core.Candidate(title="X", year=2020, source="name", score=0.9)]
        if n == "kind":
            return "tv_episode"
        if "List[str]" in t:
            return [f"mk_{n}"]
        if "int" in t.lower():
            return 4242
        if "bool" in t.lower():
            return True
        return f"mk_{n}"

    return core.PlanRow(**{n: marker(f) for n, f in fields.items()})


def run():
    row = _build_row()
    a = dataclasses.asdict(row)
    serialized = plan_row_to_jsonable(row)

    # Deserialiseur 1 : row_from_json (R8-027)
    b1 = dataclasses.asdict(row_from_json(serialized))
    lost1 = [k for k in a if k != "candidates" and a[k] != b1[k]]

    # Deserialiseur 2 : plan_row_from_jsonable (R8-090)
    b2 = dataclasses.asdict(plan_row_from_jsonable(serialized))
    lost2 = [k for k in a if k != "candidates" and a[k] != b2[k]]

    results = {
        "R8027_row_from_json_nfo_runtime_preserve": "nfo_runtime" not in lost1,
        "R8090_plan_row_from_jsonable_source_root_preserve": "source_root" not in lost2,
    }
    print("=== R8-027 (row_from_json) ===")
    print(f"  champs perdus au reload : {lost1} (AVANT contenait 'nfo_runtime' ; attendu sans)")
    print(f"  nfo_runtime reload      : {b1.get('nfo_runtime')} (attendu 4242)")
    print("\n=== R8-090 (plan_row_from_jsonable, jumeau) ===")
    print(f"  champs perdus au reload : {lost2} (AVANT contenait 'source_root' ; attendu sans)")
    print(f"  source_root reload      : {b2.get('source_root')} (attendu 'mk_source_root')")

    allok = all(results.values())
    print(f"\nVERDICT : {'CORRIGE (les 2 deserialiseurs preservent nfo_runtime ET source_root)' if allok else 'INCOMPLET'}")
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
