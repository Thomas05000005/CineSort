# V1-09 — PRAGMA integrity_check au démarrage

**Branche** : `feat/db-integrity-boot-check`
**Worktree** : `.claude/worktrees/feat-db-integrity-boot-check/`
**Effort** : 1h
**Priorité** : 🟠 MAJEUR
**Fichiers concernés** :
- `cinesort/infra/db/sqlite_store.py`
- `tests/test_db_integrity_boot.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/db-integrity-boot-check .claude/worktrees/feat-db-integrity-boot-check audit_qa_v7_6_0_dev_20260428
# Si déjà existe : git worktree add .claude/worktrees/feat-db-integrity-boot-check feat/db-integrity-boot-check
cd .claude/worktrees/feat-db-integrity-boot-check

pwd && git branch --show-current && git status
```

⚠ Cette mission a probablement déjà été commitée mais sur la mauvaise branche
(commit `cca9aaa` sur `fix/empty-state-quality-cta`). L'orchestrateur va
**cherry-pick ce commit sur la bonne branche** avant que tu commences. Vérifie
`git log --oneline | head -3`. Si le commit est déjà là → "déjà fait".

---

## RÈGLES GLOBALES

PROJET : CineSort, SQLite WAL.
RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT sqlite_store.py + nouveau test.

---

## MISSION

Une corruption volontaire du fichier .db ne déclenche aucune alerte au démarrage.
Avec 2000 users : corruption silencieuse possible (Win update kill, disk error).

### Étape 1 — Lire l'état actuel

Lis `cinesort/infra/db/sqlite_store.py`. Identifie la méthode `initialize()`.

### Étape 2 — Lire backup.py

Lis `cinesort/infra/db/backup.py`. Note les méthodes (pour suggérer restore).

### Étape 3 — Implémenter integrity_check

Avant les migrations dans `initialize()` :

```python
def _check_integrity(self) -> str:
    """Vérifie l'intégrité de la DB SQLite.
    Retourne 'ok' si OK, sinon le message d'erreur de PRAGMA integrity_check.
    """
    conn = self._get_connection()  # adapter au pattern existant
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        status = result[0] if result else "unknown"
        if status != "ok":
            logger.warning(
                "DB integrity check failed: %s. Path: %s. "
                "Consider restoring from backup.",
                status, self.db_path,
            )
        return status
    except sqlite3.DatabaseError as exc:
        logger.error("DB integrity check raised: %s", exc)
        return f"error: {exc}"
```

### Étape 4 — Exposer le flag

```python
@property
def integrity_status(self) -> str:
    return self._integrity_status
```

⚠ NE PAS toucher la couche UI ici.

### Étape 5 — Tests

Crée `tests/test_db_integrity_boot.py` :

```python
"""V1-M09 — DB integrity check au démarrage."""
from __future__ import annotations
import sqlite3, tempfile, unittest
from pathlib import Path
import sys; sys.path.insert(0, '.')
from cinesort.infra.db.sqlite_store import SQLiteStore


class IntegrityCheckBootTests(unittest.TestCase):
    def test_fresh_db_integrity_ok(self):
        tmp = tempfile.mkdtemp()
        store = SQLiteStore(Path(tmp) / "fresh.db")
        store.initialize()
        self.assertEqual(store.integrity_status, "ok")

    def test_corrupted_header_detected(self):
        tmp = tempfile.mkdtemp()
        db = Path(tmp) / "corrupt.db"
        SQLiteStore(db).initialize()
        with open(db, "r+b") as f:
            f.seek(0); f.write(b"BADBADBAD\x00\x00\x00\x00\x00\x00\x00")
        store = SQLiteStore(db)
        try:
            store.initialize()
            self.assertNotEqual(store.integrity_status, "ok")
        except (sqlite3.DatabaseError, RuntimeError):
            pass

    def test_corrupted_page_detected(self):
        tmp = tempfile.mkdtemp()
        db = Path(tmp) / "corrupt2.db"
        SQLiteStore(db).initialize()
        with open(db, "r+b") as f:
            f.seek(4096); f.write(b"\xFF" * 100)
        store = SQLiteStore(db)
        try:
            store.initialize()
            self.assertNotEqual(store.integrity_status, "ok")
        except (sqlite3.DatabaseError, RuntimeError):
            pass
```

### Étape 6 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_db_integrity_boot -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . | tail -3
```

### Étape 7 — Commit

`feat(db): integrity_check at startup with status flag (audit ID-Y-001)`

---

## LIVRABLES

Récap :
- Méthode `_check_integrity()` ajoutée
- Property `integrity_status` exposée
- Tests fresh + 2 cas corruption
- 0 régression
- 1 commit sur `feat/db-integrity-boot-check`
