# V2-11 — Migrer PlexClient vers make_session_with_retry

**Branche** : `feat/plex-client-retry-migration`
**Worktree** : `.claude/worktrees/feat-plex-client-retry-migration/`
**Effort** : 2-3h
**Priorité** : 🟠 IMPORTANT (audit ID-ROB-001)
**Fichiers concernés** :
- `cinesort/infra/plex_client.py`
- `tests/test_plex_client.py` (si existant — adapter mocks)
- `tests/test_plex_retry_integration.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/plex-client-retry-migration .claude/worktrees/feat-plex-client-retry-migration audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-plex-client-retry-migration

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT plex_client.py + ses tests.

---

## CONTEXTE

Idem V2-09/V2-10 mais pour `PlexClient`. Helper `make_session_with_retry` créé en V1-11.

Plex utilise auth via header `X-Plex-Token`.

---

## MISSION

### Étape 1 — Lire les modules

- `cinesort/infra/_http_utils.py` (helper)
- `cinesort/infra/plex_client.py` (à migrer)

### Étape 2 — Migrer la Session

Remplace `requests.Session()` par :
```python
from cinesort.infra._http_utils import make_session_with_retry
self._session = make_session_with_retry(
    user_agent="CineSort/7.6 PlexClient",
    max_attempts=3,
    backoff_base=0.5,
)
# Setter le header Plex token sur la session
self._session.headers["X-Plex-Token"] = token
```

### Étape 3 — Vérifier toutes les usages

```bash
grep -n "requests\." cinesort/infra/plex_client.py
```

Tous les appels HTTP doivent passer par `self._session`.

### Étape 4 — Tests

Lis tests existants et adapte si mocks ciblent `requests.get` direct.

Crée `tests/test_plex_retry_integration.py` :

```python
"""V2-11 — Vérifie PlexClient utilise retry helper."""
from __future__ import annotations
import unittest
import sys; sys.path.insert(0, '.')
from cinesort.infra.plex_client import PlexClient


class PlexRetryTests(unittest.TestCase):
    def test_session_uses_retry_helper(self):
        client = PlexClient(url="http://test:32400", token="fake")
        adapter = client._session.get_adapter("http://test:32400")
        retry = adapter.max_retries
        self.assertEqual(retry.total, 3)
        self.assertIn(503, retry.status_forcelist)

    def test_user_agent_set(self):
        client = PlexClient(url="http://test:32400", token="fake")
        self.assertIn("CineSort", client._session.headers["User-Agent"])
        self.assertIn("Plex", client._session.headers["User-Agent"])

    def test_plex_token_header_set(self):
        client = PlexClient(url="http://test:32400", token="my-token-123")
        self.assertEqual(client._session.headers.get("X-Plex-Token"), "my-token-123")
```

### Étape 5 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_plex_client tests.test_plex_retry_integration 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 6 — Commits

- `refactor(plex): use make_session_with_retry (audit ID-ROB-001)`
- `test(plex): add retry integration test`

---

## LIVRABLES

Récap :
- PlexClient utilise make_session_with_retry
- X-Plex-Token sur session
- 0 régression
- 2 commits sur `feat/plex-client-retry-migration`
