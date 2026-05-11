# V3-12 — Hook updater au boot + UI Settings

**Branche** : `feat/updater-boot-hook-ui`
**Worktree** : `.claude/worktrees/feat-updater-boot-hook-ui/`
**Effort** : 4-6h
**Priorité** : 🟠 IMPORTANT (sans ça, V1-13 inutilisable)
**Fichiers concernés** :
- `app.py` (hook au boot)
- `cinesort/app/updater.py` (helper "is update available?" — V1-13 a créé ce module)
- `cinesort/ui/api/cinesort_api.py` (endpoints `check_for_updates`, `get_update_info`)
- `web/dashboard/views/settings-v5.js` (section Mises à jour)
- `web/dashboard/styles.css` (notification badge)
- `tests/test_updater_boot_hook.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/updater-boot-hook-ui .claude/worktrees/feat-updater-boot-hook-ui audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-updater-boot-hook-ui

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT le système updater (hook + UI). Pas de
modif d'autres systèmes.

---

## CONTEXTE

V1-13 a créé `cinesort/app/updater.py` qui sait checker GitHub Releases. Mais :
- **Pas de hook au boot** : le check ne se déclenche jamais automatiquement
- **Pas d'UI** : aucun moyen pour l'utilisateur de voir s'il y a une MAJ ou de checker
  manuellement

→ V1-13 est livré mais **inutilisable en l'état**. V3-12 finit le travail.

---

## MISSION

### Étape 1 — Lire les modules

- `cinesort/app/updater.py` (V1-13 — chercher les fonctions exportées)
- `app.py` (chercher la fonction `_startup` ou similaire pour le hook boot)
- `cinesort/ui/api/cinesort_api.py` (pattern endpoints)
- Vérifier les settings actuels liés à update (V1-13 a peut-être ajouté
  `auto_check_updates`, `update_check_interval_h`, etc.)

### Étape 2 — Hook au boot dans `app.py`

Dans la fonction de démarrage (ex. `_startup` ou `main`), après l'init du REST :

```python
# V3-12 — Check MAJ au boot (silencieux, en thread daemon)
import threading

def _check_updates_in_background():
    try:
        settings = load_settings()  # adapter au vrai pattern
        if not settings.get("auto_check_updates", True):
            return
        from cinesort.app.updater import check_for_update_async
        # Appel non bloquant, stocke le résultat dans un cache module-level
        check_for_update_async()
    except Exception as e:
        logger.warning("V3-12 : check MAJ au boot a échoué : %s", e)

threading.Thread(target=_check_updates_in_background, daemon=True).start()
```

⚠ Adapter les noms `load_settings`, `check_for_update_async` à ce qui existe vraiment
dans le code après V1-13. Si V1-13 a livré un autre pattern (ex. cache JSON sur disque
au lieu de module-level), réutilise ce pattern.

### Étape 3 — Endpoints API

Dans `cinesort_api.py` :

```python
def check_for_updates(self) -> dict:
    """V3-12 — Force un check MAJ immédiat (manuel)."""
    from cinesort.app.updater import fetch_latest_release_now
    return {"data": fetch_latest_release_now()}

def get_update_info(self) -> dict:
    """V3-12 — Retourne le dernier check (cache si récent < 1h, sinon stale)."""
    from cinesort.app.updater import get_cached_update_info
    return {"data": get_cached_update_info()}
```

⚠ Adapter aux fonctions réelles de `updater.py` (V1-13). Si pas adaptées au pattern
sync/async/cache → faire les ajustements minimum nécessaires dans `updater.py`.

### Étape 4 — UI section Mises à jour dans Paramètres

Dans `web/dashboard/views/settings-v5.js`, ajouter (dans la section Système ou crée un
nouveau groupe "Mises à jour") :

```javascript
function _renderUpdateSection() {
  return `
    <section class="updates-section">
      <h2>Mises à jour</h2>
      <div id="updateStatusContent">
        <p class="text-muted">Chargement...</p>
      </div>
      <button class="btn" id="btnCheckUpdates">Vérifier maintenant</button>

      <label class="switch-label" style="margin-top: 1rem">
        <input type="checkbox" id="ckAutoCheckUpdates" />
        <span>Vérifier automatiquement au démarrage</span>
      </label>
    </section>
  `;
}

async function _loadUpdateStatus() {
  const res = await apiPost("get_update_info");
  const info = res.data || {};
  const el = document.getElementById("updateStatusContent");
  if (!el) return;

  const current = info.current_version || "?";
  const latest = info.latest_version;
  const updateAvailable = info.update_available;

  if (updateAvailable && latest) {
    el.innerHTML = `
      <div class="update-card update-card--available">
        <p>🎉 <strong>Nouvelle version disponible</strong> : ${escapeHtml(latest)}</p>
        <p>Tu utilises la v${escapeHtml(current)}.</p>
        <a class="btn btn--primary" href="${escapeHtml(info.release_url || '')}" target="_blank" rel="noopener">
          Télécharger sur GitHub
        </a>
        <p class="text-muted" style="margin-top: 1rem">${escapeHtml(info.release_notes_short || '')}</p>
      </div>
    `;
  } else if (latest) {
    el.innerHTML = `<p>✅ Tu es à jour (v${escapeHtml(current)}).</p>`;
  } else {
    el.innerHTML = `<p class="text-muted">Pas d'info disponible. Clique sur "Vérifier maintenant".</p>`;
  }
}

// Au boot vue settings
_loadUpdateStatus();

document.getElementById("btnCheckUpdates")?.addEventListener("click", async (e) => {
  e.target.disabled = true;
  e.target.textContent = "Vérification...";
  await apiPost("check_for_updates");
  await _loadUpdateStatus();
  e.target.disabled = false;
  e.target.textContent = "Vérifier maintenant";
});

document.getElementById("ckAutoCheckUpdates")?.addEventListener("change", async (e) => {
  await apiPost("save_settings", { ...currentSettings, auto_check_updates: e.target.checked });
});
```

### Étape 5 — Badge "MAJ dispo" dans la sidebar

Dans `web/dashboard/app.js`, après chargement initial des settings, vérifier les MAJ
et ajouter un badge sur l'item Paramètres si une MAJ est dispo :

```javascript
async function _checkUpdateBadge() {
  try {
    const { data } = await apiPost("get_update_info");
    if (data && data.update_available) {
      const settingsBtn = document.querySelector("[data-route='/settings']");
      if (settingsBtn && !settingsBtn.querySelector(".update-badge")) {
        const badge = document.createElement("span");
        badge.className = "update-badge";
        badge.title = `Nouvelle version : ${data.latest_version}`;
        badge.textContent = "•";
        settingsBtn.appendChild(badge);
      }
    }
  } catch { /* silencieux */ }
}

// Boot + recheck toutes les heures
_checkUpdateBadge();
setInterval(_checkUpdateBadge, 3600000);
```

### Étape 6 — CSS

```css
/* V3-12 — Update UI */
.update-card {
  background: var(--surface-elevated);
  border-radius: var(--radius-md);
  padding: 1rem 1.25rem;
  margin-bottom: 1rem;
}
.update-card--available {
  border-left: 4px solid var(--accent-success);
  background: rgba(16, 185, 129, 0.05);
}
.update-badge {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent-success);
  margin-left: 0.5rem;
  vertical-align: super;
  font-size: 1.25rem;
  line-height: 1;
}
```

### Étape 7 — Tests

Crée `tests/test_updater_boot_hook.py` :

```python
"""V3-12 — Hook updater au boot + UI."""
from __future__ import annotations
import unittest
from pathlib import Path


class UpdaterBootHookTests(unittest.TestCase):
    def test_app_py_has_boot_hook(self):
        app = Path("app.py").read_text(encoding="utf-8")
        # Au moins une référence au système updater au boot
        self.assertIn("updater", app.lower())
        self.assertIn("auto_check_updates", app)

    def test_updater_module_exposes_required_functions(self):
        from cinesort.app import updater
        # Au moins une de ces fonctions doit exister
        # (les noms peuvent varier selon impl V1-13)
        funcs = dir(updater)
        has_check = any(name in funcs for name in (
            "check_for_update_async", "fetch_latest_release_now",
            "check_for_update", "fetch_latest_release"
        ))
        self.assertTrue(has_check, f"Aucune fonction de check trouvée dans updater. Disponibles: {[f for f in funcs if not f.startswith('_')]}")

    def test_settings_view_has_update_section(self):
        js = Path("web/dashboard/views/settings-v5.js").read_text(encoding="utf-8")
        self.assertIn("Mises à jour", js)
        self.assertIn("btnCheckUpdates", js)
        self.assertIn("ckAutoCheckUpdates", js)

    def test_app_js_has_update_badge_logic(self):
        app = Path("web/dashboard/app.js").read_text(encoding="utf-8")
        self.assertIn("_checkUpdateBadge", app)
        self.assertIn("get_update_info", app)

    def test_css_update_styles(self):
        css = Path("web/dashboard/styles.css").read_text(encoding="utf-8")
        self.assertIn(".update-card", css)
        self.assertIn(".update-badge", css)


if __name__ == "__main__":
    unittest.main()
```

### Étape 8 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_updater_boot_hook -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 9 — Commits

- `feat(app): boot hook for background update check (V3-12)`
- `feat(api): check_for_updates + get_update_info endpoints`
- `feat(dashboard): updates section in settings + badge on sidebar`
- `test(updater): boot hook + UI structural tests`

---

## LIVRABLES

Récap :
- Hook silencieux au boot (thread daemon, non bloquant) qui check GitHub Releases
- Endpoint `check_for_updates` (force) + `get_update_info` (cache)
- Section Paramètres "Mises à jour" avec bouton + toggle auto-check
- Badge `•` vert sur l'item Paramètres si MAJ dispo
- 0 régression
- 4 commits sur `feat/updater-boot-hook-ui`
