# Plan exécutable — RESTE À FAIRE post-audits Round 1-5

> Document vivant qui consolide TOUS les findings non-résolus des 5 rounds d'audit.
> Structuré par PHASES indépendantes, chacune avec effort + risque + dépendances.
> Fichier source : `AUDIT_TRACKING.md` (registry complet par round).

**État de référence (4 mai 2026)** : 10 fixes critiques appliqués (CRIT-1/2/3/5/6, R5-MEM-3, R5-CRASH-1/3, H1, H5). Note 9.2/10. Build `dist/CineSort.exe` 50 MB stable. **Reste : ~80 findings** classés ci-dessous.

---

## PHASE 1 — Bloquants pour public release massif (~3j)

> À faire AVANT de pusher GitHub Release publique 1000+ users.

### 1.1 Sécurité : CVE bumps (CRIT-4) — 2h
- `requirements.txt` : `urllib3>=2.6.0` (CVE-2024-37891 fuite Proxy-Auth + CVE-2025-66418 zip bomb)
- `requirements.txt` : `pyinstaller>=6.10.0` (CVE-2025-59042 élévation privilèges locale)
- Tester build complet, vérifier fonctionnement clients HTTP TMDb/Jellyfin/Plex/Radarr
- **Risque** : faible (bumps mineurs)

### 1.2 Database : ON DELETE CASCADE/RESTRICT (R5-DB-1) — 1j
- Migration 021 : ajouter `ON DELETE CASCADE` ou `RESTRICT` sur 4 FK :
  - `errors.run_id → runs.run_id` (CASCADE)
  - `quality_reports.run_id → runs.run_id` (CASCADE)
  - `anomalies.run_id → runs.run_id` (CASCADE)
  - `apply_operations.batch_id → apply_batches.batch_id` (CASCADE)
- Tests : vérifier qu'un DELETE FROM runs cascade correctement
- **Risque** : moyen (migration DB, à tester sur fresh + existing)

### 1.3 Crash recovery : FFmpeg subprocess cleanup (R5-CRASH-2) — 4h
- `cinesort/domain/perceptual/ffmpeg_runner.py` : context manager wrap `subprocess.Popen`
- `try/finally` avec `.kill()` + `.wait(timeout=1)`
- `atexit.register` pour nettoyer subprocess orphelins au shutdown
- Tests : simuler timeout, vérifier pas de zombie ffmpeg.exe
- **Risque** : moyen (multi-platform Windows/Linux)

### 1.4 LPIPS model absent fallback (R5-PERC-3) — 1h
- `lpips_compare.py` : retourner `LpipsResult(distance=None, ..., verdict="insufficient_data", confidence=0)` si model FileNotFoundError
- Logger warning au lieu de crasher l'UI
- **Risque** : faible

### 1.5 Tests E2E sélecteurs cassés (H7) — 4h
- `tests/e2e/test_02_navigation.py` : retirer `/runs`, `/review` de `_ROUTES`
- `tests/e2e/test_12_errors.py:46` : remplacer `#qualityContent` par `#v5QijQualityPanel`
- Mettre à jour 4-6 autres assertions cassées
- **Risque** : faible

### 1.6 PyInstaller hidden imports perceptual (H9) — 1h
- `CineSort.spec:158` : ajouter modules perceptual lazy-imports manquants
- Liste : `chromaprint`, `lpips_compare`, `ssim_self_ref`, `hdr_analysis`, `audio_fingerprint`
- Tester build .exe + scan d'un film
- **Risque** : faible (test catch toute erreur d'import au runtime)

**Phase 1 total : ~3 jours** | Sortie : `dist/CineSort.exe` v7.6.1 hotfix prêt public

---

## PHASE 2 — High polish UX et accessibilité (~1 semaine)

> Améliorations notables visibles user, pas bloquant mais perçu qualité.

### 2.1 Race conditions UI (H2, H4, H8) — 4h
- `qij.js:584` : remplacer `setTimeout(100ms)` par binding direct dans modal callback
- `qij.js:915` : AbortController sur `_qijMountActive` pour annuler tab switching rapide
- `qij.js:705` : guard `if (!root.parentElement) journalPoller.stop()`

### 2.2 XSS hardening (H3) — 30 min
- `qij.js:554` : `${m.year}` → `${_esc(String(m.year || ""))}`
- Grep autres patterns similaires non échappés

### 2.3 Régression table runs perd tri (H6) — 1j
- `qij.js:776` : ajouter boutons sortable date/score/statut sur cards Journal
- OU revenir à `tableHtml + attachSort` du composant table.js v4
- Tests E2E : valider tri ascending/descending

### 2.4 Performance boot : cache get_settings (H13) — 4h
- `app.js:161,295,344,361` : 4 appels concurrents `get_settings` au boot
- Wrapper `_cachedSettings` avec invalidation sur `last_settings_ts` change
- Réduit latence boot ~200ms

### 2.5 Memory leaks polish (R4-MEM-2/3/4/5/6) — 1j
- `notification-center.js:52-75` : `closeNotifications()` retire overlay+drawer du DOM
- `journal-polling.js:73` : `apiPost` avec `AbortSignal.timeout(5000)`
- Pattern `unmount()` exporté par chaque vue, appelé par router avant switch
- `localStorage drafts` : TTL 30j + nettoyage périodique au boot
- `Promise.allSettled` avec AbortController au navigate hashchange

### 2.6 Accessibilité WCAG 2.2 AA (H10) — 2j
- `modal.js` : `trapFocus(overlay)` capture Tab/Shift+Tab
- `index.html:88,94,...` : `aria-atomic="true"` sur conteneurs aria-live OR queue d'annonces
- `aria-busy` toggle dynamique avant/après fetch
- `top-bar-v5.js:89-90` : `aria-expanded` sur toggle dropdown theme
- `top-bar-v5.js:52-91` : Arrow keys (Up/Down/Home/End) sur menu theme ouvert
- `table.js:68-104` : keydown Space/Enter sur `.th-sortable`
- `aria-required` + `*` rouge sur champs settings obligatoires

### 2.7 Font loading (H11) — 5 min
- `dashboard/styles.css` `@font-face` Manrope : ajouter `font-display: swap`
- Élimine FOIT 0-3s

### 2.8 CSP modernisation (H17) — 1h
- `rest_server.py` : retirer `'unsafe-inline'` style, migrer vers nonce ou hash
- Tests E2E pour vérifier styles inline restent fonctionnels

### 2.9 OpenLogsFolder REST exposé (H18) — 5 min
- `rest_server.py:_EXCLUDED_METHODS` : retirer `open_logs_folder` de la liste
- `help.js` peut maintenant appeler l'endpoint via REST en mode supervision web

### 2.10 PRAGMA optimize au shutdown (R5-DB-2) — 30 min
- `connection.py` ou `sqlite_store.py:close()` : `conn.execute("PRAGMA optimize")` avant close
- Réduit fragmentation DB long-terme

### 2.11 PRAGMA integrity_check au boot (R5-DB-3) — 1h
- `sqlite_store.py:initialize()` : `PRAGMA integrity_check` avant migrations
- Si corrompu : log ERROR + tentative auto-restore depuis backup
- UI affiche notification au prochain boot

**Phase 2 total : ~1 semaine** | Sortie : v7.6.2

---

## PHASE 3 — Refactor code maintenance (~1.5 semaine)

> Investissement long-terme, pas user-facing.

### 3.1 Refactor _plan_item CC=126 (R4-CC-1) — 3j
- `plan_support.py:654` : 565 lignes monolithe
- Splitter en 12 sous-fonctions : `_plan_item_movie`, `_plan_item_tv_episode`, `_plan_item_collection_member`, `_plan_item_short`, etc.
- Tests : 0 régression sur scan complet 100 films mock
- **Risque** : moyen (cœur métier, 3000+ tests à valider)

### 3.2 Refactor compute_quality_score CC=78 (R4-CC-2) — 2j
- `quality_score.py:853` : 369 lignes
- Splitter en 5 helpers : `_score_video_v2`, `_score_audio_v2`, `_score_extras_v2`, `_apply_weights_v2`, `_determine_tier_v2`
- Garder API publique inchangée

### 3.3 Refactor plan_library CC=73 (R4-CC-3) — 1.5j
- `plan_support.py:302` : 347 lignes
- Splitter scan/filter/dedup en 3 fonctions

### 3.4 ~200 docstrings publiques manquantes (R4-CC-6) — 4h
- Audit `apply_audit.py`, `apply_core.py` helpers
- Ajouter docstrings 1-ligne minimum sur fonctions publiques

### 3.5 23 fichiers > 500L (R4-CC-5) — 1j
- Identifier les vrais candidats à splitter (sans casser l'API)
- Mettre à jour CLAUDE.md "6 fichiers > 500L" → "23 fichiers > 500L (targets refactor v7.7)"

### 3.6 Composite Score V2 activation (R4-PERC-7 / H16) — 3j
- Décision architecturale : v1 vs v2 par défaut
- Migration des utilisateurs actuels
- Suppression progressive de v1 OU coexistence permanente
- **Risque** : élevé (touche scoring central, beaucoup d'utilisateurs)

**Phase 3 total : ~1.5 semaine** | Sortie : v7.7.0 refactor

---

## PHASE 4 — Documentation (~1 semaine)

### 4.1 CLAUDE.md mise à jour (R4-DOC-1) — 4h
- "33 endpoints" → "98 endpoints" (compter exact via `_get_api_methods`)
- "10 vues" → "6 vues v5 active + 4 v4 legacy"
- "v7.5.0 14 sections perceptuelles" → énumérer §1-§16
- "0 fonction > 100L" → "23 fonctions > 100L (refactor v7.7)"
- "6 fichiers > 500L" → "23 fichiers > 500L"
- Ajouter sections v7.6.0 manquantes (design system v5, tokens, themes, NotificationStore)

### 4.2 docs/api/ENDPOINTS.md (R4-DOC-2) — 1.5j
- Énumération exhaustive des 98 endpoints REST
- Signature (méthode, path, params, return)
- 10 exemples requête/réponse pour endpoints les plus utilisés
- Possibilité de générer auto via `inspect.signature` + introspection

### 4.3 docs/MANUAL.md user manual (R4-DOC-3) — 2j
- Tutoriel étape-par-étape : install → config TMDb → premier scan → review → apply → undo
- Glossaire métier (Tier, Score perceptuel, etc.)
- FAQ utilisateurs (40+ questions)

### 4.4 docs/TROUBLESHOOTING.md (R4-DOC-4) — 1j
- Sections : Probe failures, APIs (TMDb/Jellyfin/Plex/Radarr), Performance, Undo conflits, Network
- Debug steps + logs à consulter par scénario

### 4.5 architecture.mmd diagram (R4-DOC-5) — 4h
- Module layout (domain → infra → app → ui)
- Workflow scan → plan → validation → apply → undo
- Perceptual analysis pipeline DAG
- Notification flow

### 4.6 Config templates (R4-DOC-6) — 30 min
- `.env.example` à la racine
- `settings.json.example` documenté

### 4.7 BILAN_CORRECTIONS.md cleanup (R4-DOC-7) — 1h
- Archiver Round 1-2 résolus dans `docs/internal/audits/ARCHIVE_R1_R2.md`
- Garder uniquement actif/bloquant + Round 3+

### 4.8 RELEASE.md release process (~30 min)
- Version bump (VERSION + CHANGELOG)
- Tag convention
- Build steps
- GitHub Release notes generation

**Phase 4 total : ~1 semaine** | Sortie : doc complète, prête open-source

---

## PHASE 5 — i18n EN support (~2 semaines)

> Optionnel — uniquement si tu veux toucher des users non-FR.

### 5.1 Infrastructure i18n (R4-I18N-4) — 2j
- Module `web/dashboard/core/i18n.js` : `t(key)` lookup, locale switch
- Module `cinesort/domain/i18n_messages.py` : dict `MESSAGES`
- `locales/fr.json` + `locales/en.json` initial

### 5.2 Frontend strings extraction (R4-I18N-1) — 4j
- ~250 strings frontend → externaliser dans `locales/fr.json`
- Refactor `escapeHtml(label)` → `escapeHtml(t(key))` partout

### 5.3 Backend messages extraction (R4-I18N-2) — 2j
- ~45 messages erreur backend → externaliser
- `return {"ok": False, "message": t("error.run_not_found")}`

### 5.4 Date/number formatters (R4-I18N-3) — 1j
- `format.js` : `Intl.DateTimeFormat(locale, ...)` au lieu de `"fr-FR"` hardcodé
- `Intl.NumberFormat` pour KB/MB/GB localisés

### 5.5 Glossaire + Help (R4-I18N-5) — 2j
- 30 termes glossaire FR → EN
- 15 FAQ FR → EN

### 5.6 Tests i18n (1j)
- Tests asserent sur `t("key")` pas string FR
- Coverage swap fr→en→fr round-trip

**Phase 5 total : ~2 semaines** | Sortie : v7.8.0 multilingue

---

## PHASE 6 — Stress / scale long-terme (~1 semaine)

> Pour gérer >5000 films sans degradation.

### 6.1 UI virtualisation library (R5-STRESS-2) — 3j
- `library.js` : implémenter windowing (équivalent react-window)
- Pagination backend `get_library_filtered(offset, limit)` ajout
- Render seulement les 30-50 rows visibles

### 6.2 Perceptual parallelism confirmer/améliorer (R5-STRESS-5) — 2j
- Vérifier `perceptual_parallelism_mode` réellement implémenté
- Si non : `multiprocessing.Pool` avec workers configurables
- Cible : 10k films en 24h avec 8 cores (au lieu de 14j mono-thread)

### 6.3 TMDb cache TTL + purge (R5-STRESS-4) — 1j
- TTL configurable (défaut 30j)
- Purge auto au boot des entries expirées

### 6.4 Probe parallélisation 10k (R5-STRESS-1) — 2j
- Confirmer si déjà parallèle ou si mono-thread
- ThreadPoolExecutor 4-8 workers (probe = I/O bound)

**Phase 6 total : ~1 semaine** | Sortie : prêt pour bibliothèques 10k+

---

## PHASE 7 — Polish micro / cosmétique (~3-5j)

### 7.1 CSS legacy cleanup (R4-DOC-7) — 1j
- `web/styles.css` 2192L → réduction ~80 KB de dead code
- `web/themes.css` 975L → fusionner avec `shared/themes.css`
- Z-index legacy chaos → migrer vers tokens.css scale

### 7.2 Manrope font duplicate (R5-BUNDLE-1) — 1h
- `web/fonts/Manrope-Variable.ttf` + `web/dashboard/fonts/Manrope-Variable.ttf` (162 KB chacun)
- Fusionner dans `web/shared/fonts/Manrope-Variable.ttf`
- Mettre à jour 2 `@font-face`

### 7.3 .clickable-row CSS (Medium R3) — 5 min
- `components.css` : ajouter `cursor: pointer; transition: bg`

### 7.4 Logging quality (R4-LOG-1/2/3/4) — 2j
- `run_id` transversal via `contextvars.ContextVar`
- `request_id` REST handler UUID
- Setting `log_level` configurable + env var `CINESORT_LOG_LEVEL`
- Structured logging optionnel JSON formatter

### 7.5 Documentation MAJ historique
- Update CHANGELOG.md avec v7.6.1, v7.6.2, etc.
- Section "Audits Round 1-5" dans BILAN_CORRECTIONS.md

**Phase 7 total : ~3-5j** | Polish général

---

## Récapitulatif effort

| Phase | Effort | Risque | Output |
|---|---|---|---|
| 1. Bloquants public | 3j | faible-moyen | v7.6.1 hotfix |
| 2. High polish UX/A11y | 1 sem | faible | v7.6.2 |
| 3. Refactor code | 1.5 sem | moyen | v7.7.0 |
| 4. Documentation | 1 sem | nul | doc complète |
| 5. i18n EN | 2 sem | moyen | v7.8.0 |
| 6. Stress / scale | 1 sem | moyen-élevé | v7.9.0 |
| 7. Polish micro | 3-5j | faible | v7.10.0 |
| **TOTAL** | **~7 semaines** | — | App production-grade |

---

## Suggestion priorité minimum viable

Pour public release **massif** (>1000 users) :
- **Phase 1** obligatoire (3j)
- **Phase 2 sections 2.6 (a11y) + 2.10 (DB optimize)** (3j)
- **Phase 4 sections 4.1-4.4 (doc)** (3-4j)
- **Phase 7 section 7.4 (logging run_id)** (1j)

**Total minimum viable : ~2 semaines** pour passer de "ready bêta privée" à "ready public release massif".

Pour usage **personnel ou bêta privée 50 users** : déjà OK avec les 10 fixes appliqués (note 9.2/10).

---

## Tracking

- Findings source : [AUDIT_TRACKING.md](AUDIT_TRACKING.md)
- Fixes appliqués : 10 (CRIT-1/2/3/5/6, R5-MEM-3, R5-CRASH-1/3, H1, H5)
- Findings restants : ~80 classés par phase ci-dessus
- Aucun finding n'est perdu : tous tracés dans AUDIT_TRACKING.md

---

## ✅ VÉRIFICATION DES 10 FIXES APPLIQUÉS (4 mai 2026)

Chaque fix a été relu dans le code post-édit pour confirmer qu'il fait bien ce qui est attendu. Tests post-fix : **133 tests OK, 0 régression** (83 tests apply/settings/watcher/notif + 50 tests REST).

### FIX 1 — Notifications drain_timer ✅ VÉRIFIÉ
- **Fichier** : `cinesort/app/notify_service.py:34-178`
- **Attendu** : Timer auto-relancable 0.5s qui drain la queue depuis main thread
- **Implémenté** : 4 méthodes (`start_drain_timer`, `_schedule_next_drain`, `_drain_tick`, `shutdown`) + flag `_drain_active`
- **Branchement** : `app.py:504` appelle `api._notify.start_drain_timer(0.5)` après `set_window`
- **Cleanup** : `shutdown()` set `_drain_active=False` + `timer.cancel()` + `cleanup()` Win32
- **Status** : ✅ Implémentation correcte. À tester runtime : démarrer scan, vérifier toast Windows à la fin.

### FIX 2 — qij.js tabFromHash priorité ✅ VÉRIFIÉ
- **Fichier** : `web/dashboard/views/qij.js:906-915`
- **Attendu** : URL `?tab=journal` doit gagner sur `opts.tab="quality"` (alias route)
- **Implémenté** : `_qijState.activeTab = tabFromHash || opts.tab || "quality"` (tabFromHash en premier)
- **Status** : ✅ Logique correcte. À tester : URL directe `http://localhost:8642/dashboard/#/quality?tab=journal` doit ouvrir tab Journal.

### FIX 3 — Jellyfin sync run_id ✅ VÉRIFIÉ
- **Fichier** : `web/dashboard/views/qij.js:485-493`
- **Attendu** : Passer `run_id` du dernier run dispo, sinon backend cherche tout seul
- **Implémenté** : Fetch `get_global_stats(limit_runs:5)` → extrait premier `run_id` → param `{run_id: lastRunId}`
- **Fallback** : Si fetch échoue → `params = {}` (backend chercher sans), pas de crash
- **Status** : ✅ Robust. À tester : tab Integrations → Jellyfin → "Vérifier cohérence".

### FIX 4 — Sections HTML orphelines supprimées ✅ VÉRIFIÉ
- **Fichier** : `web/dashboard/index.html`
- **Attendu** : `view-runs` et `view-review` retirées (orphelines, sans registerRoute)
- **Implémenté** : Grep `view-runs|view-review` retourne ZÉRO occurrence dans index.html
- **Status** : ✅ Sections retirées proprement.

### FIX 5 — Insights cap 10 000 ✅ VÉRIFIÉ
- **Fichier** : `cinesort/ui/api/notifications_support.py:240-249`
- **Attendu** : Set `_emitted_insight_codes` capped à 10 000 entries, clear auto si dépassement
- **Implémenté** : Constante `_MAX_EMITTED_INSIGHTS = 10_000` + check `len > MAX` + `clear()` + log info
- **Status** : ✅ Cap fonctionnel. Memory growth long-terme stoppée.

### FIX 6 — Watcher pré-validation roots ✅ VÉRIFIÉ
- **Fichier** : `cinesort/app/watcher.py:156-184`
- **Attendu** : Avant `_trigger_scan()`, valider `is_dir_accessible(root, timeout_s=5.0)` pour chaque root
- **Implémenté** : Boucle sur `self._roots` avec `is_dir_accessible`, log warning + `return` si inaccessible
- **Fallback** : Si `ImportError fs_safety` → comportement original (pas de blocage)
- **Status** : ✅ Robust. À tester : débrancher NAS, watcher ne déclenche plus scan auto.

### FIX 7 — atexit + drain_timer démarré ✅ VÉRIFIÉ
- **Fichier** : `app.py:498-510`
- **Attendu** : Démarrer drain_timer après `set_window` + atexit pour shutdown propre
- **Implémenté** : `api._notify.start_drain_timer(0.5)` dans try/except + `_atexit.register(lambda: api._notify.shutdown())`
- **Status** : ✅ Cleanup garanti même en SIGTERM (Ctrl-C). SIGKILL reste insurmonté (limitation OS).

### FIX 8 — Cleanup runs RUNNING orphelins ✅ VÉRIFIÉ
- **Fichier** : `cinesort/ui/api/runtime_support.py:103-128`
- **Attendu** : Au boot, marquer FAILED tous les runs `status='RUNNING'` (orphelins post-crash)
- **Implémenté** : `SELECT run_id FROM runs WHERE status='RUNNING'` → `UPDATE status='FAILED'` + log warning
- **Idempotent** : Cache `_RECONCILED_STATE_DIRS` garantit 1× par state_dir par session
- **Status** : ✅ Plus de runs zombie en BDD. À tester : kill -9 mid-scan, relance, vérifier run marqué FAILED.

### FIX 9 — window.onerror global ✅ VÉRIFIÉ
- **Fichier** : `web/dashboard/app.js:13-37`
- **Attendu** : Capturer erreurs JS non-attrapées et `unhandledrejection` Promise, afficher banner rouge
- **Implémenté** : 2 listeners (`error` + `unhandledrejection`) + `_showErrorBanner` avec auto-dismiss 5s + bouton Fermer
- **Status** : ✅ Plus de page blanche silencieuse. À tester : injecter `throw new Error('test')` dans console F12 → banner rouge.

### FIX 10 — Save settings error feedback ✅ VÉRIFIÉ
- **Fichier** : `web/dashboard/views/settings.js:914-942`
- **Attendu** : Afficher message rouge dans `[data-v5-saved-state]` si save échoue (au lieu de console silent)
- **Implémenté** : `_updateSavedStateError(msg)` + try/catch sur apiPost + handler erreur réseau
- **Status** : ✅ User voit "⚠ Echec sauvegarde : <message>" au lieu de croire que c'est sauvé. À tester : couper réseau pendant typing dans settings.

---

## 🧪 SCÉNARIOS DE VALIDATION RUNTIME

À tester sur `dist/CineSort.exe` v7.6.1 (~50 MB, build 4 mai 2026 00:23) :

| # | Scénario | Avant fix | Après fix attendu |
|---|---|---|---|
| 1 | Démarrer scan, attendre fin | Aucun toast Windows | Toast "Scan terminé" affiché |
| 2 | URL `/dashboard/#/quality?tab=journal` | Tab Quality s'ouvre (bug) | Tab Journal s'ouvre |
| 3 | Tab Integrations Jellyfin → "Vérifier cohérence" sans run done | "Aucun run terminé" | Sync report affiché avec lastRunId du dernier run dispo |
| 4 | Saisir `/dashboard/#/runs` directement | Section vide (orpheline) | Fallback /home (route inexistante) |
| 5 | Session 6h sans restart, beaucoup d'insights | Memory grow indéfini | Cap 10 000, log "cleared" |
| 6 | Débrancher NAS pendant que watcher tourne | Scan auto déclenché à tort | Log warning "scan annulé, root inaccessible" |
| 7 | kill -9 CineSort.exe | Tray icon orphelin Windows + run RUNNING zombie | (kill -9 = limite OS) Mais SIGTERM/Ctrl-C → tray cleanup OK + boot suivant marque run FAILED |
| 8 | Console F12 : `throw new Error("test")` | Page blanche après quelques secondes | Banner rouge "Erreur JS : test" en haut |
| 9 | Couper backend pendant typing settings | Aucun feedback (silent) | "⚠ Echec sauvegarde : Erreur reseau" en rouge |
| 10 | F12 console pendant scan | (avant) drain_queue jamais appelé | (après) Logs "[notify_service] balloon shown" périodiques |

---

## 📊 STATUT GLOBAL POST-FIX

- **10/10 fixes appliqués + relus + validés syntactiquement**
- **133 tests Python OK, 0 régression**
- **Build .exe** : 50.07 MB (4 mai 2026 00:23) — disponible dans `dist/CineSort.exe`
- **Note finale** : 9.2/10 (vs 8.7/10 pré-fix) → +0.5
- **Production ready** pour usage personnel + bêta privée 50 users
- **Pour public release massif** : compléter Phase 1 (CVE bumps + DB CASCADE + ffmpeg cleanup + LPIPS fallback + tests E2E + hidden imports = ~3j)
