"""Analyse les rows du plan : detection unicode/emoji/brackets/long-path."""

from __future__ import annotations

import json
import sys
from pathlib import Path

RUN_DIR = Path(sys.argv[1])
plan = RUN_DIR / "plan.jsonl"
rows = []
with open(plan, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            rows.append(json.loads(line))

print(f"Total rows: {len(rows)}")
print()
print("=== ROWS A INSPECTER (tricky paths) ===")
tricky_keywords = ("Amelie", "Foret", "Chihiro", "Long Path", "ðŸŽ¬", "imdbid", "tmdb", "Ruffian", "Lea", "qui finit")
for r in rows:
    folder = r.get("folder", "")
    if any(k in folder for k in tricky_keywords):
        print(f"- folder: {folder}")
        print(f"  proposed_title: {r.get('proposed_title')!r}")
        print(f"  proposed_year:  {r.get('proposed_year')}")
        print(f"  proposed_source: {r.get('proposed_source')}")
        print(f"  confidence: {r.get('confidence')} ({r.get('confidence_label')})")
        print(f"  warning_flags: {r.get('warning_flags')}")
        print()

print("=== STATS GLOBALES ===")
sources = {}
confs = {"high": 0, "medium": 0, "low": 0, "other": 0}
flags = {}
for r in rows:
    sources[r.get("proposed_source")] = sources.get(r.get("proposed_source"), 0) + 1
    c = r.get("confidence_label") or "other"
    confs[c if c in confs else "other"] = confs.get(c if c in confs else "other", 0) + 1
    for fl in r.get("warning_flags") or []:
        flags[fl] = flags.get(fl, 0) + 1
print("Source distribution:", sources)
print("Confidence distribution:", confs)
print("Warning flags:", flags)
