# V5C-02 — Décision Jellyfin/Plex/Radarr/Logs : port v5 ou conservation v4 ?

**Branche** : `feat/v5c-integrations-v5`
**Worktree** : `.claude/worktrees/feat-v5c-integrations-v5/`
**Effort** : 4-6h (port complet) ou 30 min (juste alignement style)
**Mode** : 🟢 Parallélisable (avec V5C-01)
**Fichiers concernés** :
- `web/dashboard/views/jellyfin.js` (~200L)
- `web/dashboard/views/plex.js` (~150L)
- `web/dashboard/views/radarr.js` (~150L)
- `web/dashboard/views/logs.js` (~150L)
- `tests/test_v5c_integrations.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/v5c-integrations-v5 .claude/worktrees/feat-v5c-integrations-v5 audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-v5c-integrations-v5

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT les 4 vues integration + logs + leurs tests. Pas d'autre fichier.

---

## CONTEXTE

V5B a activé v5 mais a conservé les vues v4 pour Jellyfin/Plex/Radarr/Logs (elles n'avaient pas de version v5 dans `web/views/`). Question : faut-il les porter en v5 (effort + bénéfice cohérence) ou les laisser en v4 (déjà fonctionnelles avec V1-V4 polish) ?

---

## DÉCISION ATTENDUE DE L'INSTANCE

**L'instance évalue les 4 vues et choisit** :

### Option A — Port complet vers style v5

Si les vues actuelles ont déjà tout le polish V1-V4 et que ça vaut la peine d'avoir une cohérence stylistique parfaite avec le reste v5. Effort ~4-6h.

Pattern de port (similaire à V5bis-01 à 07) :
- Garder le pattern ESM `apiPost` actuel des vues v4 dashboard (elles utilisent déjà ce pattern, contrairement aux vues legacy `web/views/*.js`)
- Adapter visuellement : préfixe `v5-*` sur les classes CSS, layout cohérent v5
- Conserver toutes les features (test connexion, sync report, etc.)

### Option B — Conservation v4 avec alignement minimal

Si les vues v4 sont déjà bien et que les changements visuels mineurs suffisent. Effort ~30 min :
- Vérifier que les classes utilisées sont compatibles avec le shell v5
- Ajouter quelques tokens v5 si manque
- Documenter que ces vues restent en v4 par choix architectural

---

## MISSION

### Étape 1 — Audit des 4 vues

Pour chaque vue, lis et évalue :

```bash
wc -l web/dashboard/views/jellyfin.js web/dashboard/views/plex.js web/dashboard/views/radarr.js web/dashboard/views/logs.js
```

Note pour chaque :
- Lignes de code
- Pattern utilisé (déjà ESM `apiPost` ou pas ?)
- Classes CSS (préfixe v5 déjà ou v4 ?)
- Features importantes à préserver

### Étape 2 — Décision argumentée

Crée `audit/results/v5c-02-decision.md` :

```markdown
# V5C-02 — Décision intégrations

## Audit

| Vue | LOC | Pattern actuel | Classes CSS | Features V1-V4 |
|---|---|---|---|---|
| jellyfin.js | ... | ESM/apiPost | v4 | sync, test connexion, libraries |
| plex.js | ... | ... | ... | ... |
| radarr.js | ... | ... | ... | ... |
| logs.js | ... | ... | ... | ... |

## Décision

**Choisi : Option A / B**

Raison : ...

## Plan d'exécution

...
```

### Étape 3 — Exécution selon décision

#### Si Option A (port v5)

Pour chaque vue :
1. Renommer classes CSS v4 → v5 (`.btn` → `.v5-btn`, etc.)
2. Vérifier que les imports sont propres (pas de pywebview.api directe)
3. Ajouter glossary tooltip ⓘ sur termes techniques (`Jellyfin token`, `Plex library`, etc.)
4. Test structurel

#### Si Option B (conservation)

1. Vérifier que les classes utilisées sont compatibles avec shell v5
2. Ajouter mention dans CLAUDE.md : "Jellyfin/Plex/Radarr/Logs restent en v4 par choix architectural — vues simples qui ne bénéficient pas d'une refonte v5"
3. Test structurel minimal

### Étape 4 — Tests

```python
"""V5C-02 — Vérifie l'état des vues integrations post-décision."""
from __future__ import annotations
import unittest
from pathlib import Path


class V5CIntegrationsTests(unittest.TestCase):
    def test_decision_documented(self):
        decision = Path("audit/results/v5c-02-decision.md")
        self.assertTrue(decision.exists())
        content = decision.read_text(encoding="utf-8")
        self.assertIn("Option", content)

    def test_views_still_work(self):
        # Les 4 vues doivent toujours exister (qu'elles soient portées ou conservées)
        for v in ["jellyfin.js", "plex.js", "radarr.js", "logs.js"]:
            self.assertTrue(Path(f"web/dashboard/views/{v}").exists())

    def test_views_use_apiPost(self):
        # Pattern moderne (pas window.pywebview.api direct)
        for v in ["jellyfin.js", "plex.js", "radarr.js", "logs.js"]:
            content = Path(f"web/dashboard/views/{v}").read_text(encoding="utf-8")
            # apiPost utilisé OU pas d'API du tout
            if "api" in content.lower():
                self.assertNotIn("window.pywebview.api", content,
                               f"Pattern legacy détecté dans {v}")


if __name__ == "__main__":
    unittest.main()
```

### Étape 5 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_v5c_integrations -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 6 — Commits

#### Si Option A
- `feat(integrations-v5): port jellyfin/plex/radarr to v5 style`
- `feat(logs-v5): port logs view to v5 style`
- `docs(audit): document V5C-02 decision (port complet)`
- `test(v5c): integrations port verification`

#### Si Option B
- `docs(audit): V5C-02 decision (Jellyfin/Plex/Radarr/Logs restent v4 — conservation justifiée)`
- `test(v5c): minimal integration tests for v4-conservées views`

---

## LIVRABLES

- 4 vues integrations soit portées v5 soit conservées v4 (avec décision documentée)
- `audit/results/v5c-02-decision.md` avec rationale
- Test structurel
- 2-4 commits sur `feat/v5c-integrations-v5`

---

## 💡 Recommandation par défaut

**Option B** est recommandée par défaut sauf si l'audit révèle un vrai bénéfice à porter (cohérence visuelle critique, partage de composants v5, etc.). Les vues integrations sont simples (~150-200L), peu de bénéfice à les refondre.
