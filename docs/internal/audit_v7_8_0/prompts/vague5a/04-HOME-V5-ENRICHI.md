# V5A-04 — Home v5 enrichi (5 features V1-V4)

**Branche** : `feat/v5a-home-port`
**Worktree** : `.claude/worktrees/feat-v5a-home-port/`
**Effort** : 4-6h
**Mode** : 🟢 Parallélisable
**Fichiers concernés** :
- `web/views/home.js` (enrichissement)
- `tests/test_home_v5_features.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/v5a-home-port .claude/worktrees/feat-v5a-home-port audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-v5a-home-port

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT `web/views/home.js` + son test.

RÈGLE V5 : préserver le style v5 home (widgets + charts SVG).

---

## CONTEXTE

`web/views/home.js` (718L) est la vue Accueil v5 avec widgets + charts SVG (donut + line). Il manque 5 features V1-V4 :

1. **V1-07** : Banner `.alert--warning` outils manquants (dashProbeInstallBanner) + bouton auto-install
2. **V3-05** : Demo wizard premier-run (overlay + bannière)
3. **V1-06** : CTA "Configurer" pour intégrations non actives
4. **V2-04** : Promise.allSettled (au lieu de Promise.all) pour résilience
5. **V2-08** : Skeleton loading states

---

## MISSION

### Étape 1 — Lire l'existant

- `web/views/home.js` (718L — le fichier à enrichir)
- `web/dashboard/views/status.js` lignes 380-450 (référence V1-07 banner outils v4)
- `web/dashboard/views/demo-wizard.js` (composant V3-05 à réutiliser)
- `web/dashboard/app.js` lignes 329-343 (logique `_initDemoMode` v4)

### Étape 2 — Promise.allSettled (V2-04)

Cherche les `Promise.all([...])` dans home.js et remplace par `Promise.allSettled([...])`. Adapter le code qui consomme les résultats : `Promise.allSettled` retourne `[{status, value}|{status, reason}]` au lieu d'un array de valeurs directes.

Exemple :
```javascript
// AVANT
const [statsRes, settingsRes, healthRes] = await Promise.all([
  apiPost("get_global_stats"),
  apiPost("get_settings"),
  apiGet("/health"),
]);
const stats = statsRes.data;

// APRÈS
const results = await Promise.allSettled([
  apiPost("get_global_stats"),
  apiPost("get_settings"),
  apiGet("/health"),
]);
const stats = results[0].status === "fulfilled" ? results[0].value.data : null;
const settings = results[1].status === "fulfilled" ? results[1].value.data : {};
const health = results[2].status === "fulfilled" ? results[2].value : null;
// → si une endpoint plante, les autres données restent dispo
```

### Étape 3 — Skeleton states (V2-08)

Ajoute un état "skeleton" affiché AVANT que les données arrivent. Pattern :

```javascript
function _renderSkeleton(container) {
  container.innerHTML = `
    <div class="v5-skeleton v5-skeleton--home">
      <div class="v5-skeleton-card v5-skeleton-card--kpi"></div>
      <div class="v5-skeleton-card v5-skeleton-card--kpi"></div>
      <div class="v5-skeleton-card v5-skeleton-card--kpi"></div>
      <div class="v5-skeleton-chart"></div>
    </div>
  `;
}

// Dans initHome :
export function initHome(container) {
  _renderSkeleton(container);
  _loadAndRender(container).catch((err) => { ... });
}
```

CSS attendu (mention dans commit) : `.v5-skeleton-card { background: linear-gradient(90deg, var(--bg-raised) 25%, var(--bg-base) 50%, var(--bg-raised) 75%); animation: v5-skeleton-shimmer 1.5s infinite; }`. Ajouter dans `web/shared/animations.css` si simple.

### Étape 4 — Banner outils manquants (V1-07)

Ajoute une section qui s'affiche quand les outils probe sont manquants :

```javascript
async function _renderProbeBanner(container) {
  const res = await apiPost("get_probe_tools_status");
  const data = res?.data || {};
  if (data.ffprobe_ok && data.mediainfo_ok) return; // tout OK

  const banner = document.createElement("section");
  banner.className = "v5-alert v5-alert--warning v5-home-probe-banner";
  banner.setAttribute("role", "alert");
  banner.innerHTML = `
    <div class="v5-alert-icon">⚠</div>
    <div class="v5-alert-body">
      <strong>Outils d'analyse manquants</strong>
      <p>${data.ffprobe_ok ? "" : "ffprobe absent."} ${data.mediainfo_ok ? "" : "mediainfo absent."}
         L'analyse qualité sera limitée tant que ces outils ne sont pas installés.</p>
    </div>
    <button class="v5-btn v5-btn--primary" id="v5BtnAutoInstallProbe">Installer automatiquement</button>
  `;
  container.insertBefore(banner, container.firstChild);

  document.getElementById("v5BtnAutoInstallProbe")?.addEventListener("click", async (e) => {
    e.target.disabled = true;
    e.target.textContent = "Installation...";
    try {
      await apiPost("auto_install_probe_tools");
      setTimeout(() => window.location.reload(), 2000);
    } catch (err) {
      e.target.disabled = false;
      e.target.textContent = "Installer automatiquement";
      alert("Erreur installation : " + (err.message || err));
    }
  });
}
```

Appeler `_renderProbeBanner(container)` après le render principal.

### Étape 5 — CTA Configurer intégrations (V1-06)

Pour les intégrations Jellyfin/Plex/Radarr non activées, afficher une carte "Configurer" qui amène vers Paramètres. Dans la section "Intégrations" du home (si elle existe ; sinon créer un widget) :

```javascript
function _renderIntegrationsWidget(settings) {
  const items = [
    { id: "jellyfin", label: "Jellyfin", enabled: !!settings.jellyfin_enabled },
    { id: "plex", label: "Plex", enabled: !!settings.plex_enabled },
    { id: "radarr", label: "Radarr", enabled: !!settings.radarr_enabled },
  ];
  return `
    <section class="v5-home-integrations">
      <h2>Intégrations</h2>
      <div class="v5-grid v5-grid--3">
        ${items.map(it => it.enabled ? `
          <div class="v5-card v5-card--connected">
            <span class="v5-status-dot v5-status-dot--ok"></span>
            <strong>${it.label}</strong>
            <span class="v5-text-muted">Connecté</span>
          </div>
        ` : `
          <a class="v5-card v5-card--disabled" href="#/settings?focus=${it.id}">
            <strong>${it.label}</strong>
            <span class="v5-text-muted">Non configuré</span>
            <span class="v5-link-cta">Configurer →</span>
          </a>
        `).join("")}
      </div>
    </section>
  `;
}
```

Adapter selon la structure réelle de home.js (widget existant ou nouvelle section).

### Étape 6 — Demo wizard premier-run (V3-05)

Importer et appeler le wizard :

```javascript
import { showDemoWizardIfFirstRun, renderDemoBanner } from "../dashboard/views/demo-wizard.js";

// Au boot de initHome :
async function _initDemoModeIfNeeded(settings, stats) {
  try {
    await showDemoWizardIfFirstRun(settings, stats);
    await renderDemoBanner();
  } catch (err) {
    console.warn("[home v5] init demo mode", err);
  }
}
```

⚠ Si le module `demo-wizard.js` n'est pas importable depuis `web/views/`, créer un copy/shim. Vérifier le chemin résolu.

### Étape 7 — Tests structurels

Crée `tests/test_home_v5_features.py` :

```python
"""V5A-04 — Vérifie home.js v5 enrichi avec 5 features V1-V4."""
from __future__ import annotations
import unittest
from pathlib import Path


class HomeV5FeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/home.js").read_text(encoding="utf-8")

    def test_v2_04_promise_allsettled(self):
        self.assertIn("Promise.allSettled", self.src)

    def test_v2_08_skeleton(self):
        self.assertIn("v5-skeleton", self.src)
        self.assertIn("_renderSkeleton", self.src)

    def test_v1_07_probe_banner(self):
        self.assertIn("get_probe_tools_status", self.src)
        self.assertIn("v5-home-probe-banner", self.src)
        self.assertIn("auto_install_probe_tools", self.src)

    def test_v1_06_integrations_cta(self):
        self.assertIn("v5-home-integrations", self.src)
        self.assertIn("focus=jellyfin", self.src)
        self.assertIn("Configurer", self.src)

    def test_v3_05_demo_wizard(self):
        self.assertIn("showDemoWizardIfFirstRun", self.src)
        self.assertIn("renderDemoBanner", self.src)


if __name__ == "__main__":
    unittest.main()
```

### Étape 8 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_home_v5_features -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
node --check web/views/home.js 2>&1 | tail -2
```

### Étape 9 — Commits

- `refactor(home-v5): V2-04 Promise.allSettled for endpoint resilience`
- `feat(home-v5): V2-08 skeleton loading states`
- `feat(home-v5): V1-07 missing tools banner with auto-install`
- `feat(home-v5): V1-06 integrations CTA Configurer`
- `feat(home-v5): V3-05 demo wizard first-run integration`
- `test(home-v5): structural tests for V5A-04`

---

## LIVRABLES

- `home.js` enrichi avec 5 features V1-V4
- Test structurel
- Style v5 préservé (widgets + charts intacts)
- 6 commits sur `feat/v5a-home-port`
