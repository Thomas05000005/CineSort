# V3-13 — Vue Aide : bouton "Ouvrir les logs"

**Branche** : `feat/help-open-logs-button`
**Worktree** : `.claude/worktrees/feat-help-open-logs-button/`
**Effort** : 1-2h
**Priorité** : 🟢 IMPORTANT (support utilisateur — réduire friction "envoie-moi tes logs")
**Fichiers concernés** :
- `cinesort/ui/api/cinesort_api.py` (endpoints `open_logs_folder`, `get_log_paths`)
- `web/dashboard/views/help.js` (vue Aide enrichie)
- `web/dashboard/styles.css` (style boutons)
- `tests/test_help_logs_button.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/help-open-logs-button .claude/worktrees/feat-help-open-logs-button audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-help-open-logs-button

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT la vue Aide + un endpoint d'ouverture
de dossier logs. Pas de modif d'autres vues.

---

## CONTEXTE

Quand un utilisateur a un bug et contacte le support (issue GitHub, email), on lui
demande "envoie-moi tes logs". Aujourd'hui il doit :
1. Trouver `%LOCALAPPDATA%\CineSort\logs\` (impossible pour un débutant)
2. Comprendre quel fichier envoyer

**Solution** : bouton "Ouvrir le dossier des logs" + "Copier le chemin" dans la vue Aide.

---

## MISSION

### Étape 1 — Lire les modules

- `cinesort/ui/api/cinesort_api.py` (chercher si une méthode `open_path` existe déjà
  — V1-09 ou autre vague l'a peut-être créée)
- `cinesort/infra/log_scrubber.py` ou autre (chercher où sont configurés les paths logs)
- `web/dashboard/views/help.js` (V1-14 — chercher la structure)

### Étape 2 — Backend endpoints

Dans `cinesort_api.py` (ou dans un nouveau module si tu préfères, ex. `support_support.py`) :

```python
def get_log_paths(self) -> dict:
    """V3-13 — Retourne les chemins des fichiers logs (pour affichage UI + copie)."""
    import os
    log_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "CineSort", "logs")
    paths = {
        "log_dir": log_dir,
        "main_log": os.path.join(log_dir, "cinesort.log"),
        "exists": os.path.isdir(log_dir),
    }
    return {"data": paths}

def open_logs_folder(self) -> dict:
    """V3-13 — Ouvre le dossier des logs dans l'explorateur Windows."""
    import os
    import subprocess
    log_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "CineSort", "logs")
    if not os.path.isdir(log_dir):
        return {"ok": False, "error": "Dossier logs introuvable"}
    try:
        # Windows : explorer /select ou juste explorer <path>
        subprocess.Popen(["explorer", log_dir], shell=False)
        return {"ok": True, "opened": log_dir}
    except Exception as e:
        return {"ok": False, "error": str(e)}
```

⚠ **Important sécurité** : la méthode `open_logs_folder` ne doit PAS être exposée
via l'API REST distante (risque RCE). Vérifier dans `rest_server.py` qu'elle est dans
`_EXCLUDED_METHODS` (V4 audit a ajouté `open_path` dans cette liste — fais pareil pour
`open_logs_folder`).

### Étape 3 — Vue Aide enrichie

Dans `web/dashboard/views/help.js`, ajouter une section "Support" en bas :

```javascript
async function _renderSupportSection() {
  const { data } = await apiPost("get_log_paths");
  const paths = data || {};

  return `
    <section class="help-support">
      <h2>Support</h2>
      <p>Tu as un problème ? Voici comment nous aider à te dépanner :</p>
      <ol>
        <li>Reproduis le bug (refais la même action qui a posé problème)</li>
        <li>Ouvre le dossier des logs et joins le fichier <code>cinesort.log</code></li>
        <li>Décris ce que tu attendais et ce qui s'est passé</li>
      </ol>

      <div class="support-actions">
        <button class="btn btn--primary" id="btnOpenLogs" ${!paths.exists ? "disabled" : ""}>
          Ouvrir le dossier des logs
        </button>
        <button class="btn" id="btnCopyLogPath">
          Copier le chemin
        </button>
        <a class="btn" href="https://github.com/anthropics/claude-code/issues" target="_blank" rel="noopener">
          Signaler un bug sur GitHub
        </a>
      </div>

      <p class="text-muted" id="logPathDisplay">Chemin : <code>${escapeHtml(paths.log_dir || 'introuvable')}</code></p>
    </section>
  `;
}

// Wire-up
document.addEventListener("click", async (ev) => {
  if (ev.target.id === "btnOpenLogs") {
    const res = await apiPost("open_logs_folder");
    if (!res.ok) alert("Erreur : " + (res.error || "inconnue"));
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

⚠ Adapter le lien GitHub avec ton vrai repo (à ajuster manuellement après merge).

### Étape 4 — CSS

```css
/* V3-13 — Section support dans aide */
.help-support {
  margin-top: 2rem;
  padding: 1.5rem;
  background: var(--surface-elevated);
  border-radius: var(--radius-md);
  border-left: 3px solid var(--accent);
}
.support-actions {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin: 1rem 0;
}
#logPathDisplay code {
  background: var(--bg-elevated);
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 0.85rem;
}
```

### Étape 5 — Tests

```python
"""V3-13 — Bouton ouvrir logs dans vue Aide."""
from __future__ import annotations
import unittest
from pathlib import Path
import sys; sys.path.insert(0, '.')


class HelpLogsButtonTests(unittest.TestCase):
    def test_get_log_paths_endpoint(self):
        # Vérifie que la méthode existe dans CineSortApi
        from cinesort.ui.api.cinesort_api import CineSortApi
        self.assertTrue(hasattr(CineSortApi, "get_log_paths"))
        self.assertTrue(hasattr(CineSortApi, "open_logs_folder"))

    def test_open_logs_excluded_from_rest(self):
        """Sécurité : open_logs_folder ne doit pas être exposé via REST distant."""
        from cinesort.infra.rest_server import _EXCLUDED_METHODS
        self.assertIn("open_logs_folder", _EXCLUDED_METHODS)

    def test_help_view_has_support_section(self):
        js = Path("web/dashboard/views/help.js").read_text(encoding="utf-8")
        self.assertIn("help-support", js)
        self.assertIn("btnOpenLogs", js)
        self.assertIn("btnCopyLogPath", js)
        self.assertIn("get_log_paths", js)
        self.assertIn("open_logs_folder", js)

    def test_css_support_styles(self):
        css = Path("web/dashboard/styles.css").read_text(encoding="utf-8")
        self.assertIn(".help-support", css)
        self.assertIn(".support-actions", css)


if __name__ == "__main__":
    unittest.main()
```

### Étape 6 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_help_logs_button -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 7 — Commits

- `feat(api): get_log_paths + open_logs_folder endpoints (V3-13)`
- `feat(dashboard): support section in help view with logs button`
- `test(help): logs button structural + REST security exclusion`

---

## LIVRABLES

Récap :
- Endpoint `get_log_paths` (info pure)
- Endpoint `open_logs_folder` (action locale, exclu du REST distant pour sécurité)
- Vue Aide enrichie avec section "Support" : 3 boutons (ouvrir, copier chemin, GitHub)
- 0 régression
- 3 commits sur `feat/help-open-logs-button`
