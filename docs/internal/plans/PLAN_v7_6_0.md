# Plan v7.6.0 — Refonte UI/UX complete

**Date :** 2026-04-23
**Cible :** refonte UI complete alignee avec le moteur v7.5.0 + design system v5
**Philosophie :** overview-first, data-first, deep, active
**Methode :** reprise du pattern v7.5.0 (vagues + `go §X` validations successives)

---

## Vision

CineSort v7.5.0 a livre un moteur d'analyse perceptuelle avance mais **l'UI n'expose pas cette intelligence**. L'utilisateur doit fouiller pour voir ses films, les settings sont empiles, la navigation est floue, le visuel manque de vie.

v7.6.0 transforme l'app en un **tableau de bord actif** :
- 3 secondes pour comprendre l'etat de sa biblio (Home overview-first)
- 1 clic pour ouvrir une fiche film complete (Page Film standalone)
- 1 raccourci clavier (Cmd+K) pour acceder a tout (Command Palette)
- 9 groupes settings ranges par intention (fini 22 sections empilees)
- Tiers V2 partout (Platinum/Gold/Silver/Bronze/Reject) — v1 abandonne
- Design system v5 data-first avec 4 themes retravailles (tier colors invariants)
- Motion et profondeur retrouves (stagger, hover lift, glass raffine)

---

## Vagues d'implementation

### Vague 0 — Design system v5 (~12h)

**Livrables** :
- `web/shared/tokens.css` : palette + typography + spacing + radius + motion
- `web/shared/themes.css` : 4 themes (Studio / Cinema / Luxe / Neon) data-first
- `web/shared/components.css` : specs buttons / cards / badges / tables / modals
- `web/shared/utilities.css` : layout + text + spacing utilities
- `web/shared/animations.css` : keyframes et presets
- Tokens valides : tier colors invariants, surfaces 3 niveaux, motion complete
- Fichiers charges dans `index.html` desktop + `dashboard/index.html`
- Legacy `styles.css` et `themes.css` conserves temporairement (migration progressive)

**Tests** :
- Visual regression Playwright (5 captures par theme)
- Validation WCAG AA (contrast ratios)
- Reduced-motion fonctionne

### Vague 1 — Navigation v5 (sidebar + top bar + command palette) (~10h)

**Livrables** :
- `web/components/sidebar.js` : sidebar 240px collapsable 64px, 7 entrees
- `web/components/top-bar.js` : search trigger + notifications + theme switch
- `web/components/breadcrumb.js` : pour vues nested
- Refonte `web/components/command-palette.js` : v5 data-first
- Migration routing pour `/film/:id` dans `web/core/router.js`
- Dashboard : parite via composants shareable

**Tests** :
- 7 routes desktop + dashboard OK
- Cmd+K ouvre palette partout
- Keyboard navigation (Tab, Enter, Escape, fleches)

### Vague 2 — Home overview-first (~12h)

**Livrables** :
- Refonte `web/views/home.js` selon maquette
- Hero band (KPIs 5 cards + bouton scan + watch indicator)
- Section Insights (3-5 cards dismissibles)
- Graphs (distribution donut + tendance 30j line chart)
- Section "5 derniers ajouts" (poster slider)
- API : extension `get_global_stats` pour insights proactifs

**Tests** :
- KPIs corrects sur dataset de test
- Insights cliquables -> vues filtrees
- Animations stagger OK

### Vague 3 — Bibliotheque / Explorateur (~14h)

**Livrables** :
- Nouvelle vue `web/views/library.js` (distincte de Traitement)
- Toggle Table / Grid view
- Sidebar filtres composables (10 dimensions)
- Smart Playlists (persistance dans settings)
- Virtualisation table (>1000 rows)
- Pagination 50 rows/page

**Tests** :
- Filtres composables AND/OR
- Grid view responsive
- Perf table 5000 rows < 500ms initial render
- Smart Playlists persistance

### Vague 4 — Page Film standalone (~12h)

**Livrables** :
- Route `/film/:row_id` dans `web/core/router.js`
- Vue `web/views/film-detail.js` avec hero band + 4 tabs
- Fetch poster TMDb + cache
- Integration score-v2 (cercle hero + jauges + accordeon)
- Tab Historique : reutilise timeline §9.13
- Tab Comparaison : selecteur autre fichier + LPIPS

**Tests** :
- Routes /film/123 fonctionne
- Poster TMDb charge
- 4 tabs responsive

### Vague 5 — Traitement (F1 fusion) (~10h)

**Livrables** :
- Nouvelle vue `web/views/processing.js` fusion scan/validation/execution
- Progress bar 3 steps horizontale
- Step 1 Scan : formulaire roots + reglages
- Step 2 Review : table compacte (8 cols default) + filtres + actions bulk
- Step 3 Apply : preview diff + dry-run + confirm
- Transition fluide entre steps (pas navigation complete)
- Vues legacy `validation.js` + `execution.js` supprimees

**Tests** :
- 3 steps navigation OK
- Tri risque par defaut
- Approve/reject bulk
- Dry-run obligatoire avant apply

### Vague 6 — Settings refonte (9 groupes) (~14h)

**Livrables** :
- Refonte complete `web/views/settings.js`
- 9 groupes : Sources / Analyse / Nommage / Biblio / Integrations / Notifications / Serveur / Apparence / Avance
- Sidebar gauche + contenu droit
- Search fuzzy via rapidfuzz
- Badges `configure` / `a configurer` par section
- Preview live : themes, renaming, perceptual params
- Reset par section
- URL state `/settings/:category`
- Migration data : aucune (memes settings backend, UI reorganisee)

**Tests** :
- 9 groupes accessibles
- Search fonctionne
- Preview live OK
- Reset section preserve autres sections

### Vague 7 — Qualite + Integrations + Journal (~10h)

**Livrables** :
- Refonte `web/views/quality.js` : distribution V2 5 tiers + tendance 30j + scoring par realisateur/franchise (NOUVEAU)
- Nouvelle vue `web/views/integrations.js` : unification Jellyfin / Plex / Radarr cards
- Refonte `web/views/journal.js` (ex-history) : runs timeline + exports
- API : endpoint `get_scoring_rollup` pour scoring par realisateur

**Tests** :
- 5 tiers correctement comptes
- Integrations status chacune
- Exports CSV/HTML/.nfo

### Vague 8 — Parite dashboard distante (~10h)

**Livrables** :
- Fusion composants desktop/dashboard via `web/shared/components/`
- Adapter IIFE wrapper pour pywebview desktop
- Dashboard routes alignees : /, /processing, /library, /film/:id, /quality, /integrations, /journal, /settings
- Responsive 3 breakpoints maintenu
- Suppression duplication (badge.js, modal.js, score-v2.js, kpi-card.js, etc.)

**Tests** :
- Parite 1:1 desktop vs dashboard
- Responsive OK mobile
- Pas de regression fonctionnelle

### Vague 9 — Notifications & insights actifs (~6h)

**Livrables** :
- Nouveau `web/components/notification-center.js` (drawer depuis top bar)
- Endpoint `get_insights` : top warnings + nouveautes + digest
- Badge counter sur icone cloche
- Desktop notifications (deja livre, a rafraichir avec insights V2)
- Persist dismissed dans settings

**Tests** :
- Notification count correct
- Dismiss persist
- Desktop notification apres scan

### Vague 10 — Tests E2E + polish (~8h)

**Livrables** :
- ~25 tests Playwright couvrant toutes les vues
- Visual regression screenshots (3 viewports × 7 vues)
- Performance audit (Lighthouse)
- Accessibility audit (axe-core)
- Migration settings existants (v7.5 -> v7.6 mapping)
- Cleanup legacy CSS (suppression classes obsoletes)

**Tests** :
- 0 regression fonctionnelle
- Visual regression baselines valides
- Lighthouse score > 90
- WCAG AA valide

---

## Recapitulatif effort

| Vague | Titre | Effort |
|---|---|---|
| 0 | Design system v5 | 12h |
| 1 | Navigation + Command Palette | 10h |
| 2 | Home overview-first | 12h |
| 3 | Bibliotheque / Explorateur | 14h |
| 4 | Page Film standalone | 12h |
| 5 | Traitement fusion F1 | 10h |
| 6 | Settings refonte 9 groupes | 14h |
| 7 | Qualite + Integrations + Journal | 10h |
| 8 | Parite dashboard + fusion composants | 10h |
| 9 | Notifications & insights actifs | 6h |
| 10 | Tests E2E + polish | 8h |
| **Total** | | **118h** |

---

## Ordre d'execution recommande

**Phase A — Fondations (Vagues 0+1)** : 22h
Design system + Navigation. Sans ces 2, le reste est instable.

**Phase B — Vues principales (Vagues 2+3+4+5)** : 48h
Home + Bibliotheque + Film + Traitement. Le coeur du produit user-facing.

**Phase C — Settings + Extras (Vagues 6+7+9)** : 30h
Settings refonte + Qualite/Integrations/Journal + Notifications.

**Phase D — Consolidation (Vagues 8+10)** : 18h
Parite dashboard + Tests E2E + Polish.

**Total progression** : A -> B -> C -> D.
Validation utilisateur apres chaque phase avant de passer a la suivante.

---

## Risques et mitigations

| Risque | Impact | Mitigation |
|---|---|---|
| Regression visuelle sur vues existantes | Moyen | Visual regression Playwright par vague + conservation legacy CSS temp |
| Perte de features cache dans settings legacy | Eleve | Mapping complet avant migration, tests settings sur chaque groupe |
| Virtualisation table casse filtres | Moyen | Utiliser bibliotheque eprouvee (ou impl simple avec IntersectionObserver) |
| Commande palette lag sur 5000 films search | Faible | Debounce 150ms + rapidfuzz deja optimise |
| Themes data-first cassent identite | Faible | Validation visuelle utilisateur apres Vague 0 |
| User regrette densite Validation 50 cols | Faible | Mode "Advanced" toggle avec colonnes custom |
| Duplication desktop/dashboard difficile a fusionner | Moyen | Phasage progressif (1-2 composants a la fois) |

---

## Hors-scope v7.6.0

- **§10 NR-VMAF** (report v7.7+) — modele ML custom training
- **Radar chart** (report v7.7+) — composant isole
- **Scoring par realisateur/franchise** UI : inclus mais backend endpoint nouveau (rollup) reporte en v7.6.1 si complexe
- **Re-acquire smart mode** (v7.7+) : nouveau flow user
- **Integration Sonarr TV** (v7.7+) : stack *arr incomplete
- **Mode offline** : l'app necessite reseau pour TMDb (inchange)
- **I18n / autres langues** : FR uniquement (inchange)

---

## Conditions de reussite

1. L'utilisateur comprend l'etat de sa biblio en < 3 secondes (Home)
2. Accede a toute action en < 3 touches clavier (Cmd+K)
3. Trouve un reglage en < 10 secondes (Settings search)
4. Voit tous les indicateurs V2 d'un film sans fouiller (Page Film)
5. Aucune feature v7.5 perdue
6. Parite 100% desktop ↔ dashboard
7. Perfomance : time-to-interactive < 500ms meme sur 5000 films
8. Tests : 0 regression fonctionnelle, visual regression baselines valides
9. Accessibility : WCAG AA, keyboard navigation complete
10. Code : duplication desktop/dashboard reduite de 60% (900L -> ~350L)

---

## Validation attendue avant execution

Avant de partir sur Vague 0, l'utilisateur doit confirmer :

1. **Ordre des vagues** (A -> B -> C -> D accepte ?)
2. **Fusion composants desktop/dashboard** (Vague 8) : ok ou risque casser pywebview ?
3. **Wizard onboarding abandonne** : remplace par tooltips contextuels, ok ?
4. **Rows pre-v7.5 affichees avec tier "unknown"** : ok ou on force un recalcul V2 au demarrage ?
5. **Abandon vues Validation + Execution separees** (fusion dans Traitement) : ok ?

Une fois valide, on commence par **Vague 0 Design system v5** (sans laquelle rien ne peut bouger proprement).
