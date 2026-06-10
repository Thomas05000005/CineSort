"""Reset rapide DB scope test_library + recensement avant section 2."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

db = Path(os.environ["LOCALAPPDATA"]) / "CineSort" / "db" / "cinesort.sqlite"
print(f"DB: {db} exists={db.exists()}")

con = sqlite3.connect(str(db))
cur = con.cursor()

# Recense runs test_library
cur.execute("PRAGMA table_info(runs)")
print("cols runs:", [c[1] for c in cur.fetchall()])
cur.execute("SELECT * FROM runs WHERE root LIKE '%test_library%' LIMIT 50")
runs = cur.fetchall()
print(f"runs test_library AVANT reset: {len(runs)}")
for r in runs[:5]:
    print("  ", r)

# Delete runs + cascading (tri_etat_decisions, etc.) — best effort
run_ids = [r[0] for r in runs]
if run_ids:
    placeholders = ",".join("?" for _ in run_ids)
    # Trouve les tables avec colonne run_id
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in cur.fetchall()]
    for t in tables:
        try:
            cur.execute(f"PRAGMA table_info({t})")
            cols = [c[1] for c in cur.fetchall()]
            if "run_id" in cols:
                cur.execute(f"DELETE FROM {t} WHERE run_id IN ({placeholders})", run_ids)
                if cur.rowcount > 0:
                    print(f"  deleted {cur.rowcount} from {t}")
        except sqlite3.Error as e:
            print(f"  skip {t}: {e}")
    # done via cascading via run_id column; runs table itself uses run_id
    cur.execute(f"DELETE FROM runs WHERE run_id IN ({placeholders})", run_ids)
    print(f"  deleted {cur.rowcount} from runs (run_id key)")

# Purge probe_cache scope
try:
    cur.execute("DELETE FROM probe_cache WHERE LOWER(path) LIKE '%test_library%'")
    print(f"  deleted {cur.rowcount} from probe_cache")
except sqlite3.Error as e:
    print(f"  probe_cache: {e}")

con.commit()
con.close()
print("RESET DONE")
