# V5C-03 — Adapter les 26 tests legacy + supprimer `_legacy_globals.js`

**Branche** : `chore/v5c-adapt-legacy-tests`
**Worktree** : `.claude/worktrees/chore-v5c-adapt-legacy-tests/`
**Effort** : 3-4h
**Mode** : 🟢 Parallélisable (avec V5C-01 et V5C-02)
**Fichiers concernés** :
- 26 fichiers `tests/test_*.py` legacy à adapter ou supprimer
- `web/dashboard/_legacy_globals.js` (à supprimer si plus référencé)
- Toutes les vues v5 portées qui référencent encore `window.state`/`apiCall`/etc. (à migrer)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b chore/v5c-adapt-legacy-tests .claude/worktrees/chore-v5c-adapt-legacy-tests audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/chore-v5c-adapt-legacy-tests

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT les tests legacy + `_legacy_globals.js` + les vues v5 qui référencent les globals legacy.

RÈGLE PRUDENCE : avant de supprimer `_legacy_globals.js`, vérifier que **plus aucun fichier ne référence `window.state`, `apiCall`, etc.**

---

## CONTEXTE

V5B-01 a basculé le dashboard de v4 vers v5. 26 tests legacy ciblent l'ancienne structure HTML/JS et échouent maintenant :

```
tests à adapter ou supprimer :
- test_dashboard_jellyfin_polish (5 tests)
- test_dashboard_library_runs (2 tests)
- test_dashboard_parity (4 tests)
- test_dashboard_review (1 test)
- test_dashboard_shell (1 test)
- test_dashboard_status_logs (1 test)
- test_help_view (4 tests)
- test_shortcuts_discoverability (1 test)
- test_sidebar_counters (1 test)
- test_sidebar_integrations_visible (2 tests)
- test_unified_ui_contracts (1 test)
- test_updater_boot_hook (1 test)
- test_watchlist (1 test)
- test_dashboard_html_has_sidebar_nav (test_dashboard_shell, 1 test)
```

Ces tests cherchent des patterns v4 qui n'existent plus :
- `<button class="nav-btn">` (sidebar HTML statique)
- `import { initStatus } from "./views/status.js"` (vue v4 supprimée par V5C-01)
- `nav-btn-jellyfin` (classe sidebar v4)
- etc.

Aussi : `_legacy_globals.js` créé par V5B comme shim CSP-safe pour `window.state`/`apiCall` encore référencés par certaines vues v5 portées. À nettoyer.

---

## MISSION

### Étape 1 — Audit des 26 tests legacy

```bash
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | grep -E "^FAIL:" | sort -u
```

Liste les 26 fails. Pour chacun, classifier :

**Catégorie A — Test obsolète à SUPPRIMER**
Le test cible une feature/structure v4 qui est définitivement remplacée par v5 et déjà couverte par les tests v5 (`test_settings_v5_ported.py`, `test_v5b_activation.py`, etc.).

Exemples typiques :
- `test_dashboard_html_has_sidebar_nav` (la sidebar HTML statique n'existe plus)
- `test_dashboard_parity::test_*_nav_button` (boutons HTML v4)
- `test_app_js_imports_status/runs/review` (imports v4)

→ Supprimer le test (ou le fichier entier s'il ne reste rien dedans).

**Catégorie B — Test à ADAPTER**
Le test cible une feature qui existe toujours mais via un nouveau path (vue v5 portée).

Exemples typiques :
- `test_help_view` : adapter pour cibler `web/views/help.js` (v5) au lieu de `web/dashboard/views/help.js`
- `test_sidebar_counters` : adapter pour vérifier `data-badge-key` dans `sidebar-v5.js`
- `test_sidebar_integrations_visible` : adapter pour `markIntegrationState` v5
- `test_updater_boot_hook` : adapter pour le badge update v5
- `test_watchlist` : adapter pour les boutons UI dans `library-v5.js`

→ Migrer le test vers le nouveau fichier source.

### Étape 2 — Process pour chaque test

Pour chaque fichier de test à problèmes :

1. Lire le test
2. Identifier le fichier source qu'il scanne (`Path("...")`)
3. Décider Catégorie A ou B
4. Si A → supprimer le test (ou commenter avec `@unittest.skip("V4 obsolète, voir test_v5_xxx")`)
5. Si B → réécrire l'assertion pour cibler le nouveau fichier v5

### Étape 3 — Cleanup `_legacy_globals.js`

Identifier toutes les vues qui référencent encore `window.state`, `window.apiCall`, etc. :

```bash
grep -rn "window\.\(state\|apiCall\)" web/views/ web/dashboard/ 2>&1 | head -20
```

Pour chaque référence :
- Remplacer par l'import ESM équivalent (depuis `_v5_helpers.js` ou `dashboard/core/state.js`)
- Si pas équivalent direct, créer un wrapper

Une fois TOUS les usages migrés :

```bash
git rm web/dashboard/_legacy_globals.js
# Et retirer son chargement de index.html
```

⚠ Vérifier que `index.html` ne charge plus `_legacy_globals.js` :

```bash
grep "legacy_globals" web/dashboard/index.html
# Si trouvé : retirer la balise <script>
```

### Étape 4 — Tests structurels post-cleanup

Crée `tests/test_v5c_legacy_cleanup.py` :

```python
"""V5C-03 — Vérifie cleanup tests legacy + _legacy_globals.js."""
from __future__ import annotations
import unittest
from pathlib import Path


class V5CLegacyCleanupTests(unittest.TestCase):
    def test_legacy_globals_removed(self):
        """_legacy_globals.js doit avoir été supprimé."""
        self.assertFalse(
            Path("web/dashboard/_legacy_globals.js").exists(),
            "_legacy_globals.js devrait être supprimé"
        )

    def test_index_no_legacy_globals_script(self):
        html = Path("web/dashboard/index.html").read_text(encoding="utf-8")
        self.assertNotIn("legacy_globals", html)

    def test_no_window_state_apicall_in_views(self):
        """Aucune vue v5 ne doit référencer window.state ou window.apiCall."""
        for view_path in Path("web/views").glob("*.js"):
            if view_path.name.startswith("_"):
                continue  # skip helpers
            content = view_path.read_text(encoding="utf-8")
            with self.subTest(file=view_path.name):
                self.assertNotIn("window.state", content)
                self.assertNotIn("window.apiCall", content)


if __name__ == "__main__":
    unittest.main()
```

### Étape 5 — Vérifications finales

```bash
.venv313/Scripts/python.exe -m unittest tests.test_v5c_legacy_cleanup -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

**Cible** : 0 fail legacy. Reste uniquement les 2 pré-existants (radarr/plex/REST flake).

### Étape 6 — Smoke test manuel post-cleanup

```bash
.venv313/Scripts/python.exe app.py
```

Vérifier que toutes les vues v5 chargent toujours après suppression de `_legacy_globals.js`. Si une vue casse → identifier le `window.X` manquant et le migrer en ESM.

### Étape 7 — Commits

- `chore(tests): remove obsolete v4 dashboard tests (parity/shell/jellyfin_polish)` (catégorie A)
- `chore(tests): adapt v5-targeted tests (help_view/sidebar_counters/etc.)` (catégorie B)
- `refactor(views-v5): migrate window.state/apiCall references to ESM imports`
- `chore(dashboard): remove _legacy_globals.js (no longer referenced)`
- `test(v5c): structural cleanup verification`

---

## LIVRABLES

- 26 tests legacy adaptés ou supprimés (cible : 0 fail post-cleanup)
- `web/dashboard/_legacy_globals.js` supprimé
- `index.html` ne charge plus le shim
- Toutes les vues v5 utilisent ESM imports (pas de window.X)
- Test structurel V5C-03
- Smoke test post-cleanup OK
- 5 commits sur `chore/v5c-adapt-legacy-tests`

---

## ⚠️ Cas bloquants

Si une vue v5 a des dépendances trop profondes vers les globals legacy (ex: composant tiers qui ne marche qu'avec window.X) :
- Documenter dans le commit
- Garder le shim minimal dédié à ce composant uniquement
- Note dans `audit/results/v5c-03-shim-restant.md` ce qui reste et pourquoi
