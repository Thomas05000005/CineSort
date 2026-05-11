# V2-12 — Migrer RadarrClient vers make_session_with_retry

**Branche** : `feat/radarr-client-retry-migration`
**Worktree** : `.claude/worktrees/feat-radarr-client-retry-migration/`
**Effort** : 2-3h
**Priorité** : 🟠 IMPORTANT (audit ID-ROB-001)
**Fichiers concernés** :
- `cinesort/infra/radarr_client.py`
- `tests/test_radarr_client.py` (si existant — adapter mocks)
- `tests/test_radarr_retry_integration.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/radarr-client-retry-migration .claude/worktrees/feat-radarr-client-retry-migration audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-radarr-client-retry-migration

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT radarr_client.py + ses tests.

---

## CONTEXTE

Idem V2-09/10/11 mais pour `RadarrClient`. Helper `make_session_with_retry` créé en V1-11.

Radarr utilise auth via header `X-Api-Key`.

---

## MISSION

### Étape 1 — Lire les modules

- `cinesort/infra/_http_utils.py` (helper)
- `cinesort/infra/radarr_client.py` (à migrer)

### Étape 2 — Migrer la Session

```python
from cinesort.infra._http_utils import make_session_with_retry
self._session = make_session_with_retry(
    user_agent="CineSort/7.6 RadarrClient",
    max_attempts=3,
    backoff_base=0.5,
)
self._session.headers["X-Api-Key"] = api_key
```

### Étape 3 — Vérifier usages

```bash
grep -n "requests\." cinesort/infra/radarr_client.py
```

Tous les appels via `self._session`.

### Étape 4 — Tests

Adapte tests existants si mocks ciblent `requests.get` direct.

Crée `tests/test_radarr_retry_integration.py` :

```python
"""V2-12 — Vérifie RadarrClient utilise retry helper."""
from __future__ import annotations
import unittest
import sys; sys.path.insert(0, '.')
from cinesort.infra.radarr_client import RadarrClient


class RadarrRetryTests(unittest.TestCase):
    def test_session_uses_retry_helper(self):
        client = RadarrClient(url="http://test:7878", api_key="fake")
        adapter = client._session.get_adapter("http://test:7878")
        retry = adapter.max_retries
        self.assertEqual(retry.total, 3)
        self.assertIn(503, retry.status_forcelist)

    def test_user_agent_set(self):
        client = RadarrClient(url="http://test:7878", api_key="fake")
        self.assertIn("CineSort", client._session.headers["User-Agent"])
        self.assertIn("Radarr", client._session.headers["User-Agent"])

    def test_api_key_header_set(self):
        client = RadarrClient(url="http://test:7878", api_key="my-radarr-key")
        self.assertEqual(client._session.headers.get("X-Api-Key"), "my-radarr-key")
```

### Étape 5 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_radarr_client tests.test_radarr_retry_integration 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 6 — Commits

- `refactor(radarr): use make_session_with_retry (audit ID-ROB-001)`
- `test(radarr): add retry integration test`

---

## LIVRABLES

Récap :
- RadarrClient utilise make_session_with_retry
- X-Api-Key sur session
- 0 régression
- 2 commits sur `feat/radarr-client-retry-migration`
