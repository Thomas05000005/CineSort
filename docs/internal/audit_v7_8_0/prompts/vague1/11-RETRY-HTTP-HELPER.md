# V1-11 — Helper retry/backoff HTTP mutualisé (création seule)

**Branche** : `feat/http-retry-helper`
**Worktree** : `.claude/worktrees/feat-http-retry-helper/`
**Effort** : 2-3h
**Priorité** : 🟠 MAJEUR
**Fichiers concernés** :
- `cinesort/infra/_http_utils.py` (nouveau)
- `tests/test_http_utils.py` (nouveau)

⚠ **NE PAS migrer les 4 clients dans cette mission** — séparé en V2.

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/http-retry-helper .claude/worktrees/feat-http-retry-helper audit_qa_v7_6_0_dev_20260428
# Si déjà existe : git worktree add .claude/worktrees/feat-http-retry-helper feat/http-retry-helper
cd .claude/worktrees/feat-http-retry-helper

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

PROJET : CineSort, requests + urllib3.
RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT _http_utils.py + nouveau test.

---

## MISSION

TMDb / Jellyfin / Plex / Radarr clients HTTP n'ont pas de retry. Crée un helper
mutualisé. La migration des 4 clients = missions V2 séparées APRÈS merge.

### Étape 1 — Recherche web obligatoire

WebSearch :
- "urllib3 Retry backoff_factor 2025 best practices"
- "requests Session HTTPAdapter Retry 2025"
- "Retry-After header respect HTTP retry"

### Étape 2 — Lire le code existant

- `cinesort/infra/tmdb_client.py` (Session + rate limiter)
- `cinesort/infra/omdb_client.py` (retry manuel à mutualiser)
- `cinesort/infra/opensubtitles_client.py`

### Étape 3 — Créer _http_utils.py

```python
"""Audit ID-ROB-001 : helper mutualisé Session HTTP avec retry/backoff."""
from __future__ import annotations

import logging
from typing import Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

DEFAULT_RETRY_STATUS_CODES: tuple[int, ...] = (429, 500, 502, 503, 504)
DEFAULT_RETRY_METHODS: frozenset[str] = frozenset(("GET", "HEAD", "OPTIONS", "PUT", "DELETE", "POST"))
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE = 0.5
DEFAULT_POOL_CONNECTIONS = 10
DEFAULT_POOL_MAXSIZE = 20


def make_session_with_retry(
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    status_forcelist: Iterable[int] = DEFAULT_RETRY_STATUS_CODES,
    methods: Iterable[str] = DEFAULT_RETRY_METHODS,
    user_agent: str = "CineSort/7.6",
    pool_connections: int = DEFAULT_POOL_CONNECTIONS,
    pool_maxsize: int = DEFAULT_POOL_MAXSIZE,
) -> requests.Session:
    """Session avec retry+backoff exponentiel automatique."""
    retry = Retry(
        total=max_attempts,
        connect=max_attempts,
        read=max_attempts,
        status=max_attempts,
        backoff_factor=backoff_base,
        status_forcelist=tuple(status_forcelist),
        allowed_methods=frozenset(methods),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
    )
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers["User-Agent"] = user_agent
    return session
```

### Étape 4 — Tests

Crée `tests/test_http_utils.py` avec :
- test_returns_session_instance
- test_default_user_agent
- test_custom_user_agent
- test_adapter_mounted_for_http_and_https
- test_retry_config_max_attempts
- test_retry_config_status_forcelist
- test_retry_config_backoff_factor

### Étape 5 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_http_utils -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . | tail -3
```

### Étape 6 — Commit

`feat(infra): add make_session_with_retry helper for HTTP clients (audit ID-ROB-001)`

---

## LIVRABLES

Récap :
- `cinesort/infra/_http_utils.py` créé
- `tests/test_http_utils.py` ajouté
- 0 régression
- 1 commit sur `feat/http-retry-helper`
- ⚠ Migration des 4 clients = missions V2 séparées
