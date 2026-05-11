# Audit Tracking — CineSort post-fusion v7-fusion

> Fichier vivant qui tient le compte de ce qui a été audité, par qui, et ce qu'il reste à explorer.
> But : éviter les doublons inter-rounds + maintenir une vision exhaustive.

---

## Round 1 — terminé (3 mai 2026)

**Objectif** : audit fonctionnel post-fusion phases 1+2+3 (HOME, SETTINGS, QIJ).

**5 agents Explore en parallèle**, axes couverts :

### Agent 1 — Routing / Navigation
- Routes registerRoute vs sections HTML (orphelines détectées)
- Sidebar items vs SIDEBAR_ROUTE_ALIAS
- Aliases routes (/quality /jellyfin /plex /radarr /logs → QIJ)
- Hash query params parsing (`?tab=`)
- data-nav-route handlers
- Breadcrumbs ROUTE_BREADCRUMBS
- _currentRouteId() inverse mapping
- Initialisation lifecycle au boot

### Agent 2 — QIJ deep dive
- 17 endpoints utilisés vs backend (signatures + format retour)
- 14 hooks events (binding ordre, double-bind, selectors)
- Polling singleton (start/stop/cleanup)
- Modales (showModal, escape, XSS)
- Edge cases (empty states, run actif, run absent, switch tab)
- Mismatches features vs v4 (régressions)
- CSS classes utilisées
- Imports validation
- Race conditions (parallel mount tabs)

### Agent 3 — SETTINGS deep dive
- ~70 fields backend vs SETTINGS_GROUPS (mapping exhaustif)
- Endpoints settings (save/get/restart/test/qr/calibration/profile)
- Resolution `$value` / `$other_field` dans testParams
- DPAPI / secrets masquage (3 secret_fields confirmés OK)
- Sliders apparence live preview (effect_speed/glow/light)
- Mode expert toggle
- Auto-save 500ms debounce
- Danger zone reset workflow
- Update status (V3-12)
- QR dashboard + regen token
- Edge cases settings

### Agent 4 — HOME deep dive
- Section Aperçu V2 (Phase 1 conditionnelle)
- Partial-update (data-stat) toutes sections
- Polling 3s/15s + event check
- Theme apply au boot vs polling
- Hooks actions (cancel, install probes, nav-route)
- Accès distant QR
- Insights callback
- CSS classes
- Régressions vs v4 original (zéro détectée)

### Agent 5 — Cohérence transverse
- Imports orphelins (5 dead imports détectés)
- Vues v4 obsolètes (5 fichiers : quality, jellyfin, plex, radarr, logs)
- Sections HTML orphelines (#view-runs, #view-review)
- CSS non utilisées
- Endpoints backend appelés vs implémentés
- Exports orphelins
- console.* en prod
- TODO / FIXME / XXX
- Duplications fonctions helpers
- Composants partagés (empty-state, skeleton, modal, badge, table)
- Documentation CLAUDE.md vs réalité
- Preview HTML files à la racine
- Tests E2E impactés

### Findings consolidés Round 1
- **🔴 Critiques (3)** : C1 query param ?tab ignoré, C2 Jellyfin sync sans run_id, C3 routes ghost /runs et /review
- **🟠 High (7)** : Race Radarr upgrade, XSS m.year, parallel mount tabs, polling stale container, no save error feedback, table runs perd tri, tests E2E cassés
- **🟡 Medium (5)** : .clickable-row sans CSS, champs orphelins backend, insights filter_hint, CLAUDE.md outdated, preview HTML
- **⚪ Low (4)** : 5 imports dead, sections HTML inactives, vues v4 dead, console.*

**Faux positifs détectés** : 2 (data-nav-route hook, masquage TMDb/Jellyfin)

---

## Round 2 — en cours (3 mai 2026)

**Objectif** : axes COMPLÉMENTAIRES non couverts en Round 1. Ne PAS reauditer le routing/QIJ/SETTINGS/HOME/cohérence.

### 6 agents Explore en parallèle, NOUVEAUX axes :

#### Agent A — Sécurité
- XSS (escapeHtml partout, innerHTML risques, attributs href/src dynamiques)
- Injection paths/SQL (paths user, query params, filtres)
- CORS configuration
- Rate limiting REST
- Auth bypass (token validation, ntoken, native_mode)
- Token storage (localStorage vs sessionStorage, CSP)
- Path traversal handlers statiques
- Secrets dans logs (log_scrubber)
- Cookies / session

#### Agent B — Performance
- Bundle size (.exe + .js + .css)
- Paint blocking (CSS render block, font preload)
- Requêtes redondantes (multiples /get_settings)
- N+1 queries backend (SQL EXPLAIN)
- Cache HTTP headers (no-cache vs max-age cohérent)
- DOM size (innerHTML lourds vs partial)
- Event listener leaks (addEventListener sans cleanup)
- Polling fréquences excessives
- Lazy loading composants
- Animations performance (requestAnimationFrame, transform vs top/left)

#### Agent C — Accessibilité
- ARIA roles/labels/states
- Keyboard navigation (tab order, focus trap modales)
- Focus visible (--focus-ring partout)
- Contrast WCAG AA (4.5:1 sur 4 themes)
- Screen reader compatibility (aria-live, aria-busy)
- Alt text images
- Form labels associés inputs
- Skip links
- Reduced motion respect

#### Agent D — Robustesse runtime
- Network offline (fetch fails)
- Partial failures (Promise.allSettled bien géré)
- State corruption (settings json malformé)
- Race conditions cross-vues
- Timeouts (probe, TMDb, Jellyfin)
- Retry logic
- Error boundaries (silent fails)
- Récupération après crash backend
- Reconnect après token expiry

#### Agent E — Backend Python intégrité
- Signature endpoints exacts (params + types)
- Valeurs retournées vs ce que frontend attend (test direct)
- Exceptions handling (except Exception interdit, types explicites)
- State mutations thread-safe (locks)
- Logs scrubbing actif partout
- Migrations DB cohérentes (v18→v19 atomiques)
- Settings backup/restore
- DPAPI rotation
- File handles fuites
- subprocess timeouts

#### Agent F — CSS / responsive / visual
- Breakpoints (320/375/414/768/1024/1280/1440/1920)
- Media queries cohérence
- Mobile touch targets 44px
- Overflow horizontal cassé
- z-index conflits stacking contexts
- Animations smooth 60fps
- Dark mode cohérent 4 themes
- Print styles
- prefers-color-scheme
- Tier colors invariantes (test)
- Contrast text/bg sur 4 themes

---

## Round 2 — TERMINÉ (3 mai 2026)

6 agents Explore en parallèle, axes :
- A. Sécurité (XSS, injection, auth, CORS, secrets, path traversal, CSP) → 9.8/10
- B. Performance (bundle, paint, requêtes, polling, leaks, cache) → 7.2/10
- C. Accessibilité WCAG 2.2 AA (ARIA, keyboard, focus, contrast, SR) → 73/100
- D. Robustesse runtime (network, partial fails, race, timeout, retry, recovery) → 3 critiques
- E. Backend Python (signatures, exceptions, threading, migrations, DPAPI) → conforme
- F. CSS responsive visual (breakpoints, z-index, animations, themes, contrast) → 8.4/10

### Findings Round 2 (consolidé)
- **🔴 Critiques** : 4× get_settings au boot (perf), event listener leaks 16-18/vue, no window.onerror, z-index legacy chaos (9999+), aria-live non maj, focus trap modal manquant, journal poller sans timeout
- **🟠 High** : font-display:swap manquant, animations transition:all jank, dropdown arrow keys, table tri keyboard, accent contrast Cinema/Neon < 4.5:1
- **🟡 Medium** : champs requis sans aria-required, h1 manquant, charts sans alt, light theme CSS absent

---

## Round 3 — en cours (3 mai 2026)

8 agents, NOUVEAUX axes complémentaires (jamais audités) :

- A. Tests automatisés (E2E coverage, tests cassés post-fusion, tests manquants)
- B. Migrations DB / persistance (schema v20, indexes, FK, intégrité, backup)
- C. Workflow business (pipeline scan→review→apply, undo, dry-run, dedup, quality scoring)
- D. REST API conformité OpenAPI (spec exact, types, error codes)
- E. PyInstaller packaging (taille, exclusions, hiddenimports, splash, manifest, runtime hooks)
- F. Web research (general-purpose avec WebSearch) — best practices industry, CVE des libs, comparaison FileBot/Sonarr/Jellyfin
- G. Notifications Win32 + Watcher + FS events
- H. Update mechanism GitHub + Perceptual logique (composite score V2, weights, edge cases)

---

## Round 3 — TERMINÉ (3 mai 2026)

8 agents lancés : Tests, Migrations, Workflow business, OpenAPI, PyInstaller, Web research (CVE), Notifications/Watcher, Update mechanism.

### Findings consolidés Round 3 (hors duplications Round 1+2)
- **🔴 CRIT** : drain_queue() jamais appelée (notif perdues), CVE urllib3/PyInstaller, fs_safety jamais utilisé, watcher root inaccessible = scan auto
- **🟠 HIGH** : Composite V2 inactif, hidden imports perceptual incomplets PyInstaller, CSP unsafe-inline, OpenLogsFolder exclu REST, doc CLAUDE.md (98 endpoints réels vs "33"), tray icon Win32 pas cleanup crash
- **🟡 MED** : Multi-roots ajoutées runtime jamais scannées, evaluate_js sans timeout, polling 30s notif center, format API inconsistant

---

## Findings critiques registry (à fixer un jour) — TOUS ROUNDS

### Bloquants public release
- [CRIT-1] notify_service.drain_queue() jamais appelée → notifs scan_done invisibles
- [CRIT-2] qij.js opts.tab gagne sur hash ?tab → deep links cassés
- [CRIT-3] qij.js Jellyfin sync sans run_id → fail si pas dernier run done
- [CRIT-4] CVE urllib3 < 2.6.0 (Proxy-Authorization leak + zip bomb)
- [CRIT-4b] CVE PyInstaller < 6.10.0 (élévation privilèges locale)
- [CRIT-5] index.html sections /runs et /review orphelines + tests E2E cassés
- [CRIT-6] watcher.py NAS déconnecté = scan auto faux positif
- [CRIT-7] fs_safety.py modules existent mais 0 sites les appellent

### High avant release publique
- H1 window.onerror absent (white screen of death)
- H2 Race Radarr upgrade buttons setTimeout 100ms
- H3 XSS m.year non échappé sync modal
- H4 Race parallel mount tabs QIJ
- H5 Pas feedback erreur _scheduleSave
- H6 Régression table runs perd tri (Journal v4→v7)
- H7 Tests E2E cassés (#qualityContent etc.)
- H8 Polling stale container DOM detach
- H9 hiddenimports perceptual incomplets CineSort.spec
- H10 ARIA aria-live non maj + focus trap modal absent
- H11 font-display:swap manquant FOIT 0-3s
- H12 Event listener leaks 16-18/vue
- H13 4× get_settings au boot (cache absent)
- H14 Multi-roots ajout runtime jamais scannées
- H15 Win32 tray icon pas cleanup en crash (atexit manquant)
- H16 Composite V2 inactif par défaut (architecture fragmentée)
- H17 CSP 'unsafe-inline' style obsolète
- H18 OpenLogsFolder utilisé frontend mais exclu du REST
- H19 CLAUDE.md outdated 33 endpoints → 98 réels

### Medium (~25 findings) — fix opportuniste
- Z-index legacy chaos
- CSS .clickable-row non stylisée
- Champs orphelins backend invisibles UI
- Polling 30s notif center délai badge
- Sliders apparence peu d'éléments glow visibles
- TMDb cache sans TTL
- _emitted_insight_codes set sans cap memory growth
- Pre-releases GitHub /latest
- Format API inconsistant {data:} vs flat
- Bundle 4-5 polices dupliquées
- Live logs SSE > polling 2s
- Print() dans except acceptable mais à logger
- Etc.

### Faux positifs identifiés (NE PAS retraiter)
- ~~"data-nav-route sans listener"~~ (status.js:830 OK)
- ~~"TMDb/Jellyfin api_key masqués"~~ (en clair OK)
- ~~"4-5 print() en prod"~~ (1 seul, dans except)

---

## Round 4 — TERMINÉ (3 mai 2026)

6 agents lancés (memory, i18n, code complexity, logging, doc interne, perceptual deep).

### Findings nouveaux Round 4 (hors duplications)

#### Memory leaks (impact 1-3 MB/session)
- [R4-MEM-1] Pollings setInterval globaux jamais arrêtés au logout (3 timers app.js)
- [R4-MEM-2] Notification drawer listeners cumulés à chaque open (jamais detach)
- [R4-MEM-3] JournalPoller _tick sans timeout AbortSignal
- [R4-MEM-4] Vues n'exportent pas unmount() pattern → listeners survivent navigations
- [R4-MEM-5] localStorage drafts review.js sans rotation/TTL
- [R4-MEM-6] AbortController absent sur Promise.allSettled

#### i18n (FR-only verrouillé)
- [R4-I18N-1] ~250 strings FR frontend hardcodées (settings, help, qij, status)
- [R4-I18N-2] ~45 messages erreur backend FR hardcodés (apply_support, run_flow, settings)
- [R4-I18N-3] toLocaleString("fr-FR") + Ko/Mo hardcodés (format.js)
- [R4-I18N-4] Aucune infrastructure i18n (pas i18next/gettext, pas locales/)
- [R4-I18N-5] Notifications Win32 FR dur (notify_service.py)

#### Code complexity (CLAUDE.md outdated)
- [R4-CC-1] _plan_item plan_support.py:654 = 565 lignes, CC=126 (CLAUDE.md affirme "0 > 100L"!)
- [R4-CC-2] compute_quality_score quality_score.py:853 = 369L, CC=78
- [R4-CC-3] plan_library plan_support.py:302 = 347L, CC=73
- [R4-CC-4] 23 fonctions > 100L (vs "0" affirmé dans CLAUDE.md)
- [R4-CC-5] 23 fichiers > 500L (vs "6" affirmé)
- [R4-CC-6] ~200 docstrings publiques manquantes

#### Logging
- [R4-LOG-1] Pas de run_id transversal → debugging multi-couches difficile
- [R4-LOG-2] Pas de request_id REST → impossible tracer requête client
- [R4-LOG-3] Log level codé en dur (level=logging.INFO) → setting absent
- [R4-LOG-4] Env var CINESORT_DEBUG documenté mais non implémenté
- [R4-LOG-5] Frontend console.* sans guard if (DEBUG_MODE)
- [R4-LOG-6] Aucun structured logging JSON (extra={...})
- [R4-LOG-7] Timing slow-queries probe/scan absent

#### Documentation
- [R4-DOC-1] CLAUDE.md outdated (98 endpoints réels vs "33", v7.6.0 sections manquantes)
- [R4-DOC-2] Aucun docs/api/ENDPOINTS.md pour 98 endpoints
- [R4-DOC-3] Aucun docs/MANUAL.md user manual
- [R4-DOC-4] Aucun docs/TROUBLESHOOTING.md
- [R4-DOC-5] Aucun architecture.mmd diagram
- [R4-DOC-6] Aucun .env.example / settings.json.example
- [R4-DOC-7] BILAN_CORRECTIONS.md trop lourd (237 KB), R1-2 jamais archivés

#### Perceptual deep
- [R4-PERC-1] Grain v2 signatures Nolan/A24/Pixar contexte perdu (build_grain_historical_context manque tmdb_metadata)
- [R4-PERC-2] Video analysis faux positifs scènes ultra-sombres (y_avg<30) → blockiness/blur penalize
- [R4-PERC-3] LPIPS model absent → FileNotFoundError (pas fallback graceful)
- [R4-PERC-4] FFmpeg timeout subprocess zombies (pas de cleanup explicite)
- [R4-PERC-5] HDR10 sans MaxCLL → validation_flag malus -10 (mais souvent valide)
- [R4-PERC-6] Mel analysis désactivée → poids 15% conservé sans penalité (score artificiel)
- [R4-PERC-7] Composite V2 jamais activé par défaut (déjà connu R3)

---

## Round 5 — TERMINÉ (4 mai 2026)

5 agents (DB integrity, crash recovery, stress 10k, bundle analysis, config schema).

### Findings nouveaux Round 5 (consolidés)

#### Database (R5-DB)
- [R5-DB-1] FK déclarées sans ON DELETE CASCADE/RESTRICT → orphelins possibles
- [R5-DB-2] PRAGMA optimize au shutdown manquant (fragmentation DB long-terme)
- [R5-DB-3] PRAGMA integrity_check au boot manquant (corruption silencieuse)

#### Crash recovery (R5-CRASH)
- [R5-CRASH-1] Runs RUNNING orphelins au boot (pas de cleanup auto, run zombie)
- [R5-CRASH-2] FFmpeg subprocess zombies si crash mid-perceptual (pas atexit cleanup)
- [R5-CRASH-3] Tray icon Win32 orphelin si crash pywebview (atexit manquant)
- [R5-CRASH-4] Recovery UI manquante au boot (notif center signale mais pas modal)

#### Stress / scale (R5-STRESS)
- [R5-STRESS-1] Probe 10k films mono-thread = 7.6h (parallelisation à confirmer)
- [R5-STRESS-2] UI library.js non virtualisée (10k rows = freeze 5-10s)
- [R5-STRESS-3] _emitted_insight_codes set sans cap (R3 connue - growth illimité)
- [R5-STRESS-4] TMDb cache sans TTL/purge (orphelins après 1 an)
- [R5-STRESS-5] Perceptual 10k films = 14 jours mono-thread (parallelism unclear)

#### Bundle (R5-BUNDLE)
- [R5-BUNDLE-1] **Manrope-Variable.ttf duplicate** (162 KB × 2 = web/fonts + web/dashboard/fonts)
- [R5-BUNDLE-2] CSS legacy ~80 KB dead code (web/styles.css 60% utilisé)
- [R5-BUNDLE-3] themes.css duplication 80% web/themes.css vs shared/themes.css

#### Configuration (R5-CFG)
- [R5-CFG-1] **rest_api_token longueur min NON enforced** (security hole)
- [R5-CFG-2] settings.json write sans atomic lock (race condition)
- [R5-CFG-3] URL scheme http/https NON validated
- [R5-CFG-4] Interdépendances NON validées (jellyfin_enabled+url="", etc.)
- [R5-CFG-5] Long paths Windows >260 chars NON validés
- [R5-CFG-6] Pas de schema_version dans settings.json
- [R5-CFG-7] CORS origin sans validation

---

## GRAND FIX — appliqué (4 mai 2026)

10 fixes appliqués en chaîne après Round 5 :

| ID Fix | Fichier:ligne | Description | Findings résolus |
|---|---|---|---|
| FIX-1 | `notify_service.py:34-141` | start_drain_timer Timer auto-relancable 0.5s + atexit shutdown | CRIT-1 (drain_queue jamais appelée) |
| FIX-2 | `qij.js:901` | tabFromHash prioritaire sur opts.tab | CRIT-2 (?tab parsing) |
| FIX-3 | `qij.js:489-501` | Jellyfin sync passe lastRunId | CRIT-3 (sync sans run_id) |
| FIX-4 | `index.html:121-127` | Sections view-runs/view-review supprimées | CRIT-5 (routes ghost) |
| FIX-5 | `notifications_support.py:230-247` | _emitted_insight_codes cap 10000 + clear auto | R5-MEM-3 (set unbounded) |
| FIX-6 | `watcher.py:156-180` | _trigger_scan pré-valide is_dir_accessible | CRIT-6 (NAS déconnecté = scan auto) |
| FIX-7 | `app.py:498-512` | atexit.register notify.shutdown + start_drain_timer | R5-CRASH-3 (tray orphelin) |
| FIX-8 | `runtime_support.py:103-127` | Cleanup runs orphelins RUNNING au boot | R5-CRASH-1 (runs zombie) |
| FIX-9 | `app.js:11-37` | window.onerror + unhandledrejection global banner | H1 (white screen) |
| FIX-10 | `settings.js:914-942` | _scheduleSave error feedback UI rouge | H5 (silent save error) |

**Tests post-fix** : 55+27 tests passés, 0 régression. Build .exe final = 50.07 MB.

### Findings non corrigés (reportés v7.7+)

#### Critiques pas urgents
- [R5-DB-1] FK ON DELETE CASCADE/RESTRICT (impact migration DB longue)
- [R5-PERC-1-7] Perceptual edge cases (composite V2 inactif, ffmpeg zombies, LPIPS fallback)
- [CRIT-4] CVE bumps urllib3>=2.6.0 + pyinstaller>=6.10.0 (requiert validation upstream)

#### High polish (UX dégradée mais pas bloquant)
- H2 Race Radarr upgrade buttons setTimeout 100ms (cosmétique)
- H3 XSS m.year non échappé (faible risque, year=int backend)
- H4 Race parallel mount tabs QIJ (rare en usage normal)
- H6 Régression table runs perd tri (UX dégradée mais fonctionnel)
- H7 Tests E2E #qualityContent etc. (à mettre à jour)
- H8 Polling stale container DOM detach (mineur)
- H9 Hidden imports perceptual incomplets (à confirmer)
- H10 ARIA aria-live + focus trap (gros chantier accessibilité)
- H11 font-display:swap manquant (cosmétique 0-3s FOIT)
- H12 Event listener leaks (1-3 MB/8h, accepté)
- H13 4× get_settings au boot (perf mineure)

#### i18n (verrouillé FR)
- [R4-I18N-1-5] 250+ strings FR hardcodées, infra absente (8-12j de travail si l'app reste FR-only c'est OK)

#### Documentation
- [R4-DOC-1] CLAUDE.md à jour (98 endpoints vs 33, 23 fichiers >500L vs 6)
- [R4-DOC-2] docs/api/ENDPOINTS.md
- [R4-DOC-3] docs/MANUAL.md user manual
- [R4-DOC-4] docs/TROUBLESHOOTING.md
- [R4-DOC-5] architecture.mmd diagram
- [R4-DOC-6] .env.example, settings.json.example

#### Stress / scale (acceptable usage normal <1000 films)
- [R5-STRESS-2] UI library.js virtualisation 10k rows
- [R5-STRESS-5] Perceptual 14j mono-thread sur 10k

---

## Round 6+ — futur si nécessaire

- Build reproductible pinned versions
- Code coverage par module
- OpenAPI spec validation strict
- Tests E2E updates
- Backup/restore drill end-to-end
- Plan i18n EN
- Documentation user manual + troubleshooting

---

## Round 5+ — à venir si nécessaire

Axes restants envisagés :
- Database integrity (FK, indexes, EXPLAIN QUERY PLAN)
- Stress backend long-running (24h continuous scan)
- Comportement crash recovery (kill -9 mid-apply)
- Internationalisation timezones (UTC vs local)
- Build reproductible (pinned versions)
- Code coverage par module (modules critiques < 80%)
- Frontend dependency tree (peuf de poids JS hors composants v5)
- Frontend bundle size analysis
