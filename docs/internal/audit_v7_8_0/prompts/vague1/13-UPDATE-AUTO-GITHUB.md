# V1-13 — Mécanisme update auto via GitHub Releases

**Branche** : `feat/auto-update-github-releases`
**Worktree** : `.claude/worktrees/feat-auto-update-github-releases/`
**Effort** : 3-5h
**Priorité** : 🔴 BLOQUANT publication
**Fichiers concernés** :
- `cinesort/app/updater.py` (nouveau)
- `tests/test_updater.py` (nouveau)
- `cinesort/ui/api/settings_support.py` — ajout 3 setdefault uniquement

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/auto-update-github-releases .claude/worktrees/feat-auto-update-github-releases audit_qa_v7_6_0_dev_20260428
# Si déjà existe : git worktree add .claude/worktrees/feat-auto-update-github-releases feat/auto-update-github-releases
cd .claude/worktrees/feat-auto-update-github-releases

pwd && git branch --show-current && git status
```

⚠ Coordination avec V1-10 (backup settings) : tu peux ajouter de NOUVEAUX
setdefault dans settings_support.py mais NE TOUCHE PAS aux fonctions d'écriture.

---

## RÈGLES GLOBALES

PROJET : CineSort, Python 3.13.
RÈGLE PARALLÉLISATION : tu touches seulement les fichiers listés. Pour
settings_support.py, juste les setdefault() des 3 nouvelles clés.

---

## MISSION

Publication GitHub Releases prévue. Sans mécanisme de notification de mise à jour,
les users restent sur la version installée à vie.

Pattern recommandé v1 : **check-only** (notification, pas d'install auto).

### Étape 1 — Recherche obligatoire

WebSearch :
- "GitHub Releases API check latest version Python desktop app 2025"
- "semver compare Python stdlib"
- "GitHub API rate limit 60/h unauthenticated"

### Étape 2 — Lire l'existant

- `VERSION`
- `CHANGELOG.md`
- `cinesort/app/notify_service.py`
- `cinesort/ui/api/settings_support.py` section `_DEFAULT_SETTINGS` ou similaire

### Étape 3 — Créer cinesort/app/updater.py

Voir audit/parallel_prompts.md (backup) pour le code complet, ou suivre ce squelette :

```python
"""V1-M13 — Mécanisme update auto via GitHub Releases API."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
DEFAULT_CHECK_TIMEOUT_S = 5
DEFAULT_CACHE_TTL_S = 3600  # respecter rate limit GitHub 60/h non auth
USER_AGENT = "CineSort-UpdateChecker/1.0"


@dataclass(frozen=True)
class UpdateInfo:
    latest_version: str
    current_version: str
    release_url: str
    release_notes_excerpt: str
    download_url: Optional[str]
    published_at: str


def _compare_versions(current: str, latest: str) -> bool:
    """True si latest > current (semver-aware)."""
    try:
        from packaging.version import parse
        return parse(latest) > parse(current)
    except (ImportError, Exception):
        return latest != current and latest > current


def check_for_updates(
    current_version: str,
    github_repo: str,
    *,
    timeout_s: int = DEFAULT_CHECK_TIMEOUT_S,
    cache_path: Optional[Path] = None,
    cache_ttl_s: int = DEFAULT_CACHE_TTL_S,
) -> Optional[UpdateInfo]:
    """Check GitHub Releases. Retourne UpdateInfo si nouvelle version dispo."""
    # Cache check
    if cache_path and cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if time.time() - data.get("ts", 0) < cache_ttl_s:
                return _parse_cached(data, current_version)
        except (json.JSONDecodeError, OSError):
            pass

    url = f"{GITHUB_API_BASE}/repos/{github_repo}/releases/latest"
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    try:
        with urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        if e.code == 404:
            logger.info("Updater: no release published yet (404)")
        else:
            logger.warning("Updater: GitHub API HTTP %d", e.code)
        return None
    except (URLError, OSError, json.JSONDecodeError) as e:
        logger.warning("Updater: error %s: %s", type(e).__name__, e)
        return None

    if cache_path:
        try:
            cache_path.write_text(json.dumps({"ts": time.time(), "payload": payload}), encoding="utf-8")
        except OSError:
            pass

    return _build_update_info(payload, current_version)


def _build_update_info(payload: dict, current_version: str) -> Optional[UpdateInfo]:
    latest_tag = str(payload.get("tag_name") or "").lstrip("v")
    if not latest_tag or not _compare_versions(current_version, latest_tag):
        return None

    download_url = None
    for asset in payload.get("assets", []):
        if asset.get("name", "").lower().endswith(".exe"):
            download_url = asset.get("browser_download_url")
            break

    return UpdateInfo(
        latest_version=latest_tag,
        current_version=current_version,
        release_url=payload.get("html_url", ""),
        release_notes_excerpt=(payload.get("body") or "")[:500],
        download_url=download_url,
        published_at=payload.get("published_at", ""),
    )


def _parse_cached(data: dict, current_version: str) -> Optional[UpdateInfo]:
    payload = data.get("payload") or {}
    return _build_update_info(payload, current_version)
```

### Étape 4 — Settings (ajout minimal)

Dans la fonction setdefault du settings_support.py :
```python
# Audit ID-V1-M13 : update auto via GitHub Releases
payload.setdefault("update_check_enabled", True)
payload.setdefault("update_check_channel", "stable")
payload.setdefault("update_last_check_ts", 0.0)
```

3 lignes seulement. NE TOUCHE PAS au reste.

### Étape 5 — Tests

`tests/test_updater.py` — 9 tests minimum :
- _compare_versions : newer/same/older/dev_suffix
- check_for_updates : new version / same version / network error / 404 / cache respected

### Étape 6 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_updater -v 2>&1 | tail -15
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . | tail -3
```

### Étape 7 — Commits

- `feat(updater): add GitHub Releases version check (audit ID-V1-M13)`
- `feat(settings): add update_check_enabled/channel/last_check_ts defaults`

---

## LIVRABLES

Récap :
- updater.py module créé avec check_for_updates + UpdateInfo
- 3 nouveaux settings ajoutés (defaults only)
- 9 tests passent
- 0 régression
- 2 commits sur `feat/auto-update-github-releases`

⚠ NE PAS hooker dans app.py au boot — séparé en V2 (avec UI Settings updater).
