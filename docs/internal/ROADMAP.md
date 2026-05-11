# Roadmap CineSort

> **Statut au 10 mai 2026** : ce document couvre l'historique V1 → V4 (avril 2026).
> Les versions ulterieures (**V5, V5B, V5C, V6, V7.5, V7.6, V7.7**) sont documentees
> dans [`CHANGELOG.md`](CHANGELOG.md) et la section "Historique des audits" de
> [`CLAUDE.md`](CLAUDE.md).
>
> Pour le **plan de remediation v7.8.0** (suite a l'audit exhaustif du 10 mai 2026),
> voir [`audit/REMEDIATION_PLAN_v7_8_0.md`](audit/REMEDIATION_PLAN_v7_8_0.md) et
> son tracking [`audit/TRACKING_v7_8_0.md`](audit/TRACKING_v7_8_0.md).

Derniere mise a jour : 10 mai 2026 (header) — contenu historique V1-V4 conserve pour reference.

---

## V1 — Livree (12 features + refonte UI + audit) — Note 9.5/10

### Ameliorations produit

| Idee | Description | Benefice | Statut |
|------|-------------|----------|--------|
| **Undo v5** | Annulation film par film, preview avant rollback, gestion des conflits post-move, 3 endpoints API, vue frontend interactive | Granularite fine : l'utilisateur corrige un seul film sans toucher au reste du batch | **Fait — 2 avril 2026** |
| **Review triage** | Actions rapides approuver/rejeter depuis la liste, filtres avances, masquage des traites, bulk actions, inbox zero | Reduire le temps de validation de 80% sur les gros runs (500+ films) | **Fait — 3 avril 2026** |
| **Scan incremental v2** | Cache double couche (dossier v1 + video v2), invalidation granulaire par video/NFO, metriques enrichies, migration 008 | Un .nfo ajoute dans un dossier de 10 videos = 0 requete TMDb au lieu de 10 | **Fait — 3 avril 2026** |
| **Onboarding ameliore** | Wizard 5 etapes au premier lancement (bienvenue, dossier, TMDb live, test rapide 5 films, resume), flag onboarding_completed | Les nouveaux utilisateurs arrivent a un premier resultat en 2 minutes | **Fait — 3 avril 2026** |
| **Export enrichi** | CSV 30 colonnes (+15 qualite/probe), rapport HTML single-file (SVG chart, stats cards, table), export .nfo XML Kodi/Jellyfin/Emby (dry-run, skip/overwrite), 24 tests | Interoperabilite avec d'autres media centers et outils de reporting | **Fait — 3 avril 2026** |

### Nouvelles features

| Idee | Description | Benefice | Statut |
|------|-------------|----------|--------|
| **Mode batch automatique** | Auto-approbation configurable (seuil 70-100%, defaut 85%), toggle dans les reglages, resume post-scan, endpoint API | Les cas surs sont pre-approuves automatiquement, l'operateur se concentre sur les cas a risque | **Fait — 3 avril 2026** |
| **Detection series TV** | Parsing S01E01/1x01/Episode N, TMDb TV API, PlanRow etendu, apply vers Serie/Saison/S01E01.ext, badge violet, toggle reglage, 9 tests | Les bibliotheques mixtes films+series sont gerees sans filtrage manuel | **Fait — 3 avril 2026** |
| **Integration Jellyfin Phase 1** | JellyfinClient, 7 settings (url, api_key DPAPI, refresh_on_apply...), hook post-apply refresh, section UI reglages, test connexion, 2 endpoints API, 27 tests | L'utilisateur voit ses films mis a jour dans Jellyfin sans action supplementaire | **Fait — 3 avril 2026** |
| **Dashboard stats global** | Vue Bibliotheque dans Qualite. KPIs multi-runs, timeline SVG, tendance ↑↓→, distribution tiers, top anomalies, activite, films sans analyse. 1 endpoint API, 3 methodes DB, 21 tests | Vision complete de la sante de la bibliotheque sur plusieurs runs | **Fait — 4 avril 2026** |
| **Notifications desktop** | Toasts Win32 (Shell_NotifyIconW, ctypes). NotifyService thread-safe, focus detection, 5 evenements, 5 settings, section UI Reglages. 21 tests | L'utilisateur peut lancer un scan long et etre notifie quand c'est pret | **Fait — 4 avril 2026** |

### Technique

| Idee | Description | Benefice | Statut |
|------|-------------|----------|--------|
| **Migration legacy -> cinesort/** | Deplacer core.py, core_*.py, state.py, tmdb_client.py vers cinesort/ avec shims de compatibilite | Architecture en couches complete, imports propres | **Fait — 2 avril 2026** |
| **Refonte UI v2** | Reecriture complete du frontend. Design system CineSort DS. Architecture JS modulaire (core/ + components/ + views/). 10 vues → 6. CSS 9211L → 560L. JS 7800L → 2800L. | Interface coherente, maintenable, design system unifie | **Fait — 4 avril 2026** |
| **API REST pilotage distant** | Serveur HTTP stdlib (zero dep). Dispatch generique POST /api/{method}. Auth Bearer, CORS, OpenAPI 3.0.3. Mode standalone --api. 33 endpoints, 3 settings. 25 tests | Automatisation CI, pilotage depuis un dashboard web distant | **Fait — 4 avril 2026** |
| **Adapter preview mode** | Migration preview vers UI v2 : 6 vues, bridge navigateTo, mock get_global_stats, scripts capture v2, baselines regenerees | Le mode preview fonctionne avec la nouvelle structure modulaire | **Fait — 4 avril 2026** |

---

## V2 — En cours

### 1. Jellyfin Phase 2 + Refactoring fonctions longues

| Idee | Description | Benefice | Priorite |
|------|-------------|----------|----------|
| **Jellyfin sync watched** | Snapshot statuts vu/pas vu avant apply, restore apres refresh Jellyfin. Polling re-indexation, match par chemin normalise, retry. Module `jellyfin_sync.py`, 3 methodes client, 29 tests | Apres un rename/move, le statut "vu" est preserve automatiquement | **Fait — 4 avril 2026** |
| **3 fonctions > 100L** | `start_plan` 227L→54L, `undo_last_apply` 131L→45L, `build_run_report_payload` 126L→76L. Extraction de sous-fonctions privees. 0 fonction > 100L restante | Conformite avec la regle < 100L, meilleure lisibilite | **Fait — 4 avril 2026** |

### 2. Multi-root

| Idee | Description | Benefice | Priorite |
|------|-------------|----------|----------|
| **Multi-root scan** | Scanner plusieurs dossiers racines en un seul run. PlanRow.source_root, plan_multi_roots() avec merge Stats + detection doublons cross-root. Settings migration root→roots (backward compat). Apply regroupe par source_root. UI editeur multi-root + affichage statut. 25 tests multi-root, 493 tests total | L'utilisateur avec des films sur 2 disques (SSD + NAS) gere tout en un clic | **Fait — 4 avril 2026** |

### 3. Gestion sous-titres

| Idee | Description | Benefice | Priorite |
|------|-------------|----------|----------|
| **Detection sous-titres** | Detection .srt/.ass/.sub/.sup/.idx, association par stem video, detection langue par suffixe (50+ mappings ISO 639-1/2). Module subtitle_helpers.py. PlanRow +5 champs. Warning flags (missing, orphan, duplicate). Scoring qualite +6/-4. Settings 2 champs. UI colonne ST + inspecteur + reglages. 31 tests, 524 tests total | Les sous-titres suivent le dossier, alertes si langues attendues manquantes | **Fait — 4 avril 2026** |

### 4. Raccourcis clavier + drag & drop

| Idee | Description | Benefice | Priorite |
|------|-------------|----------|----------|
| **Navigation clavier** | Dispatcher central keyboard.js. Alt+1-6 navigation, Ctrl+S sauvegarde, F5 refresh, ?/F1 aide. Validation: fleches/jk, Espace/a, r, i, Ctrl+A, Escape. Modale raccourcis avec kbd tags. Migration depuis validation.js. 530 tests total | Usage rapide sans souris, accessibilite | **Fait — 4 avril 2026** |
| **Drag & drop** | Module drop.js, overlay visuel global, drop ajoute root, proposition scan sur Home. Backend validate_dropped_path. Fallback si file.path indisponible (limitation pywebview) | Onboarding ultra-rapide, geste naturel Windows | **Fait — 4 avril 2026** |

### 5. Refonte UI esthetique premium

| Idee | Description | Benefice | Statut |
|------|-------------|----------|--------|
| **Design CinemaLux v3.0** | Direction "salle de projection privee". Palette #06090F, glass morphism (backdrop-filter blur 12px), bordures lumineuses accent-border, gradient accents, icones SVG Lucide, KPI border-left coloree + fadeIn, tables barre laterale hover, badges micro-glow, boutons gradient + shadow, distribution bars gradient + glow, toggles gradient, modales glass, env bar dot indicators, animations viewEnter/kpiFadeIn/modalEnter. Theme clair adapte. 530 tests, 0 regression | Impact visuel premium, fierte d'usage, ambiance cinema/home theater | **Fait — 4 avril 2026** |

### 6. Packaging PyInstaller

| Idee | Description | Benefice | Statut |
|------|-------------|----------|--------|
| **EXE propre** | Vrai ICO multi-resolution (7 tailles), splash Win32 ctypes (CinemaLux), AllocConsole --api, version info Windows, manifest DPI/UAC, exclusions stdlib (-15-25 MB), filtrage web/preview/. Release onefile 14 MB, QA onedir 27 MB | Distribution professionnelle, premier contact soigne, mode API standalone fonctionnel | **Fait — 4 avril 2026** |

### 7. CI GitHub Actions

| Idee | Description | Benefice | Priorite |
|------|-------------|----------|----------|
| **Pipeline automatise** | Workflow tests + lint + format check + build PyInstaller sur push/PR. Matrix Python 3.13. Artefacts EXE en release. Badge status dans README | Zero regression en continu, build reproductible, confiance pour les contributeurs | Moyenne |

### 8. Dashboard web distant

| Idee | Description | Benefice | Statut |
|------|-------------|----------|--------|
| **Phase 1 — Infra** | Handler fichiers statiques `/dashboard/*` dans rest_server.py avec path traversal guard + MIME types. Rate limiting 401 (5/IP/60s → 429). Health enrichi `active_run_id`. Placeholder `web/dashboard/index.html`. 18 tests. | Fondation technique pour les phases suivantes du dashboard distant | **Fait — 4 avril 2026** |
| **Phase 2 — Shell SPA + Login** | SPA vanilla JS ES modules, hash router, guards auth. Shell responsive (sidebar/collapse/bottom tab). Login token Bearer (session/localStorage). Design CinemaLux complet (tokens, glass, responsive 3 breakpoints). Police Manrope embarquee. 9 fichiers, 26 tests. | Fondation frontend du dashboard distant, authentification fonctionnelle | **Fait — 4 avril 2026** |
| **Phase 3 — Status + Logs** | 2 composants (kpi-card, badge) + 2 vues (status, logs). KPIs via Promise.all, barre de progression, polling adaptatif 2s/15s, logs live auto-scroll, actions start/cancel. CSS: progress-bar, logs-box. 52 tests. | Supervision en temps reel : KPIs, progression, logs live, actions rapides | **Fait — 4 avril 2026** |
| **Phase 4 — Library + Runs** | 2 composants (table sortable, modal) + 2 vues (library, runs). Recherche debounce, filtres toggle tier, bar chart SVG, detail modale, timeline SVG, export CSV/HTML/JSON via Blob. 61 tests. | Consultation complete de la bibliotheque et de l'historique depuis le navigateur | **Fait — 4 avril 2026** |
| **Phase 5 — Review triage** | Vue review : table triage 7 colonnes, boutons approve/reject toggle, bulk actions (surs/all/reset), compteurs, preview check_duplicates, save_validation, apply 2 etapes (dry-run + confirmation), load_validation au mount. CSS: lignes colorees, boutons tactiles 44px, action bar sticky mobile. 46 tests. | Approuver/rejeter des films depuis le canape avec dry-run obligatoire | **Fait — 5 avril 2026** |
| **Phase 6 — Jellyfin + Polish** | Vue Jellyfin (guard enabled, KPIs, libraries, test connexion). Nav dynamique (masque si desactive). Hover glow desktop, polish animations. 19 fichiers, 4 composants, 7 vues, ~2600L JS + ~600L CSS. 41 tests. | Dashboard distant complet : 7 vues, 4 composants, 244 tests, zero dependance | **Fait — 5 avril 2026** |

### 9. Nouvelles fonctionnalites — V3

21 features validees, organisees en 4 tiers par ordre d'implementation.

#### Tier A — Fonctions core a forte valeur (faire en premier)

| # | Feature | Description | Effort | Statut |
|---|---------|-------------|--------|--------|
| 9.1 | **Profils de renommage** | Module `naming.py` 280L, 5 presets (default/plex/jellyfin/quality/custom), 20 variables template, injection apply_core.py (3 points), conformance check template-aware, settings preset/validation, endpoints preview+presets, UI desktop (dropdown+inputs+preview live debounce 300ms), dashboard status (profil actif). 91 tests | ~400L domaine + ~120L UI | **Fait — 5 avril 2026** |
| 9.2 | **Comparaison qualite doublons** | Module `duplicate_compare.py` 240L, 7 criteres ponderes, `compare_duplicates()` + `rank_duplicates()`, injection `check_duplicates()`, UI modale cote-a-cote desktop (execution.js) + dashboard (review.js), table 3 colonnes + badges + score + taille + economie. 59 tests | ~240L domaine + ~60L injection + ~200L UI | **Fait — 5 avril 2026** |
| 9.3 | **Detection contenu non-film** | Scoring 6 heuristiques (nom suspect +40, taille +30/+15, pas TMDb +25, titre court +10, extension +10, seuil 60). Flag `not_a_movie` dans warning_flags. Badge orange UI desktop + dashboard. 33 tests | ~60L scan_helpers + ~10L plan_support + ~10L UI | **Fait — 5 avril 2026** |
| 9.4 | **Verification integrite fichiers** | Module `integrity_check.py` 80L, magic bytes 5 formats (MKV/MP4/AVI/TS/WMV), `check_header()` au scan, flag `integrity_header_invalid` + `integrity_probe_failed`. Badge rouge "Corrompu ?". 23 tests | ~80L domaine + ~15L injection + ~10L UI | **Fait — 5 avril 2026** |
| 9.5 | **Collections automatiques (sagas TMDb)** | TMDb `belongs_to_collection` via `/movie/{id}` (cache unifie), Candidate + PlanRow `tmdb_collection_id/name`, apply → `_Collection/Saga/Film/`, badge violet "Saga". 22 tests | ~100L domaine + ~25L apply + ~15L UI | **Fait — 5 avril 2026** |

#### Tier B — Enrichissement bibliotheque (apres Tier A)

| # | Feature | Description | Effort | Statut |
|---|---------|-------------|--------|--------|
| 9.6 | **Detection re-encode / upgrade suspect** | Module `encode_analysis.py` 60L, 3 flags (upscale_suspect, 4k_light, reencode_degraded), seuils par resolution/codec, injection quality_report, badges UI rouge/orange. 33 tests | ~60L domaine + ~10L inject + ~15L UI | **Fait — 5 avril 2026** |
| 9.7 | **Analyse audio approfondie** | Module `audio_analysis.py` 120L, hierarchie 8 niveaux (Atmos→MP3), detection commentaire, doublons suspects, badge 4 tiers. Probe enrichie (title + is_commentary). 37 tests | ~120L domaine + ~10L probe + ~15L UI | **Fait — 5 avril 2026** |
| 9.8 | **Espace disque intelligent (Space Analyzer)** | Metrics enrichies (file_size_bytes), `_compute_space_analysis` dans get_global_stats (by_tier/resolution/codec, top gaspilleurs waste_score, archivable). Bar charts SVG dashboard + desktop. 21 tests | ~60L backend + ~50L dashboard + ~30L desktop + ~10L CSS | **Fait — 5 avril 2026** |
| 9.9 | **Mode bibliothecaire (suggestions proactives)** | Module `librarian.py` 100L, 6 suggestions triees par priorite (codec obsolete, doublons, sous-titres, non identifies, resolution, collections). Health score %. UI dashboard + desktop. 21 tests | ~100L domaine + ~15L inject + ~60L UI | **Fait — 5 avril 2026** |
| 9.10 | **Sante bibliotheque continue** | Snapshot health persiste dans stats_json par run. Timeline enrichi avec health_score. Delta trend ↑/↓/→. Line chart SVG polyline dashboard + desktop. 18 tests | ~20L run_flow + ~40L dashboard + ~50L UI | **Fait — 5 avril 2026** |

#### Tier C — Automatisation et connectivite (apres Tier B)

| # | Feature | Description | Effort | Statut |
|---|---------|-------------|--------|--------|
| 9.11 | **Mode planifie / watch folder** | `FolderWatcher` thread daemon, poll `os.scandir` toutes les N min. Snapshot initial sans scan. Detection changements → `start_plan()` auto. Toggle dynamique settings. UI toggle + indicateur dashboard | ~150L + 15 tests | **Fait** ✅ — 5 avril 2026 |
| 9.12 | **Watchlist TMDb / Letterboxd / IMDb** | Import CSV Letterboxd + IMDb. Matching titre normalise (sans accents, sans articles) + annee. Rapport owned/missing/coverage. FileReader JS + endpoint `import_watchlist` | ~130L + 18 tests | **Fait** ✅ — 5 avril 2026 |
| 9.13 | **Historique par film** | `film_identity_key()` (tmdb_id ou titre+annee). `get_film_timeline()` reconstruit events depuis plan.jsonl + BDD. Timeline verticale desktop + dashboard. Zero nouvelle table SQL | ~250L + 21 tests | **Fait** ✅ — 5 avril 2026 |
| 9.14 | **Integration Plex** | `PlexClient` HTTP direct (X-Plex-Token). Test connexion, libraries, get_movies (Guid→tmdb_id), refresh post-apply, sync report via `build_sync_report` reutilise. 6 settings. UI desktop + dashboard | ~200L + 16 tests | **Fait** ✅ — 5 avril 2026 |
| 9.15 | **Plugin hooks post-action** | Dossier `plugins/`, scripts `.py`/`.bat`/`.ps1` executes apres 4 evenements. JSON stdin + env vars. Thread daemon, timeout 30s. Convention nommage `post_scan_xxx.py` | ~150L + 15 tests | **Fait** ✅ — 5 avril 2026 |
| 9.16 | **Rapport par email** | `smtplib` stdlib, MIME texte brut. 9 settings SMTP. Thread daemon non-bloquant. Trigger post_scan + post_apply. Endpoint `test_email_report` | ~120L + 14 tests | **Fait** ✅ — 5 avril 2026 |

#### Tier D — Polish technique (intercaler selon opportunite)

| # | Feature | Description | Effort | Statut |
|---|---------|-------------|--------|--------|
| 9.17 | **Suppression shims legacy racine** | Supprimer les 9 fichiers shims (`core.py`, `backend.py`, `state.py`, `tmdb_client.py`, `core_*.py`). Tous les imports migres vers `cinesort.*` | ~30L supprimees, ~60 imports migres | **Fait** ✅ — 5 avril 2026 |
| 9.18 | **Tests Playwright dashboard E2E + catalogue visuel** | 131 tests Chromium headless dans `tests/e2e/`. 15 fichiers, 7 phases, Page Object Model (7 pages). 15 films mock + 2 runs. 3 viewports (desktop/tablet/mobile). Couverture : login, navigation, status, library, runs, review, jellyfin, responsive, visual regression, performance, accessibilite, erreurs, console, rapport UI, catalogue visuel (45 screenshots, rapport HTML 6 Mo navigable avec lightbox). 6 bugs app corriges. | ~2800L | **Fait** ✅ — 6 avril 2026 |
| 9.19 | **Coverage HTML dans la CI** | Rapport HTML coverage uploade comme artefact GitHub Actions (retention 14j). Pas de Codecov (zero dependance externe) | ~10L CI | **Fait** ✅ — 5 avril 2026 |
| 9.20 | **HTTPS dashboard (ssl stdlib)** | Wrapper `ThreadingHTTPServer` avec certificat fourni par l'utilisateur. 3 settings (`rest_api_https_enabled`, `cert_path`, `key_path`). Fallback HTTP si cert manquant | ~50L | **Fait** ✅ — 5 avril 2026 |
| 9.21 | **Refresh auto dashboard apres apply** | Health endpoint inclut `last_event_ts`. Dashboard compare et declenche refresh instantane au lieu d'attendre le polling 15s | ~30L serveur + ~20L JS | **Fait** ✅ — 5 avril 2026 |

#### Tier E — Analyse perceptuelle et ecosysteme (apres Tier D)

| # | Feature | Description | Effort | Statut |
|---|---------|-------------|--------|--------|
| 9.22 | **Editions multiples (Multi-version)** | Detection 12 types d'editions via regex. `PlanRow.edition`. Variables `{edition}` + `{edition-tag}` (Plex). `strip_edition` avant TMDb. Dedup edition-aware. Badge violet. | ~150L + 29 tests | **Fait** ✅ — 5 avril 2026 |
| 9.23 | **Conflit metadonnees MKV + nettoyage** | Detection conflit titre conteneur MKV/MP4 vs titre identifie. `container_title` extrait via probe (ffprobe + mediainfo). Warning `mkv_title_mismatch`. Badge "MKV titre" jaune. Nettoyage mkvpropedit prevu Phase 2 | ~80L + 21 tests | **Fait** ✅ — 5 avril 2026 |
| 9.24 | **Analyse qualite perceptuelle complete** | 9 phases, package `cinesort/domain/perceptual/` (7 modules, ~1500L). Frame extraction deterministe + downscale 4K. Video analysis (signalstats+blockdetect+blurdetect, histogramme, variance, banding, bit depth effectif). Grain/DNR contextualise (TMDb annee/genre/budget/studio, 7 verdicts). Audio perceptuel (EBU R128 loudnorm, astats, clipping segments, hierarchie codec). Score composite (video 60% + audio 40%, 5 tiers, 10 verdicts croises). Comparaison profonde 2 fichiers (frames alignees, diff pixel, 8 criteres, rapport justifie FR). UI desktop + dashboard (section settings 11 params, bouton inspecteur, badges 5 tiers). Edge cases (film court, audio/video-only, probe FAILED). Schema v9 (perceptual_reports). Cache DB. Zero dependance externe | ~1500L + 179 tests | **Fait** ✅ — 6 avril 2026 |
| 9.25 | **Integration Radarr bidirectionnelle** | `RadarrClient` API v3 (X-Api-Key). Matching tmdb_id. `build_radarr_report` + `should_propose_upgrade` (score<54, upscale, reencode, codec obsolete). `search_movie` pour upgrade. UI settings + dashboard | ~280L + 20 tests | **Fait** ✅ — 5 avril 2026 |
| 9.26 | **Validation croisee Jellyfin** | `build_sync_report()` matching 3 niveaux (chemin, tmdb_id, titre+annee). Rapport matched/missing/ghost/mismatch. Bouton dashboard + KPI + tables | ~150L + 13 tests | **Fait** ✅ — 5 avril 2026 |
| 9.27 | **Detection langue audio incoherente** | `_check_language_coherence()` dans audio_analysis.py. Warnings `audio_language_missing` + `audio_language_incomplete`. Badge "Langue ?" jaune | ~40L + 11 tests | **Fait** ✅ — 5 avril 2026 |

---

## V4 — En cours

### Logging structure

| # | Feature | Description | Effort | Statut |
|---|---------|-------------|--------|--------|
| V4.1 | **Logging V4 structure** | Audit 133 fichiers (68% sans logging). 5 phases : infra critique (REST + clients HTTP + migrations), app critique (apply/scan/jobs), domain (scoring + perceptual), UI/API (endpoints), JS frontend (navigation + actions). ~39 fichiers modifies, ~300L. Format : logging stdlib, DEBUG/INFO/WARNING/ERROR | ~300L, 0 tests (logging only) | **Fait** ✅ — 6 avril 2026 |

### Quality of Life

| # | Feature | Description | Effort | Statut |
|---|---------|-------------|--------|--------|
| V4.2 | **Auto-detection IP + URL cliquable** | Module `network_utils.py` (UDP socket + fallback hostname + fallback 127.0.0.1). URL dashboard affichee dans les reglages desktop + endpoint `get_server_info()`. Log au demarrage REST. | ~50L + 11 tests | **Fait** ✅ — 6 avril 2026 |
| V4.3 | **Redemarrage serveur REST a chaud** | Endpoint `restart_api_server()` : stop + relire settings + relancer. Bouton dans les reglages. Plus besoin de fermer/relancer l'EXE. | ~40L + 1 test | **Fait** ✅ — 6 avril 2026 |
| V4.4 | **Bouton Refresh dashboard** | Bouton refresh SVG dans la sidebar footer. Animation rotation CSS. F5 intercepte pour refresh sans recharger la page. | ~30L | **Fait** ✅ — 6 avril 2026 |
| V4.5 | **Bouton Copier le lien dashboard** | Bouton clipboard dans les reglages a cote de l'URL. Hint "Ouvrez ce lien sur votre telephone". Pragmatique (QR code trop lourd en 0-dep). | ~15L | **Fait** ✅ — 6 avril 2026 |

### Splash screen

| # | Feature | Description | Effort | Statut |
|---|---------|-------------|--------|--------|
| V4.6 | **Splash screen HTML pywebview** | Remplacement splash Win32 ctypes par splash HTML via pywebview. 2 fenetres (splash frameless 520x320 + main hidden). 7 etapes progression avec animation CSS. Design CinemaLux (gradient, glow, barre animee). Suppression code Win32 splash + fallback 8s. Runtime hook reduit a AllocConsole seul. | ~160L + 8 tests | **Fait** ✅ — 6 avril 2026 |

### Dependances V4

| # | Feature | Description | Effort | Statut |
|---|---------|-------------|--------|--------|
| V4.7 | **segno QR code** | Dep pure Python (MIT, 0 sous-dep). Endpoint `get_dashboard_qr()` retourne SVG inline CinemaLux. QR affiche dans les reglages desktop a cote de l'URL. Couleurs #e0e0e8 sur #0a0a0f. | ~40L + 5 tests | **Fait** ✅ — 6 avril 2026 |
| V4.8 | **rapidfuzz core** | Dep C++ (MIT, wheels Windows). Remplacement `difflib.SequenceMatcher.ratio()` → `rapidfuzz.fuzz.ratio()/100` dans `title_helpers.py:seq_ratio()` (1 fonction, toute la chaine scan/TMDb en profite). 5-100x plus rapide. Compatibilite 0.0-1.0 preservee. | ~10L + 9 tests | **Fait** ✅ — 6 avril 2026 |
| V4.9 | **Fuzzy sync Jellyfin/Radarr** | Module `_fuzzy_utils.py` (normalize_for_fuzzy + fuzzy_title_match). Level 3 des sync reports enrichi : exact → exact+fuzzy fallback (seuil 85). Gere accents, ponctuation, titres traduits. | ~60L + 12 tests | **Fait** ✅ — 6 avril 2026 |
| V4.10 | **Watchlist fuzzy fallback** | Pass 2 fuzzy dans `compare_watchlist()` via `fuzz.token_sort_ratio()`. Gere ordre mots inverse ("Lord of the Rings, The"). Filtre annee strict. Seuil 85. | ~20L + 5 tests | **Fait** ✅ — 6 avril 2026 |

### Ameliorations logiques metier

| # | Feature | Description | Effort | Statut |
|---|---------|-------------|--------|--------|
| V4.11 | **TMDb lookup IMDb ID** | `find_by_imdb_id()` via /find endpoint. .nfo avec IMDb ID → candidat score 0.95. Fallback FR→EN si 0 resultat. | ~35L + 7 tests | **Fait** ✅ — 6 avril 2026 |
| V4.12 | **Scoring contextualise** | Bonus ere (patrimoine +8, classique +4), malus film recent -4. Penalite encode (upscale -8, reencode -6, 4k_light -3). Penalite commentary-only -15. | ~30L + 10 tests | **Fait** ✅ — 6 avril 2026 |
| V4.13 | **Detection non-film amelioree** | Heuristique duree (<5min +35, <20min +25). Mots-cles : blooper, outtake, recap, gag reel. | ~20L + 6 tests | **Fait** ✅ — 6 avril 2026 |
| V4.14 | **Patterns TV enrichis** | S01.E01 (point optionnel). "Season N Episode N" / "Saison N Episode N" (texte FR/EN). | ~15L + 8 tests | **Fait** ✅ — 6 avril 2026 |
| V4.15 | **Integrite tail check** | Verification fin de fichier : MP4 moov atom, MKV fin non-nulle. Detecte les fichiers tronques. | ~35L + 5 tests | **Fait** ✅ — 6 avril 2026 |
| V4.16 | **Doublons enrichis** | Critere perceptuel (poids 10) + critere sous-titres FR (poids 5) dans la comparaison doublons. | ~25L + 7 tests | **Fait** ✅ — 6 avril 2026 |

### Systeme de themes

| # | Feature | Description | Effort | Statut |
|---|---------|-------------|--------|--------|
| V4.17 | **Systeme de themes complet** | 4 palettes (Studio/Cinema/Luxe/Neon), 3 niveaux animation (subtle/moderate/intense), 3 curseurs (vitesse/glow/luminosite). Fichier `themes.css` partage. Effets atmospheriques par theme (grain cinema, scan studio, shimmer luxe, neon border). 5 settings avec round-trip. Preview instantane via CSS custom properties. | ~350L CSS + ~100L JS + 16 tests | **Fait** ✅ — 6 avril 2026 |

### Dashboard parite complete

| # | Feature | Description | Effort | Statut |
|---|---------|-------------|--------|--------|
| V4.18 | **Dashboard parite complete** | 8 phases : (1) Page reglages 15 sections, (2) Sync temps reel settings via last_settings_ts, (3) Vue Qualite (KPIs, distribution, timeline, anomalies), (4) Undo + Export NFO, (5) Inspecteur film enrichi (candidats, perceptuel, historique, sous-titres), (6) Vues Plex + Radarr (guard enabled, KPIs, test connexion, sync report, upgrade), (7) Raccourcis clavier (1-8 nav, Escape, ?), (8) 26 tests parite. Dashboard passe de 6 a 10 vues. Sync bidirectionnelle desktop ↔ dashboard. | ~800L JS + 26 tests | **Fait** ✅ — 6 avril 2026 |
