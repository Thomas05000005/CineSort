# V4-07 — Audit a11y NVDA (guide test humain pas-à-pas)

**Branche** : `test/a11y-nvda-guide`
**Worktree** : `.claude/worktrees/test-a11y-nvda-guide/`
**Effort** : 1-2h instance + 1-2h utilisateur
**Mode** : 🟡 Hybride — instance prépare le guide pas-à-pas + checklist, **toi** lances NVDA et exécutes
**Fichiers concernés** :
- `audit/results/v4-07-nvda-checklist.md` (nouveau — guide test humain)
- `audit/results/v4-07-axe-baseline.md` (nouveau — baseline axe-core)
- `tests/test_axe_dashboard.py` (nouveau — axe-core via Playwright)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b test/a11y-nvda-guide .claude/worktrees/test-a11y-nvda-guide audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/test-a11y-nvda-guide
pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu prépares le guide + le test axe-core automatique.
Les findings réels (sur l'app) seront documentés dans une session séparée par
l'utilisateur après son test NVDA.

---

## CONTEXTE

V3-07 a fait le focus visible. V3-03 a ajouté des tooltips ARIA. Mais on n'a JAMAIS
testé l'app avec un vrai lecteur d'écran. **NVDA est gratuit** et c'est le standard
de fait pour Windows. C'est le seul moyen de valider l'accessibilité réelle.

**Ce qu'on peut automatiser** : axe-core via Playwright qui détecte ~30% des
violations a11y (les évidentes : contrast, ARIA missing, etc.).

**Ce qui doit être fait par l'humain** : NVDA + clavier seul, vérifier que tout
le workflow critique est utilisable sans souris ni écran.

---

## MISSION

### Étape 1 — Test axe-core auto

Crée `tests/test_axe_dashboard.py` :

```python
"""V4-07 — Audit a11y axe-core sur le dashboard via Playwright.

Run:
  CINESORT_API_TOKEN=<token> python -m unittest tests.test_axe_dashboard -v
"""
from __future__ import annotations
import json
import os
import unittest
from pathlib import Path

OUTPUT_DIR = Path("audit/results")
DASHBOARD_URL = "http://127.0.0.1:8642/dashboard/"
ROUTES = ["/status", "/library", "/quality", "/validation", "/settings", "/help"]


class AxeDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        token = os.environ.get("CINESORT_API_TOKEN")
        if not token:
            raise unittest.SkipTest("CINESORT_API_TOKEN required")
        cls.token = token
        try:
            from playwright.sync_api import sync_playwright
            cls.playwright = sync_playwright().start()
        except ImportError:
            raise unittest.SkipTest("playwright non installé")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "playwright"):
            cls.playwright.stop()

    def test_axe_baseline(self):
        browser = self.playwright.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        page.goto(f"{DASHBOARD_URL}?ntoken={self.token}&native=1")
        page.wait_for_load_state("networkidle")

        # Charge axe-core depuis CDN (acceptable pour test, pas runtime)
        page.add_script_tag(url="https://cdn.jsdelivr.net/npm/axe-core@4.10.0/axe.min.js")

        all_violations = {}
        for route in ROUTES:
            page.evaluate(f"window.location.hash = '{route}'")
            page.wait_for_timeout(800)
            result = page.evaluate("""
              async () => {
                const r = await axe.run({
                  runOnly: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']
                });
                return {
                  violations: r.violations.map(v => ({
                    id: v.id, impact: v.impact, help: v.help, helpUrl: v.helpUrl,
                    nodes: v.nodes.length
                  }))
                };
              }
            """)
            all_violations[route] = result["violations"]

        browser.close()

        # Génère un rapport
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        report_md = OUTPUT_DIR / "v4-07-axe-baseline.md"

        md = "# V4-07 — Baseline axe-core\n\n"
        md += "Audit automatique a11y via [axe-core](https://github.com/dequelabs/axe-core) (WCAG 2.0/2.1/2.2 A+AA).\n\n"
        total_violations = 0
        critical_violations = []

        for route, violations in all_violations.items():
            md += f"## {route}\n\n"
            if not violations:
                md += "✅ Aucune violation détectée par axe-core.\n\n"
                continue
            md += "| Règle | Impact | Aide | Nœuds touchés |\n|---|---|---|---|\n"
            for v in violations:
                md += f"| `{v['id']}` | {v['impact']} | [{v['help']}]({v['helpUrl']}) | {v['nodes']} |\n"
                total_violations += 1
                if v["impact"] in ("critical", "serious"):
                    critical_violations.append(f"{route}: {v['id']}")
            md += "\n"

        md += f"\n## Résumé\n\n"
        md += f"- **Total violations** : {total_violations}\n"
        md += f"- **Critical/Serious** : {len(critical_violations)}\n"
        if critical_violations:
            md += "\n### Critiques à fixer avant release\n"
            for v in critical_violations:
                md += f"- {v}\n"

        report_md.write_text(md, encoding="utf-8")

        # Soft assertion : on note mais on ne fail pas la suite (sera corrigé dans la suite V4)
        if critical_violations:
            print(f"\n⚠ {len(critical_violations)} violations critiques (cf {report_md})")

        # Hard assertion : 0 critique acceptable pour public release
        # → décommente après que les findings soient fixés
        # self.assertEqual(len(critical_violations), 0,
        #                  f"Violations critiques: {critical_violations}")


if __name__ == "__main__":
    unittest.main()
```

### Étape 2 — Lance le test axe-core

```bash
# Terminal 1
.venv313/Scripts/python.exe app.py

# Terminal 2
CINESORT_API_TOKEN=<ton-token> .venv313/Scripts/python.exe -m unittest tests.test_axe_dashboard -v
```

Examine `audit/results/v4-07-axe-baseline.md`. Si violations critiques → fix simples
sur le dashboard (ARIA labels manquants, etc.) ou note pour V5.

### Étape 3 — Guide test NVDA pour l'utilisateur

Crée `audit/results/v4-07-nvda-checklist.md` :

```markdown
# V4-07 — Guide test NVDA + clavier seul

## Pourquoi ?

Tester avec un vrai lecteur d'écran est le seul moyen de valider que l'app est
utilisable par les personnes aveugles ou malvoyantes. C'est aussi un excellent
révélateur de problèmes UX généraux (focus, ordre logique, labels manquants).

## Préparation

### Installer NVDA (gratuit, open-source)

1. Télécharge depuis https://www.nvaccess.org/download/
2. Installe (typique : Suivant × 4)
3. Au démarrage, choisis "Installer NVDA sur cet ordinateur"

### Raccourcis NVDA essentiels

| Raccourci | Action |
|---|---|
| `Ctrl` | Stopper la lecture en cours |
| `Insert + Espace` | Activer/désactiver le mode focus (laisser NVDA gérer le clavier) |
| `Insert + ↓` | Lire à partir d'ici jusqu'à la fin |
| `Tab` / `Shift+Tab` | Naviguer entre éléments interactifs |
| `H` | Élément suivant titre (en mode browse) |
| `B` | Bouton suivant |
| `F` | Champ formulaire suivant |
| `K` | Lien suivant |
| `Insert + N` | Menu NVDA (Quitter via ce menu) |

## Test à faire

Lance CineSort, lance NVDA, **mets un masque sur ton écran** (ou ferme les yeux).
Si tu peux tout faire au son + clavier seul, l'app est accessible.

### Workflow critique 1 : Premier scan

- [ ] Au démarrage, NVDA annonce "CineSort, dashboard distant" (ou équivalent)
- [ ] Tab te ramène sur la sidebar → annoncée comme "Navigation principale"
- [ ] Flèches verticales pour naviguer dans la sidebar (ou Tab pour entrée par entrée)
- [ ] Active "Paramètres" → annoncé "Paramètres, page principale"
- [ ] Tab vers le champ "Dossiers racine" → annoncé "Dossiers racine, champ texte"
- [ ] Saisis un dossier → NVDA confirme la saisie
- [ ] Tab vers "Enregistrer" → annoncé "Enregistrer, bouton"
- [ ] Active → confirmation entendue

### Workflow critique 2 : Validation

- [ ] Aller sur la vue Validation
- [ ] Tab dans la liste de films → chaque ligne annoncée avec titre + score + actions
- [ ] Boutons "Approuver" / "Rejeter" → annoncés clairement
- [ ] Active "Approuver" → confirmation entendue

### Vérifications globales

- [ ] **Skip link** "Aller au contenu principal" présent (Tab depuis le début)
- [ ] Tous les **boutons** ont un label parlant (pas juste "btn1")
- [ ] Tous les **icônes interactifs** ont un `aria-label` (NVDA dit "Bouton recherche", pas "Bouton")
- [ ] Les **icônes décoratives** sont silencieuses (NVDA ne dit pas leur HTML)
- [ ] **Modales** : focus piégé dedans, Escape ferme
- [ ] **Drawer mobile** (V3-06) : annoncé comme "dialog", focus à l'intérieur
- [ ] **Tooltips ⓘ** (V3-03) : focus dessus → texte annoncé
- [ ] **Compteurs sidebar** (V3-04) : "Validation, 3 films en attente" (ou équivalent)
- [ ] **Tableaux** : NVDA annonce les en-têtes de colonne quand tu navigues les cellules

## Reporter les findings

Crée `audit/results/v4-07-nvda-findings.md` avec ce que NVDA n'annonce pas
correctement, ou ce qui est inutilisable au clavier seul.

Format suggéré :

| Vue | Élément | Problème | Sévérité | Fix proposé |
|---|---|---|---|---|
| Validation | Bouton "Approuver" | NVDA dit juste "Bouton" | High | Ajouter aria-label="Approuver ce film" |
| Sidebar | Badges (V3-04) | NVDA ne lit pas les compteurs | Med | Ajouter aria-live="polite" |

## Suivi

- **Critical/High** → fix avant public release (V4 patch)
- **Medium** → roadmap V5
- **Low/cosmetic** → nice-to-have

## Ressources

- [WCAG 2.2 AA quick reference](https://www.w3.org/WAI/WCAG22/quickref/)
- [WebAIM NVDA shortcuts](https://webaim.org/resources/shortcuts/nvda)
- [Inclusive Components](https://inclusive-components.design/)
```

### Étape 4 — Tests structurels

```python
# tests/test_v4_07_artifacts.py
import unittest
from pathlib import Path

class V4_07ArtifactsTests(unittest.TestCase):
    def test_nvda_checklist_exists(self):
        self.assertTrue(Path("audit/results/v4-07-nvda-checklist.md").is_file())

    def test_axe_test_exists(self):
        self.assertTrue(Path("tests/test_axe_dashboard.py").is_file())

if __name__ == "__main__":
    unittest.main()
```

### Étape 5 — Vérifications

```bash
.venv313/Scripts/python.exe -m ruff check tests/test_axe_dashboard.py 2>&1 | tail -2
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
```

### Étape 6 — Commits

- `test(a11y): axe-core baseline test for dashboard (V4-07)`
- `docs(audit): NVDA + keyboard-only test guide for human validation`
- (si fixes simples a11y) `fix(a11y): apply axe-core suggested fixes (aria labels, etc.)`

---

## LIVRABLES

- Test axe-core qui produit baseline `audit/results/v4-07-axe-baseline.md`
- Guide pas-à-pas NVDA + clavier seul pour l'utilisateur
- Tests structurels
- 2-3 commits sur `test/a11y-nvda-guide`

## ⚠ Pour l'utilisateur après le merge

1. Installe NVDA (gratuit, ~5 min)
2. Suis le guide `v4-07-nvda-checklist.md`
3. Note les findings dans `v4-07-nvda-findings.md`
4. Fix les criticaux avant public release (peut faire l'objet d'une nouvelle vague V4-bis ou V5-01)
