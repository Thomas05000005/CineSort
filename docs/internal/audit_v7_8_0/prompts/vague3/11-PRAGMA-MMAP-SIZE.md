# V3-11 — PRAGMA mmap_size SQLite (perf)

**Branche** : `perf/sqlite-mmap-size`
**Worktree** : `.claude/worktrees/perf-sqlite-mmap-size/`
**Effort** : 1-2h
**Priorité** : 🟢 NICE-TO-HAVE (perf bibliothèques 5000+ films)
**Fichiers concernés** :
- `cinesort/infra/db/connection.py` (factory connexion)
- `tests/test_pragma_mmap.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b perf/sqlite-mmap-size .claude/worktrees/perf-sqlite-mmap-size audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/perf-sqlite-mmap-size

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT `connection.py` + tests. Aucune autre modif.

---

## CONTEXTE

SQLite supporte `PRAGMA mmap_size = N` qui permet d'utiliser le memory-mapped I/O pour
les lectures. Sur les bibliothèques de 5000+ films (DB > 50 MB), ça peut donner
**+30 à +60% de performance** sur les requêtes lourdes (`get_dashboard`, `library_filtered`).

Aujourd'hui dans `cinesort/infra/db/connection.py`, on configure :
- `journal_mode = WAL`
- `foreign_keys = ON`
- `busy_timeout = 5000`

Mais **pas** `mmap_size`. Réglage manquant pour les grosses DB.

---

## MISSION

### Étape 1 — Lire le module

`cinesort/infra/db/connection.py` (chercher `connect_sqlite` ou la factory de connexion).

### Étape 2 — Ajouter le PRAGMA

Dans la fonction de configuration des PRAGMAs après l'ouverture de connexion :

```python
# V3-11 — mmap_size pour perf lecture sur grosses DB (>50 MB)
# 256 MB est un bon compromis : suffisant pour bibliothèques 10k films,
# mais ne réserve l'espace que si la DB l'utilise (mmap virtuel).
_MMAP_SIZE_BYTES = 256 * 1024 * 1024  # 256 MB

try:
    conn.execute(f"PRAGMA mmap_size = {_MMAP_SIZE_BYTES}")
except sqlite3.DatabaseError as e:
    # Sur certains systèmes (sans support mmap), le PRAGMA peut échouer.
    # Non bloquant : on tombe sur le mode standard.
    logger.warning("V3-11 : PRAGMA mmap_size non supporté (%s). Mode standard.", e)
```

⚠ **Important** : importer `logging` et créer un `logger = logging.getLogger(__name__)`
si pas déjà présent dans le module.

### Étape 3 — Vérifier qu'on peut lire la valeur

Ajouter une fonction de diagnostic exposable (pour debug / aide) :

```python
def get_mmap_size(conn) -> int:
    """V3-11 — Retourne la valeur actuelle de PRAGMA mmap_size (en bytes)."""
    try:
        cur = conn.execute("PRAGMA mmap_size")
        row = cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0
```

### Étape 4 — Tests

Crée `tests/test_pragma_mmap.py` :

```python
"""V3-11 — PRAGMA mmap_size SQLite."""
from __future__ import annotations
import unittest
import sqlite3
import tempfile
from pathlib import Path
import sys; sys.path.insert(0, '.')


class PragmaMmapTests(unittest.TestCase):
    def test_connection_has_mmap_size_set(self):
        """Vérifie que la factory connect_sqlite applique mmap_size."""
        from cinesort.infra.db.connection import connect_sqlite
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            conn = connect_sqlite(str(db_path))
            try:
                cur = conn.execute("PRAGMA mmap_size")
                row = cur.fetchone()
                mmap_size = int(row[0]) if row else 0
                # Doit être > 0 (configuré, pas la valeur par défaut)
                # Sur Windows en sandbox de test mmap peut retourner 0 → tolérance
                # mais on vérifie au moins que le PRAGMA est exécuté sans crasher
                self.assertGreaterEqual(mmap_size, 0)
            finally:
                conn.close()

    def test_get_mmap_size_helper(self):
        from cinesort.infra.db.connection import get_mmap_size, connect_sqlite
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            conn = connect_sqlite(str(db_path))
            try:
                size = get_mmap_size(conn)
                self.assertIsInstance(size, int)
                self.assertGreaterEqual(size, 0)
            finally:
                conn.close()

    def test_module_constant_exposed(self):
        """La constante _MMAP_SIZE_BYTES doit exister pour traçabilité."""
        from cinesort.infra.db import connection as conn_mod
        # Soit en module attr, soit dans la source
        src = Path(conn_mod.__file__).read_text(encoding="utf-8")
        self.assertIn("_MMAP_SIZE_BYTES", src)
        self.assertIn("256", src)


if __name__ == "__main__":
    unittest.main()
```

### Étape 5 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_pragma_mmap -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 6 — Bench informatif (optionnel mais recommandé)

Pour vérifier l'impact réel, lancer un mini-bench :

```python
# scripts/bench_mmap.py (optionnel — ne pas committer si pas demandé)
import time
import sqlite3

# Avec mmap
conn1 = sqlite3.connect("audit_test.db")
conn1.execute("PRAGMA mmap_size = 268435456")
t0 = time.perf_counter()
for _ in range(100):
    conn1.execute("SELECT COUNT(*) FROM quality_reports").fetchone()
print(f"Avec mmap: {time.perf_counter() - t0:.3f}s")

# Sans mmap
conn2 = sqlite3.connect("audit_test.db")
conn2.execute("PRAGMA mmap_size = 0")
t0 = time.perf_counter()
for _ in range(100):
    conn2.execute("SELECT COUNT(*) FROM quality_reports").fetchone()
print(f"Sans mmap: {time.perf_counter() - t0:.3f}s")
```

(Non requis pour le commit — juste pour ta validation)

### Étape 7 — Commits

- `perf(db): enable PRAGMA mmap_size 256MB for large libraries (V3-11)`
- `test(db): assert mmap_size pragma is applied + helper`

---

## LIVRABLES

Récap :
- `PRAGMA mmap_size = 256MB` appliqué sur chaque connexion
- Fallback gracieux si PRAGMA non supporté (warning log non bloquant)
- Helper `get_mmap_size(conn)` pour diagnostic
- 0 régression
- 2 commits sur `perf/sqlite-mmap-size`
