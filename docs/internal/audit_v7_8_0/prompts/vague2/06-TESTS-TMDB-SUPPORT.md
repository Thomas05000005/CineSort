# V2-06 — Tests tmdb_support.py (15% → 80%)

**Branche** : `test/tmdb-support-coverage`
**Worktree** : `.claude/worktrees/test-tmdb-support-coverage/`
**Effort** : 1 jour
**Priorité** : 🔴 MAJEUR (audit ID-T-003 — module quasi non testé)
**Fichiers concernés** :
- `tests/test_tmdb_support.py` (nouveau)
- ❌ NE PAS modifier `cinesort/ui/api/tmdb_support.py` (zéro modif source)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b test/tmdb-support-coverage .claude/worktrees/test-tmdb-support-coverage audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/test-tmdb-support-coverage

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT le nouveau fichier test_tmdb_support.py.

---

## CONTEXTE

`cinesort/ui/api/tmdb_support.py` est un wrapper TMDb minimal (34 lignes).
Coverage actuel : **14.7%** — quasi rien testé.

TMDb est central au matching films, donc même un module wrapper mérite des tests
(régression silencieuse = mauvais matching pour 2000 users).

**Cible : 80%+ coverage.**

---

## MISSION

### Étape 1 — Lire l'état actuel

Lis `cinesort/ui/api/tmdb_support.py` (34 lignes total).

Identifie :
- Les méthodes publiques (probablement 5-7)
- Leurs signatures
- Leurs dépendances (TmdbClient, settings)

### Étape 2 — Mesurer baseline

```bash
.venv313/Scripts/python.exe -m coverage run -m pytest tests/ --ignore=tests/e2e --ignore=tests/e2e_dashboard --ignore=tests/e2e_desktop --ignore=tests/manual --ignore=tests/live --ignore=tests/stress -q 2>&1 | tail -3
.venv313/Scripts/python.exe -m coverage report --include="cinesort/ui/api/tmdb_support.py" --show-missing 2>&1 | tail -10
```

Note les lignes manquantes.

### Étape 3 — Créer tests/test_tmdb_support.py

Pour chaque méthode publique :
- Cas nominal (mock TmdbClient → vérifier retour)
- Cas erreur (api_key vide, network down, etc.)
- Cas réponse vide

Pattern type :

```python
"""V2-06 — Tests tmdb_support wrapper module."""
from __future__ import annotations
import unittest
from unittest.mock import patch, MagicMock
import sys; sys.path.insert(0, '.')
from cinesort.ui.api import tmdb_support


class TestTmdbSupport(unittest.TestCase):

    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_search_preview_success(self, mock_client_cls):
        client = MagicMock()
        client.search_movie.return_value = [
            {"id": 1, "title": "Inception", "year": 2010},
        ]
        mock_client_cls.return_value = client
        # Adapter la signature à la vraie méthode
        result = tmdb_support.get_tmdb_search_preview(query="Inception", api_key="fake")
        self.assertTrue(result.get("ok"))

    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_search_preview_no_api_key(self, mock_client_cls):
        result = tmdb_support.get_tmdb_search_preview(query="Inception", api_key="")
        self.assertFalse(result.get("ok"))

    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_search_preview_network_error(self, mock_client_cls):
        client = MagicMock()
        client.search_movie.side_effect = ConnectionError("DNS fail")
        mock_client_cls.return_value = client
        result = tmdb_support.get_tmdb_search_preview(query="Inception", api_key="fake")
        self.assertFalse(result.get("ok"))

    # ... ajouter tests pour chaque autre méthode du module
```

⚠ Adapte les noms de fonction et signatures à la réalité de `tmdb_support.py` (lis-le).

### Étape 4 — Vérifier coverage

```bash
.venv313/Scripts/python.exe -m coverage run -m pytest tests/test_tmdb_support.py -q 2>&1 | tail -3
.venv313/Scripts/python.exe -m coverage report --include="cinesort/ui/api/tmdb_support.py" 2>&1 | tail -3
```

Cible : 80%+.

### Étape 5 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 6 — Commit

`test(tmdb_support): cover wrapper methods 14.7% → 80%+`

---

## LIVRABLES

Récap :
- Coverage tmdb_support.py : 14.7% → ?
- 1 nouveau fichier test_tmdb_support.py
- 0 régression
- 1 commit sur `test/tmdb-support-coverage`
