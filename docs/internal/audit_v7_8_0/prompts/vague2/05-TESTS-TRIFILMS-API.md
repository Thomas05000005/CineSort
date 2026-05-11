# V2-05 — Tests cinesort_api.py (52% → 75%)

**Branche** : `test/cinesort-api-coverage`
**Worktree** : `.claude/worktrees/test-cinesort-api-coverage/`
**Effort** : 2-3 jours
**Priorité** : 🔴 MAJEUR (audit ID-T-002 — 512 lignes non testées sur la façade principale)
**Fichiers concernés** :
- `tests/test_cinesort_api_plex.py` (nouveau)
- `tests/test_cinesort_api_radarr.py` (nouveau)
- `tests/test_cinesort_api_email.py` (nouveau)
- `tests/test_cinesort_api_plugins.py` (nouveau)
- `tests/test_cinesort_api_misc.py` (nouveau)
- éventuellement d'autres test_cinesort_api_*.py selon coverage par domaine
- ❌ NE PAS modifier `cinesort/ui/api/cinesort_api.py` (zéro modif source)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b test/cinesort-api-coverage .claude/worktrees/test-cinesort-api-coverage audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/test-cinesort-api-coverage

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT les nouveaux fichiers tests.
Pas de modif de `cinesort_api.py` (façade source).

---

## CONTEXTE

`cinesort/ui/api/cinesort_api.py` est la façade principale exposée à pywebview + REST.
- 2192 lignes
- Coverage actuelle : **52.8%**
- 512 lignes non testées

Avec 2000 users, toute régression non détectée passe en prod immédiatement.
**Cible : 75%+ coverage.**

---

## MISSION

### Étape 1 — Mesurer baseline

```bash
.venv313/Scripts/python.exe -m coverage run -m pytest tests/ --ignore=tests/e2e --ignore=tests/e2e_dashboard --ignore=tests/e2e_desktop --ignore=tests/manual --ignore=tests/live --ignore=tests/stress -q 2>&1 | tail -3
.venv313/Scripts/python.exe -m coverage report --include="cinesort/ui/api/cinesort_api.py" --show-missing 2>&1 | tail -10
```

Note les lignes manquantes (output `Missing` colonne).

### Étape 2 — Identifier les blocs fonctionnels non couverts

Lis `cinesort/ui/api/cinesort_api.py` aux lignes manquantes. Probablement :
- **Plex** : `get_plex_libraries`, `get_plex_sync_report`, `request_plex_refresh`, etc.
- **Radarr** : `get_radarr_status`, `request_radarr_upgrade`, `get_radarr_libraries`
- **Email** : `test_email_report`, settings email
- **Plugins** : `_dispatch_plugin_hook`, `discover_plugins`, settings plugins
- **TMDb support** : `get_tmdb_search_preview`, etc.
- **Divers** : `restart_api_server`, `apply_performance_recommendation`, `import_shareable_profile`, `submit_score_feedback`, `get_calibration_report`

### Étape 3 — Pour chaque domaine, créer un test_cinesort_api_<domain>.py

Pattern type :

```python
"""V2-05 — Tests cinesort_api Plex endpoints."""
from __future__ import annotations
import unittest
from unittest.mock import patch, MagicMock
import sys; sys.path.insert(0, '.')
from cinesort.ui.api.cinesort_api import CineSortApi


class TestPlexEndpoints(unittest.TestCase):
    def setUp(self):
        self.api = CineSortApi()

    @patch("cinesort.ui.api.cinesort_api.PlexClient")
    def test_test_plex_connection_success(self, mock_client_cls):
        client = MagicMock()
        client.validate_connection.return_value = (True, {"version": "1.30"})
        mock_client_cls.return_value = client
        result = self.api.test_plex_connection(url="http://10.0.0.1:32400", token="abc")
        self.assertTrue(result["ok"])
        self.assertEqual(result["version"], "1.30")

    @patch("cinesort.ui.api.cinesort_api.PlexClient")
    def test_test_plex_connection_network_error(self, mock_client_cls):
        client = MagicMock()
        client.validate_connection.side_effect = ConnectionError("DNS fail")
        mock_client_cls.return_value = client
        result = self.api.test_plex_connection(url="bad", token="abc")
        self.assertFalse(result["ok"])
        self.assertIn("message", result)

    def test_get_plex_libraries_when_disabled(self):
        # Plex désactivé → message clair
        self.api.save_settings({"plex_enabled": False})
        result = self.api.get_plex_libraries()
        self.assertFalse(result.get("ok"))
        self.assertIn("désactivé", result.get("message", "").lower())

    # ... + 5-10 autres tests par domaine
```

### Étape 4 — Tests à écrire par domaine

Pour CHAQUE test :
- Cas nominal (mock dépendances → vérifier retour OK)
- Cas erreur réseau (mock raise → vérifier message clair)
- Cas paramètre invalide (vide, None, type incorrect)
- Cas guard désactivé (ex: `plex_enabled=False` → message "désactivé")

### Étape 5 — Mocks

Utilise `unittest.mock.patch` sur les clients (TmdbClient, PlexClient, RadarrClient,
JellyfinClient) ET sur les fonctions de fichier/network.

⚠ NE pas faire de vraies requêtes réseau (les tests live sont dans `tests/live/`).

### Étape 6 — Vérifier coverage progressivement

Après chaque nouveau fichier test :
```bash
.venv313/Scripts/python.exe -m coverage run -m pytest tests/test_cinesort_api_*.py -q 2>&1 | tail -3
.venv313/Scripts/python.exe -m coverage report --include="cinesort/ui/api/cinesort_api.py" 2>&1 | tail -3
```

Cible : 75%+ après tous les fichiers ajoutés.

### Étape 7 — Vérifications finales

```bash
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
.venv313/Scripts/python.exe -m coverage run -m pytest tests/ --ignore=tests/e2e --ignore=tests/e2e_dashboard --ignore=tests/e2e_desktop --ignore=tests/manual --ignore=tests/live --ignore=tests/stress -q 2>&1 | tail -3
.venv313/Scripts/python.exe -m coverage report --skip-empty 2>&1 | tail -5
```

### Étape 8 — Commits

5-10 commits granulaires (1 par domaine testé) :
- `test(api): add Plex endpoints coverage (52% → ~58%)`
- `test(api): add Radarr endpoints coverage`
- `test(api): add Email endpoints coverage`
- `test(api): add Plugins endpoints coverage`
- `test(api): add miscellaneous endpoints coverage (75%+)`

---

## LIVRABLES

Récap :
- Coverage cinesort_api.py : 52.8% → ?
- 5-10 nouveaux fichiers test_cinesort_api_<domain>.py
- 0 régression
- 5-10 commits sur `test/cinesort-api-coverage`
