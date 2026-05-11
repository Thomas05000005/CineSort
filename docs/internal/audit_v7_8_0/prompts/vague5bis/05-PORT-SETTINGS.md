# V5bis-05 — Port `settings-v5.js` (schema déclaratif 9 groupes, le plus lourd)

**Branche** : `feat/v5bis-port-settings`
**Worktree** : `.claude/worktrees/feat-v5bis-port-settings/`
**Effort** : 6-8h
**Mode** : 🟢 Parallélisable (après V5bis-00)
**Fichiers concernés** :
- `web/views/settings-v5.js` (port en place)
- `tests/test_settings_v5_ported.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/v5bis-port-settings .claude/worktrees/feat-v5bis-port-settings audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-v5bis-port-settings

test -f web/views/_v5_helpers.js && echo "✅" || echo "❌"
pwd && git branch --show-current && git status
```

---

## CONTEXTE

`settings-v5.js` (~995L après V5A) est le settings v5 avec :
- Schema déclaratif `SETTINGS_GROUPS` (9 groupes par intention)
- 7 field types
- Auto-save debounce 500ms
- Search fuzzy
- Badges configuré/partial
- Live preview (themes, density)
- V3-09 Danger Zone (Reset all data)
- V3-12 Section Mises à jour
- V3-02 Mode expert
- V3-03 Glossaire tooltips

IIFE expose `window.SettingsV5.mount(...)`. 9 sites d'appels API.

---

## RÈGLES GLOBALES

Standard V5bis. **Préserver impérativement** :
- Schema déclaratif `SETTINGS_GROUPS` intégral (9 groupes)
- Auto-save 500ms debounce
- Search fuzzy
- V3-02 expert mode + filtrage advanced
- V3-03 glossary tooltips
- V3-09 Danger Zone
- V3-12 Section Mises à jour

---

## MISSION

### Étape 1 — Lire + analyser

- `web/views/settings-v5.js` (~995L)
- Identifier le schema `SETTINGS_GROUPS`
- Identifier les 7 field types
- Identifier l'auto-save logic

### Étape 2 — IIFE → ES module

```javascript
import { apiPost, escapeHtml, $, $$, renderSkeleton, renderError } from "./_v5_helpers.js";
import { glossaryTooltip } from "../dashboard/components/glossary-tooltip.js";

const SETTINGS_GROUPS = [
  // ... (préserver le schema entier intact)
];

let _state = {
  settings: {},
  searchQuery: "",
  activeCategory: null,
};
let _saveTimer = null;

export async function initSettings(container, opts = {}) {
  await _loadSettings();
  _renderShell(container);
  _bindEvents(container);
}

async function _loadSettings() {
  const res = await apiPost("get_settings");
  _state.settings = res.data || {};
  _applyExpertMode(!!_state.settings.expert_mode);
}

function _scheduleSave() {
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(async () => {
    await apiPost("save_settings", { settings: _state.settings });
  }, 500);
}

// ... (toute la logique préservée — schema, render fields, validate, etc.)
```

### Étape 3 — Migrer 9 appels API

Méthodes : `get_settings`, `save_settings`, `test_tmdb_key`, `test_jellyfin_connection`, `test_plex_connection`, `test_radarr_connection`, `test_email_report`, `preview_naming_template`, `get_naming_presets`, `check_for_updates`, `get_update_info`, `reset_all_user_data`, `get_user_data_size`, etc.

⚠ Attention : settings-v5 a beaucoup d'appels (parfois positionnels). Vérifier chaque signature backend.

### Étape 4 — Cas particuliers V3-09 + V3-12

V3-09 (Reset Data) :
```javascript
async function _openResetDialog() {
  // ... même logique
  const res = await apiPost("reset_all_user_data", { confirmation: "RESET" });
  // ...
}
```

V3-12 (Updates) :
```javascript
async function _checkForUpdates() {
  await apiPost("check_for_updates");
  await _loadUpdateStatus();
}

async function _loadUpdateStatus() {
  const res = await apiPost("get_update_info");
  // ... render status
}
```

### Étape 5 — Tests

Crée `tests/test_settings_v5_ported.py` :

```python
"""V5bis-05 — Vérifie settings-v5.js porté."""
from __future__ import annotations
import unittest
from pathlib import Path


class SettingsV5PortedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/settings-v5.js").read_text(encoding="utf-8")

    def test_es_module_export(self):
        self.assertIn("export async function initSettings", self.src)

    def test_no_iife(self):
        self.assertNotIn("window.SettingsV5", self.src)

    def test_no_pywebview_api(self):
        self.assertNotIn("window.pywebview.api", self.src)

    def test_helpers_imported(self):
        self.assertIn('from "./_v5_helpers.js"', self.src)

    def test_settings_groups_preserved(self):
        self.assertIn("SETTINGS_GROUPS", self.src)
        # 9 groupes (count "id:" approximatif dans le schema)
        # Plus précis : compter "label:" qui apparaît à chaque field/group
        self.assertGreaterEqual(self.src.count('id: "'), 9)

    def test_autosave_500ms(self):
        self.assertIn("_scheduleSave", self.src)
        self.assertIn("500", self.src)

    def test_v3_02_expert_mode(self):
        self.assertIn("expert_mode", self.src)
        self.assertIn("_applyExpertMode", self.src)
        self.assertIn("data-advanced", self.src)

    def test_v3_03_glossary(self):
        self.assertIn("glossaryTooltip", self.src)

    def test_v3_09_danger_zone(self):
        self.assertIn("danger-zone", self.src)
        self.assertIn("reset_all_user_data", self.src)

    def test_v3_12_updates(self):
        self.assertIn("updates-section", self.src)
        self.assertIn("update_github_repo", self.src)


if __name__ == "__main__":
    unittest.main()
```

### Étape 6 — Vérif + Commits

```bash
.venv313/Scripts/python.exe -m unittest tests.test_settings_v5_ported -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
node --check web/views/settings-v5.js 2>&1 | tail -2
```

- `refactor(settings-v5): convert IIFE to ES module + REST apiPost (V5bis-05)`
- `refactor(settings-v5): migrate 9+ window.pywebview.api calls → apiPost`
- `refactor(settings-v5): preserve schema + autosave + V3-02/03/09/12`
- `test(settings-v5): structural tests confirm port + features V5A`

---

## LIVRABLES

- `settings-v5.js` ES module exporting `initSettings(container, opts)`
- Schema 9 groupes intact
- Auto-save 500ms intact
- V3-02 + V3-03 + V3-09 + V3-12 préservés
- 0 IIFE, 0 pywebview.api
- 4 commits sur `feat/v5bis-port-settings`
