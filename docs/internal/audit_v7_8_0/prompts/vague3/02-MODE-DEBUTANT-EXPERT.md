# V3-02 — Mode débutant `expert_mode`

**Branche** : `feat/expert-mode-toggle`
**Worktree** : `.claude/worktrees/feat-expert-mode-toggle/`
**Effort** : 1 jour
**Priorité** : 🟠 IMPORTANT (UX onboarding — 2000 users débutants en attente)
**Fichiers concernés** :
- `cinesort/ui/api/settings_support.py` (ajout setting `expert_mode`)
- `web/dashboard/views/settings-v5.js` (toggle UI)
- `web/dashboard/views/settings-v5.js` (filtrage groupes settings selon expert_mode)
- `web/dashboard/styles.css` (visuel mode débutant)
- `tests/test_expert_mode.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/expert-mode-toggle .claude/worktrees/feat-expert-mode-toggle audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-expert-mode-toggle

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT le système expert_mode (toggle setting +
filtrage UI). Tu ne modifies PAS la logique métier ni d'autres vues.

---

## CONTEXTE

Le menu Paramètres a 9 groupes avec ~50+ settings. Pour un débutant qui installe
CineSort pour la première fois, c'est intimidant. La majorité des settings sont des
options avancées (timeouts, rate limits, paths, etc.) qu'un débutant n'a aucune raison
de toucher.

**Solution** : toggle global `expert_mode` (par défaut OFF = mode débutant). En mode
débutant, on cache les settings marqués `advanced: true` dans le schéma. En mode expert,
on affiche tout.

---

## MISSION

### Étape 1 — Lire les modules

- `cinesort/ui/api/settings_support.py` (chercher la liste des defaults + validation)
- `web/dashboard/views/settings-v5.js` (chercher `SETTINGS_GROUPS` ou similaire)

### Étape 2 — Backend setting `expert_mode`

Dans `settings_support.py`, ajouter dans les defaults :

```python
# V3-02 — Mode expert (affiche tous les settings avancés)
"expert_mode": False,
```

Et dans la normalisation (chercher la fonction `_normalize_settings` ou équivalente),
ajouter :

```python
out["expert_mode"] = bool(raw.get("expert_mode", False))
```

### Étape 3 — Marquer les settings avancés

Dans `web/dashboard/views/settings-v5.js`, chercher `SETTINGS_GROUPS` (le schéma
déclaratif). Pour chaque champ, ajouter un flag `advanced: true` si c'est avancé.

**Critères "avancé"** :
- Tout ce qui touche timeouts, ports, retries, batch_size, rate limits
- Settings probe (ffmpeg path, mediainfo path)
- Settings perceptuels avancés (frame_count, downscale, etc.)
- Settings réseau (HTTPS, certs)
- Settings plugins
- Settings email SMTP
- Settings watcher avancés

**Critères "basique" (toujours visibles)** :
- Roots (dossiers à scanner)
- TMDb API key
- Naming preset
- Theme + animations
- Notifications on/off
- Auto-approve threshold
- Toggle activer Jellyfin/Plex/Radarr (les URL/clés sont avancés)
- Expert mode toggle (le toggle lui-même)

### Étape 4 — Filtrage rendu

Dans la fonction render des settings (chercher `renderField` / `renderGroup`), ajouter
au début :

```javascript
// V3-02 — Filtrage selon expert_mode
const isExpert = !!currentSettings.expert_mode;
if (field.advanced && !isExpert) return ""; // skip rendering
```

Pour les groupes : si TOUS les champs sont avancés et qu'on n'est pas expert, masquer
le groupe entier.

### Étape 5 — Toggle "Mode expert" en haut des settings

Ajouter en tête de la vue settings (avant les groupes) :

```javascript
function _renderExpertToggle(settings) {
  const checked = settings.expert_mode ? "checked" : "";
  return `
    <div class="expert-toggle-card">
      <label class="switch-label">
        <input type="checkbox" id="ckExpertMode" ${checked} />
        <span><strong>Mode expert</strong> — afficher tous les paramètres avancés</span>
      </label>
      <p class="text-muted">Désactivé par défaut. Active si tu veux tweaker timeouts, ports, retries, etc.</p>
    </div>
  `;
}
```

Le handler change l'état et re-render :

```javascript
document.getElementById("ckExpertMode")?.addEventListener("change", async (e) => {
  await apiPost("save_settings", { ...currentSettings, expert_mode: e.target.checked });
  // Re-render
  initSettings();
});
```

### Étape 6 — Indicateur visuel mode débutant actif

Dans `web/dashboard/styles.css` :

```css
/* V3-02 — Carte toggle expert mode */
.expert-toggle-card {
  background: var(--surface-elevated);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-md);
  padding: 1rem 1.25rem;
  margin-bottom: 1.5rem;
}
.expert-toggle-card .text-muted {
  margin: 0.5rem 0 0 0;
  font-size: 0.875rem;
}
```

### Étape 7 — Tests

Crée `tests/test_expert_mode.py` :

```python
"""V3-02 — Vérifie le système expert_mode."""
from __future__ import annotations
import unittest
from pathlib import Path
import sys; sys.path.insert(0, '.')


class ExpertModeBackendTests(unittest.TestCase):
    def test_expert_mode_default_false(self):
        from cinesort.ui.api.settings_support import _build_default_settings  # adapter au nom réel
        defaults = _build_default_settings()
        self.assertIn("expert_mode", defaults)
        self.assertFalse(defaults["expert_mode"])

    def test_expert_mode_normalized(self):
        from cinesort.ui.api.settings_support import _normalize_settings  # adapter
        out = _normalize_settings({"expert_mode": "true"})  # string -> bool
        self.assertIsInstance(out["expert_mode"], bool)


class ExpertModeFrontendTests(unittest.TestCase):
    def setUp(self):
        self.js = Path("web/dashboard/views/settings-v5.js").read_text(encoding="utf-8")

    def test_advanced_flag_used(self):
        self.assertIn("advanced", self.js)

    def test_expert_toggle_present(self):
        self.assertIn("ckExpertMode", self.js)
        self.assertIn("expert_mode", self.js)


if __name__ == "__main__":
    unittest.main()
```

⚠ Adapter `_build_default_settings` / `_normalize_settings` aux vrais noms dans
`settings_support.py`. Lire d'abord pour confirmer.

### Étape 8 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_expert_mode -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 9 — Commits

- `feat(settings): add expert_mode toggle to hide advanced settings (V3-02)`
- `feat(dashboard): filter advanced settings when not in expert mode`
- `test(settings): expert_mode default + filtering`

---

## LIVRABLES

Récap :
- Setting `expert_mode` (default `False`) backend + normalisation
- Toggle visible en haut des Paramètres
- ~60-70% des settings cachés en mode débutant
- 0 régression
- 3 commits sur `feat/expert-mode-toggle`
