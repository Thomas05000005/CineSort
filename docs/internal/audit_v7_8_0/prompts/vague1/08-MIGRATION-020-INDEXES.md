# V1-08 — Migration SQL 020 : indexes perf quality_reports

**Branche** : `feat/migration-020-indexes`
**Worktree** : `.claude/worktrees/feat-migration-020-indexes/`
**Effort** : 1-2h
**Priorité** : 🟠 MAJEUR
**Fichiers concernés** :
- `cinesort/infra/db/migrations/020_quality_reports_perf_indexes.sql` (nouveau)
- `tests/test_db_indexes.py` (nouveau)
- `tests/test_v7_foundations.py` (mise à jour version attendue 19→20)
- (si existant) `tests/test_api_bridge_lot3.py`

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/migration-020-indexes .claude/worktrees/feat-migration-020-indexes audit_qa_v7_6_0_dev_20260428
# Si déjà existe : git worktree add .claude/worktrees/feat-migration-020-indexes feat/migration-020-indexes
cd .claude/worktrees/feat-migration-020-indexes

pwd && git branch --show-current && git status
```

⚠ Cette branche existe déjà avec un commit parasite `8ba18bc feat(license)` qui
appartient à V1-01. **L'orchestrateur va nettoyer cette branche** avant que tu
commences. Vérifie `git log --oneline | head -3` : si tu vois ce commit parasite,
attends le cleanup.

---

## RÈGLES GLOBALES

PROJET : CineSort, SQLite WAL.
RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT migrations/020*.sql + tests listés.

---

## MISSION

L'audit perf a montré des SCAN sur GROUP BY tier et ORDER BY score sur
`quality_reports`. À 1M films, scaling pénalisant.

### Étape 1 — Comprendre l'état actuel

```bash
.venv313/Scripts/python.exe -c "
import tempfile; from pathlib import Path
import sys; sys.path.insert(0, '.')
from cinesort.infra.db.sqlite_store import SQLiteStore
import sqlite3
tmp = tempfile.mkdtemp(); db = Path(tmp)/'t.db'
SQLiteStore(db).initialize()
c = sqlite3.connect(db)
print('Schema version:', c.execute('PRAGMA user_version').fetchone()[0])
for r in c.execute('PRAGMA index_list(quality_reports)').fetchall(): print('IDX', r)
"
```

### Étape 2 — Lire le style des migrations

```bash
ls cinesort/infra/db/migrations/ | sort | tail -3
cat cinesort/infra/db/migrations/019_apply_pending_moves.sql
```

### Étape 3 — Lire migration_manager.py

Vérifier auto-découverte des migrations.

### Étape 4 — Créer la migration

Crée `cinesort/infra/db/migrations/020_quality_reports_perf_indexes.sql` :

```sql
-- Migration 020 : indexes de performance sur quality_reports
-- Audit perf 2026-05-01 : SCAN sur GROUP BY tier + ORDER BY score
-- Cible : bibliothèques 50k+ films, 2000 users en attente

CREATE INDEX IF NOT EXISTS idx_quality_reports_tier
    ON quality_reports(tier);

CREATE INDEX IF NOT EXISTS idx_quality_reports_score
    ON quality_reports(score DESC);
```

### Étape 5 — Mettre à jour les tests qui pin la version

```bash
grep -rn "schema_version.*19\|user_version.*19\|version.*= *19" tests/ 2>&1 | head -10
```

Pour chaque match, passe-le à 20.

### Étape 6 — Créer test_db_indexes.py

```python
"""Audit perf — vérifie que les indexes 020 sont créés et utilisés."""
from __future__ import annotations
import sqlite3, tempfile, time, unittest
from pathlib import Path
import sys; sys.path.insert(0, '.')
from cinesort.infra.db.sqlite_store import SQLiteStore


class QualityReportsIndexesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.db = Path(tmp) / "t.db"
        SQLiteStore(self.db).initialize()
        self.conn = sqlite3.connect(self.db)

    def test_idx_tier_exists(self):
        idxs = [r[1] for r in self.conn.execute("PRAGMA index_list(quality_reports)").fetchall()]
        self.assertIn("idx_quality_reports_tier", idxs)

    def test_idx_score_exists(self):
        idxs = [r[1] for r in self.conn.execute("PRAGMA index_list(quality_reports)").fetchall()]
        self.assertIn("idx_quality_reports_score", idxs)

    def test_group_by_tier_uses_index(self):
        for i in range(100):
            self.conn.execute(
                "INSERT INTO quality_reports (run_id, row_id, score, tier, reasons_json, metrics_json, profile_id, profile_version, ts) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (f"r{i//10}", f"row_{i}", i, ["gold","silver","bronze"][i%3], "[]", "{}", "default", 1, time.time())
            )
        self.conn.commit()
        plan = self.conn.execute("EXPLAIN QUERY PLAN SELECT tier, COUNT(*) FROM quality_reports GROUP BY tier").fetchall()
        plan_text = " ".join(str(r) for r in plan).lower()
        self.assertIn("idx_quality_reports_tier", plan_text)
```

### Étape 7 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_db_indexes -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest tests.test_v7_foundations -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . | tail -3
```

### Étape 8 — Commit

`feat(db): add migration 020 with idx_quality_reports_tier + score (perf scaling)`

---

## LIVRABLES

Récap :
- Migration 020 créée
- Schema version : 19 → 20
- Tests version mis à jour
- Test test_db_indexes.py ajouté
- 0 régression
- 1 commit sur `feat/migration-020-indexes`
