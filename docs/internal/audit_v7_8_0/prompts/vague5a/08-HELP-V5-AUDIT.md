# V5A-08 — Help v5 audit + port V3-13 si manquant

**Branche** : `feat/v5a-help-audit`
**Worktree** : `.claude/worktrees/feat-v5a-help-audit/`
**Effort** : 2-3h
**Mode** : 🟢 Parallélisable
**Fichiers concernés** :
- `web/views/help.js` (audit + enrichissement si nécessaire)
- `tests/test_help_v5_features.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/v5a-help-audit .claude/worktrees/feat-v5a-help-audit audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-v5a-help-audit

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT `web/views/help.js` + son test.

---

## CONTEXTE

V1-14 a créé une vue Aide complète (FAQ + glossaire) côté dashboard. V3-13 a ensuite ajouté une "section Support" avec 3 boutons (Ouvrir logs / Copier chemin / Signaler bug GitHub).

L'audit a noté que `web/views/help.js` (376L) existe (legacy webview) mais on ne sait pas si la section V3-13 y est. **À vérifier et porter si manquant.**

Aussi : V3-08 Kbd hints (raccourcis clavier visibles) et V3-08 section "Raccourcis clavier" enrichie dans la vue Aide. À vérifier que c'est bien dans le fichier.

---

## MISSION

### Étape 1 — Audit présence des features

Lis `web/views/help.js` (376L) et vérifie la présence de :

| Feature | Marqueur à chercher | Présent ? |
|---|---|---|
| V1-14 base | "FAQ", "glossaire", "Raccourcis clavier" | ? |
| V3-13 section Support | "help-support", "btnOpenLogs", "get_log_paths", "open_logs_folder" | ? |
| V3-13 bouton Signaler | "github.com/.../issues" | ? |
| V3-08 raccourcis enrichis | "shortcuts-table", `<kbd>`, "Alt+1" | ? |

### Étape 2 — Compléter ce qui manque

#### Si V3-13 section Support absente

Ajouter (référence : `web/dashboard/views/help.js` du même nom mais dans un autre dossier) :

```javascript
async function _renderSupportSection() {
  const { data } = await apiPost("get_log_paths");
  const paths = data || {};

  return `
    <section class="v5-help-support help-support">
      <h2>Support</h2>
      <p>Tu as un problème ? Voici comment nous aider à te dépanner :</p>
      <ol>
        <li>Reproduis le bug</li>
        <li>Ouvre le dossier des logs et joins le fichier <code>cinesort.log</code></li>
        <li>Décris ce que tu attendais et ce qui s'est passé</li>
      </ol>
      <div class="support-actions">
        <button class="v5-btn v5-btn--primary" id="btnOpenLogs" ${!paths.exists ? "disabled" : ""}>
          Ouvrir le dossier des logs
        </button>
        <button class="v5-btn" id="btnCopyLogPath">
          Copier le chemin
        </button>
        <a class="v5-btn" href="https://github.com/PLACEHOLDER/cinesort/issues" target="_blank" rel="noopener">
          Signaler un bug sur GitHub
        </a>
      </div>
      <p class="v5-text-muted help-support-hint" id="logPathDisplay">
        Chemin : <code>${escapeHtml(paths.log_dir || 'introuvable')}</code>
      </p>
    </section>
  `;
}

// Wire-up
document.addEventListener("click", async (ev) => {
  if (ev.target.id === "btnOpenLogs") {
    const res = await apiPost("open_logs_folder");
    if (!res.ok) {
      const hint = document.getElementById("logPathDisplay");
      if (hint) hint.textContent = "Erreur : " + (res.error || "fonction locale uniquement");
    }
  }
  if (ev.target.id === "btnCopyLogPath") {
    const { data } = await apiPost("get_log_paths");
    const path = data?.log_dir || "";
    try {
      await navigator.clipboard.writeText(path);
      ev.target.textContent = "Copié ✓";
      setTimeout(() => { ev.target.textContent = "Copier le chemin"; }, 2000);
    } catch {
      alert("Impossible de copier. Chemin : " + path);
    }
  }
});
```

#### Si V3-08 raccourcis manquent ou pauvres

S'assurer qu'il y a une section "Raccourcis clavier" complète avec ≥ 15 entrées dans 3 catégories (Navigation, Actions globales, Validation) — même structure que `web/dashboard/views/help.js`.

### Étape 3 — Tests structurels

Crée `tests/test_help_v5_features.py` :

```python
"""V5A-08 — Vérifie help.js v5 contient V1-14 + V3-13 + V3-08."""
from __future__ import annotations
import unittest
from pathlib import Path


class HelpV5FeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/help.js").read_text(encoding="utf-8")

    def test_v1_14_faq_glossaire(self):
        self.assertIn("FAQ", self.src)
        # Glossaire doit avoir ≥ 10 termes
        # On accepte plusieurs formats : "Glossaire", liste markdown, etc.
        self.assertTrue("glossaire" in self.src.lower() or "Glossaire" in self.src)

    def test_v3_13_support_section(self):
        self.assertIn("help-support", self.src)
        self.assertIn("btnOpenLogs", self.src)
        self.assertIn("btnCopyLogPath", self.src)

    def test_v3_13_endpoints(self):
        self.assertIn("get_log_paths", self.src)
        self.assertIn("open_logs_folder", self.src)

    def test_v3_08_shortcuts(self):
        self.assertIn("shortcuts-table", self.src)
        # Au moins 15 <kbd> tags pour 15+ raccourcis
        self.assertGreaterEqual(self.src.count("<kbd>"), 15)


if __name__ == "__main__":
    unittest.main()
```

### Étape 4 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_help_v5_features -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
node --check web/views/help.js 2>&1 | tail -2
```

### Étape 5 — Commits

Selon ce qui était présent ou pas :

- `feat(help-v5): port V3-13 Support section if missing` (si tu as ajouté la section)
- `feat(help-v5): enrich V3-08 keyboard shortcuts table if needed` (si tu as enrichi)
- `test(help-v5): structural tests for V5A-08`

OU si tout était déjà présent :

- `test(help-v5): structural tests confirm V1-14+V3-13+V3-08 already ported`

---

## LIVRABLES

- `help.js` v5 audité, complété si manquait V3-13 ou V3-08
- Test structurel
- Rapport dans le commit message si tout était déjà présent
- 1-3 commits sur `feat/v5a-help-audit`
