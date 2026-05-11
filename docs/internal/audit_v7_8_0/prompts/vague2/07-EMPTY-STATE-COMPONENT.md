# V2-07 — Composant <EmptyState> réutilisable + migration 4 écrans

**Branche** : `feat/empty-state-component`
**Worktree** : `.claude/worktrees/feat-empty-state-component/`
**Effort** : 1-2 jours
**Priorité** : 🟠 IMPORTANT (audit D-PARENT-1 — pattern racine UX)
**Fichiers concernés** :
- `web/components/empty-state.js` (existe — l'enrichir)
- `web/views/quality.js` (déjà CTA via V1-05 — migrer vers composant)
- `web/views/validation.js`
- `web/views/library.js` ou `library-v5.js`
- `web/views/history.js`
- `web/dashboard/views/quality.js` (idem desktop)
- éventuellement `web/styles.css` ou `web/shared/components.css`

⚠ Coordination : V1-05 a déjà ajouté un CTA dans Quality. Migre-le vers le composant
réutilisable (refactor, pas duplicate).

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/empty-state-component .claude/worktrees/feat-empty-state-component audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-empty-state-component

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT empty-state.js + 4-5 vues + CSS si besoin.

---

## CONTEXTE

L'audit Lot 3 D-PARENT-1 : 4 écrans ont des empty states sans CTA actionnable
(Quality, Validation, Library Hub, History). Pattern manquant : composant standardisé.

V1-05 a déjà ajouté un CTA dans Quality (en code spécifique). Migrer vers un composant
factorisé pour cohérence + maintenance.

---

## MISSION

### Étape 1 — Lire l'existant

Lis `web/components/empty-state.js` (existe avec `buildEmptyStateHtml` et
`buildTableEmptyRow`). Note l'API actuelle pour ne pas casser les usages existants.

### Étape 2 — Enrichir le composant

Ajoute une factory enrichie SANS casser les fonctions existantes :

```javascript
/**
 * V2-07 : factory empty state enrichie avec CTA actionnable.
 *
 * @param {object} opts
 * @param {string} opts.icon       Icône Lucide SVG name (search, inbox, alert-circle, etc.)
 * @param {string} opts.title      Titre court (ex: "Aucun film analysé")
 * @param {string} opts.message    Description (ex: "Lancez un scan pour commencer.")
 * @param {string} [opts.ctaLabel] Texte du bouton CTA
 * @param {string} [opts.ctaRoute] Route dashboard (ex: "/library#step-analyse")
 * @param {Function} [opts.ctaAction] Fallback si pas de route (ex: () => navigateTo("home"))
 * @param {string} [opts.variant]  'card' (defaut) | 'inline' | 'fullscreen'
 * @returns {string} HTML markup
 */
function buildEmptyState(opts) {
  const { icon, title, message, ctaLabel, ctaRoute, ctaAction, variant = "card" } = opts || {};
  const iconHtml = icon ? `<svg class="empty-state__icon"><use href="#icon-${escape(icon)}"/></svg>` : "";
  const ctaHtml = ctaLabel
    ? `<button class="btn btn--primary empty-state__cta"
         ${ctaRoute ? `data-nav-route="${escape(ctaRoute)}"` : ""}
       >${escape(ctaLabel)}</button>`
    : "";
  return `<div class="empty-state empty-state--${escape(variant)}">
    ${iconHtml}
    ${title ? `<h3 class="empty-state__title">${escape(title)}</h3>` : ""}
    ${message ? `<p class="empty-state__message">${escape(message)}</p>` : ""}
    ${ctaHtml}
  </div>`;
}

/**
 * Bind handlers CTA après insertion HTML.
 * @param {HTMLElement} root  Conteneur parent
 * @param {Function} [defaultAction]  Si data-nav-route absent
 */
function bindEmptyStateCta(root, defaultAction) {
  root?.querySelectorAll(".empty-state__cta").forEach(btn => {
    btn.addEventListener("click", () => {
      const route = btn.dataset.navRoute;
      if (route && typeof window.location !== "undefined") {
        window.location.hash = "#" + route;
      } else if (typeof defaultAction === "function") {
        defaultAction();
      }
    });
  });
}
```

### Étape 3 — CSS

Ajoute dans `web/styles.css` ou `web/shared/components.css` (suivre la convention existante) :

```css
/* V2-07 : composant empty state */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: var(--sp-8);
  gap: var(--sp-3);
  color: var(--text-muted);
}
.empty-state--card {
  background: var(--surface-2);
  border-radius: var(--radius-md);
  border: 1px solid var(--border-1);
}
.empty-state--inline {
  padding: var(--sp-4);
}
.empty-state--fullscreen {
  min-height: 60vh;
}
.empty-state__icon {
  width: 48px;
  height: 48px;
  opacity: 0.5;
}
.empty-state__title {
  margin: 0;
  font-size: var(--fs-lg);
  color: var(--text-primary);
}
.empty-state__message {
  margin: 0;
  max-width: 480px;
}
.empty-state__cta {
  margin-top: var(--sp-2);
}
```

### Étape 4 — Migrer 4-5 écrans

Pour chaque vue avec empty state :
- Lis le code actuel
- Remplace le markup empty state custom par appel à `buildEmptyState(...)`
- Bind les handlers via `bindEmptyStateCta(...)` après insertion

Exemples :
- Quality : déjà CTA via V1-05 → migre vers le composant
- Validation : "Aucun film à valider" → ajoute CTA "Lancer un scan"
- Library Hub : "Aucun run disponible" → CTA "Lancer un scan"
- History : "Aucun historique" → CTA "Lancer un scan"

### Étape 5 — Tests

Crée `tests/test_empty_state_component.py` :

```python
"""V2-07 — composant EmptyState"""
from pathlib import Path
import unittest


class EmptyStateComponentTests(unittest.TestCase):
    def test_buildEmptyState_function_exists(self):
        src = (Path(__file__).resolve().parent.parent / "web/components/empty-state.js").read_text(encoding="utf-8")
        self.assertIn("buildEmptyState(", src)
        self.assertIn("bindEmptyStateCta(", src)

    def test_views_use_component(self):
        root = Path(__file__).resolve().parent.parent
        for view in ["web/views/quality.js", "web/views/validation.js"]:
            src = (root / view).read_text(encoding="utf-8")
            # Au moins l'un des 2 helpers doit être appelé
            self.assertTrue(
                "buildEmptyState(" in src or "bindEmptyStateCta(" in src,
                f"{view} : ne semble pas utiliser le composant EmptyState"
            )

    def test_css_classes_defined(self):
        root = Path(__file__).resolve().parent.parent
        css_files = [root / "web/styles.css", root / "web/shared/components.css"]
        found = False
        for f in css_files:
            if f.exists() and ".empty-state" in f.read_text(encoding="utf-8"):
                found = True
                break
        self.assertTrue(found, "CSS .empty-state non trouvé")
```

### Étape 6 — Vérifications

```bash
node --check web/components/empty-state.js
for f in web/views/quality.js web/views/validation.js web/views/library.js web/views/history.js; do
  [ -f "$f" ] && node --check "$f"
done
.venv313/Scripts/python.exe -m unittest tests.test_empty_state_component -v 2>&1 | tail -5
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 7 — Commits

3-5 commits :
- `feat(component): EmptyState factory + bindCta helper`
- `style(empty-state): add .empty-state* CSS classes`
- `refactor(quality): use EmptyState component (replaces V1-05 inline CTA)`
- `refactor(validation): use EmptyState component`
- `refactor(library/history): use EmptyState component`

---

## LIVRABLES

Récap :
- Composant enrichi avec buildEmptyState + bindEmptyStateCta
- CSS .empty-state* ajouté
- 4-5 vues migrées
- Tests structurels
- 0 régression
- 3-5 commits sur `feat/empty-state-component`
