# V4-05 — Lighthouse score dashboard

**Branche** : `test/lighthouse-score`
**Worktree** : `.claude/worktrees/test-lighthouse-score/`
**Effort** : 2-3h
**Mode** : 🟢 Parallélisable (Lighthouse CLI sur localhost)
**Fichiers concernés** :
- `scripts/run_lighthouse.py` (nouveau — wrapper)
- `audit/results/v4-05-lighthouse-results.md` (nouveau — rapport)
- `tests/test_lighthouse_baseline.py` (nouveau — assert thresholds)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b test/lighthouse-score .claude/worktrees/test-lighthouse-score audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/test-lighthouse-score

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT le script Lighthouse + son test + le
rapport. Pas de modif applicative.

---

## CONTEXTE

Le dashboard CineSort est servi via HTTP local (`localhost:8642/dashboard/`). On veut
une mesure objective de sa performance / accessibilité / best practices via le score
Lighthouse de Google. Cible :
- **Performance** ≥ 80 (peut être limité par le bundle CSS/JS embarqué)
- **Accessibility** ≥ 90 (V3-07 a fait le focus visible, V3-03 les tooltips ARIA)
- **Best Practices** ≥ 90
- **SEO** : N/A (pas une page publique)

---

## MISSION

### Étape 1 — Vérifier disponibilité Lighthouse

```bash
node --version
npx lighthouse --version 2>&1 || echo "Pas installé"
```

Si Node.js disponible mais pas Lighthouse, install one-shot :
```bash
npm install -g lighthouse
# OU sans install global : npx lighthouse <url> --output=json --output=html
```

Si Node.js pas disponible, fallback vers la lib Python `lighthouse-bin` n'existe pas,
donc soit :
- Demander à l'utilisateur d'installer Node.js
- Utiliser une approximation Python via Playwright + métriques manuelles

### Étape 2 — Wrapper Python

Crée `scripts/run_lighthouse.py` :

```python
"""V4-05 — Lance Lighthouse sur le dashboard CineSort + parse résultats.

Usage:
  1. Lancer l'app dans un autre terminal : python app.py
  2. python scripts/run_lighthouse.py [token] [output_dir]
"""
from __future__ import annotations
import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

DASHBOARD_URL = "http://127.0.0.1:8642/dashboard/"


def run_lighthouse(url: str, output_dir: Path, categories: list[str]) -> dict:
    """Lance Lighthouse et retourne {category: score 0-100}."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "lighthouse_report.json"
    html_path = output_dir / "lighthouse_report.html"

    cmd = [
        "npx", "lighthouse", url,
        "--output=json", "--output=html",
        f"--output-path={output_dir / 'lighthouse_report'}",
        "--chrome-flags=--headless --no-sandbox",
        "--only-categories=" + ",".join(categories),
        "--quiet",
    ]
    logger.info("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"Lighthouse failed: {result.stderr}")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    scores = {}
    for cat_id, cat_data in data.get("categories", {}).items():
        scores[cat_id] = round((cat_data.get("score") or 0) * 100)
    return scores


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("token", nargs="?", default=os.environ.get("CINESORT_API_TOKEN", ""))
    parser.add_argument("output_dir", nargs="?", default="audit/results/lighthouse")
    args = parser.parse_args()

    if not args.token:
        print("⚠ Token requis. Passe en arg ou via CINESORT_API_TOKEN.")
        print("  Le token est dans <state_dir>/settings.json -> rest_api_token")
        sys.exit(1)

    if not shutil.which("npx"):
        print("⚠ Node.js + npx requis. Install: https://nodejs.org/")
        sys.exit(1)

    output_dir = Path(args.output_dir)
    url = f"{DASHBOARD_URL}?ntoken={args.token}&native=1"

    print(f"Running Lighthouse on {url}")
    scores = run_lighthouse(url, output_dir, ["performance", "accessibility", "best-practices"])

    print("\n=== Scores ===")
    for cat, score in scores.items():
        emoji = "✅" if score >= 80 else "⚠" if score >= 60 else "❌"
        print(f"  {emoji} {cat}: {score}/100")

    print(f"\nRapport HTML : {output_dir}/lighthouse_report.report.html")

    # Sauve un summary pour le test
    summary = output_dir / "summary.json"
    summary.write_text(json.dumps(scores, indent=2), encoding="utf-8")
    print(f"Summary: {summary}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
```

### Étape 3 — Lancer Lighthouse

```bash
# Terminal 1
.venv313/Scripts/python.exe app.py

# Terminal 2
.venv313/Scripts/python.exe scripts/run_lighthouse.py <ton-token>
```

Attendre fin (60-120s).

### Étape 4 — Analyser résultats + ajustements

Si un score est < seuil :
- Ouvre le `lighthouse_report.report.html` (HTML interactif)
- Lis les recommandations Lighthouse
- Pour chaque recommandation **simple** (ex. "ajouter `loading=lazy` aux images,
  préconnect CDN, etc.), applique-la

⚠ Pour les "gros" findings (refactor d'archi pour perf), juste les noter dans le
rapport, ne pas les fixer (ce sera V4+ ou ignoré).

### Étape 5 — Test baseline

Crée `tests/test_lighthouse_baseline.py` :

```python
"""V4-05 — Garantit que les scores Lighthouse ne régressent pas."""
from __future__ import annotations
import json
import unittest
from pathlib import Path


# Seuils minimum acceptés (pour CI)
THRESHOLDS = {
    "performance": 70,       # tolérance large car bundle local
    "accessibility": 85,     # exigence haute (V3-07 + V3-03)
    "best-practices": 85,
}


class LighthouseBaselineTests(unittest.TestCase):
    SUMMARY_PATH = Path("audit/results/lighthouse/summary.json")

    @classmethod
    def setUpClass(cls):
        if not cls.SUMMARY_PATH.is_file():
            raise unittest.SkipTest(
                f"Lighthouse summary missing ({cls.SUMMARY_PATH}). "
                "Lancer d'abord : python scripts/run_lighthouse.py"
            )
        cls.scores = json.loads(cls.SUMMARY_PATH.read_text(encoding="utf-8"))

    def test_performance(self):
        score = self.scores.get("performance", 0)
        self.assertGreaterEqual(score, THRESHOLDS["performance"],
                                f"Performance {score} < {THRESHOLDS['performance']}")

    def test_accessibility(self):
        score = self.scores.get("accessibility", 0)
        self.assertGreaterEqual(score, THRESHOLDS["accessibility"],
                                f"Accessibility {score} < {THRESHOLDS['accessibility']}")

    def test_best_practices(self):
        score = self.scores.get("best-practices", 0)
        self.assertGreaterEqual(score, THRESHOLDS["best-practices"],
                                f"Best Practices {score} < {THRESHOLDS['best-practices']}")


if __name__ == "__main__":
    unittest.main()
```

### Étape 6 — Rapport markdown

Crée `audit/results/v4-05-lighthouse-results.md` :

```markdown
# V4-05 — Résultats Lighthouse dashboard

**Date** : YYYY-MM-DD
**URL testée** : http://127.0.0.1:8642/dashboard/
**Mode** : headless Chrome (npx lighthouse)

## Scores

| Catégorie | Score | Seuil | Verdict |
|---|---|---|---|
| Performance | XX/100 | ≥ 70 | ✅/⚠/❌ |
| Accessibility | XX/100 | ≥ 85 | ✅/⚠/❌ |
| Best Practices | XX/100 | ≥ 85 | ✅/⚠/❌ |

## Findings principaux

### Performance
- (Lister les 3-5 recommandations Lighthouse les plus impactantes)

### Accessibility
- (Idem)

### Best Practices
- (Idem)

## Corrections appliquées

- (Lister les fixes appliqués pendant cette mission)

## Recommandations différées (V4+)

- (Lister les findings non corrigés et pourquoi)

## Verdict global
✅ Prêt pour public release / ⚠ Acceptable mais à améliorer / ❌ Bloquant
```

### Étape 7 — Vérifications

```bash
.venv313/Scripts/python.exe -m ruff check scripts/ tests/test_lighthouse_baseline.py 2>&1 | tail -2
.venv313/Scripts/python.exe -m unittest tests.test_lighthouse_baseline -v 2>&1 | tail -10
```

### Étape 8 — Commits

- `feat(scripts): Lighthouse runner for dashboard local URL (V4-05)`
- `test(perf): assert Lighthouse baseline scores (perf/a11y/best-practices)`
- (si fixes) `fix(dashboard): apply Lighthouse-recommended optimizations`
- `docs(audit): Lighthouse results V4-05`

---

## LIVRABLES

- `scripts/run_lighthouse.py` reproductible (avec ou sans Node.js documenté)
- `audit/results/lighthouse/summary.json` + rapport HTML interactif
- `tests/test_lighthouse_baseline.py` qui skip si summary absent
- `audit/results/v4-05-lighthouse-results.md` avec verdict
- 0 régression
- 3-4 commits sur `test/lighthouse-score`

## ⚠ Cas Node.js absent

Si la machine n'a pas Node.js installé, l'instance documente ça dans le rapport et
laisse le script utilisable plus tard. Le test skip alors. C'est OK pour un release —
l'utilisateur peut lancer Lighthouse manuellement avant chaque release.
