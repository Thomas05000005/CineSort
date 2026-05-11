# Plan de code — CineSort v7.6.0

**Date :** 2026-04-23
**Objet :** details d'implementation par vague (fichiers touches + signatures + ordre).
Documents lies : [PLAN_v7_6_0.md](PLAN_v7_6_0.md), [NOTES_RECHERCHE_v7_6_0.md](NOTES_RECHERCHE_v7_6_0.md), [MAQUETTES_v7_6_0.md](MAQUETTES_v7_6_0.md), [design-system-v5.md](../design-system-v5.md).

---

## Vague 0 — Design system v5

### Fichiers a creer

```
web/shared/
├── tokens.css          (~400L)  Palette + typo + spacing + radius + motion
├── themes.css          (~500L)  4 themes data-first
├── components.css      (~800L)  Buttons / cards / badges / tables / modals
├── utilities.css       (~200L)  Layout / text / spacing utilities
└── animations.css      (~150L)  @keyframes + transition presets
```

### Fichiers a modifier

- `web/index.html` : ajouter `<link rel="stylesheet">` des 5 fichiers shared/ AVANT styles.css legacy
- `web/dashboard/index.html` : idem
- `web/styles.css` : ajout commentaire "LEGACY — a migrer", suppression progressive en Vague 10
- `web/themes.css` : desactivation (conserve temporaire)

### Ordre d'implementation

1. **Etape 1** — `web/shared/tokens.css` (palette tier + severity, typo Manrope, spacing grille 4px, radius, motion variables). Ref section 2 de `design-system-v5.md`.
2. **Etape 2** — `web/shared/themes.css` (4 themes Studio/Cinema/Luxe/Neon). Tier colors invariants, uniquement surfaces + accent + atmosphere.
3. **Etape 3** — `web/shared/animations.css` (keyframes kpiFadeIn, scoreGaugeFill, modalEnter, slideInToast, etc.) + reduced-motion.
4. **Etape 4** — `web/shared/components.css` specs de base :
   - `.btn` / `.btn--primary` / `.btn--secondary` / `.btn--ghost` / `.btn--danger` (3 tailles)
   - `.card` / `.card--tier-[X]` (border-left colore)
   - `.badge` / `.badge--tier-[X]` / `.badge--severity-[X]`
   - `.table-v2` (sticky header, hover row lift, stripe)
   - `.modal-v2` (backdrop blur, entry scale)
   - `.toast-v2`
5. **Etape 5** — `web/shared/utilities.css` : `.flex-*`, `.grid-*`, `.text-*`, `.sp-*` coherent avec tokens.
6. **Etape 6** — Integration desktop : `index.html` charge shared/ avant styles.css legacy.
7. **Etape 7** — Integration dashboard : `dashboard/index.html` idem.
8. **Etape 8** — Tests visual regression : capture 5 vues legacy, verifier pas de drift majeur.
9. **Etape 9** — Tests Playwright structure : 4 themes applicables + toggles + WCAG AA.

### Signatures / structure CSS

```css
/* tokens.css — extrait */
:root {
  /* Tier colors (invariables) */
  --tier-platinum-solid: #FFD700;
  --tier-platinum-glow:  rgba(255, 215, 0, 0.25);
  --tier-platinum-bg:    rgba(255, 215, 0, 0.08);
  /* ... gold, silver, bronze, reject, unknown */

  /* Severity (invariables) */
  --sev-info-solid:    #60A5FA;
  /* ... success, warning, danger, critical */

  /* Typography */
  --font-family: 'Manrope', system-ui, -apple-system, sans-serif;
  --fs-base: 14px;
  /* ... */

  /* Motion */
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --dur-base: 240ms;
  --stagger-base: 60ms;
}
```

```css
/* themes.css — structure */
[data-theme="studio"] {
  --bg: #06090F;
  --surface-1: rgba(255, 255, 255, 0.035);
  --accent: #60A5FA;
  --atmosphere: ...;
}
[data-theme="cinema"] { /* ... */ }
[data-theme="luxe"]   { /* ... */ }
[data-theme="neon"]   { /* ... */ }
```

### Tests a ecrire (Python `tests/test_design_system_v5.py`, ~15 tests)
- `test_tokens_css_exists`
- `test_themes_css_contains_4_themes`
- `test_tier_colors_invariants_across_themes` (regex verify)
- `test_reduced_motion_fallback`
- `test_manrope_font_loaded`
- `test_index_html_loads_shared_before_legacy` (desktop + dashboard)

### Critere de sortie Vague 0
- 5 fichiers `web/shared/*.css` crees et valides
- Desktop + dashboard chargent le shared/ sans regression visuelle majeure
- 4 themes toggle fonctionne comme avant (juste avec tier colors invariants)
- 15 tests OK, 0 regression

---

## Vague 1 — Navigation + Command Palette v5

### Fichiers a creer

```
web/components/sidebar-v5.js        (~180L)  Sidebar 240px collapsable
web/components/top-bar-v5.js        (~120L)  Search trigger + notif + theme switch
web/components/breadcrumb.js        (~80L)   Breadcrumb pour vues nested
```

### Fichiers a modifier

- `web/components/command-palette.js` : refonte complete (~260L -> ~400L)
  - Search fuzzy sur films + actions + settings via rapidfuzz
  - Categories inline (Actions / Films / Reglages / Navigation)
  - Recent items persist localStorage
  - Shortcut hints inline
- `web/core/router.js` : ajout route `/film/:row_id`, ajout `/settings/:category`, breadcrumb auto
- `web/core/keyboard.js` : ajout `Cmd+K` / `Ctrl+K` global
- `web/index.html` : structure sidebar + top bar + main content (remplace header classique)
- `web/app.js` : init sidebar/top-bar au boot
- Dashboard : parite (les 3 composants dans `web/dashboard/components/`)

### Signatures

```js
// sidebar-v5.js
const NAV_ITEMS = [
  { id: 'home',         label: 'Accueil',      icon: 'Home',           shortcut: 'Alt+1' },
  { id: 'processing',   label: 'Traitement',   icon: 'Zap',            shortcut: 'Alt+2' },
  { id: 'library',      label: 'Bibliotheque', icon: 'Library',        shortcut: 'Alt+3' },
  { id: 'quality',      label: 'Qualite',      icon: 'BarChart3',      shortcut: 'Alt+4' },
  { id: 'journal',      label: 'Journal',      icon: 'History',        shortcut: 'Alt+5' },
  { id: 'integrations', label: 'Integrations', icon: 'Plug',           shortcut: 'Alt+6' },
  { id: 'settings',     label: 'Parametres',   icon: 'Settings',       shortcut: 'Alt+7' },
];

export function buildSidebar({ collapsed, onToggle, activeRoute }) { /* ... */ }
export function renderSidebar(container) { /* ... */ }
export function setSidebarCollapsed(collapsed) { /* ... */ }

// top-bar-v5.js
export function buildTopBar({ onSearchClick, onNotifClick, onThemeChange }) { /* ... */ }

// command-palette.js v5 API
export async function openCommandPalette() { /* ... */ }
export function registerAction({ id, label, category, shortcut, handler }) { /* ... */ }
export function searchFuzzy(query) { /* rapidfuzz-backed */ }

// router.js ajouts
export function navigateTo(path) { /* deja existant, ajouter /film/:id */ }
export function getBreadcrumb() { /* nouveau */ }
```

### Ordre d'implementation

1. **Etape 1** — `sidebar-v5.js` structure + CSS (3h)
2. **Etape 2** — `top-bar-v5.js` + CSS (2h)
3. **Etape 3** — Refonte `command-palette.js` v5 (2h)
4. **Etape 4** — Ajout routes `/film/:id` + breadcrumb dans `router.js` (1h)
5. **Etape 5** — Integration `index.html` + `app.js` (1h)
6. **Etape 6** — Parite dashboard (1h)
7. **Etape 7** — Tests Playwright nav + keyboard (1h)

### Tests
- `test_sidebar_7_items_visible`
- `test_sidebar_collapse_to_64px`
- `test_command_palette_cmd_k_opens`
- `test_command_palette_fuzzy_search`
- `test_breadcrumb_film_detail`
- `test_keyboard_alt_1_to_7_navigation`

### Critere de sortie Vague 1
- Sidebar + top bar + command palette fonctionnels desktop + dashboard
- Cmd+K ouvre la palette partout
- 7 routes navigables
- 0 regression fonctionnelle

---

## Vague 2 — Home overview-first

### Fichiers a modifier

- `web/views/home.js` : refonte complete (~592L -> ~400L)
  - Hero band : KPIs + scan button + watch indicator
  - Section Insights (3-5 cards dismissibles)
  - Graphs : distribution + tendance 30j
  - Section recent : 5 derniers ajouts (posters) + 5 derniers apply

### Fichiers a creer

```
web/components/kpi-grid.js       (~100L)  Grid de KPI cards avec stagger
web/components/insight-card.js   (~80L)   Card insight actionnable
web/components/donut-chart.js    (~120L)  Donut SVG pour distribution tiers
web/components/line-chart.js     (~150L)  Line chart SVG pour tendance
web/components/poster-carousel.js (~100L) Bandeau horizontal posters
```

### Fichiers backend a modifier

- `cinesort/ui/api/dashboard_support.py` : etendre `get_global_stats` pour inclure :
  - `v2_tier_distribution` : counts par tier V2
  - `trend_30days` : [{date, avg_score}] sur 30j
  - `insights` : [{type, severity, count, label, filter_hint}] proactifs

### Signatures

```js
// kpi-grid.js
export function renderKpiGrid(container, kpis) {
  // kpis = [{ id, label, value, trend?, suffix?, icon }]
}

// insight-card.js
export function renderInsight({ severity, title, count, filterHint, onAction, onDismiss }) { }

// home.js refonte
async function loadHome() {
  const stats = await apiCall("get_global_stats", ...);
  renderHero(stats);
  renderKpiGrid($("homeKpis"), buildKpiList(stats));
  renderInsights($("homeInsights"), stats.insights);
  renderDonut($("homeDonut"), stats.v2_tier_distribution);
  renderLine($("homeTrend"), stats.trend_30days);
  renderRecent($("homeRecent"), stats.recent);
}
```

### Signatures backend

```python
# dashboard_support.py ajouts
def _compute_v2_tier_distribution(store: Any, limit_runs: int) -> Dict[str, int]:
    """Compte les films par tier V2 sur les N derniers runs."""

def _compute_trend_30days(store: Any) -> List[Dict[str, Any]]:
    """Renvoie [{date: YYYY-MM-DD, avg_score: float, count: int}, ...] sur 30j."""

def _compute_active_insights(store: Any, limit_runs: int) -> List[Dict[str, Any]]:
    """Calcule les insights proactifs :
    - new_rejects : nouveaux Reject dans le dernier run
    - duplicates_to_resolve : doublons pending decision
    - dnr_partial_count : films DNR partiel
    - new_platinum_month : Platinum ajoutes ce mois
    - run_in_progress : run actif (optionnel)
    Returns list triee par severity desc + count desc.
    """
```

### Ordre d'implementation

1. **Etape 1** — Backend `_compute_v2_tier_distribution` + tests (1h)
2. **Etape 2** — Backend `_compute_trend_30days` + tests (1h)
3. **Etape 3** — Backend `_compute_active_insights` + tests (2h)
4. **Etape 4** — `get_global_stats` enrichi + endpoint tests (1h)
5. **Etape 5** — Composants `kpi-grid.js` + `insight-card.js` (2h)
6. **Etape 6** — Composants `donut-chart.js` + `line-chart.js` (2h)
7. **Etape 7** — Composant `poster-carousel.js` + fetch posters TMDb (1h)
8. **Etape 8** — Refonte `home.js` (1h)
9. **Etape 9** — Tests E2E Playwright (1h)

### Tests
- `test_get_global_stats_v2_distribution`
- `test_get_global_stats_trend_30days`
- `test_get_global_stats_insights`
- `test_home_kpi_grid_renders_5`
- `test_home_insights_dismissible`
- `test_home_donut_5_tiers`

### Critere de sortie Vague 2
- Home affiche KPIs + insights + graphs + recent
- Endpoint `get_global_stats` retourne les 3 nouveaux payloads
- Stagger animations OK
- Insights cliquables naviguent vers vue filtree
- 0 regression

---

## Vague 3 — Bibliotheque / Explorateur (overview)

### Fichiers

- Nouveau `web/views/library.js` (~500L) : table + grid + filters sidebar
- Nouveau `web/components/filter-sidebar.js` (~200L) : filtres composables
- Nouveau `web/components/smart-playlists.js` (~150L) : playlists persistees
- Nouveau `web/components/poster-grid.js` (~120L) : grid vue poster
- Backend : endpoint `get_library_filtered(filters, sort, page, page_size)` dans `cinesort_api.py`
- Backend : endpoints `get_smart_playlists`, `save_smart_playlist`, `delete_smart_playlist`

### Signatures cles

```python
def get_library_filtered(
    self,
    filters: Dict[str, List[str]],  # {tier: [...], codec: [...], warnings: [...], ...}
    sort: str,                       # "title" | "score_desc" | "year" | ...
    page: int,
    page_size: int,
) -> Dict[str, Any]:
    """Returns {rows: [...], total: int, page: int, pages: int}"""
```

**Details complets** : a affiner juste avant Vague 3 (apres Vagues 0-2 validees).

---

## Vague 4 — Page Film standalone

### Fichiers

- Nouveau `web/views/film-detail.js` (~400L)
- Nouveau `web/components/film-hero.js` (~150L)
- Refonte `web/core/router.js` : route `/film/:row_id` avec params
- Backend : endpoint `get_film_full(row_id)` unifie :
  - metadata, probe, perceptual V2, history timeline, poster URL TMDb

### Signatures cles

```python
def get_film_full(self, run_id: str, row_id: str) -> Dict[str, Any]:
    """Returns {
      row: PlanRow jsonable,
      probe: NormalizedProbe dict,
      perceptual: PerceptualResult dict + global_score_v2,
      history: timeline events,
      poster_url: str | None,
      tmdb_meta: dict | None,
    }"""
```

**Details complets** : a affiner juste avant Vague 4.

---

## Vagues 5-10 — details lors de leur demarrage

Pour eviter la longueur, je detaille les vagues 5-10 **a leur demarrage**, juste avant execution. Le pattern v7.5.0 fonctionne ainsi (recap condense + `go §X` = validation + implementation).

**Points d'attention deja identifies** :

### Vague 5 — Traitement F1
- Preserver tous les raccourcis clavier validation actuels (fleches/jk, Espace/a, r, i)
- Migration path : vues `validation.js` + `execution.js` -> suppression propre
- Progress bar 3 steps = nouveau composant `.progress-steps`

### Vague 6 — Settings 9 groupes
- Mapping 22 sections -> 9 groupes (document a faire avant demarrage)
- Search fuzzy = reutiliser rapidfuzz existant
- Preview live = extraire logique existante (themes + renaming + perceptual) dans composants reutilisables

### Vague 7 — Qualite + Integrations + Journal
- Endpoint `get_scoring_rollup(by: 'director' | 'franchise')` nouveau
- Integrations : une seule vue avec 3 sections (Jellyfin / Plex / Radarr)
- Journal (ex-history) : enrichi avec filtre runs + export batch

### Vague 8 — Fusion composants desktop/dashboard
- Pattern : `web/shared/components/score-v2.js` (ES module pur)
- Desktop wrapper : `web/components/score-v2.js` (IIFE qui importe shared et expose window.*)
- A commencer par les composants les moins critiques (badge, card, skeleton)
- Terminer par les gros (score-v2, command-palette)

### Vague 9 — Notifications & insights actifs
- `notification-center.js` = drawer avec liste + counter
- Endpoint `get_notifications` + `dismiss_notification` (persist localStorage cote UI, DB optionnel)
- Desktop notifications : deja livre v7.4, juste refresh avec insights V2

### Vague 10 — Tests E2E + polish
- 25 tests Playwright : 3-4 par vue principale
- Visual regression : 3 viewports × 7 vues = 21 baselines
- Audit Lighthouse : seuils TTI/LCP/CLS documentes
- Cleanup CSS legacy : suppression apres verification

---

## Conventions transversales

### CSS
- Prefixe nouvelles classes par `.v5-` temporairement pour debug (supprime en Vague 10)
- Variables CSS : `--<domaine>-<propriete>` (ex `--tier-platinum-solid`, `--motion-dur-base`)
- Media queries : mobile-first (`@media (min-width: ...)`)

### JS
- Desktop : IIFE `(function () { "use strict"; ... window.X = X; })()`
- Dashboard : ES modules `import { X } from "./y.js"; export function Z() { }`
- Shared components : ES modules purs, desktop wrapper via `<script type="module">`

### API REST
- Endpoints nouveaux prefixe `v2_` ? **NON**. On etend les existants avec champs supplementaires (backward compat).
- Deprecations : commentaire `@deprecated v7.7.0` dans docstring.

### Backend
- Nouveaux modules UI dans `cinesort/ui/api/` (pas dans `domain/`)
- Conserver principes v7.5.0 (subprocess direct, robustesse, migrations sequentielles)
- Aucune migration SQL necessaire en v7.6.0 (schema v18 suffit)

---

## Ordre d'execution global

```
Phase A (fondations) :
  Vague 0 (12h) -> Vague 1 (10h)               = 22h
     ↓
  VALIDATION UTILISATEUR (visual regression + nav OK)
     ↓
Phase B (vues principales) :
  Vague 2 (12h) -> Vague 3 (14h) -> Vague 4 (12h) -> Vague 5 (10h)  = 48h
     ↓
  VALIDATION UTILISATEUR (parcours user complet testable)
     ↓
Phase C (settings + extras) :
  Vague 6 (14h) -> Vague 7 (10h) -> Vague 9 (6h)  = 30h
     ↓
  VALIDATION UTILISATEUR (tous les indicateurs v7.5 accessibles)
     ↓
Phase D (consolidation) :
  Vague 8 (10h) -> Vague 10 (8h)               = 18h
     ↓
  v7.6.0 RELEASE
```

**Total : 118h** reparti sur 4 phases avec validation user entre chaque.

---

## Etat actuel

- [x] `PLAN_RECHERCHE_v7_6_0.md`
- [x] Audit UI existante (Explore agent)
- [x] `NOTES_RECHERCHE_v7_6_0.md`
- [x] `design-system-v5.md`
- [x] `MAQUETTES_v7_6_0.md`
- [x] `PLAN_v7_6_0.md`
- [x] `PLAN_CODE_v7_6_0.md` (ce document)
- [ ] Validation utilisateur sur les 5 points de `PLAN_v7_6_0.md` section "Validation attendue"
- [ ] Demarrage Vague 0 (Design system v5)
