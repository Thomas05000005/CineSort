"""PREUVE F-META-01 : round-trip plan.jsonl perd nfo_runtime (run_data_support.row_from_json ne le parse pas)."""
import sys, os, dataclasses; sys.path.insert(0, os.getcwd())
from cinesort.domain import core
from cinesort.app.plan_support_core import plan_row_to_jsonable
from cinesort.ui.api.run_data_support import row_from_json
fields={f.name:f for f in dataclasses.fields(core.PlanRow)}
def marker(f):
    n=f.name; t=str(f.type)
    if n=="candidates": return [core.Candidate(title="X",year=2020,source="name",score=0.9)]
    if n=="kind": return "tv_episode"
    if "List[str]" in t: return [f"mk_{n}"]
    if "int" in t.lower(): return 4242
    if "bool" in t.lower(): return True
    return f"mk_{n}"
row=core.PlanRow(**{n:marker(f) for n,f in fields.items()})
a=dataclasses.asdict(row); b=dataclasses.asdict(row_from_json(plan_row_to_jsonable(row)))
lost=[k for k in a if k!="candidates" and a[k]!=b[k]]
print("champs perdus au reload:", lost)
assert lost==["nfo_runtime"], f"attendu [nfo_runtime], obtenu {lost}"
print("CONFIRME")
