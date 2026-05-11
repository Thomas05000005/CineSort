# V5A-03 — Settings-v5 enrichi (V3-02 mode expert + V3-03 glossaire)

**Branche** : `feat/v5a-settings-port`
**Worktree** : `.claude/worktrees/feat-v5a-settings-port/`
**Effort** : 4-6h
**Mode** : 🟢 Parallélisable
**Fichiers concernés** :
- `web/views/settings-v5.js` (enrichissement)
- `tests/test_settings_v5_features.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/v5a-settings-port .claude/worktrees/feat-v5a-settings-port audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-v5a-settings-port

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT `web/views/settings-v5.js` + son test.

RÈGLE V5 : préserver le schema déclaratif `SETTINGS_GROUPS` (9 groupes par intention), auto-save 500ms, search fuzzy, badges configuré/partial, live preview.

---

## CONTEXTE

`settings-v5.js` (855L) a déjà 9 groupes par intention + auto-save + search fuzzy + Danger Zone (V3-09 porté) + section Mises à jour (V3-12 porté). Il manque :

1. **V3-02** : toggle "Mode expert" qui masque les fields marqués `advanced: true`
2. **V3-03** : tooltips ⓘ glossaire métier sur termes techniques (TMDb, LPIPS, Roots, etc.)

---

## MISSION

### Étape 1 — Lire l'existant

- `web/views/settings-v5.js` (855L — le fichier à enrichir)
- `web/dashboard/views/settings.js` lignes 36-42, 470-478 (référence V3-02 v4)
- `web/dashboard/components/glossary-tooltip.js` (composant V3-03 réutilisable)

### Étape 2 — Mode expert (V3-02)

#### a) Marquer les fields `advanced: true` dans SETTINGS_GROUPS

Identifie dans le schema les fields à marquer "advanced" (cohérent avec ce qui est `data-advanced="true"` dans la v4 dashboard) :

- Tous les `perceptual_*` sauf le toggle global et auto_on_scan
- `plugins_*` sauf enabled
- Tous les `*_timeout_s`
- `rest_api_https_*`, `rest_api_cors_origin`
- `effect_speed`, `glow_intensity`, `light_intensity`
- `email_*` sauf enabled + to
- `watch_*` sauf enabled

Ajoute le flag `advanced: true` à chaque field concerné dans le schema.

#### b) Toggle UI en haut du conteneur

Ajoute dans `_renderShell` ou équivalent (avant les groupes) :

```javascript
const expertChecked = _state.settings.expert_mode ? "checked" : "";
return `
  <div class="v5-settings-expert-toggle" data-v5-expert-toggle>
    <label class="v5-toggle-label">
      <input type="checkbox" id="v5CkExpertMode" ${expertChecked} />
      <span><strong>Mode expert</strong> — afficher tous les paramètres avancés</span>
    </label>
    <p class="v5-text-muted">Désactivé par défaut. Active pour tweaker timeouts, ports, retries, HTTPS, etc.</p>
  </div>
  ${shellExistant}
`;
```

#### c) Logique masquage

Ajoute :

```javascript
function _applyExpertMode(isExpert) {
  document.body.classList.toggle("v5-expert-mode-on", isExpert);
  document.body.classList.toggle("v5-expert-mode-off", !isExpert);
  document.querySelectorAll(".v5-settings-field[data-advanced='true']").forEach((el) => {
    el.style.display = isExpert ? "" : "none";
  });
}

// Au boot, après load des settings :
_applyExpertMode(!!_state.settings.expert_mode);

// Listener sur le toggle :
document.getElementById("v5CkExpertMode")?.addEventListener("change", async (e) => {
  const checked = !!e.target.checked;
  _applyExpertMode(checked);
  _state.settings.expert_mode = checked;
  // Auto-save (le mécanisme existant doit s'occuper de la persistence)
  _scheduleSave();
});
```

#### d) Render fields avec data-advanced

Dans le rendu de chaque field, ajouter conditionnellement `data-advanced="true"` :

```javascript
const dataAdvanced = field.advanced ? ' data-advanced="true"' : '';
return `<div class="v5-settings-field"${dataAdvanced} data-field-key="${escapeHtml(field.key)}">...`;
```

### Étape 3 — Glossaire ⓘ (V3-03)

#### a) Importer le composant

En haut de `settings-v5.js`, ajouter :

```javascript
import { glossaryTooltip } from "../dashboard/components/glossary-tooltip.js";
```

⚠ Si le chemin pose problème (ce fichier est dans `web/views/`, pas `web/dashboard/views/`), copier la fonction `glossaryTooltip` ou créer un alias dans `web/components/` (vérifier si un équivalent legacy existe).

Solution simple : créer un module léger `web/components/glossary-tooltip-shim.js` qui ré-exporte depuis dashboard, OU copier la fonction (la dépendance est minime).

#### b) Décorer les labels métier

Pour les fields suivants, wrapper le label avec `glossaryTooltip()` :

| Field | Label affiché | Terme glossaire |
|---|---|---|
| roots | "Dossiers racine" | "Roots" |
| tmdb_api_key | "Clé API TMDb" | "TMDb" |
| naming_movie_template | "Template film" | (NFO si présent dans le hint) |
| jellyfin_api_key | "Clé API Jellyfin" | (Jellyfin doc) |
| perceptual_enabled | "Analyse perceptuelle" | "Score perceptuel" |
| perceptual_lpips_enabled | "LPIPS activé" | "LPIPS" |
| perceptual_audio_fingerprint_enabled | "Empreinte audio" | "Chromaprint" |

Format dans le rendu :
```javascript
const labelHtml = field.glossaryTerm
  ? glossaryTooltip(field.glossaryTerm, field.label)
  : escapeHtml(field.label);
```

Ajoute `glossaryTerm: "..."` dans le schema des fields concernés.

### Étape 4 — Vérifier V3-09 + V3-12 déjà présents

Lis vite `settings-v5.js` lignes 200-220 (section "update-status") et lignes 600-664 (Danger Zone) pour confirmer que les portages de V3-09 et V3-12 sont bien là (faits lors de la session 2 mai). Si OK, ne rien toucher. Si manquant, signaler dans le commit message.

### Étape 5 — Tests structurels

Crée `tests/test_settings_v5_features.py` :

```python
"""V5A-03 — Vérifie settings-v5 enrichi avec V3-02 expert + V3-03 glossaire."""
from __future__ import annotations
import unittest
from pathlib import Path


class SettingsV5FeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/settings-v5.js").read_text(encoding="utf-8")

    def test_v3_02_expert_mode_toggle(self):
        self.assertIn("v5CkExpertMode", self.src)
        self.assertIn("expert_mode", self.src)
        self.assertIn("_applyExpertMode", self.src)

    def test_v3_02_advanced_fields_marker(self):
        # Au moins quelques fields doivent être marqués advanced: true
        self.assertGreaterEqual(self.src.count("advanced: true"), 5)

    def test_v3_02_data_advanced_render(self):
        self.assertIn('data-advanced="true"', self.src)

    def test_v3_03_glossary_imported(self):
        self.assertIn("glossaryTooltip", self.src)
        # Au moins 3 fields doivent avoir un glossaryTerm
        self.assertGreaterEqual(self.src.count("glossaryTerm:"), 3)

    def test_v3_09_danger_zone_present(self):
        self.assertIn("danger-zone", self.src)
        self.assertIn("reset_all_user_data", self.src)

    def test_v3_12_updates_section_present(self):
        self.assertIn("updates-section", self.src)
        self.assertIn("update_github_repo", self.src)


if __name__ == "__main__":
    unittest.main()
```

### Étape 6 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_settings_v5_features -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
node --check web/views/settings-v5.js 2>&1 | tail -2
```

### Étape 7 — Commits

- `feat(settings-v5): port V3-02 expert mode toggle + advanced flag`
- `feat(settings-v5): port V3-03 glossary tooltips on key fields`
- `test(settings-v5): structural tests for V5A-03`

---

## LIVRABLES

- `settings-v5.js` enrichi avec V3-02 (toggle + masquage data-advanced) et V3-03 (glossary sur fields métier)
- V3-09 + V3-12 confirmés présents (vérifiés)
- Test structurel
- Schema déclaratif préservé (style v5)
- 3 commits sur `feat/v5a-settings-port`
