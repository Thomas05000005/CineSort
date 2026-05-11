# V2-09 — Migrer TmdbClient vers make_session_with_retry

**Branche** : `feat/tmdb-client-retry-migration`
**Worktree** : `.claude/worktrees/feat-tmdb-client-retry-migration/`
**Effort** : 2-3h
**Priorité** : 🟠 IMPORTANT (audit ID-ROB-001 — robustesse réseau)
**Fichiers concernés** :
- `cinesort/infra/tmdb_client.py`
- `tests/test_tmdb_client*.py` (existants — adapter mocks si nécessaire)
- `tests/test_tmdb_phase4.py` (existant — adapter session pattern)

⚠ Le helper `make_session_with_retry` a été créé en V1-11 et mergé. Il existe dans
`cinesort/infra/_http_utils.py`.

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/tmdb-client-retry-migration .claude/worktrees/feat-tmdb-client-retry-migration audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-tmdb-client-retry-migration

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT tmdb_client.py + ses tests.
NE TOUCHE PAS jellyfin/plex/radarr_client.py (autres missions V2-10/11/12).

---

## CONTEXTE

V1-11 a créé `make_session_with_retry()` dans `cinesort/infra/_http_utils.py`.
Maintenant : migrer `TmdbClient` pour utiliser cette session avec retry/backoff
automatique sur 5xx et erreurs réseau.

---

## MISSION

### Étape 1 — Lire les 2 modules

Lis :
- `cinesort/infra/_http_utils.py` (helper créé en V1-11)
- `cinesort/infra/tmdb_client.py` (à migrer)

Note dans `tmdb_client.py` :
- `self._session = requests.Session()` actuel (probablement avec rate limiter pre-existant)
- Toutes les utilisations de `self._session.get(...)`
- Le rate limiter existant (token bucket TMDb 40 rps)

### Étape 2 — Migrer la création de Session

Remplace :
```python
import requests
self._session = requests.Session()
```

Par :
```python
from cinesort.infra._http_utils import make_session_with_retry
self._session = make_session_with_retry(
    user_agent="CineSort/7.6 TmdbClient",
    max_attempts=3,
    backoff_base=0.5,
)
```

⚠ CONSERVE le rate limiter existant ! Le retry vient EN COMPLÉMENT, pas en remplacement.
Le rate limiter contrôle le throughput (max N req/s) ; le retry gère les erreurs transitoires.

### Étape 3 — Vérifier que tous les usages sont OK

```bash
grep -n "requests\." cinesort/infra/tmdb_client.py
```

Tous les `requests.get(...)` directs (sans Session) doivent être migrés vers
`self._session.get(...)`. Vérifier qu'aucun appel reste hors session.

### Étape 4 — Adapter les tests

Lis :
- `tests/test_tmdb_client.py` (tests généraux)
- `tests/test_tmdb_phase4.py` (tests Phase 4 rate limiter + Session)

Si les mocks ciblent `requests.get` direct → migrer vers mock de `session.get` ou mock de
`urlopen` (selon ce qui est utilisé en interne par requests).

Pattern de mock à conserver :
```python
@patch("cinesort.infra.tmdb_client.requests.Session.get")
def test_search_movie(self, mock_get):
    mock_get.return_value = MagicMock(status_code=200, json=lambda: {...})
    ...
```

### Étape 5 — Vérifier que le retry fonctionne

Crée un test d'intégration dans `tests/test_tmdb_retry_integration.py` :

```python
"""V2-09 — Vérifie que TmdbClient retry sur 503."""
from __future__ import annotations
import unittest
from unittest.mock import patch, MagicMock
import requests
import sys; sys.path.insert(0, '.')
from cinesort.infra.tmdb_client import TmdbClient


class TmdbRetryTests(unittest.TestCase):
    def test_session_uses_retry_helper(self):
        client = TmdbClient(api_key="fake", cache_path=None, timeout_s=5.0)
        # Vérifier que la session a le HTTPAdapter custom
        adapter = client._session.get_adapter("https://api.themoviedb.org")
        retry = adapter.max_retries
        self.assertEqual(retry.total, 3)
        self.assertIn(503, retry.status_forcelist)
        self.assertIn(429, retry.status_forcelist)

    def test_user_agent_set(self):
        client = TmdbClient(api_key="fake", cache_path=None, timeout_s=5.0)
        self.assertIn("CineSort", client._session.headers["User-Agent"])
        self.assertIn("Tmdb", client._session.headers["User-Agent"])
```

### Étape 6 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_tmdb_client tests.test_tmdb_phase4 tests.test_tmdb_retry_integration -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 7 — Commits

- `refactor(tmdb): use make_session_with_retry for resilience (audit ID-ROB-001)`
- `test(tmdb): add retry integration test`

---

## LIVRABLES

Récap :
- TmdbClient utilise make_session_with_retry
- Rate limiter conservé
- Tests existants migrés sans régression
- 1 nouveau test retry integration
- 0 régression
- 2 commits sur `feat/tmdb-client-retry-migration`
