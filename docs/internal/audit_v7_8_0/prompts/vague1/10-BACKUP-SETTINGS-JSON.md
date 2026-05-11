# V1-10 — Backup auto de settings.json (rotation 5)

**Branche** : `feat/settings-json-auto-backup`
**Worktree** : `.claude/worktrees/feat-settings-json-auto-backup/`
**Effort** : 1-2h
**Priorité** : 🟠 MAJEUR
**Fichiers concernés** :
- `cinesort/ui/api/settings_support.py` (uniquement la fonction d'écriture)
- `tests/test_settings_backup.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/settings-json-auto-backup .claude/worktrees/feat-settings-json-auto-backup audit_qa_v7_6_0_dev_20260428
# Si déjà existe : git worktree add .claude/worktrees/feat-settings-json-auto-backup feat/settings-json-auto-backup
cd .claude/worktrees/feat-settings-json-auto-backup

pwd && git branch --show-current && git status
```

⚠ Cette branche existe déjà avec un commit `cbabb9c feat(settings): auto backup`
qui appartient bien à cette mission, ET un commit parasite `a0abfdf feat(db): migration 020`
qui appartient à V1-08. **L'orchestrateur va nettoyer le commit parasite** avant
que tu commences. Vérifie `git log --oneline | head -5`. Si le commit V1-10 est
là (`cbabb9c` ou équivalent) → "déjà fait", pas besoin de refaire.

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT settings_support.py + nouveau test.

⚠ ATTENTION : settings_support.py est un GROS fichier (1221 lignes). La mission
V2-M01 va le refactorer. TON travail doit toucher UNIQUEMENT la fonction d'écriture
et NE PAS modifier `save_settings_payload()` (pour éviter conflit).

---

## MISSION

Settings v5 a auto-save 500ms. Si l'utilisateur fait une boulette, settings.json
corrompu, pas de récupération.

### Étape 1 — Lire l'état actuel

Lis `cinesort/ui/api/settings_support.py`. Identifie :
- La fonction d'écriture (probablement `write_settings()` ou `_persist_settings()`)
- Le path résolu vers settings.json

### Étape 2 — Implémenter le backup + rotation

Constantes :
```python
DEFAULT_SETTINGS_BACKUP_COUNT = 5
SETTINGS_BACKUP_PREFIX = ".bak."
```

Fonctions privées :
```python
def _backup_settings_before_write(settings_path: Path) -> Optional[Path]:
    """Crée un backup horodaté avant écriture."""
    if not settings_path.exists():
        return None
    try:
        json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None  # Skip backup d'un fichier déjà cassé
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = settings_path.parent / f"{settings_path.name}{SETTINGS_BACKUP_PREFIX}{ts}"
    try:
        shutil.copy2(settings_path, backup_path)
        return backup_path
    except OSError:
        return None


def _rotate_settings_backups(settings_path: Path, keep: int = DEFAULT_SETTINGS_BACKUP_COUNT) -> int:
    pattern = f"{settings_path.name}{SETTINGS_BACKUP_PREFIX}*"
    backups = sorted(
        settings_path.parent.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    deleted = 0
    for old in backups[keep:]:
        try:
            old.unlink()
            deleted += 1
        except OSError:
            pass
    return deleted
```

### Étape 3 — Hooker dans `write_settings()`

```python
def write_settings(payload: dict, ...) -> None:
    settings_path = ...

    # Audit ID-J-001 : backup auto + rotation
    _backup_settings_before_write(settings_path)
    _rotate_settings_backups(settings_path)

    # ... écriture existante ...
```

### Étape 4 — Endpoints de gestion (optionnel)

```python
def list_settings_backups(state_dir: Path) -> list[dict]: ...
def restore_settings_backup(state_dir: Path, backup_filename: str) -> bool: ...
```

NE PAS exposer dans cinesort_api.py — UI séparée plus tard.

### Étape 5 — Tests

Crée `tests/test_settings_backup.py` (cf prompt original pour code complet) avec
6 tests : créer, skip si invalide, rotation, liste, restore, path traversal.

### Étape 6 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_settings_backup -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest tests.test_settings* -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m ruff check . | tail -3
```

### Étape 7 — Commit

`feat(settings): auto backup with 5-rotation before each write (audit ID-J-001)`

---

## LIVRABLES

Récap :
- _backup_settings_before_write + _rotate_settings_backups ajoutés
- list_settings_backups + restore_settings_backup ajoutés
- Tests : 6 cas couverts
- 0 régression
- 1 commit sur `feat/settings-json-auto-backup`
