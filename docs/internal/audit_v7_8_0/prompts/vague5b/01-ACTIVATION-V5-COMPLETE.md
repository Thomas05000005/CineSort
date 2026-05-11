# V5B-01 — Activation v5 complète dans le dashboard (avec vues ESM-portées)

**Branche** : `feat/v5b-activation`
**Worktree** : `.claude/worktrees/feat-v5b-activation/`
**Effort** : 1 jour
**Mode** : 🟢 1 seule mission monolithique
**Fichiers concernés** :
- `web/dashboard/app.js` (refonte imports + boot v5)
- `web/dashboard/index.html` (refonte structure : sidebar HTML statique → shell v5 mount points)
- `web/dashboard/core/router.js` (vérifier support routes paramétrées `/film/:id`)
- `tests/test_v5b_activation.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/v5b-activation .claude/worktrees/feat-v5b-activation audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-v5b-activation

# Vérifier que les ports V5bis sont en place
test -f web/views/_v5_helpers.js && grep -q "export async function initHome" web/views/home.js \
  && grep -q "export async function initLibrary" web/views/library-v5.js \
  && grep -q "export async function initSettings" web/views/settings-v5.js \
  && echo "✅ Vues v5 ESM-compatibles présentes" \
  || echo "❌ Vues v5 pas portées — V5bis pas mergée"

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE V5 : conserver le style v5 (préfixe `v5-*`, design data-first, tier colors invariantes).

RÈGLE PHASE B : on **active** v5 mais on ne supprime PAS encore les vues v4 obsolètes (`web/dashboard/views/quality.js`, `review.js`, etc.) — c'est V5C qui le fera.

RÈGLE TEST VISUEL : à la fin, l'instance lance l'app + teste manuellement la nouvelle UI avant commit final. Si bug visuel évident → fix avant commit.

RÈGLE NO-BREAK : si quelque chose casse, créer une branche `wip/v5b-debug` pour diagnostiquer plutôt que pousser un commit cassé.

---

## CONTEXTE

V5bis a porté les 7 vues v5 vers ES modules + REST `apiPost`. Maintenant V5B câble effectivement le shell + les routes :

**Avant V5B** :
```
index.html : sidebar HTML statique (250L) + topbar + 11 conteneurs vues
app.js     : import 12 vues v4 (web/dashboard/views/*.js)
```

**Après V5B** :
```
index.html : shell v5 minimal avec mount points (sidebar / topbar / breadcrumb / contenu)
app.js     : import composants v5 shell + 7 vues v5 portées (web/views/*.js)
           : routes : /home, /library, /processing, /quality, /settings, /help, /film/:id
           : routes Jellyfin/Plex/Radarr/Logs : conservent les vues v4 dashboard (V5C les portera ou supprimera)
           : notification center polling 30s
           : FAB Aide V3-08 monté
```

---

## MISSION

### Étape 1 — Lire l'existant

- `web/dashboard/index.html` (structure actuelle, ~249L)
- `web/dashboard/app.js` (~414L)
- `web/dashboard/core/router.js`
- `web/dashboard/core/api.js` (pour confirmer `apiPost` signature)
- Composants v5 shell : `web/dashboard/components/{sidebar-v5,top-bar-v5,notification-center,breadcrumb}.js`
- Vues v5 portées (V5bis) : `web/views/{_v5_helpers,home,library-v5,qij-v5,processing,settings-v5,film-detail,help}.js`

### Étape 2 — Vérifier router support `/film/:id`

```bash
grep -n "param\|:id\|matches\|test\|exec" web/dashboard/core/router.js | head -20
```

Si le router ne gère pas les routes paramétrées, ajoute le support **AVANT** d'enregistrer `/film/:id`. Pattern simple :

```javascript
// Dans registerRoute, accepter pattern "/film/:id"
// Dans la résolution, extraire les params et les passer à init(container, { params: { id } })
```

### Étape 3 — Refonte `index.html`

**Conserver** :
- `<head>` complet (CSP, meta, links CSS, font preload)
- Bloc `view-login` (login reste en HTML statique car non v5-isé)
- Skip link
- Script bootstrap

**Remplacer** la sidebar HTML statique + topbar + conteneurs vues par un **shell v5 minimal** :

```html
<body data-theme="luxe">
  <a href="#main-content" class="skip-link">Aller au contenu principal</a>

  <!-- LOGIN (préservé) -->
  <div id="view-login" class="view view--auth">
    <!-- ... contenu existant intact ... -->
  </div>

  <!-- SHELL V5 -->
  <div id="v5Shell" class="v5-shell" hidden>
    <aside id="v5SidebarMount" class="v5-sidebar-mount" role="navigation" aria-label="Navigation principale"></aside>
    <div class="v5-main">
      <header id="v5TopBarMount" class="v5-topbar-mount" role="banner"></header>
      <nav id="v5BreadcrumbMount" class="v5-breadcrumb-mount" aria-label="Fil d'Ariane"></nav>
      <main id="main-content" class="v5-content">
        <!-- Mount points pour les vues -->
        <section id="view-home" class="view" hidden></section>
        <section id="view-library" class="view" hidden></section>
        <section id="view-processing" class="view" hidden></section>
        <section id="view-quality" class="view" hidden></section>
        <section id="view-settings" class="view" hidden></section>
        <section id="view-help" class="view" hidden></section>
        <section id="view-film-detail" class="view" hidden></section>
        <!-- Vues v4 conservées temporairement (V5C les portera ou supprimera) -->
        <section id="view-jellyfin" class="view" hidden></section>
        <section id="view-plex" class="view" hidden></section>
        <section id="view-radarr" class="view" hidden></section>
        <section id="view-logs" class="view" hidden></section>
      </main>
    </div>
  </div>

  <script type="module" src="./app.js"></script>
</body>
```

### Étape 4 — Refonte `app.js`

**Préserver** :
- Détection mode natif `_detectNativeBoot()` IIFE
- Logique `hasToken`/`setToken` import
- Gestion `_currentRoute()`, `_applyTheme()`, `_initDemoMode`
- `_loadDashTheme()` actuelle si pertinente

**Remplacer** la chaîne d'imports v4 par chaîne v5 + vues portées :

```javascript
/* app.js — Bootstrap dashboard CineSort v7.6.0 (v5 active) */

import { $$ } from "./core/dom.js";
import { hasToken, setToken } from "./core/state.js";
import { apiPost } from "./core/api.js";

/* Détection mode natif (préservé) */
(function _detectNativeBoot() {
  /* ... préserver le code existant ... */
})();

import { registerRoute, requireAuth, startRouter, navigateTo } from "./core/router.js";

// === Composants v5 shell ===
import * as sidebarV5 from "./components/sidebar-v5.js";
import * as topBarV5 from "./components/top-bar-v5.js";
import * as breadcrumb from "./components/breadcrumb.js";
import * as notifCenter from "./components/notification-center.js";

// === Vues v5 portées (V5bis) ===
import { initLogin } from "./views/login.js";
import { initHome } from "../views/home.js";
import { initLibrary } from "../views/library-v5.js";
import { initProcessing } from "../views/processing.js";
import { initQij } from "../views/qij-v5.js";
import { initSettings } from "../views/settings-v5.js";
import { initFilmDetail } from "../views/film-detail.js";
import { initHelp } from "../views/help.js";

// === Vues v4 conservées (V5C les traitera) ===
import { initJellyfin } from "./views/jellyfin.js";
import { initPlex } from "./views/plex.js";
import { initRadarr } from "./views/radarr.js";
import { initLogs } from "./views/logs.js";

// === Routes v5 ===
registerRoute("/login", { view: "view-login", init: initLogin });
registerRoute("/home", { view: "view-home", guard: requireAuth, init: initHome });
registerRoute("/library", { view: "view-library", guard: requireAuth, init: initLibrary });
registerRoute("/processing", { view: "view-processing", guard: requireAuth, init: initProcessing });
registerRoute("/quality", { view: "view-quality", guard: requireAuth, init: initQij });
registerRoute("/settings", { view: "view-settings", guard: requireAuth, init: initSettings });
registerRoute("/help", { view: "view-help", guard: requireAuth, init: initHelp });
registerRoute("/film/:id", { view: "view-film-detail", guard: requireAuth, init: (el, opts) => initFilmDetail(el, { filmId: opts?.params?.id }) });

// Vues v4 conservées (routes inchangées)
registerRoute("/jellyfin", { view: "view-jellyfin", guard: requireAuth, init: initJellyfin });
registerRoute("/plex", { view: "view-plex", guard: requireAuth, init: initPlex });
registerRoute("/radarr", { view: "view-radarr", guard: requireAuth, init: initRadarr });
registerRoute("/logs", { view: "view-logs", guard: requireAuth, init: initLogs });

// Alias compat /status → /home (pour anciens liens)
registerRoute("/status", { view: "view-home", guard: requireAuth, init: initHome });

// === Mount shell v5 ===
async function _mountV5Shell() {
  const sidebarMount = document.getElementById("v5SidebarMount");
  const topBarMount = document.getElementById("v5TopBarMount");
  const breadcrumbMount = document.getElementById("v5BreadcrumbMount");

  // Sidebar v5
  sidebarV5.render(sidebarMount, {
    activeRoute: _currentRouteId(),
    collapsed: sidebarV5.isCollapsed(),
    onNavigate: (routeId) => navigateTo("/" + routeId),
    onAboutClick: _openAboutModal,
  });

  // Theme initial depuis settings
  const settingsRes = await apiPost("get_settings").catch(() => ({ data: {} }));
  const theme = settingsRes?.data?.theme || "luxe";

  // Top-bar v5
  topBarV5.render(topBarMount, {
    title: "CineSort",
    subtitle: "",
    theme,
    notificationCount: 0,
    onSearchClick: () => window.dispatchEvent(new CustomEvent("cinesort:command-palette")),
    onNotifClick: () => notifCenter.toggle(),
    onThemeChange: _applyTheme,
  });

  // Notification center
  notifCenter.mount(document.body, {
    onCountChange: (count) => topBarV5.updateNotificationBadge(count),
  });

  // Breadcrumb (si fonction disponible)
  if (breadcrumbMount && typeof breadcrumb.render === "function") {
    breadcrumb.render(breadcrumbMount, _currentRouteId());
  }

  // FAB Aide V3-08
  if (typeof topBarV5.mountHelpFab === "function") {
    topBarV5.mountHelpFab({ onClick: () => navigateTo("/help") });
  }

  // Affichage shell
  document.getElementById("v5Shell").hidden = false;
}

document.addEventListener("DOMContentLoaded", async () => {
  // Détection native (préservé)
  const isNative = !!window.__CINESORT_NATIVE__;
  if (isNative) document.body.classList.add("is-native");

  if (isNative && hasToken()) {
    if (!window.location.hash || window.location.hash.includes("/login")) {
      window.location.hash = "#/home";
    }
  } else if (!hasToken() && !window.location.hash.includes("/login")) {
    window.location.hash = "#/login";
  }

  startRouter();

  if (hasToken()) {
    await _mountV5Shell();
    await _initSidebarFeatures();
    await _initNotificationPolling();
    await _initDemoModeIfNeeded();
  }
});

/* === Utils === */

function _currentRouteId() {
  return (window.location.hash || "#/home").replace(/^#\//, "").split("?")[0].split("#")[0];
}

async function _initSidebarFeatures() {
  // V3-04 compteurs
  await _loadSidebarCounters();
  setInterval(_loadSidebarCounters, 30000);

  // V3-01 état désactivé intégrations
  await _checkIntegrationNav();

  // V1-13 badge update sur Settings
  await _checkUpdateBadge();
}

async function _loadSidebarCounters() {
  if (!hasToken()) return;
  try {
    const res = await apiPost("get_sidebar_counters");
    const data = res?.data?.data || res?.data || {};
    if (typeof sidebarV5.updateSidebarBadges === "function") {
      sidebarV5.updateSidebarBadges(data);
    }
  } catch { /* silencieux */ }
}

async function _checkIntegrationNav() {
  if (!hasToken()) return;
  try {
    const res = await apiPost("get_settings");
    const s = res?.data || {};
    if (typeof sidebarV5.markIntegrationState === "function") {
      sidebarV5.markIntegrationState("jellyfin", !!s.jellyfin_enabled, "Jellyfin");
      sidebarV5.markIntegrationState("plex", !!s.plex_enabled, "Plex");
      sidebarV5.markIntegrationState("radarr", !!s.radarr_enabled, "Radarr");
    }
  } catch { /* silencieux */ }
}

async function _checkUpdateBadge() {
  if (!hasToken()) return;
  try {
    const res = await apiPost("get_update_info");
    const data = res?.data || {};
    if (data.update_available && typeof sidebarV5.setUpdateBadge === "function") {
      sidebarV5.setUpdateBadge("settings", true, data.latest_version);
    }
  } catch { /* silencieux */ }
}

async function _initNotificationPolling() {
  setInterval(async () => {
    try {
      const res = await apiPost("get_notifications_unread_count");
      const count = res?.data?.count || 0;
      if (typeof topBarV5.updateNotificationBadge === "function") {
        topBarV5.updateNotificationBadge(count);
      }
    } catch { /* silencieux */ }
  }, 30000);
}

async function _initDemoModeIfNeeded() {
  if (!hasToken()) return;
  try {
    const settingsRes = await apiPost("get_settings");
    const settings = settingsRes?.data || {};
    const statsRes = await apiPost("get_global_stats");
    const stats = statsRes?.data || {};
    const { showDemoWizardIfFirstRun, renderDemoBanner } = await import("./views/demo-wizard.js");
    await showDemoWizardIfFirstRun(settings, stats);
    await renderDemoBanner();
  } catch (err) {
    console.warn("[v5 boot] init demo", err);
  }
}

function _applyTheme(theme) {
  document.body.dataset.theme = theme;
  apiPost("save_settings", { settings: { theme } }).catch(() => {});
}

function _openAboutModal() {
  // Si la modale About v4 existe encore, la trigger ; sinon log
  if (typeof window.openAboutModal === "function") window.openAboutModal();
  else console.info("[v5] About modal pas encore portée");
}
```

⚠ **À adapter au code réel** : les chemins exacts des imports, les noms de fonctions exportées, la signature de `_currentRoute` actuelle.

### Étape 5 — Cas particulier login

Le login `view-login` reste statique. Il bascule vers `#/home` après auth réussie. Pas de changement de logique.

### Étape 6 — Smoke test manuel (OBLIGATOIRE avant commit final)

```bash
.venv313/Scripts/python.exe app.py
```

Une fenêtre pywebview s'ouvre. **Vérifier visuellement** :
- ✅ Login s'affiche (premier lancement) ou redirection auto vers `#/home`
- ✅ Sidebar v5 visible avec 8 entrées
- ✅ Top-bar avec recherche Cmd+K + cloche notification + menu thèmes
- ✅ Click sur "Bibliothèque" → vue library v5 charge sans erreur
- ✅ Click sur "Paramètres" → settings-v5 s'affiche (avec mode expert + glossaire)
- ✅ Click sur "Aide" → help v5 (FAQ + glossaire + raccourcis + Support)
- ✅ Click sur cloche notif → drawer s'ouvre
- ✅ F12 console : aucune erreur rouge

Si un bug est détecté :
1. Diagnostic → fix → re-test
2. Si bloqué → reviens vers l'orchestrateur avec **« V5B-01 bug X »**

### Étape 7 — Tests structurels

Crée `tests/test_v5b_activation.py` :

```python
"""V5B-01 — Vérifie l'activation v5 dans app.js + index.html."""
from __future__ import annotations
import unittest
from pathlib import Path


class V5BActivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("web/dashboard/index.html").read_text(encoding="utf-8")
        cls.app = Path("web/dashboard/app.js").read_text(encoding="utf-8")

    def test_html_has_v5_shell(self):
        self.assertIn('id="v5Shell"', self.html)
        self.assertIn('id="v5SidebarMount"', self.html)
        self.assertIn('id="v5TopBarMount"', self.html)

    def test_html_no_more_static_sidebar(self):
        # Les boutons nav-btn data-route="/status" etc. ne doivent plus être en HTML statique
        # On accepte qu'ils existent dans le shell login HTML mais pas dans une <aside class="sidebar">
        # Heuristique : pas de <div class="sidebar-group">
        self.assertNotIn('<div class="sidebar-group">', self.html)

    def test_app_imports_v5_components(self):
        for comp in ["sidebar-v5.js", "top-bar-v5.js", "notification-center.js"]:
            self.assertIn(comp, self.app, f"Composant v5 non importé: {comp}")

    def test_app_imports_v5_views(self):
        for view_module in ["home.js", "library-v5.js", "processing.js", "qij-v5.js", "settings-v5.js", "film-detail.js", "help.js"]:
            self.assertIn(view_module, self.app, f"Vue v5 non importée: {view_module}")

    def test_routes_v5_registered(self):
        for route in ['"/home"', '"/library"', '"/processing"', '"/quality"', '"/settings"', '"/help"', '"/film/']:
            self.assertIn(route, self.app, f"Route manquante: {route}")

    def test_mount_v5_shell_function(self):
        self.assertIn("_mountV5Shell", self.app)

    def test_notification_polling_30s(self):
        self.assertIn("get_notifications_unread_count", self.app)
        self.assertIn("30000", self.app)

    def test_v3_04_sidebar_counters_active(self):
        self.assertIn("get_sidebar_counters", self.app)
        self.assertIn("updateSidebarBadges", self.app)

    def test_v3_01_integration_state_active(self):
        self.assertIn("markIntegrationState", self.app)

    def test_v1_13_update_badge_active(self):
        self.assertIn("setUpdateBadge", self.app)

    def test_v3_05_demo_wizard_init(self):
        self.assertIn("showDemoWizardIfFirstRun", self.app)


if __name__ == "__main__":
    unittest.main()
```

### Étape 8 — Vérifications finales

```bash
.venv313/Scripts/python.exe -m unittest tests.test_v5b_activation -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
node --check web/dashboard/app.js 2>&1 | tail -2
```

### Étape 9 — Commits

- `refactor(dashboard): rewrite index.html to v5 shell with mount points (V5B-01)`
- `feat(dashboard): activate v5 components in app.js (sidebar/top-bar/notif/breadcrumb)`
- `feat(dashboard): switch routes to v5 ESM views (home/library-v5/processing/qij/settings-v5/film-detail/help)`
- `feat(dashboard): notification polling 30s + sidebar counters + integration state + update badge`
- `test(v5b): structural tests for v5 activation`

---

## LIVRABLES

- `index.html` réduit à shell v5 minimal (mount points + login statique)
- `app.js` qui importe + active sidebar-v5, top-bar-v5, notification-center, breadcrumb
- 7 routes v5 ESM (home/library/processing/quality/settings/help/film) + 4 routes v4 conservées (jellyfin/plex/radarr/logs)
- Notification center polling 30s
- Sidebar counters V3-04 actifs
- Integration state V3-01 actif
- Update badge V1-13 actif
- Demo wizard V3-05 actif
- FAB Aide V3-08 monté
- Test structurel
- Smoke test manuel validé (sidebar visible, vues fonctionnent, no console errors)
- 5 commits sur `feat/v5b-activation`

---

## ⚠️ Cas particuliers à gérer

1. **Login** : reste en HTML statique, pas v5 (composant pas v5-isé). OK.
2. **Vues v4 conservées** : Jellyfin/Plex/Radarr/Logs gardent les vues v4 dashboard. V5C les portera ou supprimera selon décision.
3. **Route `/status` legacy** : alias vers `/home` v5 (préservation des anciens liens).
4. **Imports cross-folder** : `web/dashboard/app.js` doit importer `web/views/*.js`. Vérifier que le serveur HTTP local sert bien les 2 dossiers (cf `rest_server.py`).
5. **CSS** : les vues v5 utilisent les tokens `web/shared/*.css` qui sont déjà chargés. Si style cassé, vérifier les classes `v5-*`.
6. **Modal About** : la modale About v4 est dans `views/about.js`. Si elle est encore globale (`window.openAboutModal`), OK. Sinon créer un wrapper.
7. **Command palette** : dispatché via `CustomEvent("cinesort:command-palette")` — vérifier que le composant `command-palette.js` écoute bien cet event.

---

## ⚠️ Si bug bloquant

Documente précisément :
- Quelle vue casse (si applicable)
- Erreur console F12 exacte
- Étape du smoke test où ça plante

Reviens vers l'orchestrateur avec : **« V5B-01 bloque sur ABC »**.
