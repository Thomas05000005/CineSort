# V2-10 — Migrer JellyfinClient vers make_session_with_retry

**Branche** : `feat/jellyfin-client-retry-migration`
**Worktree** : `.claude/worktrees/feat-jellyfin-client-retry-migration/`
**Effort** : 2-3h
**Priorité** : 🟠 IMPORTANT (audit ID-ROB-001)
**Fichiers concernés** :
- `cinesort/infra/jellyfin_client.py`
- `tests/test_jellyfin_client.py` (existant — adapter mocks)
- `tests/test_jellyfin_retry_integration.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/jellyfin-client-retry-migration .claude/worktrees/feat-jellyfin-client-retry-migration audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-jellyfin-client-retry-migration

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT jellyfin_client.py + ses tests.

---

## CONTEXTE

Idem V2-09 mais pour `JellyfinClient`. Helper `make_session_with_retry` créé en V1-11.

---

## MISSION

### Étape 1 — Lire les modules

- `cinesort/infra/_http_utils.py` (helper)
- `cinesort/infra/jellyfin_client.py` (à migrer)

### Étape 2 — Migrer la Session

Remplace `requests.Session()` par :
```python
from cinesort.infra._http_utils import make_session_with_retry
self._session = make_session_with_retry(
    user_agent="CineSort/7.6 JellyfinClient",
    max_attempts=3,
    backoff_base=0.5,
)
```

### Étape 3 — Conserver auth + retry watched-state existant

⚠ JellyfinClient a un **retry custom déjà existant** sur le watched-state restore
(H-11 audit, 5 retries backoff exponentiel cap 60s, total max 135s). Ce retry custom
n'est PAS le même que le retry de la Session (3 retries 0.5s pour erreurs réseau
transitoires).

→ Garde le retry custom pour watched-state, ET ajoute la Session avec retry pour TOUS
les autres appels (validate_connection, refresh_library, get_libraries, etc.).

### Étape 4 — Vérifier auth header

Le header `Authorization: MediaBrowser Token="..."` doit toujours fonctionner. La Session
le préserve (headers persistent entre requêtes).

### Étape 5 — Adapter tests

Lis `tests/test_jellyfin_client.py`. Si mocks ciblent `requests.get` direct → migrer.

### Étape 6 — Test retry integration

Crée `tests/test_jellyfin_retry_integration.py` :

```python
"""V2-10 — Vérifie JellyfinClient utilise retry helper."""
from __future__ import annotations
import unittest
import sys; sys.path.insert(0, '.')
from cinesort.infra.jellyfin_client import JellyfinClient


class JellyfinRetryTests(unittest.TestCase):
    def test_session_uses_retry_helper(self):
        client = JellyfinClient(url="http://test", api_key="fake")
        adapter = client._session.get_adapter("http://test")
        retry = adapter.max_retries
        self.assertEqual(retry.total, 3)
        self.assertIn(503, retry.status_forcelist)

    def test_user_agent_set(self):
        client = JellyfinClient(url="http://test", api_key="fake")
        self.assertIn("CineSort", client._session.headers["User-Agent"])
        self.assertIn("Jellyfin", client._session.headers["User-Agent"])
```

### Étape 7 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_jellyfin_client tests.test_jellyfin_retry_integration -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 8 — Commits

- `refactor(jellyfin): use make_session_with_retry (audit ID-ROB-001)`
- `test(jellyfin): add retry integration test`

---

## LIVRABLES

Récap :
- JellyfinClient utilise make_session_with_retry
- Retry watched-state custom conservé
- Auth header préservé
- 0 régression
- 2 commits sur `feat/jellyfin-client-retry-migration`
