# V5C-01 — Cleanup vues v4 dashboard obsolètes (post-V5B)

**Branche** : `chore/v5c-cleanup-v4-views`
**Worktree** : `.claude/worktrees/chore-v5c-cleanup-v4-views/`
**Effort** : 3-4h
**Mode** : 🟢 Parallélisable (avec V5C-02)
**Fichiers à SUPPRIMER** :
- `web/dashboard/views/quality.js` (remplacée par qij-v5 dans /quality)
- `web/dashboard/views/review.js` (remplacée par processing dans /processing step review)
- `web/dashboard/views/runs.js` (remplacée par processing/qij)
- `web/dashboard/views/library/` (dossier entier, remplacé par library-v5)
- `web/dashboard/views/settings.js` (remplacée par settings-v5)
- `web/dashboard/views/status.js` (remplacée par home v5)
- `web/dashboard/views/help.js` (remplacée par help v5 porté)
- `web/dashboard/views/about.js` (à intégrer dans modal v5 ou supprimer)
- `web/dashboard/views/demo-wizard.js` (vérifier qu'il est bien dans web/views/ aussi, sinon laisser)

**Fichiers à ADAPTER** :
- `tests/` qui testaient les vues v4 dashboard supprimées → adapter pour cibler les vues v5 portées
- `web/dashboard/styles.css` : nettoyer sélecteurs sidebar v4 obsolètes (.sidebar-group, .nav-btn legacy patterns)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b chore/v5c-cleanup-v4-views .claude/worktrees/chore-v5c-cleanup-v4-views audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/chore-v5c-cleanup-v4-views

# Pré-vérification : V5B doit être mergée
grep -q "_mountV5Shell" web/dashboard/app.js && echo "✅ V5B présent" || echo "❌ V5B pas mergée"

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PRUDENCE : **NE PAS** supprimer un fichier sans avoir vérifié qu'il n'est plus référencé nulle part. Process pour chaque fichier candidat à suppression :

1. `grep -rn "filename.js" web/ cinesort/ tests/` → trouver toutes les références
2. Si référence depuis app.js → vérifier que c'est bien remplacé par v5
3. Si référence depuis test → adapter le test ou supprimer si obsolète
4. SEULEMENT après → supprimer le fichier
5. Tester suite complète → 0 régression

RÈGLE DE LA HACHE : si un test casse après suppression, c'est OK de l'adapter. Si du code applicatif casse, c'est qu'on a oublié quelque chose — RESTAURER + investiguer.

---

## CONTEXTE

Après V5B, les routes pointent vers les vues v5 portées. Les vues v4 dashboard ne sont plus chargées. Mais le code reste sur disque, ce qui :
- Pollue le repo (~4000 lignes mortes)
- Confuse les futurs contributeurs
- Augmente la taille du bundle PyInstaller (~100 KB inutiles)

Cette mission supprime proprement.

---

## MISSION

### Étape 1 — Audit présence référencement

Pour chaque fichier candidat, exécute :

```bash
for f in quality.js review.js runs.js settings.js status.js help.js about.js; do
  echo "===== web/dashboard/views/$f ====="
  grep -rn "views/$f\|/$f" web/dashboard/ cinesort/infra/ tests/ 2>&1 | grep -v "^Binary" | head -10
done
```

Pour `library/` (dossier) :

```bash
grep -rn "views/library/\|library/library.js\|library/lib-" web/dashboard/ tests/ 2>&1 | head -20
```

### Étape 2 — Suppressions sécurisées

Pour chaque fichier qui n'est référencé QUE depuis tests legacy ou commentaires :

```bash
# Exemple
git rm web/dashboard/views/quality.js
git rm web/dashboard/views/review.js
git rm web/dashboard/views/runs.js
git rm -r web/dashboard/views/library/
git rm web/dashboard/views/settings.js
git rm web/dashboard/views/status.js
git rm web/dashboard/views/help.js
```

⚠ Garder `web/dashboard/views/about.js` ET `demo-wizard.js` SI ils sont importés depuis `web/views/*.js` (ports V5bis). Vérifier d'abord.

### Étape 3 — Adapter les tests qui cassent

Lance `python -m unittest discover` et identifie les tests qui cassent. Pour chacun :
- Si le test ciblait spécifiquement une vue v4 supprimée → supprimer le test
- Si le test ciblait une feature qui existe maintenant en v5 → mettre à jour le sélecteur de fichier

Exemple :

```python
# AVANT (test_dashboard_settings_legacy.py)
src = Path("web/dashboard/views/settings.js").read_text(...)

# APRÈS (test_dashboard_settings_v5.py — ou supprimer si redondant avec test_settings_v5_ported.py)
src = Path("web/views/settings-v5.js").read_text(...)
```

### Étape 4 — Cleanup CSS sidebar v4

Dans `web/dashboard/styles.css`, supprimer les sélecteurs obsolètes :

```bash
grep -n "\.sidebar-group\|\.sidebar-name\|\.sidebar-desc\|\.nav-btn-jellyfin\|\.nav-btn-plex\|\.nav-btn-radarr" web/dashboard/styles.css
```

Pour chaque match, vérifier que les classes ne sont plus utilisées (ni dans HTML ni dans JS) → supprimer le bloc CSS.

⚠ Garder les classes utilisées par le shell v5 (qui peut référencer certaines classes communes).

### Étape 5 — Tests structurels post-cleanup

Crée `tests/test_v5c_cleanup.py` :

```python
"""V5C-01 — Vérifie que les vues v4 dashboard obsolètes sont supprimées."""
from __future__ import annotations
import unittest
from pathlib import Path


REMOVED_FILES = [
    "web/dashboard/views/quality.js",
    "web/dashboard/views/review.js",
    "web/dashboard/views/runs.js",
    "web/dashboard/views/settings.js",
    "web/dashboard/views/status.js",
    "web/dashboard/views/help.js",
    "web/dashboard/views/library/library.js",
    # Adapter selon ce qui a été effectivement supprimé
]

REMOVED_CSS_SELECTORS = [
    ".sidebar-group",
    ".nav-btn-jellyfin",
]


class V5CCleanupTests(unittest.TestCase):
    def test_v4_views_removed(self):
        for f in REMOVED_FILES:
            with self.subTest(file=f):
                self.assertFalse(Path(f).exists(), f"Pas supprimé: {f}")

    def test_v4_css_selectors_removed(self):
        css = Path("web/dashboard/styles.css").read_text(encoding="utf-8")
        for sel in REMOVED_CSS_SELECTORS:
            with self.subTest(selector=sel):
                self.assertNotIn(sel, css, f"Sélecteur CSS encore présent: {sel}")

    def test_app_no_more_v4_view_imports(self):
        app = Path("web/dashboard/app.js").read_text(encoding="utf-8")
        for f in REMOVED_FILES:
            basename = f.split("/")[-1]
            self.assertNotIn(f'./views/{basename}', app, f"Import encore présent: {basename}")


if __name__ == "__main__":
    unittest.main()
```

### Étape 6 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_v5c_cleanup -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
node --check web/dashboard/app.js 2>&1 | tail -2
```

### Étape 7 — Smoke test manuel post-cleanup

```bash
.venv313/Scripts/python.exe app.py
```

Vérifier que toutes les vues v5 chargent toujours correctement (le cleanup n'aurait pas dû les casser).

### Étape 8 — Commits

- `chore(dashboard): remove obsolete v4 views (status/quality/review/runs/library/settings/help)`
- `chore(dashboard-css): remove obsolete v4 sidebar selectors`
- `test(cleanup): adapt or remove tests targeting v4 views`
- `test(v5c): structural tests confirm v4 cleanup`

---

## LIVRABLES

- 7-8 fichiers `web/dashboard/views/*.js` supprimés
- 1 dossier `web/dashboard/views/library/` supprimé
- Sélecteurs CSS sidebar v4 nettoyés
- Tests legacy adaptés ou supprimés
- Test structurel V5C
- Smoke test post-cleanup OK
- 4 commits sur `chore/v5c-cleanup-v4-views`

---

## ⚠️ Si bloqué

Si un fichier qu'on veut supprimer est référencé ailleurs de manière inattendue :
- **NE PAS forcer la suppression**
- Documenter dans le commit message
- Reviens vers l'orchestrateur avec **« V5C-01 conservé X car référencé par Y »**
