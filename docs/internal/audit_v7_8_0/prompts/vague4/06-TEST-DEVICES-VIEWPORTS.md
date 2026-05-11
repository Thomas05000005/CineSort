# V4-06 — Test devices multi-viewports (script + guide humain)

**Branche** : `test/devices-multi-viewports`
**Worktree** : `.claude/worktrees/test-devices-multi-viewports/`
**Effort** : 2h instance + 2-4h utilisateur
**Mode** : 🟡 Hybride — instance prépare le script Playwright + checklist, **toi** testes sur appareils physiques
**Fichiers concernés** :
- `tests/visual/test_responsive_viewports.py` (nouveau — Playwright multi-viewports)
- `audit/results/v4-06-devices-checklist.md` (nouveau — guide humain)
- `audit/results/v4-06-screenshots/` (nouveau — captures par viewport)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b test/devices-multi-viewports .claude/worktrees/test-devices-multi-viewports audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/test-devices-multi-viewports
pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT le script Playwright + la checklist.
Aucun changement applicatif (les bugs trouvés via le script seront corrigés en V4+).

---

## CONTEXTE

L'utilisateur va publier CineSort à 2000 users qui ont des configurations variées :
Win10/Win11, écrans 1366×768 → 4K, et certains accèdent au dashboard distant depuis
leur téléphone (375×667 → 414×896).

**Ce qu'on peut automatiser** : captures Playwright en multiples viewports + détection
de débordements/clip via checks DOM.

**Ce qui doit être fait par l'humain** : tests réels sur Win10 vs Win11 (DPI scaling,
fonts, native API), 4K Windows scaling à 200%, et tests sur des téléphones physiques
réels (touch, viewport mobile réel, browser mobile).

---

## MISSION

### Étape 1 — Lire l'existant

- `tests/e2e/test_08_responsive.py` (s'il existe — éviter duplication)
- `tests/e2e/conftest.py` (pour réutiliser les fixtures Playwright)

### Étape 2 — Script multi-viewports

Crée `tests/visual/test_responsive_viewports.py` :

```python
"""V4-06 — Captures Playwright sur tous les viewports cibles + détection débordements.

Run:
  CINESORT_API_TOKEN=<token> python -m unittest tests.visual.test_responsive_viewports -v

Génère:
  audit/results/v4-06-screenshots/<viewport>/<view>.png
  audit/results/v4-06-overflow.md (si débordements détectés)
"""
from __future__ import annotations
import asyncio
import json
import os
import unittest
from pathlib import Path

OUTPUT_DIR = Path("audit/results/v4-06-screenshots")
OVERFLOW_REPORT = Path("audit/results/v4-06-overflow.md")
DASHBOARD_URL = "http://127.0.0.1:8642/dashboard/"

VIEWPORTS = [
    ("mobile_320", 320, 568),         # iPhone SE 1ère gen
    ("mobile_375", 375, 667),         # iPhone SE 2/3
    ("mobile_414", 414, 896),         # iPhone Plus
    ("tablet_768", 768, 1024),        # iPad portrait
    ("laptop_1024", 1024, 768),       # netbook
    ("laptop_1280", 1280, 800),       # MacBook 13"
    ("desktop_1366", 1366, 768),      # PC commun Win10/Win11
    ("desktop_1440", 1440, 900),      # MacBook 15"
    ("desktop_1920", 1920, 1080),     # Full HD
    ("4k_3840", 3840, 2160),          # 4K
]

ROUTES = ["/status", "/library", "/quality", "/validation", "/settings", "/help"]


class ResponsiveViewportTests(unittest.TestCase):
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

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "playwright"):
            cls.playwright.stop()

    def test_capture_all_viewports(self):
        overflow_findings = []

        for vp_name, w, h in VIEWPORTS:
            vp_dir = OUTPUT_DIR / vp_name
            vp_dir.mkdir(exist_ok=True)

            browser = self.playwright.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": w, "height": h})
            page = ctx.new_page()
            page.goto(f"{DASHBOARD_URL}?ntoken={self.token}&native=1")
            page.wait_for_load_state("networkidle")

            for route in ROUTES:
                page.evaluate(f"window.location.hash = '{route}'")
                page.wait_for_timeout(800)

                # Capture
                fname = route.replace("/", "_").strip("_") + ".png"
                page.screenshot(path=str(vp_dir / fname), full_page=False)

                # Détection débordement horizontal
                overflow = page.evaluate("""
                  () => {
                    const docW = document.documentElement.clientWidth;
                    const scrollW = document.documentElement.scrollWidth;
                    return scrollW > docW + 5; // tolérance 5px
                  }
                """)
                if overflow:
                    overflow_findings.append({
                        "viewport": vp_name,
                        "route": route,
                        "doc_width": w,
                        "scroll_width": page.evaluate("document.documentElement.scrollWidth"),
                    })

            browser.close()

        # Rapport overflow
        if overflow_findings:
            md = "# V4-06 — Débordements détectés\n\n"
            md += "| Viewport | Route | Largeur viewport | Largeur scroll |\n"
            md += "|---|---|---|---|\n"
            for f in overflow_findings:
                md += f"| {f['viewport']} | {f['route']} | {f['doc_width']}px | {f['scroll_width']}px |\n"
            OVERFLOW_REPORT.write_text(md, encoding="utf-8")

        # Soft assertion : info, ne fail pas la CI mais on note
        if overflow_findings:
            print(f"\n⚠ {len(overflow_findings)} débordements horizontaux détectés "
                  f"(cf {OVERFLOW_REPORT})")


if __name__ == "__main__":
    unittest.main()
```

### Étape 3 — Lance le script

```bash
# Terminal 1
.venv313/Scripts/python.exe app.py

# Terminal 2
CINESORT_API_TOKEN=<ton-token> .venv313/Scripts/python.exe -m unittest tests.visual.test_responsive_viewports -v
```

Ça génère ~60 screenshots (10 viewports × 6 routes) + un rapport overflow.

### Étape 4 — Checklist humaine

Crée `audit/results/v4-06-devices-checklist.md` (après que les screenshots auto soient générés) :

```markdown
# V4-06 — Checklist test devices physiques

## Préparation

L'instance Playwright a généré 60 screenshots dans `audit/results/v4-06-screenshots/<viewport>/`.
Avant de tester sur appareils physiques, **passe rapidement en revue les screenshots**
pour repérer les évidents :

- [ ] Aucune zone clippée / texte coupé
- [ ] Sidebar visible/lisible sur mobile
- [ ] Pas de débordement horizontal (cf `audit/results/v4-06-overflow.md` s'il existe)

## Tests humains à faire

Pour ces tests, l'humain doit utiliser des appareils réels (Playwright simule mais
ne reproduit pas le DPI Windows, le scaling natif, ni les browsers mobiles réels).

### A. Windows 10 (laptop ou desktop)

- [ ] Lance l'app, scan ~50 films de test
- [ ] Vérifie : fenêtre s'ouvre sans clip, fonts lisibles
- [ ] Teste les 6 vues principales (Accueil, Bibliothèque, Validation, Apply, Qualité, Paramètres)
- [ ] Note tout glitch visuel ou lag dans `audit/results/v4-06-tests-humains.md`

### B. Windows 11 (4K avec scaling 150-200%)

- [ ] Lance l'app sur écran 4K
- [ ] Vérifie : DPI awareness (pas de blur), fonts proportionnelles
- [ ] Teste un scan + apply
- [ ] Vérifie que le splash s'affiche correctement

### C. Petit écran (1366×768, courant en entrée de gamme)

- [ ] Lance l'app
- [ ] Vérifie que toutes les actions principales sont accessibles sans scroll horizontal
- [ ] Vérifie le drawer mobile inspector (V3-06) sur la vue Validation

### D. Mobile (téléphone Android ou iOS via dashboard distant)

Prérequis : dashboard activé, token configuré, IP du PC connue.

- [ ] Sur ton téléphone, ouvre `http://<ip-pc>:8642/dashboard/`
- [ ] Login avec le token
- [ ] Teste navigation sidebar bottom-tab
- [ ] Sur la vue Validation, **clique le bouton "Inspecter"** (V3-06) → drawer s'ouvre depuis la droite
- [ ] Tooltips ⓘ glossaire (V3-03) → tap fonctionne sur mobile
- [ ] Boutons assez gros pour tap (≥ 44px) → vérifier sur les actions critiques

### E. Tablette (iPad ou Android tablet)

- [ ] Mêmes tests que mobile
- [ ] Vérifie que le layout intermédiaire (768-1023px) ne clippe pas

## Reporter les bugs

Pour chaque bug trouvé :
- Capture l'écran (téléphone) ou Win+Shift+S (desktop)
- Note dans `audit/results/v4-06-tests-humains.md` :
  - Device + version OS
  - Vue concernée
  - Description courte
  - Capture
  - Niveau (bloquant / important / cosmétique)

Les bloquants doivent être fixés AVANT le public release. Les cosmétiques peuvent être
listés dans la roadmap V5+.
```

### Étape 5 — Test structurel + commit

Crée juste un test qui valide que les fichiers de checklist existent :

```python
# tests/test_v4_06_artifacts.py (court)
import unittest
from pathlib import Path

class V4_06ArtifactsTests(unittest.TestCase):
    def test_checklist_exists(self):
        self.assertTrue(Path("audit/results/v4-06-devices-checklist.md").is_file())

    def test_script_exists(self):
        self.assertTrue(Path("tests/visual/test_responsive_viewports.py").is_file())

if __name__ == "__main__":
    unittest.main()
```

### Étape 6 — Vérifications

```bash
.venv313/Scripts/python.exe -m ruff check tests/visual/ 2>&1 | tail -2
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
```

### Étape 7 — Commits

- `test(visual): multi-viewport responsive Playwright capture script (V4-06)`
- `docs(audit): V4-06 device test checklist for human validation`
- (Optionnel après run du script) `docs(audit): V4-06 baseline screenshots`

---

## LIVRABLES

- Script Playwright qui capture 10 viewports × 6 routes
- Détection automatique de débordement horizontal
- Checklist humaine claire pour tests Win10/11/4K/mobile
- Tests structurels qui valident la présence des artifacts
- 2-3 commits sur `test/devices-multi-viewports`

## ⚠ Pour l'utilisateur après le merge

Lance toi-même les tests A/B/C/D/E sur tes appareils. Note les bugs dans
`audit/results/v4-06-tests-humains.md`. Si bug bloquant → ouvre une issue et fix
avant le public release.
