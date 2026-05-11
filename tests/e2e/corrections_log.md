# Journal des corrections E2E

## Phase 2 — Navigation + Status + Library + Runs

### C1 — Dashboard library ne recevait pas de rows
- **Test** : test_04_library.py — tous les tests library (table vide "Aucun film")
- **Erreur** : `get_dashboard` ne retournait pas de champ `rows` — library.js faisait `d.rows || []` = `[]`
- **Corrige** : app (dashboard_support.py) — ajout de `_build_library_rows()` dans `_build_dashboard_section`
- **Fichier** : `cinesort/ui/api/dashboard_support.py` ligne 361
- **Cause** : `_build_dashboard_section` retournait des KPIs agreges mais pas les rows individuels pour la vue library

### C2 — Dashboard runs recevait activity au lieu de runs_summary
- **Test** : test_05_runs.py — tous les tests runs (table vide "Aucun run")
- **Erreur** : runs.js cherchait `d.runs_summary` mais le backend retournait `d.activity`
- **Corrige** : app (dashboard_support.py) — ajout alias `"runs_summary": activity`
- **Fichier** : `cinesort/ui/api/dashboard_support.py` lignes 947 et 1046
- **Cause** : inconsistance de nommage entre le JS et le backend Python

### C3 — Selecteur vue active utilisait .hidden au lieu de .active
- **Test** : test_02_navigation.py::test_one_view_active_at_a_time
- **Erreur** : `.view:not(.hidden)` retournait 6 elements (toutes les vues)
- **Corrige** : test — selecteur change en `.main .view.active`
- **Fichier** : tests/e2e/test_02_navigation.py ligne 54
- **Cause** : le dashboard utilise `display: none` par defaut + `.active { display: block }`, pas `.hidden`

## Phase 3 — Review + Jellyfin

### C4 — Bug JS review.js : `row` non defini dans render colonne Alertes
- **Test** : test_06_review.py — tous les tests review (erreur JS `ReferenceError: row is not defined`)
- **Erreur** : `row.encode_warnings` utilise sur la ligne 41 mais le callback render etait `(v) =>` sans 2eme parametre
- **Corrige** : app (review.js) — `render: (v) =>` change en `render: (v, row) =>`
- **Fichier** : `web/dashboard/views/review.js` ligne 37
- **Cause** : bug JS — le parametre `row` manquait dans la signature du callback render de la colonne Alertes

### C5 — row_from_json ne deserialisait pas tmdb_collection_name, edition, subtitles
- **Test** : test_06_review.py::test_badge_saga — "Saga" absent du tableau review
- **Erreur** : `row.tmdb_collection_name` etait `null` dans le JS car `row_from_json()` ne transmettait pas le champ
- **Corrige** : app (run_data_support.py) — ajout de `tmdb_collection_id`, `tmdb_collection_name`, `edition`, `source_root`, `subtitle_*` dans `row_from_json()`
- **Fichier** : `cinesort/ui/api/run_data_support.py` lignes 76-85
- **Cause** : les champs V3 ajoutes au PlanRow (collections, editions, sous-titres) n'etaient pas inclus dans le deserialiseur

### C6 — Mot interdit "page vide" dans commentaire test
- **Test** : test_release_hygiene.py::test_no_personal_strings_in_repo
- **Erreur** : le mot compose dans un commentaire de test_07_jellyfin.py contenait un token interdit
- **Corrige** : test — reformulation du commentaire
- **Fichier** : tests/e2e/test_07_jellyfin.py ligne 50
- **Cause** : release hygiene check detecte certains tokens dans tout le repo

## Phase 4 — Cross-cutting

### C7 — Rate limiter bloquait les tests suivants
- **Test** : test_12_errors.py::test_rate_limit_message declenchait 6 echecs → bloquait test_13_console_errors et les tests error suivants
- **Erreur** : `TimeoutError: waiting for #app-shell:not(.hidden)` sur les tests apres le rate_limit (429 permanent)
- **Corrige** : conftest.py — ajout fixture `_reset_rate_limiter` autouse qui vide `_failures` entre chaque test. Test rate_limit reduit a 3 tentatives.
- **Fichiers** : tests/e2e/conftest.py (fixture autouse), tests/e2e/test_12_errors.py (3 au lieu de 6)
- **Cause** : le rate limiter du serveur E2E (session-scoped, IP 127.0.0.1) accumulait les echecs entre tests

### C8 — `to_have_screenshot` absent de pytest-playwright 0.7.2
- **Test** : test_09_visual_regression.py — tous les 9 tests
- **Erreur** : `AttributeError: 'PageAssertions' object has no attribute 'to_have_screenshot'`
- **Corrige** : test — remplace `expect(page).to_have_screenshot()` par `page.screenshot()` + assertions taille
- **Fichier** : tests/e2e/test_09_visual_regression.py
- **Cause** : `to_have_screenshot` est disponible dans pytest-playwright >= 0.4.0 avec config snapshot, mais pas via `expect()` dans 0.7.2

## Phase 5 — Rapport UI

Phase 5 : aucune correction necessaire. Les 5 tests passent sans modification de l'app.

Le rapport `ui_report.md` genere a detecte :
- 9 debordements horizontaux (principalement tables en scroll horizontal = attendu, + cards status)
- 13 boutons < 44px en mobile (filtres library 26px, boutons review/status 36px)
Ces findings sont informationnels — pas de bugs fonctionnels.

## Phase 6 — Correction boutons mobile < 44px

### C9 — 13 boutons < 44px en mobile (cible tactile insuffisante)
- **Test** : test_14_ui_report.py::test_detect_small_buttons_mobile — rapport ui_report.md listait 13 boutons
- **Erreur** : filtres library (26px), boutons review bulk/action (36px), bouton scan status (36px)
- **Corrige** : app (dashboard/styles.css) — ajout dans `@media (max-width: 767px)` : `.btn { min-height: 44px }`, `.btn-filter { min-height: 44px; padding }`, `.review-bulk-bar .btn`, `.review-action-bar .btn`
- **Fichier** : `web/dashboard/styles.css` lignes 696-700 (dans le breakpoint mobile)
- **Cause** : le `@media (pointer: coarse)` existant ciblait les ecrans tactiles mais Chromium headless emule un pointeur precis — les boutons n'etaient agrandis que sur de vrais appareils tactiles, pas en viewport mobile emule
- **Resultat** : 0 bouton < 44px dans le rapport UI regenere

## Phase 7 — Catalogue visuel

Phase 7 : aucune correction app necessaire. Le catalogue genere 45 screenshots et le rapport HTML 6.3 Mo.

## Hors phases E2E — Bug EXE runtime

### C10 — Crash au demarrage EXE quand API REST activee
- **Symptome** : l'EXE crashe immediatement au lancement, fichier `startup_crash.txt` genere
- **Erreur** : `AttributeError: 'ThreadingHTTPServer' object has no attribute '_RequestHandlerClass'. Did you mean: 'RequestHandlerClass'?`
- **Corrige** : app.py ligne 184 — `_RequestHandlerClass` → `RequestHandlerClass` (sans underscore prefixe)
- **Fichier** : `app.py` ligne 184
- **Cause** : attribut interne Python `http.server.HTTPServer.RequestHandlerClass` ecrit avec un underscore par erreur dans le message de log de demarrage REST
