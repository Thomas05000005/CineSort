# V3-04 — Compteurs sidebar (badges)

**Branche** : `feat/sidebar-counters`
**Worktree** : `.claude/worktrees/feat-sidebar-counters/`
**Effort** : 1 jour
**Priorité** : 🟢 NICE-TO-HAVE (UX feedback visuel rapide)
**Fichiers concernés** :
- `cinesort/ui/api/dashboard_support.py` (endpoint `get_sidebar_counters`)
- `cinesort/ui/api/cinesort_api.py` (expose endpoint)
- `web/dashboard/index.html` (sidebar — ajout `<span class="nav-badge">`)
- `web/dashboard/app.js` (chargement périodique)
- `web/dashboard/styles.css` (style badge)
- `tests/test_sidebar_counters.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/sidebar-counters .claude/worktrees/feat-sidebar-counters audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-sidebar-counters

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT le système de badges sidebar
(endpoint + injection HTML + polling). Pas de modif des vues métier.

---

## CONTEXTE

La sidebar a 7 entrées (Accueil, Bibliothèque, Validation, Application, Qualité,
Journaux, Paramètres, Aide). Aucune ne montre s'il y a "quelque chose à faire".

**Solution** : ajouter des badges numériques à droite des entrées clés :
- **Validation** : nombre de films à valider (`needs_review`)
- **Application** : nombre de décisions approuvées en attente d'apply
- **Qualité** : nombre d'anomalies récentes (warnings non traités)

Pas de badge sur Accueil, Bibliothèque, Journaux, Paramètres, Aide (pas pertinent).

---

## MISSION

### Étape 1 — Lire les modules

- `cinesort/ui/api/dashboard_support.py` (chercher `get_global_stats` / `get_dashboard`)
- `cinesort/ui/api/cinesort_api.py` (voir comment exposer un endpoint)
- `web/dashboard/index.html` (voir la sidebar, lignes ~50-110)
- `web/dashboard/app.js` (voir le polling existant)

### Étape 2 — Endpoint backend

Dans `dashboard_support.py`, ajouter :

```python
def get_sidebar_counters(api) -> dict:
    """V3-04 — Compteurs pour les badges sidebar.

    Retourne {validation, application, quality}. Compteurs basés sur le dernier run actif
    ou le run le plus récent.
    """
    store = api._get_store()
    last_run_id = store.get_latest_run_id() if hasattr(store, "get_latest_run_id") else None
    if not last_run_id:
        return {"validation": 0, "application": 0, "quality": 0}

    # Validation : films marqués "needs_review" (confiance < seuil OU warnings critiques)
    rows = store.get_rows_for_run(last_run_id) if hasattr(store, "get_rows_for_run") else []
    validation = sum(1 for r in rows if _row_needs_review(r))

    # Application : décisions "approve" non encore appliquées (état stocké côté front via save_validation)
    # Approximation : compter les rows approuvés non encore présents dans apply_operations
    applied_paths = set(store.get_applied_paths_for_run(last_run_id)) if hasattr(store, "get_applied_paths_for_run") else set()
    application = sum(1 for r in rows if _row_is_approved(r) and r.get("path") not in applied_paths)

    # Qualité : warnings dans le dernier run
    quality = sum(1 for r in rows if r.get("warning_flags"))

    return {
        "validation": validation,
        "application": application,
        "quality": quality,
    }


def _row_needs_review(row) -> bool:
    """Heuristique : confiance < 70 OU warning critique."""
    conf = row.get("confidence", 0) or 0
    if conf < 70:
        return True
    flags = row.get("warning_flags") or []
    critical = {"integrity_header_invalid", "integrity_probe_failed", "duplicate_quality"}
    return any(f in critical for f in flags)


def _row_is_approved(row) -> bool:
    """Approximation : décision = approve dans validation_decisions."""
    return row.get("decision") == "approve"
```

⚠ Adapter les noms `get_latest_run_id`, `get_rows_for_run`, `get_applied_paths_for_run`
aux vrais noms dans le store. Si une méthode n'existe pas, choisir l'approche la plus
simple (ex. lire la table directement via `store.conn.execute`).

### Étape 3 — Exposer l'endpoint

Dans `cinesort_api.py`, ajouter une méthode publique :

```python
def get_sidebar_counters(self) -> dict:
    """V3-04 — Compteurs sidebar pour badges UI."""
    from cinesort.ui.api.dashboard_support import get_sidebar_counters
    return {"data": get_sidebar_counters(self)}
```

### Étape 4 — Injection HTML

Dans `web/dashboard/index.html`, ajouter un `<span class="nav-badge" data-badge-key="..."></span>`
sur les 3 entrées concernées :

```html
<button class="nav-btn" data-route="/validation">
  <span class="nav-icon">...</span>
  <span>Validation</span>
  <span class="nav-badge" data-badge-key="validation"></span>
</button>
```

(Idem pour Application et Qualité — adapte les sélecteurs réels)

### Étape 5 — Chargement périodique

Dans `web/dashboard/app.js`, ajouter une fonction qui charge les compteurs et les injecte :

```javascript
async function _loadSidebarCounters() {
  try {
    const { apiPost } = await import("./core/api.js");
    const res = await apiPost("get_sidebar_counters");
    const data = res.data || {};
    document.querySelectorAll("[data-badge-key]").forEach((el) => {
      const key = el.dataset.badgeKey;
      const v = data[key] || 0;
      el.textContent = v > 0 ? String(v) : "";
      el.classList.toggle("nav-badge--active", v > 0);
    });
  } catch (e) { /* silencieux */ }
}

// Polling toutes les 30s + au boot
_loadSidebarCounters();
setInterval(_loadSidebarCounters, 30000);
```

### Étape 6 — Style CSS

Dans `web/dashboard/styles.css` :

```css
/* V3-04 — Badges sidebar */
.nav-badge {
  display: inline-block;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  margin-left: auto;
  background: var(--surface-elevated);
  color: var(--text-muted);
  border-radius: 10px;
  font-size: 0.75rem;
  font-weight: 600;
  line-height: 20px;
  text-align: center;
  visibility: hidden; /* caché par défaut quand vide */
}
.nav-badge--active {
  visibility: visible;
  background: var(--accent);
  color: var(--bg-primary);
}
```

### Étape 7 — Tests

Crée `tests/test_sidebar_counters.py` :

```python
"""V3-04 — Vérifie l'endpoint et l'injection des badges sidebar."""
from __future__ import annotations
import unittest
from pathlib import Path
import sys; sys.path.insert(0, '.')


class SidebarCountersBackendTests(unittest.TestCase):
    def test_function_exists(self):
        from cinesort.ui.api.dashboard_support import get_sidebar_counters
        self.assertTrue(callable(get_sidebar_counters))

    def test_returns_expected_keys(self):
        from cinesort.ui.api.dashboard_support import get_sidebar_counters

        # Mock api avec store qui retourne pas de run
        class FakeStore:
            def get_latest_run_id(self): return None
        class FakeApi:
            def _get_store(self): return FakeStore()

        out = get_sidebar_counters(FakeApi())
        for k in ("validation", "application", "quality"):
            self.assertIn(k, out)
            self.assertIsInstance(out[k], int)


class SidebarCountersFrontendTests(unittest.TestCase):
    def setUp(self):
        self.html = Path("web/dashboard/index.html").read_text(encoding="utf-8")
        self.css = Path("web/dashboard/styles.css").read_text(encoding="utf-8")
        self.app_js = Path("web/dashboard/app.js").read_text(encoding="utf-8")

    def test_badge_spans_present(self):
        for key in ("validation", "application", "quality"):
            self.assertIn(f'data-badge-key="{key}"', self.html, f"Badge manquant: {key}")

    def test_loader_function_present(self):
        self.assertIn("_loadSidebarCounters", self.app_js)
        self.assertIn("get_sidebar_counters", self.app_js)

    def test_polling_interval(self):
        self.assertIn("setInterval(_loadSidebarCounters", self.app_js)

    def test_css_styles(self):
        self.assertIn(".nav-badge", self.css)
        self.assertIn(".nav-badge--active", self.css)


if __name__ == "__main__":
    unittest.main()
```

### Étape 8 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_sidebar_counters -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 9 — Commits

- `feat(api): get_sidebar_counters endpoint (V3-04)`
- `feat(dashboard): sidebar badges with 30s polling`
- `test(dashboard): sidebar counters structural + backend tests`

---

## LIVRABLES

Récap :
- Endpoint `get_sidebar_counters` retourne `{validation, application, quality}`
- Badges visibles sur 3 entrées sidebar
- Polling 30s
- Vide = invisible (no-noise)
- 0 régression
- 3 commits sur `feat/sidebar-counters`
