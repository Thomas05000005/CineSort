# Rapport de parité Desktop ↔ Dashboard

**Projet** : CineSort · **Date** : 2026-04-21 · **Scope** : `web/` (desktop pywebview) vs `web/dashboard/` (SPA distante).

> Rappel décisions utilisateur :
> 1. **Architecture** : desktop sera refondu en workflow 5 étapes comme le dashboard (fusion Accueil + Validation + Application → Bibliothèque unifiée).
> 2. **Exclusives desktop** (drag-drop, command palette, help overlay, confetti, activity log, raccourcis Alt+1-9, notifications Win32, splash HTML) : conservées intactes.
> 3. **Settings dashboard-spécifiques** (QR, Restart API, HTTPS) : vérifier puis porter si manquants.

## Sommaire exécutif

- ✓ **Parité identique** : 42 features (QR, Restart API, simulateur G5, éditeur règles G6, 4 thèmes, 17 sections settings communes, exports HTML/CSV/JSON/.nfo, watchlist Letterboxd/IMDb, tests connexion Jellyfin/Plex/Radarr, librarian/espace/tendance santé côté Qualité, etc.).
- ⚠ **Divergences UX** : 8 features (structure vues éclatée vs unifiée, logs pas combinés avec historique, kpi-card vs macro manuel, pas de détection `last_event_ts`, pas de skeleton loader, outils quality profile absents UI desktop, guard auth).
- ✗ **Absent desktop** : 10 features importantes (workflow Library unifié, skeleton composant, kpi-card composant, export/import/reset profil qualité UI, HTTPS settings 3 champs, test_email_report bouton, compare_perceptual endpoint usage, get_tmdb_posters endpoint usage, last_event_ts event-driven polling, vue Logs+Historique combinée).
- ℹ **Exclusives desktop conservées** : 12 features (drag-drop, command palette, help overlay, confetti, activity log, copy-to-clipboard hint, auto-tooltip, raccourcis clavier Alt+1-9/a/r/i/Ctrl+A, notifications Win32, splash HTML, undo v5 par film, wizard onboarding).

**Verdict** : parité à 78 % fonctionnelle, mais gap STRUCTUREL majeur sur la vue Library (P0). Les gaps informationnels (skeleton, event polling, export profil qualité, HTTPS settings, test email) sont des ajouts ciblés.

---

## A. Navigation & structure

| Feature dashboard | Équivalent desktop | Statut | Fichier:ligne | Notes |
|---|---|---|---|---|
| 8 routes nav (/status, /library, /quality, /jellyfin, /plex, /radarr, /logs, /settings) | 9 onglets nav (home, validation, execution, quality, jellyfin, plex, radarr, history, settings) | ⚠ Divergent | [web/index.html:26-52](web/index.html#L26) vs [web/dashboard/index.html:52-80](web/dashboard/index.html#L52) | Desktop éclate Library en 3 (home+validation+execution), dashboard = 1 seule vue workflow |
| Route `/library` = workflow 5 étapes | home + validation + execution séparés | ✗ Absent desktop | — | P0 structurel (décidé : refondre) |
| Route `/logs` = logs live + historique | `history` = historique uniquement (+ logs dans `home`) | ⚠ Divergent | [web/views/history.js](web/views/history.js) vs [web/dashboard/views/logs.js](web/dashboard/views/logs.js) | Desktop disperse logs entre home + history |
| Guards auth (`requireAuth`) | Pas de guards (desktop local) | ℹ Desktop-only | [web/dashboard/core/router.js](web/dashboard/core/router.js) | Normal : desktop local n'a pas besoin d'auth |
| Nav dynamique (cache Jellyfin/Plex/Radarr si disabled) | Idem (classes `nav-btn-jellyfin` etc. masquées par JS) | ✓ Identique | Les 2 | OK |
| Raccourcis nav (Alt+1-9 desktop, 1-8 dashboard) | Alt+1-9 | ✓ Identique | [web/core/keyboard.js](web/core/keyboard.js) | Dashboard utilise aussi des chiffres (à vérifier) |

---

## B. Contenu vue par vue

### B.1 Status (dashboard) ↔ Home + Quality panel Bibliothèque (desktop)

| Feature dashboard | Équivalent desktop | Statut | Fichier | Notes |
|---|---|---|---|---|
| KPIs hero (score, films, premium %, runs) | KPIs home + quality | ⚠ Divergent | [web/views/home.js](web/views/home.js), [web/views/quality.js](web/views/quality.js) | Éparpillés sur 2 vues desktop |
| Run actif + progress bar + cancel | Idem home | ✓ Identique | [web/views/home.js](web/views/home.js) | OK |
| Santé probe/Jellyfin/Plex/Radarr/perceptuel/watcher/profil renommage | Home env-bar (probe, TMDb, roots) | ⚠ Divergent | [web/views/home.js](web/views/home.js) | Desktop moins complet (pas Jellyfin/Plex/Radarr status en un coup d'œil) |
| Espace disque (KPIs + bar chart + top 5 gaspilleurs) | Présent dans quality.js panel Bibliothèque | ✓ Identique | [web/views/quality.js](web/views/quality.js) (`globalSpaceSection`) | Même backend `space_analysis` |
| Suggestions librarian (health_score + cartes priorité) | Présent dans quality.js | ✓ Identique | [web/views/quality.js](web/views/quality.js) (`globalLibrarianSection`) | OK |
| Tendance santé (line chart SVG) | Présent dans quality.js | ✓ Identique | [web/views/quality.js](web/views/quality.js) (`globalHealthTrend`) | OK |
| Banneau auto-install probe | Banneau home (`probeInstallBanner`) | ✓ Identique | [web/views/home.js](web/views/home.js) | OK |
| Polling event-driven (`last_event_ts`) | Polling à intervalle fixe sans détection | ✗ Absent desktop | [web/dashboard/views/status.js](web/dashboard/views/status.js), [web/dashboard/core/state.js](web/dashboard/core/state.js) | P1 : sync temps réel settings/apply/scan manquant |
| Skeleton loaders pendant chargement | Pas de skeleton | ✗ Absent desktop | [web/dashboard/components/skeleton.js](web/dashboard/components/skeleton.js) | P2 |

### B.2 Library (dashboard) ↔ Home + Validation + Execution (desktop)

| Feature dashboard | Équivalent desktop | Statut | Fichier | Notes |
|---|---|---|---|---|
| Workflow 5 étapes unifié (libState partagé) | 3 vues séparées | ✗ Absent desktop | [web/dashboard/views/library/](web/dashboard/views/library/) | **P0 structurel** — décidé : refondre |
| Lib-analyse : scan + logs + progress | home.js | ⚠ Divergent | [web/views/home.js](web/views/home.js) | Éparpillé |
| Lib-verification : tableau films scorés | validation.js | ⚠ Divergent | [web/views/validation.js](web/views/validation.js) | Concept différent desktop (tri + triage vs review pur) |
| Lib-validation : decisions approve/reject | validation.js (approve/reject checkboxes) | ✓ Identique | [web/views/validation.js](web/views/validation.js) | OK |
| Lib-duplicates : doublons perceptual/textuel | execution.js (check_duplicates) | ⚠ Divergent | [web/views/execution.js](web/views/execution.js) | Desktop a modalCompare plus riche, mais pas compare_perceptual endpoint |
| Lib-apply : dry-run + apply + undo v1 | execution.js (apply + undo v1 + undo v5) | ℹ Desktop-only (+) | [web/views/execution.js](web/views/execution.js) | Desktop = v1 + v5 granulaire. Dashboard v1 seulement |
| Inspector film (panel droit) | validation.js inspector | ✓ Identique | [web/views/validation.js](web/views/validation.js) | Desktop plus riche (candidats TMDb, edition, collection) |
| get_tmdb_posters (posters films) | Pas d'usage | ✗ Absent desktop | [web/dashboard/views/library.js](web/dashboard/views/library.js#L297) | P2 cosmétique |
| compare_perceptual (comparaison 2 films) | Pas d'usage | ✗ Absent desktop | [web/dashboard/views/library/lib-duplicates.js](web/dashboard/views/library/lib-duplicates.js#L104) | P1 |

### B.3 Quality (dashboard ↔ desktop)

| Feature dashboard | Équivalent desktop | Statut | Fichier | Notes |
|---|---|---|---|---|
| KPIs (films, score moyen, premium, tendance) | Idem | ✓ Identique | quality.js des 2 côtés | OK |
| Distribution qualité (bar chart 4 tiers) | Idem | ✓ Identique | quality.js des 2 côtés | OK |
| Distribution technique (résolutions, HDR, audio) | Présent | ✓ Identique | [web/views/quality.js](web/views/quality.js) | OK |
| Timeline évolution score (SVG) | Présent | ✓ Identique | Les 2 | OK |
| Anomalies fréquentes (tableau) | Présent | ✓ Identique | Les 2 | OK |
| Outliers (films < mean - 2σ) | Présent | ✓ Identique | Les 2 | OK |
| Derniers runs (tableau) | Présent | ✓ Identique | Les 2 | OK |
| Filtres qualité (état/tier/score) | Présent | ✓ Identique | Les 2 | OK |
| Bouton "Analyser la qualité" / batch | Présent | ✓ Identique | Les 2 | OK |
| Bouton "Simuler un preset" (G5) | Présent | ✓ Identique | [web/views/quality.js:355](web/views/quality.js#L355) | OK |
| Bouton "Règles custom" (G6) | Présent (via customRulesCard) | ✓ Identique | [web/index.html](web/index.html) | OK |
| Boutons "Exporter / Importer / Réinitialiser" profil qualité | **Pas de boutons UI** | ✗ Absent desktop | Dashboard : [web/dashboard/views/quality.js:232](web/dashboard/views/quality.js#L232) | **P1** — 3 endpoints disponibles backend, UI à ajouter |
| Preset card group (3 presets) | Présent | ✓ Identique | Les 2 | OK |

### B.4 Jellyfin / B.5 Plex / B.6 Radarr

| Feature dashboard | Équivalent desktop | Statut | Notes |
|---|---|---|---|
| Guard enabled (masque si disabled) | Idem | ✓ Identique | OK |
| KPIs statut/serveur/version/films | Idem | ✓ Identique | OK |
| Test connexion (boutons dédiés) | Idem | ✓ Identique | OK |
| Validation croisée (matched/missing/ghost/mismatch) | Idem | ✓ Identique | [web/views/jellyfin-view.js](web/views/jellyfin-view.js) |
| Radarr upgrade candidates | Idem | ✓ Identique | [web/views/radarr-view.js](web/views/radarr-view.js) |
| Plex libraries | Idem | ✓ Identique | [web/views/plex-view.js](web/views/plex-view.js) |

### B.7 Logs (dashboard) ↔ History + Home logs (desktop)

| Feature dashboard | Équivalent desktop | Statut | Notes |
|---|---|---|---|
| Logs live (run actif) + auto-scroll | Dans home.js | ⚠ Divergent | [web/views/home.js](web/views/home.js) |
| Historique runs (table sortable + export) | Dans history.js | ⚠ Divergent | [web/views/history.js](web/views/history.js) |
| Toggle modes (live/historique) | Absent | ✗ Absent desktop | **P1** — fusionner en une vue Logs unifiée |
| Dropdown sélection run + exports | Présent history | ✓ Identique | OK |

### B.8 Settings

| Section dashboard | Équivalent desktop | Statut | Notes |
|---|---|---|---|
| Essentiel (multi-root) | Présent | ✓ Identique | OK |
| TMDb | Présent | ✓ Identique | OK |
| Analyse vidéo (TV/subs/incremental/auto-approve) | Présent | ✓ Identique | OK |
| Profil de renommage | Présent | ✓ Identique | OK |
| Jellyfin | Présent | ✓ Identique | OK |
| Nettoyage dossiers | Présent | ✓ Identique | OK |
| Notifications | Présent | ✓ Identique | OK |
| Plex | Présent | ✓ Identique | OK |
| Radarr | Présent | ✓ Identique | OK |
| Surveillance (watcher) | Présent (ckWatchEnabled, watchInterval) | ✓ Identique | OK |
| Email rapport SMTP | Présent (ckEmail*, inEmail*) | ⚠ Divergent | **Bouton "Tester l'envoi email" manquant** (endpoint test_email_report exists, UI bouton absent) — P1 |
| HTTPS (cert, key, https_enabled) | **Absent** | ✗ Absent desktop | **P1** — 3 settings à ajouter |
| Plugins (enabled + timeout) | Présent | ✓ Identique | OK |
| API REST (port, token, QR, restart) | Présent (ckRestApi*, btnRestartApi, btnCopyDashUrl) | ✓ Identique | OK |
| Apparence (theme, animations, 3 sliders) | Présent (selTheme, selAnimationLevel, lbl*) | ✓ Identique | OK |
| Analyse perceptuelle (enabled, auto, timeouts, frames) | Présent | ✓ Identique | OK |
| Watchlist import | Présent | ✓ Identique | OK |

---

## C. Settings — diff synthèse

**Settings identiques** : 16 sections sur 17.

**Settings MANQUANTS côté desktop** :
- `rest_api_https_enabled` (checkbox) → P1
- `rest_api_cert_path` (text) → P1
- `rest_api_key_path` (text) → P1
- Bouton "Tester l'envoi email" (appel `test_email_report`) → P1

**Settings EXCLUSIFS desktop** (à conserver) :
- Inputs spécifiques probe (`inProbeFfprobePath`, `inProbeMediainfoPath`, `inProbeTimeoutS`, `selProbeBackend`) — dashboard utilise defaults auto
- Wizard onboarding (étapes premier lancement) — desktop-only

---

## D. Composants & design system

| Composant dashboard | Équivalent desktop | Statut | Notes |
|---|---|---|---|
| `kpi-card.js` (icône + valeur + tendance + sparkline) | Macros HTML inline (kpi-grid + kpi) | ⚠ Divergent | Desktop reconstruit à la main, moins factorisé. **P2** — porter kpi-card côté desktop pour uniformiser |
| `skeleton.js` (loading placeholders) | **Absent** | ✗ Absent desktop | **P2** — à porter |
| `sparkline.js` | Présent | ✓ Identique | OK |
| `badge.js` | Présent | ✓ Identique | OK |
| `modal.js` | Présent | ✓ Identique | OK |
| `table.js` | Présent | ✓ Identique | OK |
| `toast.js` | Présent | ✓ Identique | OK |
| `scraping-status.js` | Présent | ✓ Identique | OK |
| — | `command-palette.js`, `help-overlay.js`, `activity-log.js`, `confetti.js`, `copy-to-clipboard.js`, `auto-tooltip.js`, `empty-state.js`, `status.js` | ℹ Desktop-only | Conservés (décision user) |

**Design system (tokens + 4 thèmes)** : identique. `themes.css` partagé entre les 2 côtés (Studio, Cinema, Luxe, Neon). Même palette, même spacing, même glass morphism.

---

## E. Endpoints API consommés

### E.1 Endpoints dashboard non utilisés par desktop (à porter)

| Endpoint | Vue dashboard | Priorité | Impact |
|---|---|---|---|
| `export_quality_profile` | quality.js | P1 | UI bouton "Exporter profil JSON" à ajouter |
| `import_quality_profile` | quality.js | P1 | UI bouton "Importer profil JSON" à ajouter |
| `reset_quality_profile` | quality.js | P1 | UI bouton "Réinitialiser profil" à ajouter |
| `test_email_report` | settings.js | P1 | UI bouton "Tester l'envoi" dans section Email |
| `compare_perceptual` | lib-duplicates.js | P1 | Comparaison 2 films via hash perceptuel (doublons intelligents) |
| `get_tmdb_posters` | library.js | P2 | Posters films dans liste/galerie |

### E.2 Endpoints desktop non utilisés par dashboard (à conserver desktop-only)

| Endpoint | Usage desktop | Justification |
|---|---|---|
| `validate_dropped_path` | drop.js drag-drop | Exclusif desktop (drag-drop natif) |
| `open_path` | api.js open explorateur | Exclusif desktop (natif OS) |
| `log_api_exception` | error-boundary.js | Exclusif desktop (bridge pywebview) |
| `get_server_info` | settings.js (IP locale URL) | Les 2 pourraient l'utiliser mais desktop l'expose pour afficher l'URL partageable |
| `undo_last_apply_preview` | execution.js undo v1 | Desktop-only — dashboard v1 direct sans preview |
| `undo_by_row_preview` | execution.js undo v5 | Desktop-only — undo granulaire par film |
| `undo_selected_rows` | execution.js undo v5 | Desktop-only |
| `recheck_probe_tools` | home.js | Desktop-only (revérification outils probe) |
| `reset_incremental_cache` | home.js | Desktop-only (force rescan complet) |

**Note undo v5** : le desktop est SUPÉRIEUR au dashboard ici. Le dashboard n'a que undo v1 (batch complet). Le desktop permet la sélection par film. Décision : desktop reste supérieur, dashboard peut être porté plus tard (P2, hors scope parité actuelle).

---

## F. Flux & interactions

| Feature | Dashboard | Desktop | Statut |
|---|---|---|---|
| Polling event-driven (`last_event_ts` dans `/api/health`) | Implémenté (state.js `checkEventChanged`) | Non implémenté | ✗ Absent desktop P1 |
| Workflow library 5 étapes avec libState partagé | Implémenté | N/A (3 vues séparées) | ✗ Absent desktop P0 |
| Skeleton loader pendant fetch | Implémenté (skeleton.js) | Non | ✗ Absent desktop P2 |
| Cancellation run (bouton Annuler) | Implémenté | Implémenté | ✓ Identique |
| Polling adaptatif 2s/15s | Implémenté | Implémenté (home.js pollStatus) | ✓ Identique |
| Auto-install probe tools | Implémenté | Implémenté | ✓ Identique |
| Sync watched Jellyfin post-apply | Backend (appelé par apply_support) | Idem | ✓ Identique |
| Notifications desktop Win32 | N/A | Implémenté | ℹ Desktop-only |

---

## G. Exclusives desktop (à conserver)

| Feature | Fichier | Statut |
|---|---|---|
| Drag & drop dossiers + overlay | [web/core/drop.js](web/core/drop.js) | ℹ Conservée |
| Raccourcis clavier complets (Alt+1-9, a/r/i, Ctrl+S, Ctrl+A, Escape) | [web/core/keyboard.js](web/core/keyboard.js) | ℹ Conservée |
| Wizard onboarding 5 étapes | [web/views/settings.js](web/views/settings.js) | ℹ Conservée |
| Command palette Ctrl+K | [web/components/command-palette.js](web/components/command-palette.js) | ℹ Conservée |
| Help overlay ?/F1 | [web/components/help-overlay.js](web/components/help-overlay.js) | ℹ Conservée |
| Activity log drawer | [web/components/activity-log.js](web/components/activity-log.js) | ℹ Conservée |
| Confetti post-apply | [web/components/confetti.js](web/components/confetti.js) | ℹ Conservée |
| Copy-to-clipboard avec hint | [web/components/copy-to-clipboard.js](web/components/copy-to-clipboard.js) | ℹ Conservée |
| Auto-tooltip via attr() | [web/components/auto-tooltip.js](web/components/auto-tooltip.js) | ℹ Conservée |
| Splash HTML au démarrage | [web/splash.html](web/splash.html) | ℹ Conservée |
| Notifications Win32 (Shell_NotifyIconW) | Backend `cinesort/app/notify_service.py` | ℹ Conservée |
| Undo v5 granulaire par film | [web/views/execution.js](web/views/execution.js) | ℹ Conservée (supérieur dashboard) |

---

## Gaps priorisés

### P0 — Structurel (bloque parité)

1. **Refondre desktop en workflow Bibliothèque 5 étapes unifié** (fusion Accueil+Validation+Application). libState partagé, 5 sections séquentielles avec indicateur étape. Conserver 3 onglets redirigeant vers sections ? ou supprimer onglets au profit d'une seule nav Bibliothèque ?

### P1 — Divergence UX importante

2. **Ajouter settings HTTPS** dans UI desktop (`rest_api_https_enabled`, `rest_api_cert_path`, `rest_api_key_path`) dans section API REST.
3. **Ajouter bouton "Tester l'envoi email"** dans section Email settings desktop (endpoint `test_email_report` déjà backend).
4. **Ajouter 3 boutons profil qualité** dans vue Quality desktop : Exporter JSON / Importer JSON / Réinitialiser (endpoints `export_quality_profile`, `import_quality_profile`, `reset_quality_profile` dispo).
5. **Ajouter `compare_perceptual`** dans vue Execution (modale duplicates enrichie avec comparaison perceptuelle 2 films).
6. **Polling event-driven `last_event_ts`** : porter la logique `checkEventChanged` de dashboard dans desktop pour détecter les changements sans attendre l'intervalle fixe.
7. **Fusionner Home-live-logs + History → une seule vue Logs unifiée** (toggle live/historique) côté desktop. Optionnel selon P0 (si Library workflow fusionne, les logs live vont dans l'étape 1 Analyse).

### P2 — Cosmétique / factorisation

8. **Porter `skeleton.js`** dans composants desktop et l'utiliser dans home/quality/history pendant les fetch.
9. **Porter `kpi-card.js`** (factoriser) dans composants desktop pour remplacer les macros kpi-grid inline — uniformisation visuelle.
10. **Ajouter `get_tmdb_posters`** : galerie posters dans la future vue Library desktop (optionnel).

### P3 — Exclusives desktop (pas d'action)

- 12 features desktop conservées (voir section G).

---

## Annexes

### Annexe 1 — Diff endpoints API

**Dashboard-only endpoints** (6) : `export_quality_profile`, `import_quality_profile`, `reset_quality_profile`, `test_email_report`, `compare_perceptual`, `get_tmdb_posters`.

**Desktop-only endpoints** (9) : `validate_dropped_path`, `open_path`, `log_api_exception`, `get_server_info`, `undo_last_apply_preview`, `undo_by_row_preview`, `undo_selected_rows`, `recheck_probe_tools`, `reset_incremental_cache`.

### Annexe 2 — Diff settings clés

**Manquants desktop** : `rest_api_https_enabled`, `rest_api_cert_path`, `rest_api_key_path`.

**Champs équivalents mais IDs différents** : vérifier que l'introduction de HTTPS côté desktop utilise la même convention (`ckRestHttpsEnabled`, `inRestCertPath`, `inRestKeyPath`).

### Annexe 3 — Fichiers critiques pour le plan de correction

- **Refonte Library (P0)** : [web/index.html](web/index.html), [web/core/router.js](web/core/router.js), [web/views/home.js](web/views/home.js), [web/views/validation.js](web/views/validation.js), [web/views/execution.js](web/views/execution.js), référence : [web/dashboard/views/library/](web/dashboard/views/library/) (6 fichiers workflow)
- **HTTPS settings (P1)** : [web/index.html](web/index.html) (section API REST), [web/views/settings.js](web/views/settings.js) (load/save)
- **Boutons profil qualité (P1)** : [web/views/quality.js](web/views/quality.js), [web/index.html](web/index.html)
- **Skeleton (P2)** : nouveau [web/components/skeleton.js](web/components/skeleton.js), imports dans views
- **kpi-card (P2)** : nouveau [web/components/kpi-card.js](web/components/kpi-card.js)
- **Logs unifiés (P1)** : [web/views/history.js](web/views/history.js) ou fusion dans la future Library

---

## Prochaine étape

Rapport validé → **Plan de correction détaillé** à concevoir, structuré en lots :
- **Lot P0** : refonte Library workflow (chantier principal, ~6-8 h)
- **Lot P1** : 6 ajouts ciblés (HTTPS, test email, export/import/reset profil, compare_perceptual, polling event-driven, logs unifiés ou intégrés à Library) (~3-4 h)
- **Lot P2** : factorisation (skeleton, kpi-card, posters) (~2 h)
- **Tests** : adapter tests UI contrat, ajouter tests pour nouveaux endpoints/UI (~1-2 h)

**Total estimé** : 12-16 h pour parité complète.
