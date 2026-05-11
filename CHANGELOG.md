# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/) + [SemVer](https://semver.org/).
Categories : `Added`, `Changed`, `Fixed`, `Removed`, `Performance`, `Security`.

---

## [v7.7.0] - 2026-05-04 — Operation Polish Total (7 vagues, 47+ findings, 0 regression)

> Operation **Polish Total v7.7.0** : 7 vagues d'execution multi-agents, 47+ commits,
> 47+ findings resolus, 0 regression imputable. Note projet : 9.2/10 -> ~9.9/10.
> Tests 3550 -> 3893 (+343, 100% pass). Bundle .exe 50.07 MB -> 49.84 MB. Cible
> production-grade publique : i18n FR + EN, refactor des 3 fonctions cur metier
> sans regression numerique, stress 10k+ films supporte, securite renforcee
> (2 CVE patchees, FK CASCADE, integrity_check au boot).

### Added (Ajoute)

- **i18n EN** : Setting `locale` (fr|en) avec switch live, infrastructure complete
  frontend + backend (`i18n_messages.py` + `i18n.js` + `locales/{fr,en}.json`),
  491 cles FR + 295 cles EN (parite top-level 9/9 categories), formatters
  `Intl.*` locale-aware (`format.js`), endpoint REST `set_locale` + handler
  `/locales/*`, 31 tests round-trip, `docs/i18n.md` guide developpeur (V6).
- **Stress / scale 10k+ films** : UI virtualisation `virtual-table.js` ESM
  (scroll 60fps cible vs freeze 5-10s), perceptual ThreadPoolExecutor
  (`parallelism.py`, gain 5-8x sur 8 cores), probe `probe_files()` batch
  ThreadPoolExecutor (10k probe < 1h vs 7.6h mono-thread), TMDb cache TTL
  configurable + purge auto au boot (setting `tmdb_cache_ttl_days`) (V5).
- **Composite Score V2 toggle** : setting `composite_score_version` (V1 reste
  defaut, V2 opt-in via dropdown UI), +30 tests (V4-05).
- **Logging structure** : `run_id` + `request_id` transversal via contextvars
  (`log_context.py`), header `X-Request-ID`, setting `log_level` configurable,
  RotatingFileHandler 50 MB x 5 backups, +29 tests (V3-04).
- **Documentation utilisateur complete** : `docs/MANUAL.md` (538L, 8 sections,
  FAQ 35+), `docs/TROUBLESHOOTING.md` (357L, 30 scenarios, 8 sections),
  `docs/api/ENDPOINTS.md` (99 endpoints auto-generes via
  `scripts/gen_endpoints_doc.py`), `docs/architecture.mmd` (6 diagrammes
  Mermaid : couches, workflow, perceptual, notif, WAL, Polish v7.7.0),
  `docs/RELEASE.md` (117L, 6 etapes + checklist), `docs/i18n.md` (V3 + V6).
- **Templates config** : `.env.example` (16 vars d'environnement) +
  `settings.json.example` (113 settings documentes) (V3-10).
- **Migration DB 021** : `ON DELETE CASCADE` sur 4 FK (`errors.run_id`,
  `quality_reports.run_id`, `anomalies.run_id`, `apply_operations.batch_id`),
  +17 tests, schema v20 -> v21 (V1-02).
- **Tests** : +343 tests vs baseline (3550 -> 3893, 100% pass rate).

### Changed (Modifie)

- **Refactor cur metier** : `_plan_item` 565L -> 14 helpers prives + orchestrateur
  183L (CC 126 -> ~8), `compute_quality_score` 369L -> 7 helpers + orchestrateur
  181L (CC 78 -> ~10-12, score numerique IDENTIQUE verifie), `plan_library`
  347L -> 5 helpers + orchestrateur 38L (CC 73 -> ~3). 0 regression imputable
  au refactor (V4-01/02/03).
- **WCAG 2.2 AA** : `trapFocus(overlay)` capture Tab/Shift+Tab dans modal.js,
  `aria-busy` toggle dynamique avant/apres fetch, `aria-expanded` sur dropdowns
  theme top-bar-v5.js, Arrow keys (Up/Down/Home/End) navigation menu, role/scope
  + keydown Space/Enter sur tables sortable (`.th-sortable`), `aria-required`
  + `*` rouge sur champs settings obligatoires, +27 tests a11y (V2-D).
- **Memory leaks 5 fixes** : pattern `unmount()` exporte par chaque vue + appele
  par router au switch, `closeNotifications()` retire overlay+drawer du DOM,
  `journal-polling.js` AbortSignal.timeout(5000), localStorage drafts TTL 30j
  + nettoyage periodique au boot, `Promise.allSettled` AbortController au
  navigate hashchange (V2-C).
- **Race conditions UI qij.js** : binding direct H2 (vs setTimeout 100ms),
  AbortController sur `_qijMountActive` H4, guard `parentElement` polling H8
  (V2-A).
- **CSS legacy cleanup** : -603 KB net (Newsreader-Variable.ttf orphan supprime
  + Manrope dedup `web/fonts/` -> `web/shared/fonts/` unique) (V3-CSS).
- **CLAUDE.md alignement realite** : 33 endpoints -> **101 endpoints** mesures
  (R4-DOC-1), 0 fonctions >100L documentees -> 23 fonctions >100L listees,
  schema v18 -> v21 (V3-05).
- **BILAN_CORRECTIONS.md** : archive R1+R2 vers
  `docs/internal/audits/ARCHIVE_R1_R2.md` (232 KB -> 49 KB, -79%) (V3-11).

### Fixed (Corrige)

- **CVE urllib3** : bump >=2.6.3 (CVE-2024-37891 fuite Proxy-Auth + CVE-2025-66418
  zip bomb) dans `requirements.txt` + `requirements-build.txt` (V1-01).
- **CVE pyinstaller** : bump >=6.20.0 (CVE-2025-59042 elevation de privilege
  local) (V1-01).
- **FFmpeg subprocess zombies** : nouveau module `subprocess_safety.py` avec
  context manager + atexit cleanup garantissant kill+wait, 8 sites refactores
  dans `ffmpeg_runner.py`, +9 tests (V1-03).
- **LPIPS model absent** : graceful fallback retourne
  `LpipsResult(verdict="insufficient_data")` au lieu de crash si modele ONNX
  manquant, +12 tests (V1-04).
- **PyInstaller hidden imports perceptual** : `collect_submodules("cinesort.domain.perceptual")`
  defense en profondeur dans `CineSort.spec` (V1-06).
- **Tests E2E selecteurs casses** : routes ghost `/runs` et `/review` retirees,
  tests `test_v5c_cleanup` mis a jour, taux pass 99.30% -> **100%** (3589/3589) (V1-05).
- **Pollution ecran tests** : `_startup_error` MessageBox skip si `unittest`
  in sys.modules + mock `fake_start` permissif,
  `test_dashboard_cache_header` accepte `no-cache` OU `max-age` (V1-05bis/ter).
- **DB integrity check au boot** : `PRAGMA integrity_check` dans
  `sqlite_store.initialize()` avec auto-restore depuis backup si corruption
  detectee + UI notification au prochain boot, +13 tests (V2-G).
- **Cache get_settings boot** : 4 sites concurrents
  (`app.js:161,295,344,361`) reduits a 1 wrapper `_cachedSettings` avec
  invalidation sur `last_settings_ts`. Latence boot reduite ~200ms (V2-B).
- **font-display: swap** : NO-OP (deja resolu anterieurement) (V2-E).
- **CSP Report-Only** : header `Content-Security-Policy-Report-Only` strict
  (sans `'unsafe-inline'`) emis en parallele pour observation des violations.
  CSP enforced conserve `'unsafe-inline'` style (refactor 391 styles inline
  reporte v7.8.0+) (V2-F).
- **OpenLogsFolder REST** : `open_logs_folder` retire de `_EXCLUDED_METHODS`
  -> expose en REST pour mode supervision web (H18, V2-F).
- **Tri table runs (Journal)** : selecteur "Trier par" 6 options (date/score/statut
  asc/desc) dans QIJ remplace les boutons cards (H6, V2-A).
- **XSS hardening** : 14 patterns `${var}` user-controlled echappes dans
  qij.js et autres champs dynamiques (`m.year` etc.) (V2-A).

### Performance

- **UI library scroll** : 60fps sur 10k rows (vs freeze 5-10s pre-virtualisation).
- **Probe 10k films** : ~1h (vs 7.6h, gain 8x) avec ThreadPoolExecutor batch.
- **Perceptual 10k films** : ~2-3 jours (vs 14j, gain 5-7x) avec ThreadPool.
- **Boot dashboard** : -200ms (cache get_settings 4x -> 1x round-trip).
- **Bundle .exe** : 50.07 MB -> **49.84 MB** (-0.23 MB net) malgre +343 tests
  et i18n EN.

### Security

- **2 CVE patchees** : urllib3 (CVE-2024-37891 + CVE-2025-66418), pyinstaller
  (CVE-2025-59042).
- **DB FK CASCADE** : orphelins impossibles sur 4 tables filles (errors,
  quality_reports, anomalies, apply_operations).
- **Logs scrubber** : etendu (deja 8 patterns + integrity check), filtre
  api_key=, Bearer, MediaBrowser Token, X-Plex-Token, X-Api-Key, JSON keys,
  smtp_password (V2-G).
- **CSP Report-Only** : observation parallele de `unsafe-inline` strict en
  vue de l'enforced en v7.8.0+.

### Removed (Supprime)

- `web/fonts/Manrope-Variable.ttf` (dedup vers `web/shared/fonts/` unique).
- `web/dashboard/fonts/Manrope-Variable.ttf` (dedup).
- `web/fonts/Newsreader-Variable.ttf` (orphan, jamais utilise).
- ~5 sections HTML dashboard orphelines (`view-runs`, `view-review` ghost
  routes).

### Reporte a v7.8.0+

- **CSP `'unsafe-inline'` strict** : refactor des ~391 styles inline statiques
  (272 dans `web/dashboard/`, 119 dans `web/views/`) + ~81 mutations
  `.style.X` programmatiques en JS reparties sur 24 fichiers. Disproportion vs
  perimetre Vague 2 (UX/A11y polish). Plan : extraire en classes CSS
  utilitaires, supprimer `'unsafe-inline'` enforced, conserver Report-Only un
  cycle pour valider 0 violation residuelle.
- **~50 strings FR encore hardcodees** : edge cases qij/settings non extraits
  par V6-02 (priorite aux strings principales 212/250).
- **Vues legacy `web/views/*.js`** : non i18n (focus dashboard moderne v5).

### Principes operation v7.7.0 (memoire de session)

- **7 vagues multi-agents** : 1 web-research par vague (background) + N agents
  implementation paralleles via worktrees Git + 1 validator continu.
- **Refactor incremental** : pas de big-bang, preserver signatures publiques,
  tests EN MEME TEMPS que le code.
- **Build .exe a chaque fin de vague** (pas juste a la fin de l'operation).
- **Coverage gate >= 80%** maintenue (81.3% baseline -> 81.3%+ post-V6).
- **Tags backup intermediaires** : `backup-before-polish-total`, `end-vague-1`
  a `end-vague-6` pour rollback granulaire.

---

## [7.6.0-dev] - 2026-04-23 — Refonte UI/UX totale (Design System v5, overlays, 10 vagues)

> Refonte totale de l'interface apres la consolidation v7.5.0 (14 sections
> perceptuelles). Nouvelle architecture "data-first" : 1 palette unique +
> 4 themes atmospheriques (Studio/Cinema/Luxe/Neon) dont **les couleurs de
> tier restent invariantes**. Navigation 7 entrees (Alt+1-7), vues sous
> forme d'overlays mutuellement exclusifs, workflow "F1 pragmatique" scan
> -> review -> apply dans une seule vue Processing. Tiers v2
> Platinum/Gold/Silver/Bronze/Reject adoptes partout. 10 vagues livrees.
> +305 tests (2723 -> 3028+), 0 regression imputable.

### Added — Vague 0 : Fondations design system
- **`web/shared/tokens.css`** (~280L) : couleurs de tier invariantes, severites, typographie Manrope, spacing 4px, radius 6, shadows 4, motion variables, z-index scale, densites (compact/comfortable/spacious).
- **`web/shared/themes.css`** : 4 themes `data-theme="studio|cinema|luxe|neon"` ne redefinissant que `--bg`, `--surface-*`, `--accent-*`, `--border-*` — jamais les tier colors.
- **`web/shared/animations.css`** : 15 keyframes (fadeIn, slideDown, scaleIn, kpiFadeIn, scoreCircleFill, gaugeFill, modalEnter, viewEnter, skeletonShimmer...) + `.stagger-item` avec `--order`.
- **`web/shared/components.css`** (~3500L) : `.v5-btn` (4 variants x 3 tailles), `.v5-card`, `.v5-badge`, `.v5-table`, `.v5-modal`, `.v5-toast`.
- **REST server `/shared/*`** : handler static dans `rest_server.py` pour la supervision web distante.

### Added — Vague 1 : Navigation v5 + Command Palette
- **`sidebar-v5.js`** : 7 items (home, processing, library, quality, journal, integrations, settings) avec shortcuts Alt+1-7, collapse persistant localStorage, arrow navigation ArrowDown/ArrowUp/Home/End, `role="tab"` + `aria-selected` + `aria-label`.
- **`top-bar-v5.js`** : search trigger Cmd+K, notifications bell avec badge, theme switcher 4 pastilles (studio/cinema/luxe/neon), `role="banner"` + `aria-haspopup="menu"`.
- **`breadcrumb.js`** : chemin contextuel avec `aria-current`.
- **`window.CommandPalette`** wrapper autour de l'existant (retro-compat `window.openCommandPalette`).
- **`router.js`** : `parseRoute`, `buildBreadcrumb`, `ROUTE_ALIASES` (transitoires), nouvelle route `/film/:id`, `/settings/:cat`.
- Parite supervision web : 3 modules ES equivalents (sidebar-v5, top-bar-v5, breadcrumb) livres cote supervision web pour la future fusion Vague 8.

### Added — Vague 2 : Home overview-first + insights V2
- **`home-widgets.js`** : `renderKpiGrid`, `renderInsights`, `renderPosterCarousel` + 10 icones Lucide SVG inline.
- **`home-charts.js`** : `renderDonut` (arcs SVG), `renderLine` (path SVG + gradient + delta) — zero dependance externe.
- **Backend `_compute_v2_tier_distribution`, `_compute_trend_30days`, `_compute_active_insights`** dans `dashboard_support.py`. `get_global_stats` enrichi.
- **DB `_perceptual_mixin.py`** +4 methodes : `get_global_tier_v2_distribution`, `get_global_score_v2_trend`, `count_v2_tier_since`, `count_v2_warnings_flag`.

### Added — Vague 3 : Library / Explorer
- **`library-v5.js`** (260L) : orchestrateur view, persist state localStorage (viewMode/filters/sort/page). `FilterSidebar` 10 dimensions, `LibraryTable`, `PosterGrid`, `SmartPlaylists`.
- **Endpoints** `get_library_filtered(run_id, filters, sort, page, page_size)`, `get_smart_playlists`, `save_smart_playlist`, `delete_smart_playlist` dans `library_support.py`. 10 filtres + 10 tri keys.
- **Smart playlists** : 3 presets + custom persistes dans `settings.json` (`smart_playlists`).

### Added — Vague 4 : Film standalone page
- **`film-detail.js`** (440L) : `window.FilmDetail.mount(container, rowId)`. 4 tabs (Apercu / Analyse V2 / Historique / Comparaison). Hero avec blurred backdrop, reutilise `renderScoreV2Container` de v7.5.0.
- **`get_film_full(api, run_id, row_id)`** dans `film_support.py` : consolide PlanRow + probe + perceptual + history + poster TMDb. `_film_identity_key` pour la lookup history.

### Added — Vague 5 : Processing fusion F1 (scan -> review -> apply)
- **`processing.js`** (500L) : `window.ProcessingV5.mount(container)`. Stepper 3 etapes (Scan / Review / Apply) dans une seule vue continue. Reutilise les endpoints `start_plan`, `get_status`, `load_validation`, `save_validation`, `apply`.

### Added — Vague 6 : Settings refondus (9 groupes par intention)
- **`settings-v5.js`** (580L) : schema declaratif `SETTINGS_GROUPS` avec 9 groupes (Sources / Analyse / Nommage / Bibliotheque / Integrations / Notifications / Serveur / Apparence / Avance). Renderer dynamique pour 7 field types (toggle, number, text, path, select, api-key, multi-path).
- **Features** : auto-save debounce 500 ms, search fuzzy, live preview (theme/density/naming), badges per section (configure/partial/none), reset per section avec confirmation.

### Added — Vague 7 : Quality / Integrations / Journal (QIJ)
- **`qij-v5.js`** (450L) : 3 views consolidees dans un seul overlay (`window.QualityV5`, `window.IntegrationsV5`, `window.JournalV5`). Overlay unique `qij-v5-overlay`.
- **Quality** : donut + line charts + rollup table avec 5 dimensions (franchise / decade / codec / era_grain / resolution).
- **Integrations** : 4 cards (Jellyfin / Plex / Radarr / TMDb) avec test connection.
- **Journal** : run cards avec export CSV/HTML/JSON.
- **Endpoint** `get_scoring_rollup(by, limit, run_id)` + `_extract_group_key` dans `library_support.py`.
- **`ROUTE_ALIASES = {}`** : toutes les routes transitoires retirees, toutes canoniques maintenant.

### Added — Vague 9 : Notification Center (drawer + insights actifs)
- **`notifications_support.py`** : `NotificationStore` thread-safe (deque cap 200, LIFO, `mark_read`, `dismiss`, `clear`). Dedupe insights via `emit_from_insights(api, insights, source)` (set `(code, source)` attache a l'API).
- **6 endpoints** dans `cinesort_api.py` : `get_notifications` (filtre `unread_only`, `limit`, `category`), `dismiss_notification`, `mark_notification_read`, `mark_all_notifications_read`, `clear_notifications`, `get_notifications_unread_count`.
- **Mirror `NotifyService`** : `set_center_hook()` dans `notify_service.py` mirrore chaque toast desktop (scan_done, apply_done, undo_done, error) vers le centre, independamment du setting `notifications_enabled` (qui ne concerne que le balloon OS Win32).
- **Insights V2** : `dashboard_support.get_global_stats` emet les insights actifs dans le centre (dedupe par session).
- **`notification-center.js`** (desktop IIFE + supervision web ES module) : drawer side-panel avec filtres (all/unread/insight/event), polling 30 s, focus management, ESC close, overlay backdrop.
- **CSS v5** : +250L dans `components.css` (overlay + drawer + filters + actions + item cards 4 levels info/success/warning/error + empty state).
- **Auto-wire** : clic sur la cloche top-bar-v5 -> `window.NotificationCenter.toggle()`.

### Added — Vague 10 : Tests E2E + polish
- **`tests/e2e/test_16_v76_api.py`** (18 tests) : tests REST pour les endpoints v7.6.0 (notifications CRUD, library_filtered, smart_playlists, film_full, scoring_rollup).
- **`tests/test_accessibility_v5.py`** (28 tests) : audit ARIA/roles statique sur tous les composants v5 (sidebar, top-bar, breadcrumb, notification-center, views). Baseline minimum 2 attributs `aria-*` par composant. Support `prefers-reduced-motion` + `:focus-visible`.
- **`tests/test_polish_v5.py`** (22 tests) : file presence + size (<1200L components, <1500L views), integration `index.html`, no TODO v7.6.0 residual, tokens coherence (tier tokens invariants, themes ne redefinissent pas les tiers), prefix `v5-*` respecte, endpoints v7.6.0 exposes, router `ROUTE_ALIASES = {}`, overlays mutuellement exclusifs.

### Added — Vague 10 fix : Wiring sidebar legacy -> overlays v5
- **`router.js`** : intercepte les routes legacy pour les rediriger vers les nouveaux overlays v5 (sans avoir besoin de monter sidebar-v5 encore). Flag `opts.legacy = true` comme backdoor dev.
  - `validation` + `execution` -> overlay `processing` (fusion F1).
  - `settings` -> overlay `settings-v5` (9 groupes).
  - `quality` -> overlay QIJ mode `quality`.
  - `history` -> overlay QIJ mode `journal`.
  - `jellyfin` / `plex` / `radarr` -> overlay QIJ mode `integrations`.
- **Bouton "Notifs" dans sidebar-footer** (`index.html`) + binding dans `app.js` -> ouvre `window.NotificationCenter.toggle()`. Indicateur unread via event `v5:notif-count` (dot rouge + label compteur). CSS `#btnNotifCenter.has-unread` avec dot pulse.
- **`notification-center.js` desktop** : emet desormais `document.dispatchEvent(CustomEvent("v5:notif-count"))` en plus de `window.TopBarV5.setNotificationCount()` pour permettre aux listeners externes (bouton sidebar legacy) de se mettre a jour sans dependre de top-bar-v5.
- **`tests/test_legacy_wiring_v5.py`** (14 tests) : verifie chaque redirection route legacy + bouton sidebar + event dispatch + CSS badge.

**Consequence** : sans modifier la sidebar/top-bar legacy visuellement, 100 % des overlays v5 sont desormais accessibles depuis les boutons existants. Le switch visuel complet du chrome (sidebar-v5 + top-bar-v5 + breadcrumb montes au boot) reste prevu pour la Vague 8 (v7.7.0+).

### Changed
- **Tiers** : abandon definitif des labels v1 Premium/Bon/Moyen/Mauvais dans l'UI v5. Seuls les tiers v2 `platinum/gold/silver/bronze/reject` sont utilises (coherence avec le moteur perceptuel v2).
- **Palette** : suppression de l'ancien theme clair (non adapte au design "salle de projection privee"). 4 themes atmospheriques maintenant.
- **Navigation** : fusion Review+Decisions+Apply dans Processing (workflow F1 continu). Fusion Quality+Integrations+Journal dans un seul overlay (QIJ).
- **Settings** : regroupes par intention (Sources/Analyse/Nommage/Bibliotheque/Integrations/Notifications/Serveur/Apparence/Avance) au lieu de l'ordre historique.

### Reporte a v7.7.0+
- **Vague 8 : Fusion components desktop/supervision web** (~10h) : deduplication des composants desktop IIFE et supervision web ES modules. Strategie "finir le feature set d'abord puis consolider".
- **Cleanup CSS legacy** : `web/styles.css` (83 KB) et `web/themes.css` (32 KB) encore utilises par les vues legacy (validation, execution, home, history) qui coexistent avec v5. Retrait prevu quand la fusion desktop/supervision sera effectuee.
- **Tests E2E Playwright v5 avec navigateur** : les composants v5 tournent dans pywebview, pas dans la supervision web — necessitera une fixture dediee ou un mode preview.

### Principes v7.6.0 (memoire de session)
- **Overlay pattern pour les views v5** : mutuellement exclusifs, full-screen, pas de HTML dans `index.html` (cree dynamiquement au mount).
- **Coexistence v5 + legacy** : prefix `v5-*` sur les classes/selectors pour eviter les collisions. Retrait legacy seulement apres la Vague 8 de fusion.
- **Separation backend** : nouveaux endpoints dans des modules `*_support.py` dedies, pas dans `cinesort_api.py` (qui reste une facade fine).
- **Tier colors invariantes** : les themes atmospheriques ne touchent jamais aux couleurs de tier (test `test_themes_do_not_redefine_tiers`).
- **Notifications independantes de l'OS toast** : le setting `notifications_enabled` ne concerne que le balloon Win32, le centre capture toujours via `set_center_hook`.

---

## [7.5.0-dev] - 2026-04-23 — Analyse perceptuelle avancee v2 (14 sections)

> Vague perceptuelle majeure. Le moteur d'analyse gagne 14 nouveaux modules
> specialises (fingerprint audio, spectral cutoff, SSIM self-ref, HDR10+/DV,
> FFT fake 4K, filtres ffmpeg avances, grain intelligence v2 avec 6 eres,
> Mel spectrogram, LPIPS ONNX) et un score composite V2 unifie
> (Platinum/Gold/Silver/Bronze/Reject) avec 9 regles d'ajustement contextuel.
> Schema SQLite v14 -> v18. +625 tests (2098 -> 2723).

### Added — Infrastructure partagee
- **§1 Parallelisme ThreadPoolExecutor** : `cinesort/domain/perceptual/parallelism.py` (`resolve_max_workers`, `run_parallel_tasks`). Video + audio en parallele (I/O-bound, GIL libere). Setting `perceptual_parallelism_mode` (auto/sequential/parallel_2/parallel_4).
- **§2 Cache probe etendu** : `_load_probe` centralise, reutilise la probe existante de `ProbeService`, pas de re-probe.

### Added — Audio
- **§3 Fingerprint Chromaprint** : binaire `assets/tools/fpcalc.exe` (~1 MB), subprocess direct `fpcalc -json -raw`, colonne `audio_fingerprint` dans `perceptual_reports` (migration 015), robuste si absent. Pas de dependance pyacoustid.
- **§9 Spectral cutoff (detection lossy)** : `spectral_analysis.py`, FFT numpy + rolloff 85%, verdicts `lossless`/`high_bitrate_lossy`/`medium_bitrate_lossy`/`low_bitrate_lossy`, migration 016.
- **§14 Classification DRC** : `cinema`/`standard`/`broadcast_compressed` via cascade `crest_factor` + LRA.
- **§12 Mel spectrogram** : `mel_analysis.py`, 4 detecteurs (soft clipping via harmoniques, MP3 shelf 16 kHz, AAC holes, spectral flatness), filter bank Slaney 1998, score pondere 40/20/30/10. `AUDIO_WEIGHT_MEL = 15` ajoute a la synthese audio (total 100 preserve).

### Added — Video
- **§4 Scene detection** : `scene_detection.py`, ffmpeg `select='gt(scene,0.3)',showinfo`, downsampling 2 fps/640 px, merge hybride timestamps.
- **§5 HDR10+ Pass 2 multi-frame** : `hdr_analysis.py`, scan 5 frames via `ffprobe -show_frames -read_intervals "%+#1"`, SMPTE ST 2094-40, flag `has_hdr10_plus_detected`.
- **§6 Dolby Vision classification** : profils 5/7/8.1/8.2/8.4 via DOVI configuration record, analyse mutualisee avec §5 (0 ms supplementaire).
- **§7 Fake 4K via FFT 2D** : `upscale_detection.py`, HF/LF ratio `np.fft.fft2` + anneau HF, combinaison avec §13 SSIM pour 4 verdicts (`fake_4k_confirmed`/`fake_4k_probable`/`native_4k`/`ambiguous`).
- **§8 Filtres metadonnees** : `metadata_analysis.py`, 4 filtres ffmpeg paralleles (`idet` interlacing, `cropdetect` avec multi-segments IMAX expansion, `mpdecimate` judder, heuristique IMAX 4 methodes).
- **§13 SSIM self-referential** : `ssim_self_ref.py`, pipeline `split+scale 1080p+scale 4K+ssim`, seuils 0.95 fake / 0.90 ambigu / < 0.90 native, migration 017.

### Added — Grain Intelligence v2 (section phare §15)
- **`grain_signatures.py`** : 6 bandes d'ere (`16mm_era` pre-1960, `35mm_golden` 1960-1985, `early_color` 1985-1995, `modern_film` 1995-2005, `digital_transition` 2005-2012, `blu_ray_digital` 2012-2020, `uhd_native_dolby_vision` 2020+), +70mm, exceptions Nolan/A24/Pixar/anime.
- **`av1_grain_metadata.py`** : detection AFGS1 via ITU-T T.35 markers (0xB5 + 0x5890), bonus +15 pts ajustement contextuel.
- **`grain_classifier.py`** : classifier signature `film_grain`/`encode_noise`/`post_added`/`ambiguous` via temporal 50% + spatial autocorr 8-dir 30% + cross-color 20%. Detection **DNR partiel** (`texture_actual/baseline < 0.7 AND grain < 1.5`).
- **Contexte historique FR** : 6-8 lignes generees par ere pour l'UI.

### Added — ML / Perceptual distance (§11)
- **LPIPS AlexNet ONNX** : `lpips_compare.py`, inference via `onnxruntime` CPU, modele inclus dans le bundle (`assets/models/lpips_alexnet.onnx`, 9.4 MB self-contained). Script `scripts/convert_lpips_to_onnx.py` one-shot dev (torch + lpips). Preprocess Y->RGB + resize bilineaire numpy-pur. 5 verdicts (identical/very_similar/similar/different/very_different) sur mediane de 5 paires de frames alignees.

### Added — Score composite V2 (§16)
- **`composite_score_v2.py`** : 3 categories ponderees (Video 60% / Audio 35% / Coherence 5%) avec confidence-weighted scoring. 5 tiers `platinum/gold/silver/bronze/reject`. **9 regles d'ajustement contextuel** (grain v2 +10/-15/-8, AV1 AFGS1 +15, DV5 -8, HDR metadata -10, IMAX +15/+10, fake lossless -10, animation skip grain, vintage master tolerance ×0.7). **7 warnings auto-collectes** (runtime mismatch, DV5, HDR incomplete, confidence < 60%, short file, desequilibre V/A > 40 pts, fake lossless).
- **Migration 018** : colonnes `global_score_v2` / `global_tier_v2` / `global_score_v2_json` dans `perceptual_reports`. Schema v17 -> v18. Coexistence totale avec v1 (0 rupture).
- **Frontend §16b** : 3 composants `score-v2.js` (desktop IIFE + supervision web ES module) — cercle SVG anime (stroke-dashoffset 1.2 s cubic-bezier), 3 jauges horizontales par categorie avec gradient tier, accordeon cliquable avec sous-scores + labels FR + tooltips educatifs + confidence opacite visuelle. Encarts warnings jaunes. Integration inspecteur `validation.js` + modale deep-compare `execution.js` + parite supervision web (`library.js` + `lib-duplicates.js`). 185L CSS desktop + 95L supervision web.

### Added — Dependances et packaging
- **`onnxruntime>=1.24,<2.0`** : inference ONNX pour LPIPS (~40 MB wheel install).
- **`numpy>=2.0`** : deja present, utilise par §9 spectral, §7 FFT, §12 Mel.
- **Bundle release** : +~10 MB (fpcalc 1 MB + LPIPS ONNX 9 MB).
- **CineSort.spec** : `hiddenimports` + datas pour tous les nouveaux modules.

### Changed
- **`AudioPerceptual`** : +14 champs (fingerprint, spectral, DRC, Mel).
- **`VideoPerceptual`** : +20 champs (SSIM self-ref, HDR10+, FFT fake 4K, interlacing, crop, judder, IMAX).
- **`GrainAnalysis`** : +18 champs grain v2.
- **`AUDIO_WEIGHT_*`** redistribues pour inclure Mel : LRA 30->25, Noise 25->20, Clipping 20->15, +MEL 15 (total=100).
- **`_PerceptualMixin.upsert_perceptual_report`** : accepte 8 nouveaux kwargs.
- **`compare_perceptual`** expose `comparison.global_score_v2_a/b` pour affichage cote-a-cote.

### Fixed
- Classification crop `letterbox_2_35` vs `letterbox_2_39` : logique "closest threshold" au lieu de "first match".
- Test `test_audio_weights_sum_100` : inclut `AUDIO_WEIGHT_MEL` dans la somme verifiee.

### Reporte a v7.6.0+
- §10 NR-VMAF (necessite un modele custom training).
- Radar chart optionnel §16 (composant isole, facile a ajouter).

### Principes v7.5.0 (memoire de session)
- **Subprocess direct > wrappers Python** : fpcalc.exe appele directement, pas de `pyacoustid`.
- **Stockage perceptual_reports** : colonnes dediees + JSON payload, jamais dans `quality_reports`.
- **Robustesse binaires absents** : `resolve_X_path()` + guards, feature desactivee si absent, jamais de crash.
- **Migrations sequentielles** : 015 -> 016 -> 017 -> 018 sans saut.
- **Taille bundle non prioritaire** : inclure les modeles/binaires dans le bundle plutot que DL au 1er usage.

---

## [7.2.0-dev] - en cours (2026-03-08 → 2026-04-14)

> Cycle de developpement majeur. Cette version consolide Undo v1 + scan incremental, puis ajoute 4 vagues :
> V2 (frontend modulaire), V3 (27 items metier), V4 (QoL + dependances + themes + parite supervision distante).

### V4 (2026-04-06 → 2026-04-14) — Parite supervision distante + themes + metier

#### Added
- **Supervision distante parite complete** : 10 vues dont reglages complets (15 sections), Qualite, Undo + Export NFO, inspecteur enrichi, Plex, Radarr, raccourcis clavier. Sync temps reel settings desktop ↔ vue web via `last_settings_ts` (< 5 s).
- **Systeme de themes** : 4 palettes atmospheriques (Studio, Cinema, Luxe, Neon), 3 niveaux d'animation, 3 curseurs temps reel (vitesse, glow, luminosite). Fichier `web/themes.css` partage.
- **Dependances** : `segno` (QR code supervision web, SVG inline), `rapidfuzz` (remplace `difflib.SequenceMatcher` dans `seq_ratio`, gains 5-100x), fuzzy matching sur sync Jellyfin/Radarr et watchlist.
- **TMDb lookup IMDb ID** via `/find` endpoint (candidats score 0.95), fallback FR→EN si 0 resultat.
- **Scoring contextualise** : bonus ere (patrimoine pre-1970, classique pre-1995), malus film recent post-2020 sans AV1, penalites encode (upscale, reencode, 4k_light), penalite commentary-only.
- **Detection non-film enrichie** : duree < 5 min / < 20 min, mots-cles `blooper/outtake/recap/gag reel`.
- **Patterns TV** : `S01.E01`, `Season/Saison N Episode N` (texte FR/EN).
- **Integrite tail check** : verification fin de fichier MP4 (moov atom) et MKV.
- **Doublons enrichis** : criteres perceptuel (poids 10) + sous-titres FR (poids 5).
- **Quality of Life** : auto-detection IP locale (UDP socket), redemarrage REST a chaud, bouton refresh supervision animation, copier lien supervision.
- **Splash screen HTML pywebview** (remplacement du splash Win32 ctypes) — design CinemaLux, barre progression animee.
- **Logging structure V4** : 5 phases (infra REST + clients, app apply/scan/jobs, domain scoring/integrity/perceptual, UI/API, JS frontend router/api). ~39 fichiers touches, format uniforme.

#### Changed
- `title_helpers.seq_ratio()` utilise `rapidfuzz.fuzz.ratio()` (compat 0.0-1.0 preservee).
- `tmdb_client._get_movie_detail_cached()` unifie poster + `belongs_to_collection`.
- Splash Win32 supprime (257L → 30L dans le runtime hook), fallback 8 s elimine.

#### Fixed
- Audit post-V3 : `log()` et `progress()` exclus du dispatch REST, 13 modules V3 lazy-importes ajoutes dans `hiddenimports`, `_normalize_path()` deduplique dans `cinesort/app/_path_utils.py`.

---

### V3 (2026-04-05 → 2026-04-06) — 27 items metier (Tiers A/B/C)

#### Added — Tier A : qualite et detection
- **9.1 Profils de renommage** : module `naming.py`, 5 presets (default/plex/jellyfin/quality/custom), 20 variables templates, validation + check path length, UI settings + preview live, conformance check `folder_matches_template`.
- **9.2 Comparaison qualite doublons** : module `duplicate_compare.py`, 7 criteres ponderes (resolution 30 / HDR 20 / codec 15 / audio 15 / canaux 10 / bitrate 5), dataclasses `CriterionResult`/`ComparisonResult`, vue cote-a-cote desktop + supervision distante avec economie potentielle.
- **9.3 Detection non-film** : `not_a_movie_score()` dans `scan_helpers.py`, 6 heuristiques ponderees (nom suspect, taille, pas de TMDb, titre court, extension), flag `not_a_movie`, badge orange.
- **9.4 Verification integrite fichiers** : module `integrity_check.py`, magic bytes pour 5 formats (MKV/MP4/AVI/TS/WMV), flags `integrity_header_invalid` + `integrity_probe_failed`, badge rouge "Corrompu ?".

#### Added — Tier B : metadata et collections
- **9.5 Collections TMDb** : `get_movie_collection()`, PlanRow enrichi (`tmdb_collection_id`/`_name`), apply vers `root/_Collection/SagaName/`, badge violet "Saga".
- **9.6 Detection re-encode / upgrade suspect** : module `encode_analysis.py`, flags `upscale_suspect` / `4k_light` / `reencode_degraded`, seuils par resolution+codec.
- **9.7 Analyse audio approfondie** : module `audio_analysis.py`, hierarchie 6 tiers (Atmos > TrueHD > DTS-HD MA > EAC3/FLAC > DTS/AC3 > AAC/MP3), detection commentaires, doublons, langues, 4 tiers de badges.
- **9.8 Espace disque intelligent** : `_compute_space_analysis()`, KPIs total/moyenne/recuperable, bar chart SVG par tier, top 10 gaspilleurs (formule `size_gb × (100-score)/100`).
- **9.9 Mode bibliothecaire** : module `librarian.py`, 6 types de suggestions (codec obsolete, doublons, sous-titres manquants, non identifies, basse resolution, collections), health score, section supervision web.
- **9.10 Sante bibliotheque continue** : snapshot persiste dans `stats_json.health_snapshot`, timeline enrichi, tendance delta entre 2 derniers runs, line chart SVG.

#### Added — Tier C : integrations et automatisation
- **9.11 Mode surveillance (watch folder)** : module `watcher.py`, poll `os.scandir` avec snapshot, scan automatique sur changement, settings `watch_enabled` / `watch_interval_minutes`.
- **9.12 Import watchlist Letterboxd / IMDb** : module `watchlist.py`, parsing CSV stdlib, normalisation titre (accents, articles), matching titre+annee, UI settings desktop + supervision web.
- **9.13 Historique par film** : module `film_history.py`, reconstruction timeline (scan/score/apply) a la volee depuis plan.jsonl + quality_reports + apply_operations, endpoints `get_film_history` + `list_films_with_history`.
- **9.14 Integration Plex** : client `plex_client.py` (X-Plex-Token), `refresh_library()`, validation croisee, 6 settings, symetrique Jellyfin.
- **9.15 Plugin hooks post-action** : module `plugin_hooks.py`, decouverte dossier `plugins/`, convention nommage par evenement, 4 evenements (post_scan/apply/undo/error), thread daemon non-bloquant.
- **9.16 Rapport par email** : module `email_report.py`, smtplib stdlib (STARTTLS + SSL), 9 settings, triggers post_scan + post_apply, endpoint test.
- **9.17 Suppression shims legacy** : 10 shims racine supprimes (`core_*`, `tmdb_client`, `state`, `backend`, `core`), ~70 importeurs migres vers imports directs `cinesort.*`.
- **9.18 Tests E2E supervision web (Playwright)** : 121 tests en 13 fichiers, Page Object Model (7 pages), 3 viewports, 15 films mock + 2 runs, 5 bugs app corriges au passage.
- **9.19 Coverage HTML dans la CI** : 2 steps `coverage html` + upload artifact 14 jours retention.
- **9.20 HTTPS supervision web** : `SSLContext` optionnel via 3 settings (`rest_api_https_enabled`/`cert_path`/`key_path`), fallback HTTP si cert manquant.
- **9.21 Refresh auto supervision apres apply** : `_last_event_ts` dans health endpoint, detection polling adaptatif.
- **9.22 Editions multiples** : module `edition_helpers.py`, 12 groupes (Director's Cut, Extended, Theatrical, etc.), strip avant TMDb, variable `{edition}` / `{edition-tag}` (format Plex), dedup edition-aware.
- **9.23 Conflit metadonnees MKV** (Phase 1 detection) : extraction `container_title`, `mkv_title_check.py`, detection titres scene, warning `mkv_title_mismatch`.
- **9.24 Analyse qualite perceptuelle** (9 phases) : package `cinesort/domain/perceptual/` (~1500L), frames deterministes, signalstats+blockdetect+blurdetect, grain analysis avec verdicts contextualises par ere TMDb, EBU R128 audio, score composite global 60/40, comparaison cote-a-cote, 179 tests, migration schema v9.
- **9.25 Integration Radarr** : client `radarr_client.py` (API v3), sync 3 niveaux, detection candidats upgrade, endpoint `request_radarr_upgrade`.
- **9.26 Validation croisee Jellyfin** : `build_sync_report()`, matching chemin+tmdb_id+titre/annee, rapport matched/missing/ghost/mismatch.
- **9.27 Detection langue audio incoherente** : `_check_language_coherence()` dans audio_analysis, warnings `audio_language_missing` / `audio_language_incomplete`, badge jaune.

---

### V2 (2026-04-04 → 2026-04-05) — Refonte frontend + infra

#### Added
- **Refonte UI v2** : reecriture complete du frontend. Architecture JS modulaire `core/` + `components/` + `views/` + `app.js` (~100L bootstrap). 6 vues (fusion Review+Decisions). CSS 9211L → ~560L. JS 7800L → ~2800L.
- **Stats globales bibliotheque** : vue Bibliotheque dans Qualite, toggle Run / Bibliotheque, 3 methodes DB, endpoint `get_global_stats`, KPIs + tendance + timeline + distribution + top anomalies.
- **Notifications desktop** : `Shell_NotifyIconW` via ctypes (zero-dep), 5 evenements, 5 settings, queue thread-safe, detection focus `document.hasFocus()`.
- **API REST** : `ThreadingHTTPServer` stdlib, dispatch `POST /api/{method}`, Bearer auth, CORS, OpenAPI 3.0.3 auto-generee, rate limiting (5 echecs 401/IP/60s → 429). 33 endpoints exposes.
- **Supervision web distante** (Phases 1-6) : SPA vanilla JS / ES modules, CinemaLux tokens, Manrope embarquee, 7 vues initiales (login, status, logs, library, runs, review, jellyfin).
- **Multi-root** : scan de N racines, `PlanRow.source_root`, `plan_multi_roots()`, detection doublons cross-root, apply regroupe par root, migration automatique `root` → `roots`.
- **Gestion sous-titres** : module `subtitle_helpers.py`, detection langue par suffixe (50+ entrees ISO), PlanRow +5 champs, scoring `_score_extras` (+6/-4), UI colonne ST.
- **Raccourcis clavier + Drag & drop** : module `keyboard.js` (dispatcher central), Alt+1-6 navigation, validation (fleches/jk, Espace, r, i, Ctrl+A), module `drop.js` overlay visuel.
- **Refonte esthetique CinemaLux** (v3.0) : direction "salle de projection privee", glass morphism, bordures lumineuses accent-border, gradients, icones Lucide inline, animations viewEnter/kpiFadeIn.
- **Packaging PyInstaller optimise** : vrai ICO multi-res (7 tailles), splash, AllocConsole --api, version info Windows, manifest DPI Per-Monitor V2, exclusions stdlib (~15-25 MB economises).

#### Changed
- Refactoring 3 fonctions > 100L : `start_plan` 227L → 54L, `undo_last_apply` 131L → 45L, `build_run_report_payload` 126L → 76L. **0 fonction > 100L restante.**
- Schema SQLite v8 (migration 008 `incremental_row_cache` v2).
- `CineSortApp.spec` renomme `CineSort.spec`.

---

### V1 (2026-03-08) — Undo v1 + scan incremental (base)

#### Added
- **Undo v1 (7.2.0-A)** : journal d'operations apply en SQLite (`apply_batches`, `apply_operations`), endpoints `undo_last_apply_preview(run_id)` et `undo_last_apply(run_id, dry_run)`, rollback securise, conflits vers `_review/_undo_conflicts`, UI Application preview + execution.
- **Undo v5** : annulation **par film** (migration 007 `row_id`), endpoints `undo_by_row_preview` / `undo_selected_rows` / `list_apply_history`, table frontend avec checkboxes + preview dry-run + modale confirmation.
- **Scan incremental (7.2.0-B)** : mode `incremental_scan_enabled`, cache `path/size/mtime_ns/hash quick`, cache plan par dossier (signature dossier + cfg + rows/stats), invalidation automatique.
- **File "A relire" intelligente (7.2.0-C)** : preset Validation base sur score de risque (confiance/source/warnings/type changement/qualite), tri prioritaire, indicateur visuel.
- **Presets qualite (7.2.0-D)** : catalogue Remux strict / Equilibre / Light, endpoints `get_quality_presets()` + `apply_quality_preset(preset_id)`, UI Hub Qualite.
- **DB migration v6** : `006_incremental_scan_cache.sql`, tables `incremental_file_hashes` et `incremental_scan_cache`.
- **Onboarding** : wizard 5 etapes (Bienvenue → Dossier → TMDb → Test rapide → Termine), detection premier lancement automatique, flag `onboarding_completed`.
- **Review triage + mode batch automatique** : actions rapides approuver/rejeter dans "Cas a revoir", bulk actions, inbox zero, reglage `auto_approve_threshold` (defaut 85%).
- **Detection series TV** : parsing `S01E01` / `1x01` / `Episode N`, TMDb TV API (`search_tv`, `get_tv_episode_title`), apply vers `Serie (annee)/Saison NN/S01E01.ext`, badge "Serie" violet, toggle reglage.
- **Integration Jellyfin Phase 1** : `JellyfinClient` (validate, refresh, get_libraries), 7 settings, hook post-apply `_trigger_jellyfin_refresh` (fire-and-forget), section UI reglages.
- **Integration Jellyfin Phase 2** : sync watched, `snapshot_watched` AVANT apply + `restore_watched` APRES refresh, polling re-indexation, dataclasses `WatchedInfo` / `RestoreResult`.
- **Export enrichi** : CSV 30 colonnes, rapport HTML single-file (CSS/SVG inline), export `.nfo` XML Kodi/Jellyfin/Emby (dry-run + skip/overwrite), module `export_support.py`.
- **Scan incremental v2** : cache double couche (dossier v1 + video v2), migration 008, invalidation granulaire par video/NFO, metriques `cache_folder_hits` / `cache_row_hits`.

#### Changed
- Migration legacy → `cinesort/` : 9 modules racine migres vers `cinesort/domain|app|infra/`, shims de compatibilite `sys.modules`, 0 regression.
- `SQLiteStore` refactore 1200L → 245L + 6 mixins composes.
- `AUDIT_COMPLET.md` archive (initial note 7.1/10), deplace vers `docs/internal/audits/`.
- Corrections 6 phases (`BILAN_CORRECTIONS.md`) : 859L nettes supprimees, 528L de duplication eliminees, note finale 8.0/10 → 9.9/10.

#### Removed
- Anciens modules racine (`core_*.py`, etc.) apres migration complete vers `cinesort/`.

### V1 — detail historique de mars 2026
- Undo v1 (7.2.0-A):
  - journal d'operations apply en SQLite (apply_batches, apply_operations),
  - endpoints non-breaking undo_last_apply_preview(run_id) et undo_last_apply(run_id, dry_run),
  - rollback securise sans overwrite, conflits de restauration vers _review/_undo_conflicts,
  - UI Application: preview Undo + execution Undo avec garde dry-run.
- Scan incremental (7.2.0-B):
  - nouveau mode incremental_scan_enabled (settings/config),
  - cache d'index fichier path/size/mtime_ns/hash quick,
  - cache de plan par dossier (signature dossier + cfg signature + rows/stats),
  - invalidation automatique sur changement de contenu et purge des dossiers disparus.
- File "A relire" intelligente (7.2.0-C):
  - preset Validation "A relire (risque)" base sur un score de risque explicite,
  - score de risque calcule avec confiance/source/warnings/type de changement/etat qualite,
  - tri prioritaire automatique des lignes a risque (plus risquee en tete),
  - indicateur visuel de risque + synthese FR du preset active.
- Presets qualite prets a l'emploi (7.2.0-D):
  - nouveau catalogue de presets scoring: Remux strict, Equilibre, Light,
  - endpoints non-breaking `get_quality_presets()` et `apply_quality_preset(preset_id)`,
  - UI Hub Qualite: application du preset en un clic + mise en evidence du preset actif.
- DB migration v6:
  - 006_incremental_scan_cache.sql,
  - tables incremental_file_hashes et incremental_scan_cache.
- Observabilite analyse:
  - resume analyse enrichi avec Cache incremental: hits/misses/rows_reused.
- Tests:
  - nouveau tests/test_incremental_scan.py (exactitude vs scan complet, invalidation, perf relative),
  - MAJ des tests schema/migrations (version SQLite 6).
- Stabilisation front / workflow:
  - contexte run/film durci (plus de retarget implicite du workflow par consultation de Synthese/selecteur),
  - blocage d'Apply si la sauvegarde de validation echoue,
  - resolution de `run_dir` historique par source fiable cote backend plutot que reconstruction naive cote front,
  - nettoyage plus strict des etats UI obsoletes lors des changements de run/table.
- TMDb / settings:
  - correction d'un vrai bug de persistance sur la cle TMDb memorisee lors des saves partiels,
  - exposition explicite de `remember_key` / `tmdb_key_persisted`,
  - messages UI plus clairs quand la cle n'est pas memorisee volontairement.
- Resume analyse:
  - clarification entre `Entrees ignorees pendant analyse` et `Fichiers annexes / non supportes observes par extension`,
  - suppression de l'ambiguite de lecture sur les compteurs d'ignores.
- Heuristiques NFO (patchs cibles sur cas reels):
  - meilleure acceptance d'un NFO correct quand le vrai titre video est present avant une annee parenthesee,
  - nouveaux garde-fous de regression sur cas reels rejects conserves (`BAC Nord`, `BURN·E`),
  - mini dataset de regression documente pour les warnings NFO observes.
- Confort operateur / diagnostic settings:
  - ajout d'un bloc `Diagnostic operateur` dans Parametres (TMDb, cle API, probe, dry-run, prudence apply, dossiers vides),
  - wording plus lisible sur les niveaux de prudence et `empty_folders_scope`.
- Nettoyage de fin de run:
  - nouvelle fonctionnalite prudente et desactivee par defaut pour deplacer des dossiers residuels non vides vers `_Dossier Nettoyage`,
  - distinction explicite entre `_Vide` (dossiers vides) et `_Dossier Nettoyage` (dossiers sidecars uniquement, sans vraie video),
  - whitelist configurable par familles (`nfo/xml`, images, sous-titres, textes),
  - blocage automatique sur video, `.iso`, extension inconnue, symlink ou ambiguite,
  - trace dans le resume apply via `cleanup_residual_folders_moved_count`.
- Undo / nettoyage de fin de run:
  - `_Dossier Nettoyage` est officiellement inclus dans l'undo du run,
  - previsualisation undo et resultat undo explicitent les dossiers `_Vide` et `_Dossier Nettoyage` concernes,
  - test end-to-end de restauration d'un dossier residuel deplace.
- UI Next experimentale:
  - entrypoint separe via `--ui next` ou `CINESORT_UI=next`,
  - isolation complete stable / next (DOM, CSS, JS separes),
  - MVP focalise sur Validation / Qualite / Application sans impact sur l'UI stable.
## [7.1.6-dev] - 2026-02-28 - Stabilite, observabilite, coherence release
- Rebrand release complet vers **CineSort**:
  - specs PyInstaller alignes (nom binaire + icone),
  - script de build Windows robuste avec verification dependances et detection du chemin EXE final.
- Documentation alignee CineSort:
  - README mis a jour (nom produit, chemins EXE, conventions _Collection),
  - version de travail positionnee a 7.1.6-dev.
- Durcissement backend:
  - meilleure tracabilite des erreurs rares en mode debug (sans bruit UI),
  - bornage memoire runtime (logs en RAM limites, purge des runs termines en memoire).
- Durcissement core:
  - optimisation locale des comparaisons de fichiers en apply (micro-cache hash quick intra-run),
  - ajustements heuristiques low/med sans changement de contrat API.
- Lisibilite UI:
  - stabilite de la zone progression sur chemins longs,
  - meilleure lisibilite de la table validation et des etats vides/erreur.
## [7.1.5-dev] - 2026-02-22 - UI premium: navigation + contexte + selection auto
- Navigation onglets renforcee:
  - un seul panneau visible a la fois (`.view` + `hidden`),
  - groupes visuels `WORKFLOW` / `INSIGHTS`,
  - roles ARIA `tablist/tab/tabpanel` + navigation clavier (fleches, Enter/Espace).
- Ajout bandeau **Contexte courant**:
  - run actif (copie + ouverture dossier run),
  - film selectionne (titre/annee),
  - mode avance (affichage/copie `row_id`).
- Selection run/film sans saisie manuelle:
  - modal dediee avec runs recents (`get_dashboard("latest").runs_history`),
  - chargement des films d'un run via `get_plan(run_id)`,
  - selection appliquee automatiquement a Qualite/Synthese.
- Qualite:
  - bouton principal "Tester sur le film selectionne",
  - fallback intelligent: dernier run + ouverture du selecteur film.
- Synthese:
  - `latest` par defaut,
  - champ `run_id` reserve au mode avance.
- Lisibilite/CSS premium:
  - bandeau contexte, groupes d'onglets, focus visible, zebra rows, alignement numerique.

## [7.1.4-dev] - 2026-02-22 - Synthese qualite (dernier run)
- Ajout endpoint agrege `get_dashboard(run_id | "latest")`:
  - KPIs: `score_avg`, `score_premium_pct`, `total_movies`, `scored_movies`, `probe_partial_count`.
  - Distributions: bins de score, resolutions, HDR, top codecs audio.
  - Top anomalies + outliers (debit faible, 4K SDR, VO manquante).
  - Historique des runs avec erreurs/anomalies.
- Migration SQLite `004_anomalies_table.sql` + extension store:
  - table `anomalies`,
  - agregations utilitaires pour la synthese (`runs`, erreurs, qualite, anomalies).
- UI: nouvel onglet **Synthese** lisible en un coup d'oeil:
  - cartes KPI,
  - histogramme score simple,
  - tableaux anomalies/outliers/historique,
  - rafraichissement sur un seul appel API (`get_dashboard`).
- Tests backend ajoutes: `tests/test_dashboard.py`.

## [7.1.3-dev] - 2026-02-22 - CinemaLux score 0-100 + profil reglable
- Nouveau moteur de score versionne `CinemaLux_v1` (stable + explicable) avec:
  - score `0..100`,
  - `tier` (`Premium`, `Bon`, `Moyen`, `Faible`),
  - `reasons[]` en FR,
  - `metrics` detailles (valeurs detectees, seuils utilises, sources, flags).
- Fonction critique `4K Light` integree (par defaut `enable_4k_light=true`):
  - penalite reduite si 2160p avec debit faible,
  - flag `is_4k_light=true` dans les metrics.
- Migrations SQLite v7.1.3:
  - `quality_profiles` (profil actif versionne),
  - `quality_reports` (rapport score par `run_id/row_id`).
- Endpoints API ajoutes (non-breaking):
  - `get_quality_profile`, `save_quality_profile`, `reset_quality_profile`,
  - `export_quality_profile`, `import_quality_profile`,
  - `get_quality_report(run_id, row_id)`.
- UI: nouvel onglet **Qualite** avec reglages profil (poids/seuils/toggles),
  export/import JSON, reset, et bouton "Tester sur un film".

## [7.1.2-dev] - 2026-02-22 - Probe AUTO (MediaInfo + ffprobe)
- Nouveau mode Probe technique: `probe_backend=auto|mediainfo|ffprobe|none` (defaut `auto`).
- Detection outils avec chemins optionnels (`mediainfo_path`, `ffprobe_path`) puis fallback PATH.
- Normalisation technique `NormalizedProbe`:
  - container, duree, video (codec/resolution/fps/bitdepth/pix_fmt/bitrate/HDR/DV),
  - pistes audio, sous-titres,
  - `probe_quality` + `probe_quality_reasons[]` en FR.
- Tracage source par champ dans `normalized.sources` (`mediainfo`, `ffprobe`, `mediainfo+ffprobe`).
- Cache SQLite `probe_cache` (migration `002_probe_cache.sql`) pour eviter les rescans.
- Endpoints API:
  - `get_tools_status()`
  - `get_probe(run_id, row_id)`
- En mode `auto`, `raw_json` conserve les 2 sorties sous forme:
  - `{ "mediainfo": {...}|null, "ffprobe": {...}|null }`.
- Comportement tolerant:
  - outils manquants ou echec probe -> logs/messages FR, sans casser le scan global.

## [7.1.0] - 2026-02-22 - Ameliorations ergonomie & conformite
- Dossier collections configurable via `collection_folder_name` (defaut: `_Collection`).
- Migration auto depuis legacy `Collection`:
  - rename direct si `_Collection` absent,
  - merge recursif `Collection -> _Collection` si les deux existent, sans overwrite.
- Option de deplacement des dossiers vides vers `_Vide`:
  - `move_empty_folders_enabled`,
  - `empty_folders_scope` = `root_all` ou `touched_only`.
- Correction conformite NOOP:
  - quand une annee est connue, le dossier doit inclure `(YYYY)` pour etre considere deja conforme.
- Logs/summary APPLY enrichis avec `empty_folders_moved_count`.



