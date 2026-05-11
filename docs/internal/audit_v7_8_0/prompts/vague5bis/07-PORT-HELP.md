# V5bis-07 — Port `help.js` v5 (FAQ + glossaire + raccourcis + Support)

**Branche** : `feat/v5bis-port-help`
**Worktree** : `.claude/worktrees/feat-v5bis-port-help/`
**Effort** : 2-3h
**Mode** : 🟢 Parallélisable (après V5bis-00)
**Fichiers concernés** :
- `web/views/help.js` (port en place)
- `tests/test_help_v5_ported.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/v5bis-port-help .claude/worktrees/feat-v5bis-port-help audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-v5bis-port-help

test -f web/views/_v5_helpers.js && echo "✅" || echo "❌"
pwd && git branch --show-current && git status
```

---

## CONTEXTE

`help.js` (~470L après V5A — V1-14 FAQ + glossaire + V3-08 raccourcis enrichis + V3-13 Support section).

IIFE expose `window.HelpView.open()`. 2 sites API (`get_log_paths`, `open_logs_folder`).

---

## RÈGLES GLOBALES

Standard V5bis. Préserver toutes les sections (FAQ + glossaire + raccourcis + Support).

---

## MISSION

### Étape 1 — Lire + grep

- `web/views/help.js`

### Étape 2 — IIFE → ES module

```javascript
import { apiPost, escapeHtml, $, $$ } from "./_v5_helpers.js";

export async function initHelp(container, opts = {}) {
  // Charger les chemins de logs en parallèle (V3-13)
  const pathsRes = await apiPost("get_log_paths").catch(() => ({ data: {} }));
  const paths = pathsRes.data || {};

  container.innerHTML = `
    <div class="v5-help">
      ${_renderFaqSection()}
      ${_renderGlossarySection()}
      ${_renderShortcutsSection()}
      ${_renderSupportSection(paths)}
    </div>
  `;

  _bindEvents(container);
}

function _renderFaqSection() {
  // ... (préservé tel quel)
}

function _renderGlossarySection() {
  // ... (16 termes glossaire)
}

function _renderShortcutsSection() {
  // ... (3 catégories : Navigation, Actions globales, Validation)
}

function _renderSupportSection(paths) {
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

function _bindEvents(container) {
  document.getElementById("btnOpenLogs")?.addEventListener("click", async () => {
    const res = await apiPost("open_logs_folder");
    const hint = document.getElementById("logPathDisplay");
    if (!res.ok && hint) {
      hint.textContent = "Erreur : " + (res.error || "fonction locale uniquement");
    }
  });

  document.getElementById("btnCopyLogPath")?.addEventListener("click", async (e) => {
    const { data } = await apiPost("get_log_paths");
    const path = data?.log_dir || "";
    try {
      await navigator.clipboard.writeText(path);
      e.target.textContent = "Copié ✓";
      setTimeout(() => { e.target.textContent = "Copier le chemin"; }, 2000);
    } catch {
      alert("Impossible de copier. Chemin : " + path);
    }
  });
}
```

### Étape 3 — Tests

Crée `tests/test_help_v5_ported.py` :

```python
"""V5bis-07 — Vérifie help.js v5 porté."""
from __future__ import annotations
import unittest
from pathlib import Path


class HelpV5PortedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/help.js").read_text(encoding="utf-8")

    def test_es_module_export(self):
        self.assertIn("export async function initHelp", self.src)

    def test_no_iife(self):
        self.assertNotIn("window.HelpView", self.src)

    def test_no_pywebview_api(self):
        self.assertNotIn("window.pywebview.api", self.src)

    def test_helpers_imported(self):
        self.assertIn('from "./_v5_helpers.js"', self.src)

    def test_v1_14_faq_glossaire(self):
        self.assertIn("FAQ", self.src)
        # Glossaire avec ≥ 10 termes
        self.assertIn("glossaire", self.src.lower())

    def test_v3_08_shortcuts_enriched(self):
        self.assertIn("shortcuts-table", self.src)
        # ≥ 15 raccourcis (kbd tags)
        self.assertGreaterEqual(self.src.count("<kbd>"), 15)

    def test_v3_13_support_section(self):
        self.assertIn("help-support", self.src)
        self.assertIn("btnOpenLogs", self.src)
        self.assertIn("btnCopyLogPath", self.src)
        self.assertIn("get_log_paths", self.src)
        self.assertIn("open_logs_folder", self.src)


if __name__ == "__main__":
    unittest.main()
```

### Étape 4 — Vérif + Commits

```bash
.venv313/Scripts/python.exe -m unittest tests.test_help_v5_ported -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
node --check web/views/help.js 2>&1 | tail -2
```

- `refactor(help-v5): convert IIFE to ES module + REST apiPost (V5bis-07)`
- `test(help-v5): structural tests confirm port + V1-14/V3-08/V3-13`

---

## LIVRABLES

- `help.js` ES module exporting `initHelp(container, opts)`
- FAQ + glossaire + raccourcis + Support intégral préservés
- 0 IIFE, 0 pywebview.api
- 2 commits sur `feat/v5bis-port-help`
