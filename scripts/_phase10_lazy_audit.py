"""Phase 10 v7.8.0 — Audit lazy imports detect cycle hotspots."""
import re
from pathlib import Path

lazy_count = {}
for f in Path('cinesort').rglob('*.py'):
    txt = f.read_text(encoding='utf-8')
    for ln in txt.splitlines():
        if re.match(r'^[ \t]+(import |from )cinesort\.', ln):
            fn = str(f).replace('\\', '/')
            lazy_count[fn] = lazy_count.get(fn, 0) + 1
total = sum(lazy_count.values())
print(f'lazy imports cinesort.X: {total} total in {len(lazy_count)} files')
top = sorted(lazy_count.items(), key=lambda x: -x[1])[:15]
for fn, n in top:
    print(f'  {n:3d}  {fn}')
